import hashlib
import json
import sqlite3
import time
from datetime import UTC, datetime
from uuid import uuid4

from app.core.config import Settings
from app.core.errors import AppError, not_found
from app.core.identity import AuthContext
from app.db.database import Database


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def require_conversation(connection: sqlite3.Connection, auth: AuthContext, session_id: str):
    row = connection.execute(
        "SELECT * FROM conversations WHERE user_id = ? AND id = ?",
        (auth.user_id, session_id),
    ).fetchone()
    if row is None:
        raise not_found()
    return dict(row)


class AuthRepository:
    def __init__(self, database: Database):
        self.database = database

    def register(self, username: str, password_hash: str) -> dict:
        user = {"id": str(uuid4()), "username": username, "created_at": now_iso()}
        try:
            with self.database.connect(write=True) as connection:
                connection.execute(
                    "INSERT INTO users(id, username, password_hash, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (user["id"], username, password_hash, user["created_at"]),
                )
        except sqlite3.IntegrityError as exc:
            raise AppError("USERNAME_TAKEN", "用户名已存在", 409) from exc
        return user

    def find_user(self, username: str) -> dict | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ).fetchone()
            return dict(row) if row else None

    def reserve_login(self, username: str, address: str, settings: Settings) -> None:
        now = time.time()
        limits = [
            (f"account:{address}:{username.lower()}", settings.login_max_attempts),
            (f"address:{address}", settings.login_max_attempts * 10),
        ]
        with self.database.connect(write=True) as connection:
            connection.execute("DELETE FROM login_limits WHERE expires_at <= ?", (now,))
            keys = [(hashlib.sha256(key.encode()).hexdigest(), limit) for key, limit in limits]
            for key, limit in keys:
                row = connection.execute(
                    "SELECT attempts FROM login_limits WHERE key = ?", (key,)
                ).fetchone()
                if row and row["attempts"] >= limit:
                    raise AppError("RATE_LIMITED", "登录尝试过于频繁，请稍后重试", 429)
            for key, _ in keys:
                connection.execute(
                    "INSERT INTO login_limits(key, attempts, expires_at) VALUES (?, 1, ?) "
                    "ON CONFLICT(key) DO UPDATE SET attempts = attempts + 1",
                    (key, now + settings.login_window_seconds),
                )

    def store_token(self, digest: str, user_id: str, expires_at: float) -> None:
        with self.database.connect(write=True) as connection:
            connection.execute(
                "INSERT INTO auth_tokens(token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                (digest, user_id, expires_at),
            )

    def authenticate(self, digest: str) -> dict:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT u.id, u.username, u.created_at FROM auth_tokens t "
                "JOIN users u ON u.id = t.user_id "
                "WHERE t.token_hash = ? AND t.revoked_at IS NULL AND t.expires_at > ?",
                (digest, time.time()),
            ).fetchone()
        if row is None:
            raise AppError("UNAUTHORIZED", "请登录或重新登录", 401)
        return dict(row)

    def revoke(self, digest: str) -> None:
        with self.database.connect(write=True) as connection:
            connection.execute(
                "UPDATE auth_tokens SET revoked_at = ? WHERE token_hash = ?",
                (time.time(), digest),
            )


