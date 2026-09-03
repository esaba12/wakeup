"""Optional bearer-token auth, shared by the REST and WebSocket transports.
See docs/07-api-and-state.md "Auth": LAN-only, no auth by default; an
operator exposing the daemon beyond the LAN (Tailscale, a reverse proxy) can
set a bearer token. Never an account system."""

from __future__ import annotations

from openrestore.app import AppContext


def is_authorized(
    ctx: AppContext, authorization_header: str | None, query_token: str | None = None
) -> bool:
    """`True` when no token is configured (the default), or the caller
    presented it — as `Authorization: Bearer <token>` (REST, and WebSocket
    clients that can set headers), or a `?token=` query param (WebSocket
    clients in a browser/puck that can't set headers on the upgrade
    request)."""
    if ctx.bearer_token is None:
        return True
    if authorization_header is not None:
        scheme, _, value = authorization_header.partition(" ")
        if scheme.lower() == "bearer" and value == ctx.bearer_token:
            return True
    return query_token == ctx.bearer_token
