CREATE TABLE run_jobs (
    run_id TEXT PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    publish_owner TEXT,
    publish_until REAL NOT NULL DEFAULT 0,
    published_at TEXT,
    worker_id TEXT,
    heartbeat_at REAL
);
CREATE INDEX idx_run_jobs_publish ON run_jobs(published_at, publish_until);
CREATE INDEX idx_run_jobs_worker ON run_jobs(worker_id, heartbeat_at);
INSERT INTO run_jobs(run_id, created_at)
    SELECT id, created_at FROM runs WHERE status = 'queued';
