"""In-process async pub/sub event bus. Event types match docs/07-api-and-state.md
so the WebSocket fan-out, the SQLite event log, and the MQTT bridge can all
subscribe to the same stream."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class EventType(StrEnum):
    STATE_CHANGED = "state.changed"
    ROUTINE_TRANSITION = "routine.transition"
    ALARM_FIRED = "alarm.fired"
    ALARM_MISSED = "alarm.missed"
    ALARM_SNOOZED = "alarm.snoozed"
    PREFLIGHT_FAILED = "preflight.failed"
    DEVICE_UNREACHABLE = "device.unreachable"
    DEVICE_RECOVERED = "device.recovered"
    CLOCK_UNSAFE = "clock.unsafe"


@dataclass(frozen=True, slots=True)
class Event:
    type: EventType
    payload: dict[str, Any] = field(default_factory=dict)


Handler = Callable[[Event], Awaitable[None]]


class EventBus:
    """Subscribers are awaited in registration order. A handler that raises
    stops delivery to the remaining subscribers for that event."""

    def __init__(self) -> None:
        self._subscribers: list[Handler] = []

    def subscribe(self, handler: Handler) -> None:
        self._subscribers.append(handler)

    def unsubscribe(self, handler: Handler) -> None:
        self._subscribers.remove(handler)

    async def publish(self, event: Event) -> None:
        for handler in list(self._subscribers):
            await handler(event)
