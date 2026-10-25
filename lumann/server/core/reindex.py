"""Re-indexing: fit an existing timeline onto a re-formatted source.

This is the part that silently destroys work if it is wrong. A segment carries
its id, its tags and its entire take history; those travel by identity, never by
position. Nothing here writes — `plan_reindex` produces a preview, and only
`apply_reindex` commits, after the user has looked at it.

Two markers come out of this and they mean different things:

  moved   — the ordinal changed, the text did not. Audio is still valid.
  changed — the text changed. Existing takes become outdated and the segment
            goes stale; the audio stays playable so the user can hear what it
            used to say.
"""
import difflib
import os
import shutil

from . import paths, projects, textprep
from .segmenter import build_segments


def _pair(old_norm, new_norm):
    """-> {new_index: old_index} for every segment that carries over.

    Three passes, most confident first:

      1. difflib's `equal` runs — the structural backbone.
      2. Exact text matches among everything still unpaired, in order. This pass
         is what makes reordering free: difflib reports a swapped
         pair as insert+delete, and taking that literally would move a
         perfectly good take to _trash and re-record identical text. Anything
         whose text survives verbatim keeps its audio, wherever it landed.
      3. Positional 1:1 inside each `replace` run, for the genuine rewrites.
    """
    matcher = difflib.SequenceMatcher(a=old_norm, b=new_norm, autojunk=False)
    opcodes = matcher.get_opcodes()

    pairing = {}
    used_old = set()

    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            for k in range(i2 - i1):
                pairing[j1 + k] = i1 + k
                used_old.add(i1 + k)

    free_old_by_text = {}
    for i, text in enumerate(old_norm):
        if i not in used_old:
            free_old_by_text.setdefault(text, []).append(i)
    for j, text in enumerate(new_norm):
        if j in pairing:
            continue
        bucket = free_old_by_text.get(text)
        if bucket:
            old_index = bucket.pop(0)
            pairing[j] = old_index
            used_old.add(old_index)

    for tag, i1, i2, j1, j2 in opcodes:
        if tag != "replace":
            continue
        olds = [i for i in range(i1, i2) if i not in used_old]
        news = [j for j in range(j1, j2) if j not in pairing]
        for j, i in zip(news, olds):          # 1:1 as far as the shorter side goes
            pairing[j] = i
            used_old.add(i)

    return pairing


def _anchor_map(timeline):
    """For every insert, which segment id it currently follows (None = start)."""
    anchors = {}
    last_segment = None
    for item in timeline:
        if item["kind"] == "segment":
            last_segment = item["id"]
        else:
            anchors[item["id"]] = last_segment
    return anchors


def _carry(old_seg, new_seg, changed, drop_override=False):
    """Copy a new segmenter output onto an existing segment, keeping identity."""
    item = dict(old_seg)
    if drop_override:
        # The edited formatted text already contains the override inline, so
        # keeping it would make it win over the very edit that produced it.
        item["text_override"] = None
    item["line"] = new_seg["line"]
    item["char_start"] = new_seg["char_start"]
    item["char_end"] = new_seg["char_end"]
    item["text"] = new_seg["text"]
    projects.refresh_hash(item)          # honours text_override
    if changed:
        item["error"] = None
    projects.sync_status(item)
    return item


def plan_reindex(project, new_source, fmt=None, preformatted=False):
    """-> (preview, staged) where `staged` is what apply_reindex would commit.

    Nothing is written. `staged` holds the new timeline, the new formatted text
    and the segments that would be deleted.

    `preformatted` means the text came from the formatted view rather than the
    source: adapt() is skipped and source.txt is left alone, because the
    original is the record of what was imported and no longer the input.
    """
    opts = dict(project.get("format_options") or {})
    if fmt:
        opts.update({k: v for k, v in fmt.items() if v is not None})
    from .segmenter import format_options
    opts = format_options(opts)

    formatted, new_segs = build_segments(new_source, preformatted=preformatted, **opts)
    old_segs = projects.segments(project)
    anchors = _anchor_map(project["timeline"])
    inserts = {i["id"]: i for i in project["timeline"] if i["kind"] == "insert"}

    old_norm = [textprep.norm(projects.effective_text(s)) for s in old_segs]
    new_norm = [textprep.norm(s["text"]) for s in new_segs]
    pairing = _pair(old_norm, new_norm)

    result = []          # new segment items, in order
    entries = []         # per-segment preview rows
    deleted = []

    for new_index, new_seg in enumerate(new_segs):
        old_index = pairing.get(new_index)
        if old_index is None:
            item = projects.make_segment(new_seg)
            result.append(item)
            entries.append(_entry("new", item, None, new_index))
            continue

        old_seg = old_segs[old_index]
        before = old_seg.get("text_hash")
        item = _carry(old_seg, new_seg, old_norm[old_index] != new_norm[new_index],
                      drop_override=preformatted)
        hash_changed = item.get("text_hash") != before
        override_conflict = bool(
            not preformatted and old_seg.get("text_override")
            and textprep.canonical(old_seg["text"]) != textprep.canonical(new_seg["text"]))

        if hash_changed:
            kind = "changed"
        elif old_index != new_index:
            kind = "moved"
        else:
            kind = "unchanged"
        item["moved"] = (kind == "moved")
        result.append(item)
        entries.append(_entry(kind, item, old_index, new_index,
                              override_conflict=override_conflict))

    carried = set(pairing.values())
    for old_index, old_seg in enumerate(old_segs):
        if old_index not in carried:
            deleted.append(old_seg)
            entries.append(_entry("deleted", old_seg, old_index, None))

    timeline, insert_notes = _weave_inserts(result, inserts, anchors,
                                            [s["id"] for s in old_segs])

    preview = {
        "counts": _counts(entries),
        "segments": entries,
        "inserts": insert_notes,
        "format_options": opts,
        "formatted_length": len(formatted),
    }
    staged = {
        "timeline": timeline,
        "formatted": formatted,
        "source": new_source,
        "format_options": opts,
        "deleted": [s["id"] for s in deleted],
        "preformatted": preformatted,
    }
    return preview, staged


