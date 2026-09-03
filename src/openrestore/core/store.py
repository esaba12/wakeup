"""SQLite (WAL) persistence: alarms, occurrences, event log. See docs/05-scheduler.md.

Deliberately dumb: `Store` knows rows, not domain objects. It doesn't import
`Alarm` from `core/scheduler.py` (that would create a circular import, since
`Scheduler` depends on `Store`) and it doesn't know what an alarm "means" —
`core/scheduler.py` owns converting between `Alarm` and `AlarmRow`, matching
the "drivers/store own persistence, engines own timing" split in CLAUDE.md.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import aiosqlite

from openrestore.core.events import Event

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


@dataclass(frozen=True, slots=True)
class AlarmRow:
    id: str
    enabled: bool
    time: str  # "HH:MM:SS"
    days: str  # JSON array of ints, e.g. "[1, 2, 3, 4, 5]"
    routine_id: str
    pre_roll_s: int
    skip_next: bool
    last_fired_at: str | None
    timezone: str


@dataclass(frozen=True, slots=True)
class OccurrenceRow:
    alarm_id: str
    local_date: str
    fired_at: str | None
    outcome: str


class Store:
    """Owns one `aiosqlite` connection. Construct via `Store.open()`, not
    directly, so migrations always run before any query does."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    @classmethod
    async def open(cls, path: str | Path) -> Store:
        conn = await aiosqlite.connect(str(path))
        conn.row_factory = aiosqlite.Row
        # WAL + synchronous=FULL: durability for the alarms table per
        # tasks/04-scheduler.md — a power cut must not lose or corrupt an
        # alarm. (WAL is a no-op on ":memory:" databases; harmless there.)
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA synchronous=FULL")
        await conn.commit()
        store = cls(conn)
        await store._migrate()
        return store

    async def close(self) -> None:
        await self._conn.close()

    async def _migrate(self) -> None:
        cur = await self._conn.execute("PRAGMA user_version")
        row = await cur.fetchone()
        current_version = int(row[0]) if row is not None else 0
        for path in sorted(_MIGRATIONS_DIR.glob("*.sql")):
            version = int(path.name.split("_", 1)[0])
            if version <= current_version:
                continue
            await self._conn.executescript(path.read_text())
            await self._conn.execute(f"PRAGMA user_version = {version}")
            await self._conn.commit()

    # --- alarms --------------------------------------------------------

    async def list_alarms(self) -> list[AlarmRow]:
        cur = await self._conn.execute(
            "SELECT id, enabled, time, days, routine_id, pre_roll_s, "
            "skip_next, last_fired_at, timezone FROM alarms"
        )
        rows = await cur.fetchall()
        return [_row_to_alarm_row(r) for r in rows]

    async def upsert_alarm(self, row: AlarmRow) -> None:
        await self._conn.execute(
            """
            INSERT INTO alarms
                (id, enabled, time, days, routine_id, pre_roll_s,
                 skip_next, last_fired_at, timezone)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                enabled = excluded.enabled,
                time = excluded.time,
                days = excluded.days,
                routine_id = excluded.routine_id,
                pre_roll_s = excluded.pre_roll_s,
                skip_next = excluded.skip_next,
                last_fired_at = excluded.last_fired_at,
                timezone = excluded.timezone
            """,
            (
                row.id,
                int(row.enabled),
                row.time,
                row.days,
                row.routine_id,
                row.pre_roll_s,
                int(row.skip_next),
                row.last_fired_at,
                row.timezone,
            ),
        )
        await self._conn.commit()

    async def delete_alarm(self, alarm_id: str) -> None:
        await self._conn.execute("DELETE FROM alarms WHERE id = ?", (alarm_id,))
        await self._conn.execute("DELETE FROM occurrences WHERE alarm_id = ?", (alarm_id,))
        await self._conn.commit()

    # --- occurrences -----------------------------------------------------

    async def list_occurrences(self) -> list[OccurrenceRow]:
        cur = await self._conn.execute(
            "SELECT alarm_id, local_date, fired_at, outcome FROM occurrences"
        )
        rows = await cur.fetchall()
        return [
            OccurrenceRow(
                alarm_id=str(r["alarm_id"]),
                local_date=str(r["local_date"]),
                fired_at=r["fired_at"],
                outcome=str(r["outcome"]),
            )
            for r in rows
        ]

    async def reserve_occurrence(
        self, alarm_id: str, local_date: str, *, outcome: str, fired_at: str | None
    ) -> bool:
        """Insert the `(alarm_id, local_date)` occurrence row if it doesn't
        already exist. Returns whether it was newly inserted.

        This is the idempotency gate from docs/05-scheduler.md rule 7: the
        caller must reserve the occurrence *before* triggering any side
        effect (emitting `alarm.fire`, starting a routine), and only follow
        through if this returns `True` — so a crash-and-restart that replays
        the same tick can never double-fire.
        """
        cur = await self._conn.execute(
            "INSERT INTO occurrences (alarm_id, local_date, fired_at, outcome) "
            "VALUES (?, ?, ?, ?) ON CONFLICT (alarm_id, local_date) DO NOTHING",
            (alarm_id, local_date, fired_at, outcome),
        )
        await self._conn.commit()
        return cur.rowcount == 1

    # --- events ------------------------------------------------------------

    async def log_event(self, event: Event, at: datetime) -> None:
        """Every event is written here with a timestamp (docs/07-api-and-state.md)
        — `at` comes from the caller's injected `Clock`, not wall-clock I/O,
        so the log stays deterministic under tests."""
        await self._conn.execute(
            "INSERT INTO events (type, payload, at) VALUES (?, ?, ?)",
            (event.type.value, json.dumps(event.payload), at.isoformat()),
        )
        await self._conn.commit()


def _row_to_alarm_row(r: aiosqlite.Row) -> AlarmRow:
    return AlarmRow(
        id=str(r["id"]),
        enabled=bool(r["enabled"]),
        time=str(r["time"]),
        days=str(r["days"]),
        routine_id=str(r["routine_id"]),
        pre_roll_s=int(r["pre_roll_s"]),
        skip_next=bool(r["skip_next"]),
        last_fired_at=r["last_fired_at"],
        timezone=str(r["timezone"]),
    )
