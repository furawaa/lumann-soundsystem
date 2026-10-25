// The strip that replaces a row's title while that row is playing:
// -5 s, a click-anywhere scrub track, +5 s.
import { clock } from "../format";
import { useI18n } from "../i18n";
import type { Player } from "../player";

export function PlayerBar({ player }: { player: Player }) {
  const { t } = useI18n();
  const duration = player.duration;
  const progress = duration > 0 ? Math.min(player.time / duration, 1) : 0;

  function scrub(event: React.MouseEvent<HTMLDivElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    const fraction = (event.clientX - rect.left) / rect.width;
    player.seek(fraction * duration);
  }

  return (
    <div className="player" onClick={(event) => event.stopPropagation()}>
      <button className="skip" onClick={() => player.skip(-5)} title={t("player.back")}>
        ↺5
      </button>
      <button className="skip" onClick={() => player.skip(5)} title={t("player.forward")}>
        5↻
      </button>
      <span className="player-time">{clock(player.time)}</span>
      <div className="scrub" onClick={scrub} role="slider"
           aria-valuenow={Math.round(player.time)} aria-valuemin={0}
           aria-valuemax={Math.round(duration)} tabIndex={-1}>
        <div className="scrub-track">
          <div className="scrub-fill" style={{ width: `${progress * 100}%` }} />
        </div>
        <div className="scrub-head" style={{ left: `${progress * 100}%` }} />
      </div>
      <span className="player-time">{duration ? clock(duration) : "—"}</span>
    </div>
  );
}
