import { useEffect, useState } from "react";

const UNDO_WINDOW_MS = 5000;

/** docs/08-web-ui.md: "No destructive action without undo (deleting an
 * alarm shows a 5s undo toast)." Purely presentational + a countdown timer
 * for the toast's own lifetime — not the daemon's wall clock, so a plain
 * `setTimeout` is fine here (this never claims to reflect device state). */
export function UndoToast({
  message,
  onUndo,
  onExpire,
}: {
  message: string;
  onUndo: () => void;
  onExpire: () => void;
}): JSX.Element {
  const [remaining, setRemaining] = useState(UNDO_WINDOW_MS);

  useEffect(() => {
    const start = Date.now();
    const interval = setInterval(() => {
      const left = UNDO_WINDOW_MS - (Date.now() - start);
      if (left <= 0) {
        clearInterval(interval);
        onExpire();
      } else {
        setRemaining(left);
      }
    }, 100);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="toast" role="alert">
      <span>{message}</span>
      <button type="button" className="btn btn--ghost" onClick={onUndo}>
        Undo ({Math.ceil(remaining / 1000)}s)
      </button>
    </div>
  );
}
