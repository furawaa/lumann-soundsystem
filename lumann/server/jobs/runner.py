"""Owns the TTS worker subprocess and the global work queue.

One worker exists for the whole app regardless of how many projects are open:
there is one GPU (or one espeak-ng at a time is plenty), and parallel
generation would only thrash it. Two books being
narrated at once therefore share one model and one queue, and take turns:
whichever was queued first drains first, except that a re-record anywhere
overtakes first-pass work everywhere.

Stop must be instant. The user hits stop because something is wrong, and a
model in the middle of matrix math will not shut down politely — so stop means
SIGKILL, and correctness comes from the fact that nothing is committed until a
finished `.tmp` is renamed into place.

Stop is per project. Pausing one book leaves the others running, and the worker
is only killed when the segment in flight belongs to the book being stopped —
otherwise stopping the book you are not listening to would cost the other one a
45-second Qwen model reload. A paused project keeps its place in the queue; it is
skipped, not dropped, so pressing record again resumes where it stood.
"""
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time

from ..core import estimate, paths, projects, takes, voices
from . import events

WORKER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tts_worker.py")
IDLE_UNLOAD = 15 * 60         # release the Qwen model after this long idle
MAX_RESTARTS = 3
READY_TIMEOUT = 60            # process start; the Qwen model loads later, per job


RERECORD, FIRST_PASS = 0, 1        # queue priorities; lower goes first


class Job:
    __slots__ = ("project_id", "segment_id", "id", "priority", "order")

    def __init__(self, project_id, segment_id, priority=FIRST_PASS, order=0):
        self.project_id = project_id
        self.segment_id = segment_id
        self.id = projects.new_id()
        self.priority = priority
        # Position in the timeline. Re-records are ordered by where they sit in
        # the book, not by the order the user happened to click them in.
        self.order = order


