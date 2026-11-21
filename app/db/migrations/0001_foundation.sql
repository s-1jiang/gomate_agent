CREATE TABLE users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE auth_tokens (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at REAL NOT NULL,
    revoked_at REAL
);
CREATE INDEX idx_auth_tokens_user ON auth_tokens(user_id);

CREATE TABLE login_limits (
    key TEXT PRIMARY KEY,
    attempts INTEGER NOT NULL CHECK (attempts > 0),
    expires_at REAL NOT NULL
);

CREATE TABLE conversations (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (user_id, id)
);
CREATE INDEX idx_conversations_owner ON conversations(user_id, created_at);

CREATE TABLE messages (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    client_message_id TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (user_id, session_id, id),
    UNIQUE (user_id, session_id, client_message_id),
    FOREIGN KEY (user_id, session_id) REFERENCES conversations(user_id, id) ON DELETE CASCADE
);
CREATE INDEX idx_messages_session ON messages(user_id, session_id, created_at, id);

CREATE TABLE runs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    message_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (status IN (
        'queued', 'running', 'waiting_user', 'succeeded', 'partial', 'failed',
        'cancelled', 'timed_out', 'interrupted'
    )),
    deadline REAL NOT NULL,
    tool_calls INTEGER NOT NULL DEFAULT 0,
    external_requests INTEGER NOT NULL DEFAULT 0,
    llm_calls INTEGER NOT NULL DEFAULT 0,
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (user_id, session_id, id),
    FOREIGN KEY (user_id, session_id, message_id)
        REFERENCES messages(user_id, session_id, id) ON DELETE CASCADE
);
CREATE INDEX idx_runs_owner_status ON runs(user_id, status);

CREATE TABLE session_leases (
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    expires_at REAL NOT NULL,
    fencing_token INTEGER NOT NULL CHECK (fencing_token > 0),
    PRIMARY KEY (user_id, session_id),
    FOREIGN KEY (user_id, session_id, run_id)
        REFERENCES runs(user_id, session_id, id) ON DELETE CASCADE
);
