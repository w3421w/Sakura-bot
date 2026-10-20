CREATE TABLE IF NOT EXISTS consent (
    group_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    agreed_at REAL NOT NULL,
    PRIMARY KEY (group_id, user_id)
);

CREATE TABLE IF NOT EXISTS opt_out (
    group_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    opted_out_at REAL NOT NULL,
    PRIMARY KEY (group_id, user_id)
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    group_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    ts REAL NOT NULL,
    is_bot INTEGER NOT NULL DEFAULT 0,
    message TEXT,
    timestamp REAL,
    message_id TEXT,
    sender_info TEXT
);

CREATE INDEX IF NOT EXISTS idx_messages_group_ts ON messages(group_id, ts);

CREATE TABLE IF NOT EXISTS proactive (
    group_id INTEGER NOT NULL,
    ts REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS memory (
    id INTEGER PRIMARY KEY,
    group_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at REAL NOT NULL,
    source_message_id TEXT,
    source_user_id INTEGER,
    source_kind TEXT NOT NULL DEFAULT 'manual'
);

CREATE TABLE IF NOT EXISTS user_profiles (
    group_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    nickname TEXT,
    preferred_name TEXT,
    role TEXT,
    notes TEXT,
    updated_at REAL NOT NULL,
    PRIMARY KEY (group_id, user_id)
);

CREATE TABLE IF NOT EXISTS user_memory (
    id INTEGER PRIMARY KEY,
    group_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'approved',
    created_at REAL NOT NULL,
    source_message_id TEXT,
    source_user_id INTEGER,
    source_kind TEXT NOT NULL DEFAULT 'manual'
);

CREATE INDEX IF NOT EXISTS idx_user_memory_scope
    ON user_memory(group_id, user_id, status, created_at);

CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Tulpa-inspired durable event and send idempotency.  These tables are kept
-- separate from chat content so a replay cannot trigger a second reply.
CREATE TABLE IF NOT EXISTS event_receipts (
    event_key TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    message_id TEXT,
    received_at REAL NOT NULL,
    expires_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_event_receipts_expiry
    ON event_receipts(expires_at);

CREATE TABLE IF NOT EXISTS outbound_receipts (
    idempotency_key TEXT PRIMARY KEY,
    scope_id TEXT NOT NULL,
    message TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    error TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_outbound_receipts_scope
    ON outbound_receipts(scope_id, updated_at);

-- Durable persona mode/timer so a restart cannot silently undo Black Sakura
-- or reset the 30-minute quiet timer.
CREATE TABLE IF NOT EXISTS persona_state (
    group_id INTEGER PRIMARY KEY,
    mode TEXT NOT NULL DEFAULT 'sakura',
    insult_count INTEGER NOT NULL DEFAULT 0,
    last_insult_at REAL,
    auto_black INTEGER NOT NULL DEFAULT 0,
    changed_at REAL NOT NULL DEFAULT 0,
    switch_count INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL
);
