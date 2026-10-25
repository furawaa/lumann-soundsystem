"""In-memory pub/sub feeding the single SSE stream.

Publishers are mostly background threads (the runner, the compose worker);
subscribers are asyncio generators. Everything crossing that boundary goes
through `loop.call_soon_threadsafe`.

No websockets: the dependency is not installed and this is one-way push.
"""
import asyncio
import collections
import threading

MAX_QUEUE = 1000          # a slow browser tab must not grow memory without bound
HISTORY = 50              # replayed to a client that reconnects mid-run


class EventBus:
    def __init__(self):
        self._subscribers = set()
        self._lock = threading.Lock()
        self._loop = None
        self._history = collections.deque(maxlen=HISTORY)
        self._seq = 0

    def bind(self, loop) -> None:
        """Called once from the server's startup hook."""
        self._loop = loop

    def publish(self, payload: dict) -> None:
        """Thread-safe. Never raises — a dead subscriber must not fail a job."""
        with self._lock:
            self._seq += 1
            event = {"seq": self._seq, **payload}
            self._history.append(event)
            targets = list(self._subscribers)
            loop = self._loop
        if loop is None:
            return
        for queue in targets:
            try:
                loop.call_soon_threadsafe(self._offer, queue, event)
            except RuntimeError:                  # loop already closed
                pass

    @staticmethod
    def _offer(queue: asyncio.Queue, event: dict) -> None:
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            pass

    def history(self):
        with self._lock:
            return list(self._history)

    def subscribe(self) -> asyncio.Queue:
        queue = asyncio.Queue(maxsize=MAX_QUEUE)
        with self._lock:
            self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers.discard(queue)


bus = EventBus()


def segment_event(project_id, segment, **extra):
    return bus.publish({
        "type": "segment",
        "project": project_id,
        "id": segment["id"],
        "status": segment["status"],
        "active_take": segment.get("active_take"),
        "takes": len(segment.get("takes") or []),
        "error": segment.get("error"),
        **extra,
    })


def queue_event(project_id, remaining, done, state):
    return bus.publish({"type": "queue", "project": project_id,
                        "remaining": remaining, "done": done, "state": state})


def worker_event(state, message=None):
    return bus.publish({"type": "worker", "state": state, "message": message})


def compose_event(compose_id, project_id, status, progress=None, **extra):
    return bus.publish({"type": "compose", "id": compose_id, "project": project_id,
                        "status": status, "progress": progress, **extra})


def estimate_event(project_id, eta_seconds, projected_duration, rate):
    return bus.publish({"type": "estimate", "project": project_id,
                        "eta_seconds": eta_seconds,
                        "projected_duration": projected_duration,
                        "rate": rate})


def project_event(project_id, action):
    return bus.publish({"type": "project", "project": project_id, "action": action})