def _entry(kind, item, old_index, new_index, override_conflict=False):
    takes = len(item.get("takes") or [])
    row = {
        "kind": kind,
        "id": item["id"],
        "old_index": old_index,
        "new_index": new_index,
        "text": (item.get("text_override") or item.get("text") or "")[:160],
        "takes": takes,
        "has_audio": bool(item.get("active_take")),
        "favorite": bool(item.get("favorite")),
    }
    if override_conflict:
        row["override_conflict"] = True
    return row


def _counts(entries):
    counts = {"unchanged": 0, "moved": 0, "changed": 0, "new": 0, "deleted": 0,
              "changed_with_audio": 0, "deleted_with_audio": 0, "override_conflict": 0}
    for e in entries:
        counts[e["kind"]] = counts.get(e["kind"], 0) + 1
        if e["kind"] == "changed" and e["has_audio"]:
            counts["changed_with_audio"] += 1
        if e["kind"] == "deleted" and e["has_audio"]:
            counts["deleted_with_audio"] += 1
        if e.get("override_conflict"):
            counts["override_conflict"] += 1
    return counts


def _weave_inserts(segments_new, inserts, anchors, old_order):
    """Put inserts back where they were, relative to the segment they followed.

    If that segment is gone, the insert falls back to the nearest earlier
    segment that survived, and is flagged — a sound effect that silently moved
    somewhere else in a 70-minute book is very hard to notice.
    """
    surviving = {s["id"] for s in segments_new}
    after = {}          # segment id (or None, meaning "before everything") -> [inserts]
    notes = []

    for insert_id, item in inserts.items():
        anchor = anchors.get(insert_id)
        note = {"id": insert_id, "insert_type": item.get("insert_type"),
                "anchor": anchor, "review": False}
        if anchor is None or anchor in surviving:
            target = anchor
        else:
            target = _previous_surviving(anchor, old_order, surviving)
            note["review"] = True
            note["reattached_to"] = target
        after.setdefault(target, []).append(item)
        notes.append(note)

    timeline = list(after.get(None, []))
    for seg in segments_new:
        timeline.append(seg)
        timeline.extend(after.get(seg["id"], []))
    return timeline, notes


def _previous_surviving(anchor, old_order, surviving):
    """Nearest segment before `anchor` in the old order that still exists.

    None means the start of the book — every earlier segment was deleted too.
    """
    try:
        pos = old_order.index(anchor)
    except ValueError:
        return None
    for earlier in reversed(old_order[:pos]):
        if earlier in surviving:
            return earlier
    return None


def apply_reindex(project, staged):
    """Commit a staged plan. Deleted audio goes to _trash/, not to /dev/null."""
    pid = project["id"]
    for seg_id in staged["deleted"]:
        src = paths.segment_dir(pid, seg_id)
        if os.path.isdir(src):
            os.makedirs(paths.trash_dir(pid), exist_ok=True)
            dst = os.path.join(paths.trash_dir(pid), seg_id)
            shutil.rmtree(dst, ignore_errors=True)
            shutil.move(src, dst)

    project["timeline"] = staged["timeline"]
    project["format_options"] = staged["format_options"]
    if not staged.get("preformatted"):
        projects._write_atomic(paths.source_txt(pid), staged["source"])
    projects._write_atomic(paths.formatted_txt(pid), staged["formatted"])
    projects.save(project)
    projects.log_event(pid, "reindex", deleted=len(staged["deleted"]),
                       segments=len([i for i in staged["timeline"] if i["kind"] == "segment"]))
    return project
