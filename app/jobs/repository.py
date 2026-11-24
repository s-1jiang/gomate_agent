import time
from uuid import uuid4

from app.core.identity import AuthContext
from app.db.repositories import now_iso


class QueueRepository:
    """Durable outbox and worker liveness. No prompt or credential enters the broker."""

    def __init__(self, database):
        self.database = database

    def claim_publication(self):
        now, token = time.time(), str(uuid4())
        with self.database.connect(write=True) as connection:
            row = connection.execute(
                "SELECT j.run_id FROM run_jobs j JOIN runs r ON r.id = j.run_id "
                "WHERE j.published_at IS NULL AND j.publish_until <= ? "
                "AND r.status = 'queued' AND r.deadline > ? ORDER BY j.created_at LIMIT 1",
                (now, now),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE run_jobs SET publish_owner = ?, publish_until = ? WHERE run_id = ?",
                (token, now + 15, row["run_id"]),
            )
            return row["run_id"], token

    def publication_done(self, run_id, token):
        with self.database.connect(write=True) as connection:
            connection.execute(
                "UPDATE run_jobs SET published_at = ?, publish_until = 0 "
                "WHERE run_id = ? AND publish_owner = ?",
                (now_iso(), run_id, token),
            )

    def publication_failed(self, run_id, token):
        with self.database.connect(write=True) as connection:
            connection.execute(
                "UPDATE run_jobs SET publish_until = 0, publish_owner = NULL "
                "WHERE run_id = ? AND publish_owner = ? AND published_at IS NULL",
                (run_id, token),
            )

    def identity(self, run_id):
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT r.user_id, u.username FROM runs r JOIN users u ON u.id = r.user_id "
                "JOIN run_jobs j ON j.run_id = r.id WHERE r.id = ?",
                (run_id,),
            ).fetchone()
        return AuthContext(row["user_id"], row["username"]) if row else None

    def heartbeat(self, worker_id, run_ids):
        if not run_ids:
            return
        with self.database.connect(write=True) as connection:
            connection.executemany(
                "UPDATE run_jobs SET heartbeat_at = ? WHERE run_id = ? AND worker_id = ?",
                [(time.time(), run_id, worker_id) for run_id in run_ids],
            )

    def maintain(self, stale_seconds):
        now = time.time()
        with self.database.connect(write=True) as connection:
            connection.execute(
                "UPDATE runs SET status = 'timed_out', error_code = 'RUN_TIMEOUT', "
                "error_message = '任务已超时，请重新发送消息', updated_at = ? "
                "WHERE status IN ('queued', 'running') AND deadline <= ?",
                (now_iso(), now),
            )
            # A claimed job may already have spent provider budget: never replay it from zero.
            connection.execute(
                "UPDATE runs SET status = 'interrupted', error_code = 'WORKER_LOST', "
                "error_message = '后台任务已中断，请重新发送消息', updated_at = ? "
                "WHERE status = 'running' AND NOT EXISTS (SELECT 1 FROM run_jobs j "
                "WHERE j.run_id = runs.id AND j.worker_id IS NOT NULL AND j.heartbeat_at > ?)",
                (now_iso(), now - stale_seconds),
            )
            connection.execute(
                "UPDATE session_leases SET expires_at = 0 WHERE EXISTS "
                "(SELECT 1 FROM runs r WHERE r.id = session_leases.run_id "
                "AND r.status NOT IN ('queued', 'running', 'waiting_user'))"
            )
