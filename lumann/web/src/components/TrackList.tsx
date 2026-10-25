import { useEffect, useMemo, useRef, useState } from "react";
import {
  api, isSegment, playable, segmentDownloadUrl, takeDownloadUrl,
  type Insert, type Item, type Sample, type Segment, type Take,
} from "../api";
import { clock, pad4, takeStamp } from "../format";
import { useI18n } from "../i18n";
import type { Player } from "../player";
import { PlayerBar } from "./PlayerBar";

type Edge = "before" | "after";

interface Props {
  items: Item[];
  selected: string | null;
  player: Player;
  samples: Sample[];
  onSelect: (id: string) => void;
  /** The project's voice right now: a take from a different one says so. */
  currentVoice: string | null;
  onPlaySegment: (segment: Segment) => void;
  onPlayInsert: (insert: Insert) => void;
  onPlayTake: (segment: Segment, take: Take) => void;
  onChanged: () => void;
  onEditText: (segment: Segment) => void;
  onInsertAfter: (segment: Segment) => void;
}

export function TrackList(props: Props) {
  const { t } = useI18n();
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [takes, setTakes] = useState<Record<string, Take[]>>({});
  const [menu, setMenu] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);

  // --- dragging an insert to a new place ----------------------------------
  //
  // Refs and hand-placed classes rather than state, deliberately: dragover
  // fires continuously, and re-rendering a list of five hundred rows for each
  // event turns the drag into a slideshow. Nothing here outlives the drag.
  const dragging = useRef<string | null>(null);
  const dropAt = useRef<{ id: string; edge: Edge } | null>(null);

  /** Where an insert lands if dropped on `id`: after_id for the PATCH. */
  const previousId = useMemo(() => {
    const map = new Map<string, string>();
    props.items.forEach((item, at) => map.set(item.id, at === 0 ? "" : props.items[at - 1].id));
    return map;
  }, [props.items]);

  function paintDrop(next: { id: string; edge: Edge } | null) {
    const was = dropAt.current;
    if (was?.id === next?.id && was?.edge === next?.edge) return;
    if (was) {
      const node = listRef.current?.querySelector(`[data-row="${was.id}"]`);
      node?.classList.remove("drop-before", "drop-after");
    }
    if (next) {
      const node = listRef.current?.querySelector(`[data-row="${next.id}"]`);
      node?.classList.add(next.edge === "before" ? "drop-before" : "drop-after");
    }
    dropAt.current = next;
  }

  function onDragOver(event: React.DragEvent) {
    if (!dragging.current) return;
    event.preventDefault();                       // without this there is no drop
    event.dataTransfer.dropEffect = "move";
    const row = (event.target as HTMLElement).closest?.("[data-row]") as HTMLElement | null;
    const id = row?.dataset.row;
    if (!row || !id || id === dragging.current) {
      paintDrop(null);
      return;
    }
    const box = row.getBoundingClientRect();
    paintDrop({ id, edge: event.clientY < box.top + box.height / 2 ? "before" : "after" });
  }

  async function onDrop(event: React.DragEvent) {
    event.preventDefault();
    const id = dragging.current;
    const target = dropAt.current;
    endDrag();
    if (!id || !target) return;

    const afterId = target.edge === "after" ? target.id : previousId.get(target.id) ?? "";
    // Dropping an insert back where it already sits.
    if (afterId === id) return;
    await api.patchInsert(id, { after_id: afterId });
    props.onChanged();
  }

  function endDrag() {
    paintDrop(null);
    dragging.current = null;
  }

  // Keep the selected row visible when selection comes from the text panel or
  // the keyboard rather than from a click in here.
  useEffect(() => {
    if (!props.selected) return;
    const node = listRef.current?.querySelector(`[data-row="${props.selected}"]`);
    node?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [props.selected]);

  // The ⋯ menu hangs below its row, so an open one covers the next row's
  // buttons and eats their clicks. It has to close on anything else happening.
  useEffect(() => {
    if (!menu) return;
    const close = (event: Event) => {
      const target = event.target as HTMLElement;
      // The trigger is exempt: closing here and letting its own handler toggle
      // would immediately re-open the menu, so a second click never shuts it.
      if (target?.closest?.(".menu") || target?.closest?.(".menu-trigger")) return;
      setMenu(null);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenu(null);
    };
    document.addEventListener("pointerdown", close, true);
    document.addEventListener("keydown", onKey);
    listRef.current?.addEventListener("scroll", close);
    const list = listRef.current;
    return () => {
      document.removeEventListener("pointerdown", close, true);
      document.removeEventListener("keydown", onKey);
      list?.removeEventListener("scroll", close);
    };
  }, [menu]);

  async function toggleTakes(segment: Segment) {
    const next = new Set(open);
    if (next.has(segment.id)) {
      next.delete(segment.id);
    } else {
      next.add(segment.id);
      setTakes((prev) => ({ ...prev, [segment.id]: segment.takes ?? [] }));
      const listing = await api.takes(segment.id);
      setTakes((prev) => ({ ...prev, [segment.id]: listing }));
    }
    setOpen(next);
  }

  async function refreshTakes(segmentId: string) {
    if (!open.has(segmentId)) return;
    const listing = await api.takes(segmentId);
    setTakes((prev) => ({ ...prev, [segmentId]: listing }));
  }

  async function promote(segment: Segment, take: Take) {
    if (take.outdated) {
      if (!window.confirm(t("take.promoteOutdated", { n: take.n }))) return;
    }
    await api.promoteTake(segment.id, take.id);
    await refreshTakes(segment.id);
    props.onChanged();
  }

  async function removeTake(segment: Segment, take: Take) {
    if (take.active) return;
    if (!window.confirm(t("take.deleteConfirm", { n: take.n }))) return;
    await api.deleteTake(segment.id, take.id);
    await refreshTakes(segment.id);
    props.onChanged();
  }

  return (
    <div
      className="tracks"
      ref={listRef}
      onDragOver={onDragOver}
      onDrop={onDrop}
      onDragEnd={endDrag}
      onDragLeave={(event) => {
        // Only when the pointer actually leaves the list, not on every hop
        // between the rows inside it.
        if (!listRef.current?.contains(event.relatedTarget as Node)) paintDrop(null);
      }}
    >
      {props.items.map((item) =>
        isSegment(item)
          ? (
            <SegmentRow
              key={item.id}
              segment={item}
              selected={props.selected === item.id}
              player={props.player}
              expanded={open.has(item.id)}
              takes={takes[item.id] ?? item.takes ?? []}
              currentVoice={props.currentVoice}
              menuOpen={menu === item.id}
              onMenu={() => setMenu(menu === item.id ? null : item.id)}
              onCloseMenu={() => setMenu(null)}
              onToggleTakes={() => toggleTakes(item)}
              onSelect={() => props.onSelect(item.id)}
              onPlay={() => props.onPlaySegment(item)}
              onPlayTake={(take) => props.onPlayTake(item, take)}
              onPromote={(take) => promote(item, take)}
              onDeleteTake={(take) => removeTake(item, take)}
              onChanged={props.onChanged}
              onEditText={() => props.onEditText(item)}
              onInsertAfter={() => props.onInsertAfter(item)}
            />
          )
          : (
            <InsertRow
              key={item.id}
              insert={item}
              samples={props.samples}
              selected={props.selected === item.id}
              player={props.player}
              onSelect={() => props.onSelect(item.id)}
              onPlay={() => props.onPlayInsert(item)}
              onChanged={props.onChanged}
              onDragStart={() => { dragging.current = item.id; }}
              onDragEnd={endDrag}
            />
          ))}
    </div>
  );
}

