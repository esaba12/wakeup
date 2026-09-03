"""The action set shared by REST POST handlers and WebSocket client->server
messages (docs/07-api-and-state.md: "Client->server messages are limited to
the same actions as the REST verbs, so the puck and the UI use one
protocol"). Every function here takes plain Python primitives (not Pydantic
models or FastAPI request objects) so both transports can call the same
code; each raises one of the four errors below, uniformly, so both
transports can translate failures the same way.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, time
from typing import Any

from openrestore.app import AppContext
from openrestore.core.errors import ConfigError, DeviceUnreachable, RoutineError
from openrestore.core.scheduler import Alarm
from openrestore.core.sunrise import off_state
from openrestore.drivers.audio.base import parse_audio_source
from openrestore.drivers.light.base import LightState


class ActionError(Exception):
    """Base class for user-facing action failures."""


class NotFound(ActionError):
    pass


class Conflict(ActionError):
    pass


class BadRequest(ActionError):
    pass


class Unavailable(ActionError):
    pass


# docs/07-api-and-state.md doesn't define preset values — no other spec in
# scope for this task does either — so these are deliberately simple,
# hardcoded light targets, not config-driven curves. Flagged in the task
# report as something spec 07 (or 11) should probably pin down explicitly.
_LIGHT_PRESETS: dict[str, tuple[float, int]] = {
    "nightlight": (0.03, 2000),
    "reading": (0.6, 3000),
}


def alarm_to_dict(alarm: Alarm) -> dict[str, Any]:
    return {
        "id": alarm.id,
        "enabled": alarm.enabled,
        "time": alarm.time.isoformat(),
        "days": sorted(alarm.days),
        "routine_id": alarm.routine_id,
        "pre_roll_s": alarm.pre_roll_s,
        "timezone": alarm.timezone,
        "skip_next": alarm.skip_next,
        "last_fired_at": alarm.last_fired_at.isoformat() if alarm.last_fired_at else None,
    }


def _require(message: dict[str, Any], key: str) -> Any:
    if key not in message or message[key] is None:
        raise BadRequest(f"missing required field {key!r}")
    return message[key]


async def create_or_replace_alarm(
    ctx: AppContext,
    *,
    alarm_id: str,
    enabled: bool,
    time_str: str,
    days: list[int],
    routine_id: str,
    pre_roll_s: int,
    timezone: str,
    skip_next: bool = False,
) -> dict[str, Any]:
    existing = ctx.scheduler.get_alarm(alarm_id)
    try:
        alarm = Alarm(
            id=alarm_id,
            enabled=enabled,
            time=time.fromisoformat(time_str),
            days=set(days),
            routine_id=routine_id,
            pre_roll_s=pre_roll_s,
            timezone=timezone,
            skip_next=skip_next,
            last_fired_at=existing.last_fired_at if existing is not None else None,
        )
    except (ValueError, TypeError) as exc:
        raise BadRequest(str(exc)) from exc
    saved = await ctx.scheduler.upsert(alarm)
    return alarm_to_dict(saved)


async def delete_alarm(ctx: AppContext, alarm_id: str) -> None:
    if ctx.scheduler.get_alarm(alarm_id) is None:
        raise NotFound(f"no alarm {alarm_id!r}")
    await ctx.scheduler.delete(alarm_id)


async def skip_next_alarm(ctx: AppContext, alarm_id: str) -> dict[str, Any]:
    if ctx.scheduler.get_alarm(alarm_id) is None:
        raise NotFound(f"no alarm {alarm_id!r}")
    await ctx.scheduler.skip_next(alarm_id)
    result = ctx.scheduler.get_alarm(alarm_id)
    assert result is not None
    return alarm_to_dict(result)


async def start_routine(
    ctx: AppContext, routine_id: str, trigger_at: datetime | None = None
) -> dict[str, Any]:
    """docs/07: "409 on conflicting routine starts" — starting the routine
    that's already the active run is the conflict; starting a *different*
    routine is allowed and cancels the current one (RoutineEngine's own
    documented behavior, docs/06-routine-engine.md)."""
    current = ctx.routine_engine.current_run
    if current is not None and current.routine.id == routine_id:
        raise Conflict(f"routine {routine_id!r} is already running")
    try:
        routine = ctx.load_routine(routine_id)
    except ConfigError as exc:
        raise NotFound(str(exc)) from exc
    at = trigger_at if trigger_at is not None else ctx.clock.now()
    try:
        run = await ctx.routine_engine.start_routine(routine, trigger_at=at)
    except RoutineError as exc:
        raise BadRequest(str(exc)) from exc
    return {"id": run.routine.id, "state": run.state.value}


async def stop_routine(ctx: AppContext) -> None:
    await ctx.routine_engine.stop_routine()


async def snooze(ctx: AppContext) -> None:
    try:
        await ctx.routine_engine.snooze()
    except RoutineError as exc:
        raise Conflict(str(exc)) from exc


async def dismiss(ctx: AppContext) -> None:
    try:
        await ctx.routine_engine.dismiss()
    except RoutineError as exc:
        raise Conflict(str(exc)) from exc


async def apply_light_preset(ctx: AppContext, preset: str) -> None:
    if preset == "off":
        target = off_state()
    else:
        values = _LIGHT_PRESETS.get(preset)
        if values is None:
            raise NotFound(f"unknown light preset {preset!r}")
        brightness, cct = values
        target = LightState(on=True, brightness=brightness, cct=cct, rgb=None)
    try:
        await ctx.light.apply(target)
    except DeviceUnreachable as exc:
        raise Unavailable(str(exc)) from exc


async def apply_light_state(
    ctx: AppContext, brightness: float | None, cct: int | None
) -> None:
    try:
        current = await ctx.light.get()
        b = brightness if brightness is not None else current.brightness
        c = cct if cct is not None else current.cct
        await ctx.light.apply(LightState(on=True, brightness=b, cct=c, rgb=None))
    except DeviceUnreachable as exc:
        raise Unavailable(str(exc)) from exc
    except ValueError as exc:
        raise BadRequest(str(exc)) from exc


async def audio_play(
    ctx: AppContext,
    source: str,
    gain_db: float | None,
    sleep_timer_s: float | None,
) -> None:
    try:
        parsed = parse_audio_source(source)
    except ValueError as exc:
        raise BadRequest(str(exc)) from exc
    applied_gain = gain_db if gain_db is not None else ctx.audio.max_gain_db
    try:
        await ctx.audio.play(parsed, gain_db=applied_gain)
    except DeviceUnreachable as exc:
        raise Unavailable(str(exc)) from exc
    if sleep_timer_s is not None:
        ctx.schedule_sleep_timer(sleep_timer_s)


async def audio_stop(ctx: AppContext) -> None:
    await ctx.audio.stop()


async def audio_test_tone(ctx: AppContext) -> None:
    try:
        await ctx.audio.test_tone()
    except DeviceUnreachable as exc:
        raise Unavailable(str(exc)) from exc


async def discover_lights(ctx: AppContext) -> list[dict[str, Any]]:
    """No `LightDiscovery` implementation exists yet (task 09's LIFX driver
    is where one would live) — always an empty result for now, which is
    still the correct answer for a mock-only setup."""
    return []


# --- WebSocket action dispatch -----------------------------------------
# docs/07: WS client->server messages are "limited to the same actions as
# the REST verbs" — this table is that action set, by name, for the puck
# and any other non-REST client.

_Handler = Callable[[AppContext, dict[str, Any]], Awaitable[Any]]


async def _ws_alarms_create(ctx: AppContext, msg: dict[str, Any]) -> Any:
    return await create_or_replace_alarm(
        ctx,
        alarm_id=str(msg.get("id") or uuid.uuid4().hex[:12]),
        enabled=bool(msg.get("enabled", True)),
        time_str=_require(msg, "time"),
        days=list(msg.get("days", [])),
        routine_id=_require(msg, "routine_id"),
        pre_roll_s=int(msg.get("pre_roll_s", 0)),
        timezone=_require(msg, "timezone"),
    )


async def _ws_alarms_update(ctx: AppContext, msg: dict[str, Any]) -> Any:
    alarm_id = _require(msg, "id")
    return await create_or_replace_alarm(
        ctx,
        alarm_id=alarm_id,
        enabled=bool(msg.get("enabled", True)),
        time_str=_require(msg, "time"),
        days=list(msg.get("days", [])),
        routine_id=_require(msg, "routine_id"),
        pre_roll_s=int(msg.get("pre_roll_s", 0)),
        timezone=_require(msg, "timezone"),
    )


async def _ws_alarms_delete(ctx: AppContext, msg: dict[str, Any]) -> Any:
    await delete_alarm(ctx, _require(msg, "id"))
    return None


async def _ws_alarms_skip_next(ctx: AppContext, msg: dict[str, Any]) -> Any:
    return await skip_next_alarm(ctx, _require(msg, "id"))


async def _ws_routines_start(ctx: AppContext, msg: dict[str, Any]) -> Any:
    trigger_at = None
    if msg.get("trigger_at") is not None:
        trigger_at = datetime.fromisoformat(msg["trigger_at"])
    return await start_routine(ctx, _require(msg, "id"), trigger_at)


async def _ws_routines_stop(ctx: AppContext, _msg: dict[str, Any]) -> Any:
    await stop_routine(ctx)
    return None


async def _ws_snooze(ctx: AppContext, _msg: dict[str, Any]) -> Any:
    await snooze(ctx)
    return None


async def _ws_dismiss(ctx: AppContext, _msg: dict[str, Any]) -> Any:
    await dismiss(ctx)
    return None


async def _ws_light_preset(ctx: AppContext, msg: dict[str, Any]) -> Any:
    await apply_light_preset(ctx, _require(msg, "preset"))
    return None


async def _ws_light_state(ctx: AppContext, msg: dict[str, Any]) -> Any:
    await apply_light_state(ctx, msg.get("brightness"), msg.get("cct"))
    return None


async def _ws_audio_play(ctx: AppContext, msg: dict[str, Any]) -> Any:
    await audio_play(ctx, _require(msg, "source"), msg.get("gain_db"), msg.get("sleep_timer"))
    return None


async def _ws_audio_stop(ctx: AppContext, _msg: dict[str, Any]) -> Any:
    await audio_stop(ctx)
    return None


_ACTIONS: dict[str, _Handler] = {
    "alarms.create": _ws_alarms_create,
    "alarms.update": _ws_alarms_update,
    "alarms.delete": _ws_alarms_delete,
    "alarms.skip_next": _ws_alarms_skip_next,
    "routines.start": _ws_routines_start,
    "routines.stop": _ws_routines_stop,
    "snooze": _ws_snooze,
    "dismiss": _ws_dismiss,
    "light.preset": _ws_light_preset,
    "light.state": _ws_light_state,
    "audio.play": _ws_audio_play,
    "audio.stop": _ws_audio_stop,
}


async def dispatch(ctx: AppContext, action: str, message: dict[str, Any]) -> Any:
    handler = _ACTIONS.get(action)
    if handler is None:
        raise BadRequest(f"unknown action {action!r}")
    return await handler(ctx, message)
