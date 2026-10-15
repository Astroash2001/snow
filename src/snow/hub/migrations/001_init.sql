CREATE TABLE events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ns INTEGER NOT NULL,
    type TEXT NOT NULL,
    source TEXT NOT NULL,
    correlation_id TEXT,
    turn_id TEXT,
    causation_id INTEGER,
    user_id TEXT NOT NULL DEFAULT 'owner',
    risk_tier TEXT NOT NULL DEFAULT 'free',
    reason TEXT,
    result TEXT,
    payload TEXT NOT NULL,
    content TEXT
);

CREATE INDEX idx_events_ts_ns ON events (ts_ns);
CREATE INDEX idx_events_type_seq ON events (type, seq);

CREATE TABLE state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
