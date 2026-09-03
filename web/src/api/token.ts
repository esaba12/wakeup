/**
 * Optional bearer token (docs/07-api-and-state.md "Auth" — LAN-only, no
 * auth by default; an operator exposing the daemon via Tailscale/a reverse
 * proxy can set one). No account system, no login form: a `?token=` in the
 * URL (e.g. a link the operator hands out once) is captured into
 * localStorage and stripped from the address bar, then reused for every
 * REST call (`Authorization: Bearer`) and the WebSocket (`?token=`, since
 * browsers can't set headers on a WS upgrade — `api/auth.py`).
 */

const STORAGE_KEY = "openrestore.token";

export function resolveToken(): string | null {
  const url = new URL(window.location.href);
  const fromUrl = url.searchParams.get("token");
  if (fromUrl) {
    try {
      window.localStorage.setItem(STORAGE_KEY, fromUrl);
    } catch {
      // localStorage unavailable (private mode, etc.) — still honor it
      // for this page load via the URL itself.
    }
    url.searchParams.delete("token");
    window.history.replaceState({}, "", url.toString());
    return fromUrl;
  }
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}
