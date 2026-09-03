import type { Routine } from "../types";
import { formatDurationShort } from "../utils/format";
import { layoutRoutineTimeline, stepAudioLevel, stepBrightness } from "../utils/timeline";

function lightColor(brightness: number | null): string {
  if (brightness === null) return "var(--bg-elevated)";
  // 0 -> near-black, 1 -> the accent's brightest stop.
  const clamped = Math.max(0, Math.min(1, brightness));
  return `color-mix(in srgb, var(--accent-strong) ${Math.round(clamped * 100)}%, var(--bg-sunken))`;
}

export function RoutineTimeline({ routine }: { routine: Routine }): JSX.Element {
  const { totalS, segments } = layoutRoutineTimeline(routine);
  return (
    <div className="stack">
      <div className="timeline" role="img" aria-label={`Timeline for ${routine.name}`}>
        {segments.map((seg, i) => {
          const brightness = stepBrightness(seg.step);
          const audioLevel = stepAudioLevel(seg.step);
          const widthPct = (seg.widthS / totalS) * 100;
          const isRamp = Boolean(seg.step.light?.curve);
          return (
            <div
              key={`${seg.step.id}-${i}`}
              className="timeline-step"
              title={`${seg.step.id} — ${
                seg.kind === "duration"
                  ? formatDurationShort(seg.widthS)
                  : seg.kind === "open-ended"
                    ? "runs until cancelled / next step"
                    : "triggers at an offset from the alarm"
              }`}
              style={{
                width: `${widthPct}%`,
                background: isRamp
                  ? `linear-gradient(90deg, var(--bg-sunken), ${lightColor(brightness)})`
                  : lightColor(brightness),
                opacity: seg.kind === "offset-marker" ? 0.85 : 1,
                borderLeft:
                  seg.kind === "offset-marker" ? "2px solid var(--accent-strong)" : undefined,
              }}
            >
              {audioLevel !== null && (
                <div
                  style={{
                    position: "absolute",
                    left: 0,
                    right: 0,
                    bottom: 0,
                    height: `${Math.max(4, audioLevel * 100)}%`,
                    background: "color-mix(in srgb, var(--text) 35%, transparent)",
                  }}
                  aria-hidden
                />
              )}
            </div>
          );
        })}
      </div>
      <div className="timeline-legend">
        <span>
          <span className="legend-swatch" style={{ background: lightColor(0.9) }} />
          Light
        </span>
        <span>
          <span
            className="legend-swatch"
            style={{ background: "color-mix(in srgb, var(--text) 35%, transparent)" }}
          />
          Audio level
        </span>
        <span className="faint">Total ≈ {formatDurationShort(totalS)}</span>
      </div>
    </div>
  );
}