function SegmentRow(props: {
  segment: Segment;
  selected: boolean;
  player: Player;
  expanded: boolean;
  takes: Take[];
  currentVoice: string | null;
  menuOpen: boolean;
  onMenu: () => void;
  onCloseMenu: () => void;
  onToggleTakes: () => void;
  onSelect: () => void;
  onPlay: () => void;
  onPlayTake: (take: Take) => void;
  onPromote: (take: Take) => void;
  onDeleteTake: (take: Take) => void;
  onChanged: () => void;
  onEditText: () => void;
  onInsertAfter: () => void;
}) {
  const { t, lang } = useI18n();
  const s = props.segment;
  // Chevron whenever there is anything to disclose, not only for re-recorded
  // segments: an invisible affordance is one nobody finds.
  const hasTakes = s.take_count > 0;
  const active: import("../player").Playing = { kind: "segment", id: s.id, take: null };
  const isPlaying = props.player.isPlaying(active);
  const activeTake = (s.takes ?? []).find((take) => take.id === s.active_take);
  // A row with no audio at all. It still occupies a place in the list, so it
  // has to say why it is silent rather than just looking like the others.
  const silent = !s.active_take && s.status !== "recording" && s.status !== "queued";

  async function toggle(field: "favorite" | "rerecord") {
    await api.patchSegment(s.id, { [field]: !s[field] });
    props.onChanged();
  }

  return (
    <>
      <div
        data-row={s.id}
        className={`row track ${props.selected ? "selected" : ""} ${s.status}`}
        onClick={props.onSelect}
      >
        <button
          className={`chev ${hasTakes ? "" : "hidden"} ${props.expanded ? "open" : ""}`}
          onClick={(event) => { event.stopPropagation(); props.onToggleTakes(); }}
          title={props.expanded ? t("track.hideTakes") : t("track.takes", { n: s.take_count })}
          aria-label={props.expanded ? t("track.hideTakes") : t("track.showTakes")}
          aria-expanded={props.expanded}
        >
          ▸
        </button>

        <span
          className={`idx ${s.moved ? "moved" : ""}`}
          title={s.moved ? t("track.movedTitle") : undefined}
        >
          {pad4(s.index)}
        </span>

        <button
          className={`play ${isPlaying ? "on" : ""}`}
          disabled={!s.active_take}
          onClick={(event) => { event.stopPropagation(); props.onPlay(); }}
          aria-label={t("track.play")}
        >
          {isPlaying && !props.player.paused ? "❙❙" : "▶"}
        </button>

        {isPlaying
          ? <PlayerBar player={props.player} />
          : <span className="track-text">{s.effective_text || s.text}</span>}

        <span className="track-meta">
          {s.status === "recording" && <span className="tag recording">{t("track.recording")}</span>}
          {s.status === "queued" && <span className="tag queued">{t("track.queued")}</span>}
          {s.status === "stale" && <span className="tag stale">{t("track.staleTag")}</span>}
          {s.status === "failed" && (
            <span className="tag failed" title={s.error ?? ""}>{t("track.failedTag")}</span>
          )}
          {s.rerecord && <span className="tag rerecord" title={t("track.markRerecord")}>⟳</span>}
          {silent && (
            <button
              className="tag notrec"
              title={t("track.recordThis")}
              onClick={(event) => {
                event.stopPropagation();
                api.requeue(s.id).then(props.onChanged);
              }}
            >
              {t("track.notRecorded")}
            </button>
          )}
          {s.text_override && <span className="tag override">{t("track.overrideTag")}</span>}
          {s.take_count > 1 && (
            <button
              className="takes-count"
              onClick={(event) => { event.stopPropagation(); props.onToggleTakes(); }}
              title={props.expanded ? t("track.hideTakes") : t("track.showTakes")}
            >
              {t("track.takes", { n: s.take_count })}
            </button>
          )}
          {activeTake?.duration ? (
            <span className="track-dur">{clock(activeTake.duration)}</span>
          ) : null}
        </span>

        <button
          className={`icon fav ${s.favorite ? "on" : ""}`}
          onClick={(event) => { event.stopPropagation(); toggle("favorite"); }}
          title={t("track.favorite")}
        >
          ♥
        </button>
        <button
          className={`icon rec ${s.rerecord ? "on" : ""}`}
          onClick={(event) => { event.stopPropagation(); toggle("rerecord"); }}
          title={t("track.markRerecord")}
        >
          ⟳
        </button>
        <button
          className="icon menu-trigger"
          onClick={(event) => { event.stopPropagation(); props.onMenu(); }}
          title={t("track.more")}
        >
          ⋯
        </button>

        {props.menuOpen && (
          <div className="menu" onClick={(event) => event.stopPropagation()}>
            <button onClick={() => { props.onCloseMenu(); api.requeue(s.id).then(props.onChanged); }}>
              {t("menu.rerecordNow")}
            </button>
            <button onClick={() => { props.onCloseMenu(); props.onEditText(); }}>
              {t("menu.editText")}
            </button>
            <button onClick={() => { props.onCloseMenu(); props.onInsertAfter(); }}>
              {t("menu.insertAfter")}
            </button>
            <button
              disabled={!s.active_take}
              onClick={() => {
                props.onCloseMenu();
                window.location.href = segmentDownloadUrl(s.id);
              }}
            >
              {t("menu.download")}
            </button>
          </div>
        )}
      </div>

      {props.expanded && props.takes.map((take) => {
        const target: import("../player").Playing =
          { kind: "segment", id: s.id, take: take.id };
        const playing = props.player.isPlaying(target);
        return (
          <div key={take.id} className={`row take ${take.outdated ? "outdated" : ""}`}>
            <span className="chev hidden" />
            <span className="idx" />
            <button
              className={`play ${playing ? "on" : ""}`}
              onClick={() => props.onPlayTake(take)}
              aria-label={t("track.playTake")}
            >
              {playing && !props.player.paused ? "❙❙" : "▶"}
            </button>
            {playing
              ? <PlayerBar player={props.player} />
              : (
                <span className="take-label">
                  {t("take.label", { n: take.n })} · {takeStamp(take.created_at, lang)}
                  {take.duration ? ` · ${clock(take.duration)}` : ""}
                  {take.note ? ` · ${take.note}` : ""}
                </span>
              )}
            <span className="track-meta">
              {take.voice_name && take.voice !== props.currentVoice && (
                <span className="tag voice">{t("take.voice", { name: take.voice_name })}</span>
              )}
              {take.outdated && <span className="tag older">{t("take.older")}</span>}
            </span>
            {take.active
              ? <span className="active-mark" title={t("take.activeTitle")}>✓</span>
              : (
                <button className="link small" onClick={() => props.onPromote(take)}>
                  {t("take.makeActive")}
                </button>
              )}
            <a
              className="icon"
              href={takeDownloadUrl(take.id)}
              title={t("menu.download")}
              onClick={(event) => event.stopPropagation()}
            >
              ↓
            </a>
            <button
              className="icon"
              disabled={take.active}
              title={take.active ? t("take.deleteActiveTitle") : t("take.delete")}
              onClick={() => props.onDeleteTake(take)}
            >
              ✕
            </button>
          </div>
        );
      })}
    </>
  );
}

