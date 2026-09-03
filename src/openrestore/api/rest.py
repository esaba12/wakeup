"""FastAPI REST routes. See docs/07-api-and-state.md.

Conventions enforced uniformly here: JSON only, ISO-8601 timestamps with UTC
offsets (never naive, never `Z`), `409` on a conflicting routine start,
`503` when the clock is unsafe (alarm-mutating endpoints only — `GET
/api/state` and `/api/health` must still work so a client can *see* the
degraded status), and an `Idempotency-Key` header collapses retries of any
POST that fires a side effect.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from openrestore.api import actions
from openrestore.api.auth import is_authorized
from openrestore.app import AppContext
from openrestore.core.errors import ConfigError
from openrestore.core.routines import load_routine, parse_routine_text
from openrestore.core.state import build_state, state_to_dict

# --- request bodies -----------------------------------------------------


class AlarmIn(BaseModel):
    id: str | None = None
    enabled: bool = True
    time: str  # "HH:MM" or "HH:MM:SS", local wall time
    days: list[int] = Field(default_factory=list)  # ISO weekdays 1-7; [] = one-shot
    routine_id: str
    pre_roll_s: int = 0
    timezone: str


class LightStateIn(BaseModel):
    brightness: float | None = Field(default=None, ge=0.0, le=1.0)
    cct: int | None = Field(default=None, gt=0)


class AudioPlayIn(BaseModel):
    source: str
    gain_db: float | None = None
    sleep_timer: float | None = None  # seconds


class RoutineStartIn(BaseModel):
    trigger_at: str | None = None


# --- plumbing ------------------------------------------------------------


def get_context(request: Request) -> AppContext:
    ctx: AppContext = request.app.state.ctx
    return ctx


def require_auth(request: Request, ctx: AppContext = Depends(get_context)) -> None:
    if not is_authorized(ctx, request.headers.get("authorization")):
        raise HTTPException(status_code=401, detail="unauthorized")


def require_clock_synced(ctx: AppContext = Depends(get_context)) -> None:
    """docs/00-overview.md rule 6 / docs/07 "503 when the clock is unsafe":
    refusing to create, edit, or arm alarms when the wall clock itself
    isn't trustworthy this boot. `GET /api/state` and `/api/health` are
    deliberately exempt — a client needs to be able to *see* `degraded`."""
    if not ctx.scheduler.clock_synced:
        raise HTTPException(status_code=503, detail="clock not synced; refusing alarm changes")


_STATUS_FOR_ERROR: dict[type[actions.ActionError], int] = {
    actions.NotFound: 404,
    actions.Conflict: 409,
    actions.BadRequest: 400,
    actions.Unavailable: 503,
}


def _raise_http(exc: actions.ActionError) -> None:
    for exc_type, code in _STATUS_FOR_ERROR.items():
        if isinstance(exc, exc_type):
            raise HTTPException(status_code=code, detail=str(exc)) from exc
    raise HTTPException(status_code=500, detail=str(exc)) from exc


def _idempotency_key(request: Request) -> str | None:
    header = request.headers.get("Idempotency-Key")
    if not header:
        return None
    return f"{request.method}:{request.url.path}:{header}"


async def _with_idempotency(
    request: Request,
    ctx: AppContext,
    status_code: int,
    action: Callable[[], Awaitable[Any]],
) -> JSONResponse:
    """Shared body of every side-effecting POST handler: replay a cached
    response for a repeated `Idempotency-Key`, else run `action()` once,
    translate any `actions.ActionError` into the matching HTTP status, and
    cache the successful result. `action` is a thunk (not an already-created
    coroutine) so a cache hit never creates — and leaves unawaited — a
    coroutine for the real side effect."""
    key = _idempotency_key(request)
    if key is not None:
        cached = ctx.idempotency.get(key)
        if cached is not None:
            cached_status, cached_body = cached
            return JSONResponse(status_code=cached_status, content=cached_body)
    try:
        result = await action()
    except actions.ActionError as exc:
        _raise_http(exc)
        raise AssertionError("unreachable") from exc
    encoded = jsonable_encoder(result)
    if key is not None:
        ctx.idempotency.put(key, status_code, encoded)
    return JSONResponse(status_code=status_code, content=encoded)


router = APIRouter(dependencies=[Depends(require_auth)])


# --- state & health --------------------------------------------------------


@router.get("/api/state")
async def get_state(ctx: AppContext = Depends(get_context)) -> dict[str, Any]:
    state = await build_state(
        clock=ctx.clock,
        tz=ctx.tz,
        scheduler=ctx.scheduler,
        routine_engine=ctx.routine_engine,
        light=ctx.light,
        audio=ctx.audio,
        clock_source=ctx.clock_source,
    )
    return state_to_dict(state)


@router.get("/api/health")
async def get_health(ctx: AppContext = Depends(get_context)) -> dict[str, Any]:
    """A minimal stand-in for the full health object docs/10-reliability.md
    owns (out of scope for this task) — enough for a client to tell "ok" vs
    "degraded" and why."""
    return {
        "status": ctx.scheduler.health,
        "clock_synced": ctx.scheduler.clock_synced,
        "light_reachable": await ctx.light.is_reachable(),
        "audio_available": await ctx.audio.is_available(),
    }


# --- alarms ----------------------------------------------------------------


@router.get("/api/alarms")
async def list_alarms(ctx: AppContext = Depends(get_context)) -> list[dict[str, Any]]:
    return [actions.alarm_to_dict(a) for a in ctx.scheduler.list_alarms()]


@router.post("/api/alarms", status_code=201, dependencies=[Depends(require_clock_synced)])
async def create_alarm(
    payload: AlarmIn, request: Request, ctx: AppContext = Depends(get_context)
) -> JSONResponse:
    alarm_id = payload.id or uuid.uuid4().hex[:12]
    return await _with_idempotency(
        request,
        ctx,
        201,
        lambda: actions.create_or_replace_alarm(
            ctx,
            alarm_id=alarm_id,
            enabled=payload.enabled,
            time_str=payload.time,
            days=payload.days,
            routine_id=payload.routine_id,
            pre_roll_s=payload.pre_roll_s,
            timezone=payload.timezone,
        ),
    )


@router.put("/api/alarms/{alarm_id}", dependencies=[Depends(require_clock_synced)])
async def update_alarm(
    alarm_id: str, payload: AlarmIn, ctx: AppContext = Depends(get_context)
) -> dict[str, Any]:
    try:
        return await actions.create_or_replace_alarm(
            ctx,
            alarm_id=alarm_id,
            enabled=payload.enabled,
            time_str=payload.time,
            days=payload.days,
            routine_id=payload.routine_id,
            pre_roll_s=payload.pre_roll_s,
            timezone=payload.timezone,
        )
    except actions.ActionError as exc:
        _raise_http(exc)
        raise AssertionError("unreachable") from exc


@router.delete(
    "/api/alarms/{alarm_id}", status_code=204, dependencies=[Depends(require_clock_synced)]
)
async def delete_alarm(alarm_id: str, ctx: AppContext = Depends(get_context)) -> Response:
    try:
        await actions.delete_alarm(ctx, alarm_id)
    except actions.ActionError as exc:
        _raise_http(exc)
    return Response(status_code=204)


@router.post(
    "/api/alarms/{alarm_id}/skip-next", dependencies=[Depends(require_clock_synced)]
)
async def skip_next_alarm(
    alarm_id: str, request: Request, ctx: AppContext = Depends(get_context)
) -> JSONResponse:
    return await _with_idempotency(
        request, ctx, 200, lambda: actions.skip_next_alarm(ctx, alarm_id)
    )


# --- routines ----------------------------------------------------------


@router.get("/api/routines")
async def list_routines(ctx: AppContext = Depends(get_context)) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    if not ctx.routines_dir.is_dir():
        return results
    for path in sorted(ctx.routines_dir.glob("*.yaml")):
        try:
            routine = load_routine(path)
        except ConfigError:
            continue
        results.append(
            {
                "id": routine.id,
                "name": routine.name,
                "trigger": routine.trigger.model_dump(mode="json"),
            }
        )
    return results


@router.get("/api/routines/{routine_id}")
async def get_routine(routine_id: str, ctx: AppContext = Depends(get_context)) -> dict[str, Any]:
    try:
        routine = ctx.load_routine(routine_id)
    except ConfigError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return routine.model_dump(mode="json", by_alias=True)


@router.put("/api/routines/{routine_id}")
async def put_routine(
    routine_id: str, request: Request, ctx: AppContext = Depends(get_context)
) -> dict[str, Any]:
    """Upload YAML/JSON, validated (docs/07). JSON is valid YAML 1.1, so the
    same parser handles both — the raw request body is read directly rather
    than binding to a Pydantic model, since the payload's *shape* is the
    routine schema itself, not a REST envelope around it."""
    raw = (await request.body()).decode("utf-8")
    try:
        routine = parse_routine_text(raw, f"<upload {routine_id}>")
    except ConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if routine.id != routine_id:
        raise HTTPException(
            status_code=400,
            detail=f"routine id {routine.id!r} in the body does not match path {routine_id!r}",
        )
    ctx.routines_dir.mkdir(parents=True, exist_ok=True)
    (ctx.routines_dir / f"{routine_id}.yaml").write_text(raw)
    return routine.model_dump(mode="json", by_alias=True)


@router.post("/api/routines/{routine_id}/start")
async def start_routine(
    routine_id: str,
    request: Request,
    ctx: AppContext = Depends(get_context),
    payload: RoutineStartIn = RoutineStartIn(),
) -> JSONResponse:
    trigger_at = datetime.fromisoformat(payload.trigger_at) if payload.trigger_at else None
    return await _with_idempotency(
        request, ctx, 200, lambda: actions.start_routine(ctx, routine_id, trigger_at)
    )


@router.post("/api/routines/current/stop")
async def stop_routine(request: Request, ctx: AppContext = Depends(get_context)) -> JSONResponse:
    async def _stop() -> dict[str, Any]:
        await actions.stop_routine(ctx)
        return {"stopped": True}

    return await _with_idempotency(request, ctx, 200, _stop)


# --- alarm-lifecycle actions ------------------------------------------


@router.post("/api/snooze")
async def snooze(request: Request, ctx: AppContext = Depends(get_context)) -> JSONResponse:
    async def _snooze() -> dict[str, Any]:
        await actions.snooze(ctx)
        return {"snoozed": True}

    return await _with_idempotency(request, ctx, 200, _snooze)


@router.post("/api/dismiss")
async def dismiss(request: Request, ctx: AppContext = Depends(get_context)) -> JSONResponse:
    async def _dismiss() -> dict[str, Any]:
        await actions.dismiss(ctx)
        return {"dismissed": True}

    return await _with_idempotency(request, ctx, 200, _dismiss)


# --- light -------------------------------------------------------------


@router.post("/api/light/preset/{preset}")
async def light_preset(
    preset: Literal["nightlight", "reading", "off"],
    request: Request,
    ctx: AppContext = Depends(get_context),
) -> JSONResponse:
    async def _apply() -> dict[str, Any]:
        await actions.apply_light_preset(ctx, preset)
        return {"preset": preset}

    return await _with_idempotency(request, ctx, 200, _apply)


@router.post("/api/light/state")
async def light_state(
    payload: LightStateIn, request: Request, ctx: AppContext = Depends(get_context)
) -> JSONResponse:
    async def _apply() -> dict[str, Any]:
        await actions.apply_light_state(ctx, payload.brightness, payload.cct)
        return {"brightness": payload.brightness, "cct": payload.cct}

    return await _with_idempotency(request, ctx, 200, _apply)


# --- audio ---------------------------------------------------------------


@router.post("/api/audio/play")
async def audio_play(
    payload: AudioPlayIn, request: Request, ctx: AppContext = Depends(get_context)
) -> JSONResponse:
    async def _play() -> dict[str, Any]:
        await actions.audio_play(ctx, payload.source, payload.gain_db, payload.sleep_timer)
        return {"source": payload.source}

    return await _with_idempotency(request, ctx, 200, _play)


@router.post("/api/audio/stop")
async def audio_stop(request: Request, ctx: AppContext = Depends(get_context)) -> JSONResponse:
    async def _stop() -> dict[str, Any]:
        await actions.audio_stop(ctx)
        return {"stopped": True}

    return await _with_idempotency(request, ctx, 200, _stop)


# --- devices -------------------------------------------------------------


@router.get("/api/devices/lights")
async def list_light_devices(ctx: AppContext = Depends(get_context)) -> dict[str, Any]:
    return {
        "configured": [
            {"id": ctx.light.id, "reachable": await ctx.light.is_reachable()}
        ],
        "discovered": [jsonable_encoder(d) for d in await actions.discover_lights(ctx)],
    }


@router.post("/api/devices/lights/discover")
async def discover_lights(request: Request, ctx: AppContext = Depends(get_context)) -> JSONResponse:
    async def _discover() -> dict[str, Any]:
        found = await actions.discover_lights(ctx)
        return {"discovered": found}

    return await _with_idempotency(request, ctx, 200, _discover)


@router.get("/api/devices/audio")
async def list_audio_devices(ctx: AppContext = Depends(get_context)) -> list[dict[str, Any]]:
    return [{"id": ctx.audio.id, "description": "configured output"}]


@router.post("/api/devices/audio/test")
async def test_audio_device(
    request: Request, ctx: AppContext = Depends(get_context)
) -> JSONResponse:
    async def _test() -> dict[str, Any]:
        await actions.audio_test_tone(ctx)
        return {"tested": True}

    return await _with_idempotency(request, ctx, 200, _test)


# --- history -------------------------------------------------------------


@router.get("/api/history")
async def get_history(
    days: int = 7, ctx: AppContext = Depends(get_context)
) -> list[dict[str, Any]]:
    cutoff = (ctx.clock.now() - timedelta(days=days)).date()
    occurrences = await ctx.store.list_occurrences()
    result = []
    for occ in occurrences:
        try:
            occ_date = date.fromisoformat(occ.local_date)
        except ValueError:
            continue
        if occ_date >= cutoff:
            result.append(
                {
                    "alarm_id": occ.alarm_id,
                    "local_date": occ.local_date,
                    "fired_at": occ.fired_at,
                    "outcome": occ.outcome,
                }
            )
    result.sort(key=lambda r: str(r["local_date"]), reverse=True)
    return result
