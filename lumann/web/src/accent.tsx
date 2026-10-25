// Accent colour. Unlike the language, nothing in React reads this value — it is
// applied as [data-accent] on <html> and the stylesheet does the rest — so it
// needs no context, just the toggle that owns it.
import { useCallback, useEffect, useState } from "react";
import { useI18n } from "./i18n";

export type Accent = "green" | "blue";

const STORAGE_KEY = "lumann.accent";
const SWATCH: Record<Accent, string> = { green: "#4D9537", blue: "#007AFF" };

/** Green unless the user picked blue. */
function stored(): Accent {
  try {
    return localStorage.getItem(STORAGE_KEY) === "blue" ? "blue" : "green";
  } catch {
    return "green";
  }
}

/** Called before the first render so the page never flashes the wrong accent. */
export function applyStoredAccent(): void {
  document.documentElement.dataset.accent = stored();
}

export function AccentToggle() {
  const { t } = useI18n();
  const [accent, setAccent] = useState<Accent>(stored);

  useEffect(() => {
    document.documentElement.dataset.accent = accent;
  }, [accent]);

  const choose = useCallback((next: Accent) => {
    localStorage.setItem(STORAGE_KEY, next);
    setAccent(next);
  }, []);

  return (
    <div className="accent-toggle" title={t("common.accent")}>
      {(Object.keys(SWATCH) as Accent[]).map((name) => (
        <button
          key={name}
          className={name === accent ? "on" : ""}
          style={{ background: SWATCH[name] }}
          onClick={() => choose(name)}
          aria-pressed={name === accent}
          aria-label={t(name === "blue" ? "accent.blue" : "accent.green")}
        />
      ))}
    </div>
  );
}