class ConversationRepository:
    def __init__(self, database: Database, auth: AuthContext):
        self.database = database
        self.auth = auth

    def create(self, title: str) -> dict:
        item = {"id": str(uuid4()), "title": title, "created_at": now_iso()}
        with self.database.connect(write=True) as connection:
            connection.execute(
                "INSERT INTO conversations(id, user_id, title, created_at) VALUES (?, ?, ?, ?)",
                (item["id"], self.auth.user_id, title, item["created_at"]),
            )
        return item

    def list_conversations(self, limit: int, offset: int) -> list[dict]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT id, title, created_at FROM conversations WHERE user_id = ? "
                "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                (self.auth.user_id, limit, offset),
            ).fetchall()
        return [dict(row) for row in rows]

    def messages(self, session_id: str, limit: int, after: str | None) -> list[dict]:
        from app.retrieval.repository import visible_sources

        with self.database.connect() as connection:
            require_conversation(connection, self.auth, session_id)
            cursor_time, cursor_id = "", ""
            if after:
                cursor = connection.execute(
                    "SELECT created_at, id FROM messages WHERE user_id = ? AND session_id = ? "
                    "AND id = ?",
                    (self.auth.user_id, session_id, after),
                ).fetchone()
                if cursor is None:
                    raise not_found()
                cursor_time, cursor_id = cursor["created_at"], cursor["id"]
            rows = connection.execute(
                "SELECT * FROM messages WHERE user_id = ? AND session_id = ? "
                "AND (created_at, id) > (?, ?) ORDER BY created_at, id LIMIT ?",
                (self.auth.user_id, session_id, cursor_time, cursor_id, limit),
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                sources = json.loads(item.pop("sources_json"))
                map_result = item.pop("map_result_json")
                item["map_result"] = json.loads(map_result) if map_result else None
                item["sources"] = visible_sources(connection, self.auth, session_id, sources)
                result.append(item)
        return result

    def delete(self, session_id: str) -> None:
        with self.database.connect(write=True) as connection:
            require_conversation(connection, self.auth, session_id)
            connection.execute(
                "DELETE FROM conversations WHERE user_id = ? AND id = ?",
                (self.auth.user_id, session_id),
            )


class RunRepository:
    def __init__(self, database: Database, auth: AuthContext):
        self.database = database
        self.auth = auth

    def accept(self, session_id: str, client_id: str, content: str, settings: Settings):
        now, timestamp = time.time(), now_iso()
        with self.database.connect(write=True) as connection:
            require_conversation(connection, self.auth, session_id)
            previous = connection.execute(
                "SELECT m.content, r.* FROM messages m JOIN runs r ON r.message_id = m.id "
                "AND r.user_id = m.user_id AND r.session_id = m.session_id "
                "WHERE m.user_id = ? AND m.session_id = ? AND m.client_message_id = ?",
                (self.auth.user_id, session_id, client_id),
            ).fetchone()
            if previous:
                if previous["content"] != content:
                    raise AppError("IDEMPOTENCY_CONFLICT", "同一消息标识不能提交不同内容", 409)
                return dict(previous), False
            connection.execute(
                "UPDATE runs SET status = 'timed_out', error_code = 'RUN_TIMEOUT', "
                "updated_at = ? WHERE user_id = ? AND status IN ('queued', 'running') "
                "AND deadline <= ?",
                (timestamp, self.auth.user_id, now),
            )
            lease = connection.execute(
                "SELECT * FROM session_leases WHERE user_id = ? AND session_id = ?",
                (self.auth.user_id, session_id),
            ).fetchone()
            if lease and lease["expires_at"] > now:
                raise AppError("SESSION_BUSY", "此会话已有运行中的任务", 409)
            active = connection.execute(
                "SELECT COUNT(*) FROM runs WHERE user_id = ? AND status IN ('queued', 'running')",
                (self.auth.user_id,),
            ).fetchone()[0]
            if active >= settings.max_active_runs_per_user:
                raise AppError("RUN_LIMIT_EXCEEDED", "活跃任务数量已达上限", 429)
            message_id, run_id = str(uuid4()), str(uuid4())
            deadline = now + settings.run_timeout_seconds
            connection.execute(
                "INSERT INTO messages(id, user_id, session_id, role, content, client_message_id, "
                "created_at) VALUES (?, ?, ?, 'user', ?, ?, ?)",
                (message_id, self.auth.user_id, session_id, content, client_id, timestamp),
            )
            connection.execute(
                "INSERT INTO runs(id, user_id, session_id, message_id, status, deadline, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, 'queued', ?, ?, ?)",
                (run_id, self.auth.user_id, session_id, message_id, deadline, timestamp, timestamp),
            )
            connection.execute(
                "INSERT INTO session_leases"
                "(user_id, session_id, run_id, expires_at, fencing_token) "
                "VALUES (?, ?, ?, ?, 1) ON CONFLICT(user_id, session_id) DO UPDATE SET "
                "run_id = excluded.run_id, expires_at = excluded.expires_at, "
                "fencing_token = session_leases.fencing_token + 1",
                (self.auth.user_id, session_id, run_id, deadline),
            )
            row = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            if settings.task_execution_mode == "queue":
                connection.execute(
                    "INSERT INTO run_jobs(run_id, created_at) VALUES (?, ?)", (run_id, timestamp)
                )
        return dict(row), True

    def get(self, run_id: str) -> dict:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM runs WHERE user_id = ? AND id = ?", (self.auth.user_id, run_id)
            ).fetchone()
        if row is None:
            raise not_found()
        item = dict(row)
        item["workflow_events"] = json.loads(item.pop("workflow_json"))
        return item

    def progress(self, run_id: str, fencing_token: int, events: list, counts: dict) -> None:
        with self.database.connect(write=True) as connection:
            if self._active(connection, run_id, fencing_token) is None:
                raise AppError("CANCELLED", "任务已取消或过期", 409)
            connection.execute(
                "UPDATE runs SET workflow_json = ?, tool_calls = ?, external_requests = ?, "
                "llm_calls = ?, updated_at = ? WHERE user_id = ? AND id = ?",
                (
                    json.dumps(events, ensure_ascii=False),
                    counts["tool"],
                    counts["external"],
                    counts["llm"],
                    now_iso(),
                    self.auth.user_id,
                    run_id,
                ),
            )

    def latest(self, session_id: str) -> dict | None:
        with self.database.connect() as connection:
            require_conversation(connection, self.auth, session_id)
            row = connection.execute(
                "SELECT id FROM runs WHERE user_id = ? AND session_id = ? "
                "ORDER BY created_at DESC, id DESC LIMIT 1",
                (self.auth.user_id, session_id),
            ).fetchone()
        return self.get(row["id"]) if row else None

    def start(self, run_id: str, worker_id: str | None = None) -> dict | None:
        with self.database.connect(write=True) as connection:
            row = connection.execute(
                "SELECT r.*, l.fencing_token FROM runs r JOIN session_leases l "
                "ON l.user_id = r.user_id AND l.session_id = r.session_id AND l.run_id = r.id "
                "WHERE r.user_id = ? AND r.id = ? AND r.status = 'queued' "
                "AND r.deadline > ? AND l.expires_at > ?",
                (self.auth.user_id, run_id, time.time(), time.time()),
            ).fetchone()
            if row is None:
                connection.execute(
                    "UPDATE runs SET status = 'timed_out', error_code = 'RUN_TIMEOUT', "
                    "updated_at = ? WHERE user_id = ? AND id = ? AND status = 'queued' "
                    "AND deadline <= ?",
                    (now_iso(), self.auth.user_id, run_id, time.time()),
                )
                return None
            connection.execute(
                "UPDATE runs SET status = 'running', updated_at = ? WHERE user_id = ? AND id = ?",
                (now_iso(), self.auth.user_id, run_id),
            )
            if worker_id:
                updated = connection.execute(
                    "UPDATE run_jobs SET worker_id = ?, heartbeat_at = ? "
                    "WHERE run_id = ? AND worker_id IS NULL",
                    (worker_id, time.time(), run_id),
                ).rowcount
                if updated != 1:
                    raise AppError("INVALID_JOB_CLAIM", "后台任务领取失败", 409)
        return dict(row)

    def active(self, run_id: str, fencing_token: int) -> bool:
        with self.database.connect() as connection:
            return self._active(connection, run_id, fencing_token) is not None

    def _active(self, connection, run_id: str, fencing_token: int):
        return connection.execute(
            "SELECT r.* FROM runs r JOIN session_leases l ON l.user_id = r.user_id "
            "AND l.session_id = r.session_id AND l.run_id = r.id "
            "WHERE r.user_id = ? AND r.id = ? AND r.status = 'running' "
            "AND r.deadline > ? AND l.expires_at > ? AND l.fencing_token = ?",
            (self.auth.user_id, run_id, time.time(), time.time(), fencing_token),
        ).fetchone()

    def history(self, run: dict, limit: int) -> list[dict]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT role, content, map_result_json FROM messages "
                "WHERE user_id = ? AND session_id = ? "
                "AND (created_at, id) <= (SELECT created_at, id FROM messages "
                "WHERE user_id = ? AND session_id = ? AND id = ?) "
                "ORDER BY created_at DESC, id DESC LIMIT ?",
                (
                    self.auth.user_id,
                    run["session_id"],
                    self.auth.user_id,
                    run["session_id"],
                    run["message_id"],
                    limit,
                ),
            ).fetchall()
        history = []
        for row in reversed(rows):
            item = dict(row)
            stored_map = item.pop("map_result_json")
            item["map_result"] = json.loads(stored_map) if stored_map else None
            history.append(item)
        return history

    def finish(
        self, run_id, fencing_token, content, sources, retrieval_status, counts, map_result=None
    ) -> bool:
        from app.retrieval.repository import visible_sources

        with self.database.connect(write=True) as connection:
            run = self._active(connection, run_id, fencing_token)
            if run is None:
                return False
            checked = visible_sources(connection, self.auth, run["session_id"], sources)
            if any(not source["available"] for source in checked):
                raise AppError("KNOWLEDGE_CHANGED", "检索资料已删除，请重新发送问题", 409)
            connection.execute(
                "INSERT INTO messages(id, user_id, session_id, role, content, created_at, "
                "sources_json, retrieval_status, map_result_json) "
                "VALUES (?, ?, ?, 'assistant', ?, ?, ?, ?, ?)",
                (
                    str(uuid4()),
                    self.auth.user_id,
                    run["session_id"],
                    content,
                    now_iso(),
                    json.dumps(sources, ensure_ascii=False),
                    retrieval_status,
                    json.dumps(map_result, ensure_ascii=False) if map_result else None,
                ),
            )
            connection.execute(
                "UPDATE runs SET status = 'succeeded', tool_calls = ?, external_requests = ?, "
                "llm_calls = ?, updated_at = ? WHERE user_id = ? AND id = ?",
                (
                    counts["tool"],
                    counts["external"],
                    counts["llm"],
                    now_iso(),
                    self.auth.user_id,
                    run_id,
                ),
            )
            connection.execute(
                "UPDATE session_leases SET expires_at = 0 WHERE user_id = ? AND run_id = ? "
                "AND fencing_token = ?",
                (self.auth.user_id, run_id, fencing_token),
            )
        return True

    def fail(self, run_id, fencing_token, error: AppError, counts) -> None:
        status = "timed_out" if error.code in ("RUN_TIMEOUT", "LLM_TIMEOUT") else "failed"
        if error.code == "SERVICE_RESTARTED":
            status = "interrupted"
        with self.database.connect(write=True) as connection:
            connection.execute(
                "UPDATE runs SET status = ?, error_code = ?, error_message = ?, updated_at = ? "
                "WHERE user_id = ? AND id = ? AND status = 'running' "
                "AND EXISTS (SELECT 1 FROM session_leases l WHERE l.user_id = runs.user_id "
                "AND l.run_id = runs.id AND l.fencing_token = ?)",
                (
                    status,
                    error.code,
                    error.message,
                    now_iso(),
                    self.auth.user_id,
                    run_id,
                    fencing_token,
                ),
            )
            # Counts also survive explicit cancellation, without overwriting its status.
            connection.execute(
                "UPDATE runs SET tool_calls = ?, external_requests = ?, llm_calls = ? "
                "WHERE user_id = ? AND id = ?",
                (counts["tool"], counts["external"], counts["llm"], self.auth.user_id, run_id),
            )
            connection.execute(
                "UPDATE session_leases SET expires_at = 0 WHERE user_id = ? AND run_id = ?",
                (self.auth.user_id, run_id),
            )

    def cancel(self, run_id: str) -> dict:
        self.get(run_id)
        with self.database.connect(write=True) as connection:
            connection.execute(
                "UPDATE runs SET status = 'cancelled', updated_at = ? "
                "WHERE user_id = ? AND id = ? AND status IN ('queued', 'running', 'waiting_user')",
                (now_iso(), self.auth.user_id, run_id),
            )
            connection.execute(
                "UPDATE session_leases SET expires_at = 0 WHERE user_id = ? AND run_id = ?",
                (self.auth.user_id, run_id),
            )
        return self.get(run_id)


def interrupt_pending_runs(database: Database) -> None:
    """Single-worker development mode: previous in-process tasks cannot survive restart."""
    with database.connect(write=True) as connection:
        connection.execute(
            "UPDATE runs SET status = 'interrupted', error_code = 'SERVICE_RESTARTED', "
            "updated_at = ? WHERE status IN ('queued', 'running')",
            (now_iso(),),
        )
        connection.execute("UPDATE session_leases SET expires_at = 0")
