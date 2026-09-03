-- Initial schema: alarms, occurrences (the fire/miss audit log and the
-- idempotency gate from docs/05-scheduler.md rule 7), and the event log.

CREATE TABLE alarms (
    id TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL,
    time TEXT NOT NULL,              -- "HH:MM:SS" local wall time
    days TEXT NOT NULL,              -- JSON array of ISO weekdays 1-7; "[]" = one-shot
    routine_id TEXT NOT NULL,
    pre_roll_s INTEGER NOT NULL,
    skip_next INTEGER NOT NULL DEFAULT 0,
    last_fired_at TEXT,              -- ISO-8601, nullable
    timezone TEXT NOT NULL           -- IANA zone name
);

CREATE TABLE occurrences (
    alarm_id TEXT NOT NULL,
    local_date TEXT NOT NULL,        -- "YYYY-MM-DD" in the alarm's own timezone
    fired_at TEXT,
    outcome TEXT NOT NULL,           -- 'fired' | 'missed' | 'skipped'
    PRIMARY KEY (alarm_id, local_date)
);

CREATE INDEX idx_occurrences_alarm ON occurrences(alarm_id);

CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    payload TEXT NOT NULL,           -- JSON
    at TEXT NOT NULL                 -- ISO-8601
);

CREATE INDEX idx_events_at ON events(at);
