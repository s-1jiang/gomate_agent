ALTER TABLE messages ADD COLUMN sources_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE messages ADD COLUMN retrieval_status TEXT;

CREATE TABLE knowledge_documents (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id TEXT,
    title TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    document_version INTEGER NOT NULL DEFAULT 1,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    deleted_at TEXT,
    UNIQUE (user_id, id),
    FOREIGN KEY (user_id, session_id) REFERENCES conversations(user_id, id) ON DELETE CASCADE
);
CREATE INDEX idx_knowledge_visibility ON knowledge_documents(user_id, session_id, deleted_at);

CREATE TABLE knowledge_chunks (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    text TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    FOREIGN KEY (user_id, document_id)
        REFERENCES knowledge_documents(user_id, id) ON DELETE CASCADE
);
CREATE INDEX idx_chunks_document ON knowledge_chunks(user_id, document_id);
