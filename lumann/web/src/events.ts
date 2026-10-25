// One EventSource for the whole app, fanned out by event type.
import { useEffect, useRef } from "react";

export interface SegmentEvent {
  type: "segment"; project: string; id: string; status: string;
  active_take: string | null; takes: number; error: string | null; duration?: number;
}
export interface QueueEvent {
  type: "queue"; project: string; remaining: number; done: number; state: string;
}
export interface WorkerEvent {
  type: "worker"; state: "loading" | "ready" | "stopped" | "error"; message: string | null;
}
export interface ComposeEvent {
  type: "compose"; id: string; project: string; status: string;
  progress: number | null; duration?: number; size?: number;
  skipped?: number; error?: string;
}
export interface EstimateEvent {
  type: "estimate"; project: string; eta_seconds: number;
  projected_duration: number; rate: number;
}
export interface ProjectEvent { type: "project"; project: string; action: string }
export interface HelloEvent { type: "hello" }

export type AppEvent =
  | SegmentEvent | QueueEvent | WorkerEvent | ComposeEvent
  | EstimateEvent | ProjectEvent | HelloEvent;

/**
 * Subscribes for the lifetime of the app. The handler is held in a ref so that
 * re-rendering with a new closure does not tear down and rebuild the stream —
 * reconnecting on every keystroke would drop events mid-run.
 */
export function useEventStream(onEvent: (event: AppEvent) => void) {
  const handler = useRef(onEvent);
  handler.current = onEvent;

  useEffect(() => {
    const source = new EventSource("/api/events");
    source.onmessage = (message) => {
      try {
        handler.current(JSON.parse(message.data) as AppEvent);
      } catch {
        /* a malformed frame must not kill the stream */
      }
    };
    // EventSource reconnects on its own; nothing to do but let it.
    source.onerror = () => {};
    return () => source.close();
  }, []);
}
