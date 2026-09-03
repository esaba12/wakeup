const SIZE = 220;
const STROKE = 10;
const RADIUS = (SIZE - STROKE) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

/** Renders the server-provided `routine.progress` (0..1, or `null` when
 * idle) as a ring. No client-side math beyond drawing what it's given —
 * docs/07: "clients never compute derived state." */
export function ProgressRing({
  progress,
  stateLabel,
  stepLabel,
}: {
  progress: number | null;
  stateLabel: string;
  stepLabel: string | null;
}): JSX.Element {
  const fraction = progress ?? 0;
  const offset = CIRCUMFERENCE * (1 - fraction);
  return (
    <div className="progress-ring">
      <svg width={SIZE} height={SIZE}>
        <circle
          className="progress-ring-track"
          cx={SIZE / 2}
          cy={SIZE / 2}
          r={RADIUS}
          strokeWidth={STROKE}
        />
        {progress !== null && (
          <circle
            className="progress-ring-fill"
            cx={SIZE / 2}
            cy={SIZE / 2}
            r={RADIUS}
            strokeWidth={STROKE}
            strokeDasharray={CIRCUMFERENCE}
            strokeDashoffset={offset}
          />
        )}
      </svg>
      <div className="progress-ring-label">
        <span className="progress-ring-state">{stateLabel}</span>
        <span className="progress-ring-step">{stepLabel ?? "—"}</span>
      </div>
    </div>
  );
}