class Runner:
    def __init__(self):
        self._queue = []                       # [Job], ordered
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._running = False                  # is the consumer allowed to consume
        self._thread = None
        self._proc = None
        self._replies = queue.Queue()
        self._reader = None
        self._stderr_reader = None
        self._worker_state = "stopped"
        self._current = None                   # Job in flight
        self._restarts = 0
        self._last_activity = time.time()
        self._stopping = False
        self._stderr_tail = []
        self._project_rank = {}        # project id -> when it joined the queue
        self._rank_seq = 0
        self._paused = set()           # project ids whose jobs are skipped
        # Job ids killed on purpose. Without this, a scoped stop would look
        # exactly like a worker crash and the segment would be marked failed.
        self._interrupted = set()

    # --- public API -------------------------------------------------------

    def state(self):
        with self._lock:
            by_project = {}
            for job in self._queue:
                by_project[job.project_id] = by_project.get(job.project_id, 0) + 1
            return {
                "worker": self._worker_state,
                "running": self._running,
                "queued": len(self._queue) + (1 if self._current else 0),
                "by_project": by_project,
                "paused": sorted(self._paused),
                "current": {"project": self._current.project_id,
                            "segment": self._current.segment_id} if self._current else None,
            }

    def all_jobs(self):
        """The whole queue across projects, in the order it will be recorded.

        -> [{project, segment, rerecord, paused, recording}], the job in flight
        first. This is what the queue panel shows when it stops filtering by
        project: the order only makes sense as one list, because the projects
        interleave by priority.
        """
        with self._lock:
            rows = []
            if self._current:
                rows.append({"project": self._current.project_id,
                             "segment": self._current.segment_id,
                             "rerecord": self._current.priority == RERECORD,
                             "paused": False,
                             "recording": True})
            rows.extend({"project": job.project_id,
                         "segment": job.segment_id,
                         "rerecord": job.priority == RERECORD,
                         "paused": job.project_id in self._paused,
                         "recording": False}
                        for job in self._queue)
            return rows

    def queued_ids(self, project_id):
        with self._lock:
            return [j.segment_id for j in self._queue if j.project_id == project_id]

    def queued_jobs(self, project_id):
        """-> [(segment_id, priority)] in the order they will be recorded."""
        with self._lock:
            return [(j.segment_id, j.priority)
                    for j in self._queue if j.project_id == project_id]

    def project_order(self):
        """Books with work waiting, in the order the scheduler will take them."""
        with self._lock:
            active = {job.project_id for job in self._queue}
            if self._current:
                active.add(self._current.project_id)
            return sorted(active, key=self._rank)

    def set_project_order(self, project_ids):
        """Put the books in this order. Anything left out keeps its place after.

        This is the middle term of the sort key, so it decides two things at
        once: which book is narrated first, and — when re-records from two
        books are waiting — whose re-record goes first.
        """
        with self._lock:
            listed = [pid for pid in project_ids if pid in self._project_rank]
            rest = sorted((pid for pid in self._project_rank if pid not in listed),
                          key=self._project_rank.get)
            self._rank_seq = 0
            for pid in listed + rest:
                self._rank_seq += 1
                self._project_rank[pid] = self._rank_seq
            self._resort()
        for pid in self._projects_in_queue():
            self._publish_queue(pid)
        return self.project_order()

    def _rank(self, project_id):
        if project_id not in self._project_rank:
            self._rank_seq += 1
            self._project_rank[project_id] = self._rank_seq
        return self._project_rank[project_id]

    def _prune_ranks(self):
        """Forget the queue position of projects that have left the queue.

        A rank answers "when did this book join the queue". Keeping one for a
        book that finished an hour ago would let it walk back in ahead of a
        book queued in the meantime — and a deleted project would hand its
        place to whatever is created with the same slug. Call with the lock.
        """
        active = {job.project_id for job in self._queue}
        if self._current:
            active.add(self._current.project_id)
        for pid in [p for p in self._project_rank if p not in active]:
            del self._project_rank[pid]

    def _resort(self):
        """The whole scheduling rule, in one sort key:

            1. re-records before first-pass work, across every book;
            2. then the book order, which the user can set;
            3. then position in the book.

        So a re-record always jumps the queue — that is the segment somebody is
        sitting and waiting for — and when two books each have re-records
        waiting, the one standing higher in the book order is served first.

        Called with the lock held. The in-flight job is not in `_queue`, so it
        is never reordered out from under itself.
        """
        self._queue.sort(key=lambda j: (j.priority, self._rank(j.project_id), j.order))

    def reconcile(self, project_id):
        """Clear statuses that claim work nobody is doing.

        `recording` is written before generation starts and cleared when it
        ends, so any interruption the release path never saw — a worker killed
        from outside, a reply that never arrived, a thread that died between
        the two — leaves a segment permanently claiming to be recording. That
        is not cosmetic: `select()` does not offer such a segment for recording
        and `enqueue` skips it, so it can never be recorded again while the
        server lives. The same goes for `queued` with no job behind it.

        -> how many segments were freed.
        """
        with self._lock:
            in_flight = self._current.segment_id if self._current else None
            queued = {job.segment_id for job in self._queue if job.project_id == project_id}

        freed = []
        with projects.lock(project_id):
            try:
                project = projects.load(project_id)
            except OSError:
                return 0
            for seg in projects.segments(project):
                if seg["status"] not in ("recording", "queued"):
                    continue
                if seg["id"] == in_flight or seg["id"] in queued:
                    continue
                projects.sync_status(seg, force=True)
                freed.append(seg["id"])
            if freed:
                projects.save(project)
                for seg_id in freed:
                    _idx, seg = projects.find_item(project, seg_id)
                    events.segment_event(project_id, seg)
        return len(freed)

    def enqueue(self, project, segment_ids, priority=FIRST_PASS):
        """Mark segments queued and add them to the work queue."""
        pid = project["id"]
        order = {seg["id"]: i for i, seg in enumerate(projects.segments(project))}
        added = []
        with projects.lock(pid):
            for seg_id in segment_ids:
                _idx, seg = projects.find_item(project, seg_id)
                if seg is None or seg["kind"] != "segment":
                    continue
                if seg["status"] in ("queued", "recording"):
                    continue
                seg["status"] = "queued"
                seg["error"] = None
                added.append(seg_id)
            projects.save(project)
            for seg_id in added:
                _idx, seg = projects.find_item(project, seg_id)
                events.segment_event(pid, seg)

        with self._lock:
            existing = {j.segment_id: j for j in self._queue if j.project_id == pid}
            in_flight = (self._current.segment_id
                         if self._current and self._current.project_id == pid else None)
            self._rank(pid)
            for seg_id in segment_ids:
                if seg_id not in order or seg_id == in_flight:
                    continue
                job = existing.get(seg_id)
                if job is not None:
                    # Already waiting. Marking it for re-record has to move it
                    # up, not be silently dropped as a duplicate.
                    job.priority = min(job.priority, priority)
                    continue
                self._queue.append(Job(pid, seg_id, priority, order[seg_id]))
            self._resort()
            running = self._running
        if running:
            self._wake.set()          # do not make live work wait for the poll
        self._publish_queue(pid)
        return added

    def dequeue(self, project, segment_ids):
        """Take segments out of the queue without touching their audio.

        Nothing is counted as recorded and nothing is deleted — the segment
        simply goes back to whatever resting state its takes imply.
        """
        pid = project["id"]
        wanted = set(segment_ids)
        with self._lock:
            removed = [j.segment_id for j in self._queue
                       if j.project_id == pid and j.segment_id in wanted]
            self._queue = [j for j in self._queue
                           if not (j.project_id == pid and j.segment_id in wanted)]
            self._prune_ranks()
        if removed:
            with projects.lock(pid):
                project = projects.load(pid)
                for seg_id in removed:
                    _idx, seg = projects.find_item(project, seg_id)
                    if seg is not None and seg["status"] == "queued":
                        seg["rerecord"] = False
                        projects.sync_status(seg, force=True)
                projects.save(project)
                for seg_id in removed:
                    _idx, seg = projects.find_item(project, seg_id)
                    if seg is not None:
                        events.segment_event(pid, seg)
        self._publish_queue(pid)
        return removed

    def start(self, project_id=None):
        with self._lock:
            self._running = True
            self._stopping = False
            self._restarts = 0
            if project_id:
                self._paused.discard(project_id)
        self._ensure_thread()
        self._wake.set()
        if project_id:
            self._publish_queue(project_id)

    def stop(self, project_id=None):
        """Pause one project, or everything when no project is given.

        Queued work stays queued either way, so recording resumes where it
        stood. The worker only dies if the segment in flight belongs to the
        project being paused — that is the only case where something has to be
        interrupted, and interrupting means SIGKILL and a reload afterwards.
        """
        if project_id is None:
            return self._stop_everything()

        with self._lock:
            self._paused.add(project_id)
            current = self._current
            interrupt = current is not None and current.project_id == project_id
            if interrupt:
                self._interrupted.add(current.id)
            # Anything left for the worker once this project steps aside?
            still_busy = ((current is not None and not interrupt)
                          or any(job.project_id not in self._paused for job in self._queue))

        if interrupt:
            self._kill_worker()
            # _run_job owns the in-flight job and puts it back to pending when
            # it sees the worker gone; releasing it here as well would race.
        if not still_busy:
            with self._lock:
                self._running = False
            events.worker_event("stopped")

        for pid in self._projects_in_queue() | {project_id}:
            self._publish_queue(pid)

    def _stop_everything(self):
        with self._lock:
            self._running = False
            self._stopping = True
            self._paused.clear()
            current = self._current
        self._kill_worker()
        if current:
            self._release(current, "pending")
        with self._lock:
            self._current = None
        events.worker_event("stopped")
        for pid in self._projects_in_queue():
            self._publish_queue(pid)

    def clear(self, project_id):
        """Drop a project's queued work and put the segments back to pending."""
        with self._lock:
            dropped = [j for j in self._queue if j.project_id == project_id]
            self._queue = [j for j in self._queue if j.project_id != project_id]
            # Nothing of this project's is left to resume, so the pause it may
            # have been under is meaningless now.
            self._paused.discard(project_id)
            self._prune_ranks()
        if dropped:
            with projects.lock(project_id):
                project = projects.load(project_id)
                for job in dropped:
                    _idx, seg = projects.find_item(project, job.segment_id)
                    if seg is not None and seg["status"] == "queued":
                        projects.sync_status(seg, force=True)
                        events.segment_event(project_id, seg)
                projects.save(project)
        self._publish_queue(project_id)
        return len(dropped)

    def restore(self):
        """After a server restart: rebuild the queue from `queued` segments and
        sweep half-written wavs. Deliberately does not start consuming — starting
        a book on boot is not something the user asked for."""
        restored = 0
        for pid in projects.list_ids():
            takes.sweep_orphans(pid)
            with projects.lock(pid):
                project = projects.load(pid)
                dirty = False
                pending = []
                for seg in projects.segments(project):
                    if seg["status"] == "recording":      # interrupted mid-generation
                        seg["status"] = "queued"
                        dirty = True
                    if seg["status"] == "queued":
                        pending.append(seg["id"])
                if dirty:
                    projects.save(project)
            if pending:
                order = {seg["id"]: i for i, seg in enumerate(projects.segments(project))}
                with self._lock:
                    self._rank(pid)
                    self._queue.extend(
                        Job(pid, s, RERECORD if _marked(project, s) else FIRST_PASS,
                            order.get(s, 0))
                        for s in pending)
                    self._resort()
                restored += len(pending)
        return restored

    def shutdown(self):
        with self._lock:
            self._running = False
            self._stopping = True
        self._kill_worker()
        self._wake.set()

    # --- consumer thread --------------------------------------------------

    def _ensure_thread(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._loop, name="tts-runner", daemon=True)
            self._thread.start()

    def _loop(self):
        while True:
            self._wake.wait(timeout=30)
            self._wake.clear()

            drained = []
            while True:
                with self._lock:
                    job = self._take_job()
                    if job is None:
                        break
                    self._current = job
                try:
                    self._run_job(job)
                except Exception as exc:                    # noqa: BLE001
                    self._release(job, "failed", str(exc))
                finally:
                    with self._lock:
                        self._current = None
                    if job.project_id not in drained:
                        drained.append(job.project_id)
                    self._publish_queue(job.project_id)

            # Work ran out on its own. "Running" means the model is chewing
            # through a queue, so it stops being true here — and the UI goes
            # back to inviting a press rather than claiming to be busy. Jobs
            # belonging to a paused project do not count as work: they are
            # waiting for the user, not for the model.
            with self._lock:
                finished = self._running and not self._runnable()
                if finished:
                    self._running = False
                self._prune_ranks()
            if finished:
                events.worker_event("idle")
                for pid in drained:
                    self._publish_queue(pid)

            if self._idle_expired():
                self._kill_worker()
                events.worker_event("stopped", "idle")

    def _runnable(self):
        """Queued jobs whose project is not paused. Call with the lock held."""
        return [job for job in self._queue if job.project_id not in self._paused]

    def _take_job(self):
        """Next job to record, or None. Call with the lock held."""
        if not self._running:
            return None
        for at, job in enumerate(self._queue):
            if job.project_id not in self._paused:
                return self._queue.pop(at)
        return None

    def _idle_expired(self):
        with self._lock:
            if self._proc is None or self._queue:
                return False
            return time.time() - self._last_activity > IDLE_UNLOAD

    def _run_job(self, job):
        with projects.lock(job.project_id):
            project = projects.load(job.project_id)
            _idx, segment = projects.find_item(project, job.segment_id)
            if segment is None or segment["kind"] != "segment":
                return
            text = projects.effective_text(segment)
            text_hash = segment["text_hash"]
            if not text.strip():
                return
            segment["status"] = "recording"
            projects.save(project)
            events.segment_event(job.project_id, segment)

        proc = self._ensure_worker()
        if proc is None:
            self._release(job, "pending")
            return

        tmp = paths.take_path(job.project_id, job.segment_id, "job-" + job.id) + ".tmp"
        os.makedirs(os.path.dirname(tmp), exist_ok=True)
        engine = voices.request_for(project)
        voice_id, voice_name = voices.label(project)
        request = {
            "cmd": "generate", "job": job.id, "text": text, "out": tmp,
            **engine,
            "retries": (project.get("tts_options") or {}).get("retries", 2),
        }
        if engine["engine"] == "qwen":
            request["temperature"] = (project.get("tts_options") or {}).get("temperature", 0.8)
        try:
            proc.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
            proc.stdin.flush()
        except (BrokenPipeError, ValueError):
            self._release(job, "pending")
            return

        result = self._await_job(job.id)
        self._last_activity = time.time()

        if result is None:                               # killed, or worker died
            self._cleanup_tmp(tmp)
            with self._lock:
                paused_here = job.id in self._interrupted
                self._interrupted.discard(job.id)
                stopping = self._stopping
            if paused_here and not stopping:
                # This project was paused with this very segment inside the
                # model. Nothing was lost: the segment stays queued and the job
                # goes back into the queue, in its usual place, so pressing
                # record again continues rather than skips it.
                self._release(job, "queued")
                with self._lock:
                    self._queue.append(job)
                    self._resort()
            else:
                self._release(job, "pending" if stopping else "failed",
                              None if stopping else "worker exited")
            return
        if result.get("event") == "error":
            self._cleanup_tmp(tmp)
            self._release(job, "failed", result.get("message"))
            return

        self._commit(job, tmp, result, text_hash, request.get("temperature"),
                     voice_id, voice_name)

    def _commit(self, job, tmp, result, text_hash, temperature,
                voice_id=None, voice_name=None):
        with projects.lock(job.project_id):
            project = projects.load(job.project_id)
            _idx, segment = projects.find_item(project, job.segment_id)
            if segment is None:
                self._cleanup_tmp(tmp)
                return
            try:
                takes.append_take(project, segment, tmp,
                                  duration=result.get("seconds") or 0.0,
                                  text_hash=text_hash,
                                  temperature=temperature,
                                  gen_seconds=result.get("gen_seconds"),
                                  voice=voice_id, voice_name=voice_name)
            except OSError as exc:
                self._cleanup_tmp(tmp)
                segment["status"] = "failed"
                segment["error"] = str(exc)
            segment["rerecord"] = False
            projects.save(project)
            events.segment_event(job.project_id, segment,
                                 duration=result.get("seconds"))
            est = estimate.compute(project)
            events.estimate_event(job.project_id, est["eta_seconds"],
                                  est["projected_duration"], est["rate"])

    def _release(self, job, status, error=None):
        """Put a segment back to a resting state after a kill or a failure."""
        with projects.lock(job.project_id):
            try:
                project = projects.load(job.project_id)
            except OSError:
                return
            _idx, segment = projects.find_item(project, job.segment_id)
            if segment is None:
                return
            segment["error"] = error
            if status == "pending":
                projects.sync_status(segment, force=True)
            else:
                segment["status"] = status
            projects.save(project)
            events.segment_event(job.project_id, segment)

    @staticmethod
    def _cleanup_tmp(path):
        try:
            os.remove(path)
        except OSError:
            pass

    # --- worker process ---------------------------------------------------

    def _ensure_worker(self):
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return self._proc
            if self._restarts >= MAX_RESTARTS:
                events.worker_event("error", f"worker failed {MAX_RESTARTS} times")
                self._running = False
                return None

        env = dict(os.environ, PYTHONUNBUFFERED="1")
        proc = subprocess.Popen(
            [sys.executable, WORKER],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", bufsize=1, env=env,
            start_new_session=True)

        with self._lock:
            self._proc = proc
            self._replies = queue.Queue()
            self._stderr_tail = []
            self._reader = threading.Thread(target=self._read_stdout, args=(proc,),
                                            daemon=True, name="tts-stdout")
            self._reader.start()
            self._stderr_reader = threading.Thread(target=self._read_stderr, args=(proc,),
                                                   daemon=True, name="tts-stderr")
            self._stderr_reader.start()

        deadline = time.time() + READY_TIMEOUT
        while time.time() < deadline:
            try:
                msg = self._replies.get(timeout=1.0)
            except queue.Empty:
                if proc.poll() is not None:
                    break
                continue
            if msg.get("event") == "ready":
                with self._lock:
                    self._restarts = 0
                    self._worker_state = "ready"
                events.worker_event("ready")
                return proc
            if msg.get("event") in ("fatal", "exit"):
                break

        with self._lock:
            self._restarts += 1
            tail = " / ".join(self._stderr_tail[-3:])
        self._kill_worker()
        events.worker_event("error", f"worker did not become ready. {tail}".strip())
        return None

    def _read_stdout(self, proc):
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    self._replies.put(json.loads(line))
                except ValueError:
                    pass
        finally:
            self._replies.put({"event": "exit"})

    def _read_stderr(self, proc):
        for line in proc.stderr:
            line = line.rstrip()
            if line:
                with self._lock:
                    self._stderr_tail.append(line)
                    del self._stderr_tail[:-20]

    def _await_job(self, job_id):
        """-> the terminal message for this job, or None if the worker went away."""
        while True:
            try:
                msg = self._replies.get(timeout=1.0)
            except queue.Empty:
                with self._lock:
                    proc, stopping = self._proc, self._stopping
                if stopping or proc is None or proc.poll() is not None:
                    return None
                continue
            if msg.get("event") == "exit":
                return None
            if msg.get("job") != job_id:
                continue
            if msg.get("event") in ("loading", "loaded"):
                # The Qwen model loads on the first clone job, not at start.
                state = "loading" if msg["event"] == "loading" else "ready"
                with self._lock:
                    self._worker_state = state
                events.worker_event(state)
                continue
            if msg.get("event") in ("done", "error"):
                with self._lock:
                    was_loading = self._worker_state == "loading"
                    self._worker_state = "ready"
                if was_loading:                   # the load itself failed
                    events.worker_event("ready")
                return msg

    def _kill_worker(self):
        with self._lock:
            proc, self._proc = self._proc, None
            self._worker_state = "stopped"
        if proc is None or proc.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.kill()
            except OSError:
                pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            try:
                stream.close()
            except (OSError, ValueError):
                pass

    # --- events -----------------------------------------------------------

    def _projects_in_queue(self):
        with self._lock:
            return {j.project_id for j in self._queue}

    def _publish_queue(self, project_id):
        if not project_id:
            return
        with self._lock:
            remaining = sum(1 for j in self._queue if j.project_id == project_id)
            state = ("running" if self._running and project_id not in self._paused
                     else "paused")
            if self._current and self._current.project_id == project_id:
                remaining += 1
        try:
            done = projects.stats(projects.load(project_id))["done"]
        except OSError:
            done = 0
        events.queue_event(project_id, remaining, done, state)


def _marked(project, segment_id):
    _idx, seg = projects.find_item(project, segment_id)
    return bool(seg and seg.get("rerecord"))


runner = Runner()
