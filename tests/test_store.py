from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from openrestore.core.events import Event, EventType
from openrestore.core.store import AlarmRow, Store

_ALARM = AlarmRow(
    id="a1",
    enabled=True,
    time="06:40:00",
    days="[1, 2, 3, 4, 5]",
    routine_id="sunrise",
    pre_roll_s=1200,
    skip_next=False,
    last_fired_at=None,
    timezone="America/Detroit",
)


async def test_upsert_and_list_alarm_round_trips(tmp_path: Path) -> None:
    store = await Store.open(tmp_path / "db.sqlite")
    await store.upsert_alarm(_ALARM)
    rows = await store.list_alarms()
    assert rows == [_ALARM]
    await store.close()


async def test_upsert_alarm_updates_existing_row(tmp_path: Path) -> None:
    store = await Store.open(tmp_path / "db.sqlite")
    await store.upsert_alarm(_ALARM)
    updated = replace(_ALARM, enabled=False, skip_next=True)
    await store.upsert_alarm(updated)
    rows = await store.list_alarms()
    assert rows == [updated]
    await store.close()


async def test_delete_alarm_removes_its_occurrences_too(tmp_path: Path) -> None:
    store = await Store.open(tmp_path / "db.sqlite")
    await store.upsert_alarm(_ALARM)
    await store.reserve_occurrence("a1", "2024-06-03", outcome="fired", fired_at="x")
    await store.delete_alarm("a1")
    assert await store.list_alarms() == []
    assert await store.list_occurrences() == []
    await store.close()


async def test_reserve_occurrence_is_idempotent(tmp_path: Path) -> None:
    store = await Store.open(tmp_path / "db.sqlite")
    first = await store.reserve_occurrence("a1", "2024-06-03", outcome="fired", fired_at="x")
    second = await store.reserve_occurrence("a1", "2024-06-03", outcome="fired", fired_at="y")
    assert first is True
    assert second is False  # already reserved: the write-before-side-effect gate holds
    occurrences = await store.list_occurrences()
    assert len(occurrences) == 1
    assert occurrences[0].fired_at == "x"  # the second call's payload never landed
    await store.close()


async def test_log_event_persists_type_payload_and_timestamp(tmp_path: Path) -> None:
    store = await Store.open(tmp_path / "db.sqlite")
    at = datetime(2024, 6, 3, 6, 40, tzinfo=UTC)
    await store.log_event(Event(type=EventType.ALARM_FIRED, payload={"alarm_id": "a1"}), at)
    cur = await store._conn.execute("SELECT type, payload, at FROM events")
    row = await cur.fetchone()
    assert row is not None
    assert row["type"] == "alarm.fired"
    assert row["payload"] == '{"alarm_id": "a1"}'
    assert row["at"] == at.isoformat()
    await store.close()


async def test_migrations_are_idempotent_across_reopen(tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite"
    store1 = await Store.open(db_path)
    await store1.upsert_alarm(_ALARM)
    await store1.close()

    # Reopening a fully-migrated database must not fail or re-run migrations.
    store2 = await Store.open(db_path)
    assert await store2.list_alarms() == [_ALARM]
    await store2.close()
