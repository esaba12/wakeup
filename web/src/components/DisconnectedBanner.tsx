/** docs/08-web-ui.md: "shows a clear 'disconnected from device' banner
 * rather than stale data pretending to be live." The last known state
 * stays visible underneath (dimmed by the caller), but this banner is
 * unmissable whenever the socket isn't currently open. */
export function DisconnectedBanner({ connected }: { connected: boolean }): JSX.Element | null {
  if (connected) return null;
  return (
    <div className="banner" role="status">
      Disconnected from device — showing the last known state
    </div>
  );
}
