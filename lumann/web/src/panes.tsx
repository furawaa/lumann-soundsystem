// Pane widths. Kept in px rather than fractions: the user drags a real edge, and
// a fraction would move that edge again the next time the window is resized.
import { useCallback, useEffect, useState } from "react";
import { useI18n } from "./i18n";

const STORAGE_KEY = "lumann.panes";
export const DEFAULT_PANES: [number, number] = [220, 560];

const LIMITS = { sidebar: [150, 420], middle: [280, 1200] } as const;

function clamp(value: number, [min, max]: readonly [number, number]) {
  return Math.min(max, Math.max(min, value));
}

function stored(): [number, number] {
  try {
    const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "");
    if (Array.isArray(raw) && raw.length === 2 && raw.every((n) => typeof n === "number")) {
      return [clamp(raw[0], LIMITS.sidebar), clamp(raw[1], LIMITS.middle)];
    }
  } catch { /* nothing stored, or stored by an older version */ }
  return DEFAULT_PANES;
}

export function usePanes() {
  const [panes, setPanes] = useState<[number, number]>(stored);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(panes));
  }, [panes]);

  const setSidebar = useCallback(
    (width: number) => setPanes(([, m]) => [clamp(width, LIMITS.sidebar), m]), []);
  const setMiddle = useCallback(
    (width: number) => setPanes(([s]) => [s, clamp(width, LIMITS.middle)]), []);
  const reset = useCallback(() => setPanes(DEFAULT_PANES), []);

  return { sidebar: panes[0], middle: panes[1], setSidebar, setMiddle, reset };
}

/**
 * A 5px grid column you can drag. Pointer capture means the drag survives the
 * cursor leaving the divider, which it will — people drag fast.
 */
export function Divider(props: {
  width: number;
  onChange: (width: number) => void;
  onReset: () => void;
}) {
  const { t } = useI18n();

  const down = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = props.width;
    const target = event.currentTarget;
    target.setPointerCapture(event.pointerId);
    document.body.classList.add("resizing");

    const move = (moved: PointerEvent) =>
      props.onChange(startWidth + moved.clientX - startX);
    const up = () => {
      target.removeEventListener("pointermove", move);
      target.removeEventListener("pointerup", up);
      target.removeEventListener("pointercancel", up);
      document.body.classList.remove("resizing");
    };
    target.addEventListener("pointermove", move);
    target.addEventListener("pointerup", up);
    target.addEventListener("pointercancel", up);
  }, [props]);

  return (
    <div
      className="divider"
      onPointerDown={down}
      onDoubleClick={props.onReset}
      title={t("text.resetPanes")}
      role="separator"
      aria-orientation="vertical"
    />
  );
}
