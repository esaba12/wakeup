from __future__ import annotations

from openrestore.core.events import Event, EventBus, EventType


async def test_publish_delivers_event_to_subscriber() -> None:
    bus = EventBus()
    received: list[Event] = []

    async def handler(event: Event) -> None:
        received.append(event)

    bus.subscribe(handler)
    event = Event(type=EventType.ALARM_FIRED, payload={"id": "a1"})
    await bus.publish(event)

    assert received == [event]


async def test_unsubscribed_handler_receives_nothing() -> None:
    bus = EventBus()
    received: list[Event] = []

    async def handler(event: Event) -> None:
        received.append(event)

    bus.subscribe(handler)
    bus.unsubscribe(handler)
    await bus.publish(Event(type=EventType.CLOCK_UNSAFE))

    assert received == []
