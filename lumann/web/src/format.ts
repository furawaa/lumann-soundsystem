import type { Lang, Translate } from "./i18n";

export function clock(seconds: number | null | undefined): string {
  if (seconds == null || !isFinite(seconds)) return "—";
  const total = Math.max(0, Math.round(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h > 0
    ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
    : `${m}:${String(s).padStart(2, "0")}`;
}

/** Long durations read better as "2 h 12 min" than as a running clock. */
export function humanDuration(seconds: number | null | undefined, t: Translate): string {
  if (seconds == null || !isFinite(seconds)) return t("unit.none");
  if (seconds < 60) return t("unit.seconds", { n: Math.round(seconds) });
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return t("unit.minutes", { n: minutes });
  return t("unit.hours", { h: Math.floor(minutes / 60), m: minutes % 60 });
}

export function bytes(n: number | null | undefined, t: Translate): string {
  if (!n) return t("unit.mb", { n: 0 });
  const mb = n / (1024 * 1024);
  return mb >= 1024
    ? t("unit.gb", { n: (mb / 1024).toFixed(1) })
    : t("unit.mb", { n: mb.toFixed(mb < 10 ? 1 : 0) });
}

/** "14:32" for today, "29.07 14:32" otherwise. */
export function takeStamp(iso: string, lang: Lang): string {
  const date = new Date(iso.endsWith("Z") ? iso : iso + "Z");
  if (isNaN(date.getTime())) return iso;
  const locale = lang === "ru" ? "ru-RU" : "en-GB";
  const time = date.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
  const today = new Date();
  const sameDay = date.getFullYear() === today.getFullYear()
    && date.getMonth() === today.getMonth()
    && date.getDate() === today.getDate();
  if (sameDay) return time;
  const day = String(date.getDate()).padStart(2, "0");
  const month = String(date.getMonth() + 1).padStart(2, "0");
  return `${day}.${month} ${time}`;
}

export const pad4 = (n: number) => String(n).padStart(4, "0");