function InsertRow(props: {
  insert: Insert;
  samples: Sample[];
  selected: boolean;
  player: Player;
  onSelect: () => void;
  onPlay: () => void;
  onChanged: () => void;
  onDragStart: () => void;
  onDragEnd: () => void;
}) {
  const { t } = useI18n();
  const i = props.insert;
  const [seconds, setSeconds] = useState(String(i.seconds ?? 1));
  // The row is only draggable while the grip is held. Marking it draggable
  // outright would cost the row its text selection and let a stray drag start
  // from the seconds field or the sample menu.
  const [armed, setArmed] = useState(false);
  const [lifted, setLifted] = useState(false);
  const isPlaying = props.player.isPlaying({ kind: "insert", id: i.id });

  useEffect(() => { setSeconds(String(i.seconds ?? 1)); }, [i.seconds]);

  return (
    <div
      data-row={i.id}
      className={`row insert ${props.selected ? "selected" : ""} ${lifted ? "dragging" : ""}`}
      onClick={props.onSelect}
      draggable={armed}
      onDragStart={(event) => {
        // Firefox starts no drag at all without payload; the list itself reads
        // the id from the ref, not from here.
        event.dataTransfer.setData("text/plain", i.id);
        event.dataTransfer.effectAllowed = "move";
        setLifted(true);
        props.onDragStart();
      }}
      onDragEnd={() => { setArmed(false); setLifted(false); props.onDragEnd(); }}
    >
      <button
        className="grip"
        title={t("insert.drag")}
        aria-label={t("insert.drag")}
        onMouseDown={() => setArmed(true)}
        onMouseUp={() => setArmed(false)}
        onClick={(event) => event.stopPropagation()}
      >
        ☰
      </button>
      <span className="idx">◆</span>
      <button
        className={`play ${isPlaying ? "on" : ""}`}
        disabled={!playable(i)}
        onClick={(event) => { event.stopPropagation(); props.onPlay(); }}
        aria-label={t("insert.preview")}
      >
        {isPlaying && !props.player.paused ? "❙❙" : "▶"}
      </button>

      {isPlaying
        ? <PlayerBar player={props.player} />
        : (
          <span className="track-text">
            {i.insert_type === "silence"
              ? (
                <>
                  {t("insert.pause")}{" "}
                  <input
                    className="inline-number"
                    type="number"
                    min="0"
                    step="0.1"
                    value={seconds}
                    onClick={(event) => event.stopPropagation()}
                    onChange={(event) => setSeconds(event.target.value)}
                    onBlur={() =>
                      api.patchInsert(i.id, { seconds: Number(seconds) }).then(props.onChanged)}
                  />{" "}
                  {t("insert.seconds")}
                </>
              )
              : (
                <select
                  className="inline-select"
                  value={i.sample ?? ""}
                  onClick={(event) => event.stopPropagation()}
                  onChange={(event) =>
                    api.patchInsert(i.id, { sample: event.target.value }).then(props.onChanged)}
                >
                  {props.samples.every((sample) => sample.name !== i.sample) && (
                    <option value={i.sample ?? ""}>{i.sample} {t("insert.missingFile")}</option>
                  )}
                  {props.samples.map((sample) => (
                    <option key={sample.name} value={sample.name}>{sample.name}</option>
                  ))}
                </select>
              )}
          </span>
        )}

      <span className="track-meta">{clock(i.duration)}</span>
      <button
        className="icon"
        onClick={(event) => {
          event.stopPropagation();
          api.deleteInsert(i.id).then(props.onChanged);
        }}
        title={t("insert.delete")}
      >
        ✕
      </button>
    </div>
  );
}
