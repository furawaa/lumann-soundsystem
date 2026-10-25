// One <audio> element for the whole app, and the state a row needs to render
// itself as a player strip while it is the thing being played.
import { useCallback, useMemo, useRef, useState } from "react";

export type Playing =
  | { kind: "segment"; id: string; take: string | null }
  | { kind: "insert"; id: string }
  | { kind: "compose"; id: string };

export interface Player {
  playing: Playing | null;
  paused: boolean;
  time: number;
  duration: number;
  /** Same target -> toggle play/pause. New target -> load and play. */
  play: (target: Playing, src: string) => void;
  seek: (seconds: number) => void;
  skip: (delta: number) => void;
  /** Pause if playing, resume if paused. Does nothing with nothing loaded. */
  toggle: () => void;
  stop: () => void;
  /** Called when a track ends; return true if it started the next one. */
  setAdvance: (fn: ((finished: Playing) => boolean) | null) => void;
  isPlaying: (target: Playing) => boolean;
  bind: {
    ref: React.RefObject<HTMLAudioElement | null>;
    onTimeUpdate: () => void;
    onLoadedMetadata: () => void;
    onPlay: () => void;
    onPause: () => void;
    onEnded: () => void;
  };
}

// A pause has nothing to stream, so it is synthesised as a real WAV of silence
// and played through the same element as everything else. A timer would have
// been less code and a second code path: no scrub bar, no pause, and its own
// idea of when a track has ended.
const silence = new Map<number, string>();

export function silenceUrl(seconds: number): string {
  const secs = Math.round(Math.max(seconds, 0.05) * 100) / 100;
  const cached = silence.get(secs);
  if (cached) return cached;

  const rate = 8000;                       // 8-bit mono at 8 kHz: ~8 KB/s
  const frames = Math.round(rate * secs);
  const bytes = new Uint8Array(44 + frames);
  const view = new DataView(bytes.buffer);
  const ascii = (at: number, text: string) => {
    for (let i = 0; i < text.length; i++) view.setUint8(at + i, text.charCodeAt(i));
  };
  ascii(0, "RIFF");
  view.setUint32(4, 36 + frames, true);
  ascii(8, "WAVEfmt ");
  view.setUint32(16, 16, true);            // fmt chunk size
  view.setUint16(20, 1, true);             // PCM
  view.setUint16(22, 1, true);             // mono
  view.setUint32(24, rate, true);
  view.setUint32(28, rate, true);          // byte rate
  view.setUint16(32, 1, true);             // block align
  view.setUint16(34, 8, true);             // bits per sample
  ascii(36, "data");
  view.setUint32(40, frames, true);
  bytes.fill(128, 44);                     // 8-bit PCM silence is 0x80, not 0

  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  const url = `data:audio/wav;base64,${btoa(binary)}`;
  silence.set(secs, url);
  return url;
}

export function same(a: Playing | null, b: Playing | null): boolean {
  if (!a || !b || a.kind !== b.kind || a.id !== b.id) return false;
  return a.kind === "segment" && b.kind === "segment" ? a.take === b.take : true;
}

export function usePlayer(): Player {
  const ref = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState<Playing | null>(null);
  const [paused, setPaused] = useState(true);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);

  // What is loaded right now, tracked outside React state: `play` must not put
  // side effects in a setState updater, which StrictMode invokes twice — a
  // toggle would fire twice and cancel itself out.
  const current = useRef<Playing | null>(null);

  const play = useCallback((target: Playing, src: string) => {
    const el = ref.current;
    if (!el) return;
    if (same(current.current, target)) {
      if (el.paused) void el.play().catch(() => {});
      else el.pause();
      return;
    }
    current.current = target;
    setPlaying(target);
    setTime(0);
    setDuration(0);
    el.src = src;
    el.currentTime = 0;
    void el.play().catch(() => {});
  }, []);

  const seek = useCallback((seconds: number) => {
    const el = ref.current;
    if (!el || !isFinite(el.duration)) return;
    el.currentTime = Math.min(Math.max(seconds, 0), el.duration);
    setTime(el.currentTime);
  }, []);

  const skip = useCallback((delta: number) => {
    const el = ref.current;
    if (el) seek(el.currentTime + delta);
  }, [seek]);

  const toggle = useCallback(() => {
    const el = ref.current;
    if (!el || !current.current) return;
    if (el.paused) void el.play().catch(() => {});
    else el.pause();
  }, []);

  // Set by the "play all" controls. Kept in a ref so the <audio> handlers never
  // hold a stale closure over the track list.
  const advance = useRef<((finished: Playing) => boolean) | null>(null);
  const setAdvance = useCallback(
    (fn: ((finished: Playing) => boolean) | null) => { advance.current = fn; }, []);

  const stop = useCallback(() => {
    ref.current?.pause();
    current.current = null;
    setPlaying(null);
  }, []);

  const isPlaying = useCallback(
    (target: Playing) => same(playing, target), [playing]);

  return useMemo(() => ({
    playing, paused, time, duration, play, seek, skip, toggle, stop, isPlaying,
    setAdvance,
    bind: {
      ref,
      onTimeUpdate: () => setTime(ref.current?.currentTime ?? 0),
      onLoadedMetadata: () => {
        const d = ref.current?.duration;
        setDuration(d && isFinite(d) ? d : 0);
      },
      onPlay: () => setPaused(false),
      onPause: () => setPaused(true),
      onEnded: () => {
        const finished = current.current;
        if (finished && advance.current?.(finished)) return;   // sequence goes on
        current.current = null;
        setPlaying(null);
        setPaused(true);
      },
    },
  }), [playing, paused, time, duration, play, seek, skip, toggle, stop, isPlaying,
       setAdvance]);
}
