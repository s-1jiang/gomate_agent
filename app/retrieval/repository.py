"""Small, local lexical retriever. No embedding or reranking service is implied."""

import hashlib
import json
import math
import re
from collections import Counter
from uuid import uuid4

from app.core.errors import AppError, not_found
from app.core.identity import AuthContext
from app.db.database import Database
from app.db.repositories import now_iso, require_conversation
from app.schemas.knowledge import DocumentCreate


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunks(content: str):
    """Retain exact normalized source text and 1-based line positions."""
    pieces, size, start, previous_line = [], 0, 1, 1
    for line_number, line in enumerate(content.splitlines(keepends=True), 1):
        for offset in range(0, len(line), 1000):
            part = line[offset : offset + 1000]
            if pieces and size + len(part) > 1000:
                yield "".join(pieces), start, previous_line
                pieces, size = [], 0
            if not pieces:
                start = line_number
            pieces.append(part)
            size += len(part)
            previous_line = line_number
    if pieces:
        yield "".join(pieces), start, previous_line


def terms(text: str) -> Counter:
    result = Counter(re.findall(r"[a-z0-9_]+", text.casefold()))
    for word in re.findall(r"[\u3400-\u9fff]+", text):
        if len(word) == 1:
            result[word] += 1
        else:
            result.update(word[index : index + 2] for index in range(len(word) - 1))
    return result


def visible_sources(connection, auth: AuthContext, session_id: str, sources: list) -> list:
    """Reauthorize each source on history reads; deleted evidence is not exposed."""
    result = []
    for source in sources:
        if not source.get("available", True):
            result.append(source)
            continue
        row = connection.execute(
            "SELECT 1 FROM knowledge_documents d JOIN knowledge_chunks c "
            "ON c.document_id = d.id AND c.user_id = d.user_id "
            "WHERE d.user_id = ? AND d.id = ? AND c.id = ? AND d.deleted_at IS NULL "
            "AND (d.session_id IS NULL OR d.session_id = ?) "
            "AND d.content_hash = ? AND c.content_hash = ?",
            (
                auth.user_id,
                source["document_id"],
                source["chunk_id"],
                session_id,
                source["document_hash"],
                source["content_hash"],
            ),
        ).fetchone()
        result.append(
            source
            if row
            else {
                "label": source["label"],
                "cited": source["cited"],
                "available": False,
            }
        )
    return result


class KnowledgeRepository:
    def __init__(self, database: Database, auth: AuthContext):
        self.database, self.auth = database, auth

    def create(self, body: DocumentCreate) -> dict:
        content = body.content.replace("\r\n", "\n").replace("\r", "\n")
        item = {
            "id": str(uuid4()),
            "title": body.title,
            "source_ref": body.source_ref or body.title,
            "scope": body.scope,
            "session_id": body.session_id,
            "document_version": 1,
            "content_hash": digest(content),
            "created_at": now_iso(),
        }
        slices = list(chunks(content))
        with self.database.connect(write=True) as connection:
            if body.session_id:
                require_conversation(connection, self.auth, body.session_id)
            count = connection.execute(
                "SELECT COUNT(*) FROM knowledge_documents WHERE user_id = ? AND deleted_at IS NULL",
                (self.auth.user_id,),
            ).fetchone()[0]
            if count >= 100:
                raise AppError("KNOWLEDGE_LIMIT", "最多保存 100 份资料，请先删除不需要的资料", 409)
            connection.execute(
                "INSERT INTO knowledge_documents(id, user_id, session_id, title, source_ref, "
                "content_hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    item["id"],
                    self.auth.user_id,
                    body.session_id,
                    item["title"],
                    item["source_ref"],
                    item["content_hash"],
                    item["created_at"],
                ),
            )
            connection.executemany(
                "INSERT INTO knowledge_chunks(id, user_id, document_id, text, start_line, "
                "end_line, content_hash) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (str(uuid4()), self.auth.user_id, item["id"], text, start, end, digest(text))
                    for text, start, end in slices
                ],
            )
        return {**item, "chunk_count": len(slices)}

    def list_documents(self, session_id: str | None) -> list[dict]:
        with self.database.connect() as connection:
            if session_id:
                require_conversation(connection, self.auth, session_id)
            rows = connection.execute(
                "SELECT d.*, COUNT(c.id) AS chunk_count FROM knowledge_documents d "
                "JOIN knowledge_chunks c ON c.user_id = d.user_id AND c.document_id = d.id "
                "WHERE d.user_id = ? AND d.deleted_at IS NULL "
                "AND (d.session_id IS NULL OR d.session_id = ?) GROUP BY d.id "
                "ORDER BY d.created_at DESC, d.id DESC",
                (self.auth.user_id, session_id),
            ).fetchall()
        return [{**dict(row), "scope": "session" if row["session_id"] else "user"} for row in rows]

    def delete(self, document_id: str) -> None:
        with self.database.connect(write=True) as connection:
            row = connection.execute(
                "SELECT id FROM knowledge_documents WHERE user_id = ? AND id = ? "
                "AND deleted_at IS NULL",
                (self.auth.user_id, document_id),
            ).fetchone()
            if row is None:
                raise not_found()
            connection.execute(
                "UPDATE knowledge_documents SET deleted_at = ? WHERE user_id = ? AND id = ?",
                (now_iso(), self.auth.user_id, document_id),
            )
            connection.execute(
                "DELETE FROM knowledge_chunks WHERE user_id = ? AND document_id = ?",
                (self.auth.user_id, document_id),
            )
            snapshots = connection.execute(
                "SELECT id, sources_json FROM messages WHERE user_id = ? AND sources_json != '[]'",
                (self.auth.user_id,),
            ).fetchall()
            for snapshot in snapshots:
                sources = json.loads(snapshot["sources_json"])
                if not any(item.get("document_id") == document_id for item in sources):
                    continue
                cleaned = [
                    {"label": item["label"], "cited": item["cited"], "available": False}
                    if item.get("document_id") == document_id
                    else item
                    for item in sources
                ]
                connection.execute(
                    "UPDATE messages SET sources_json = ? WHERE user_id = ? AND id = ?",
                    (json.dumps(cleaned, ensure_ascii=False), self.auth.user_id, snapshot["id"]),
                )

    def search(self, session_id: str, query: str, limit: int = 5) -> list[dict]:
        query_terms = terms(query)
        with self.database.connect() as connection:
            require_conversation(connection, self.auth, session_id)
            # Authorization happens before scoring/top-k, including session visibility.
            rows = connection.execute(
                "SELECT c.*, d.title, d.source_ref, d.session_id, d.document_version, "
                "d.content_hash AS document_hash FROM knowledge_chunks c "
                "JOIN knowledge_documents d ON c.document_id = d.id AND c.user_id = d.user_id "
                "WHERE d.user_id = ? AND d.deleted_at IS NULL "
                "AND (d.session_id IS NULL OR d.session_id = ?) ORDER BY d.id, c.start_line, c.id",
                (self.auth.user_id, session_id),
            ).fetchall()
        scored = []
        for row in rows:
            counts = terms(row["text"] + " " + row["title"])
            score = sum(math.log1p(counts[term]) for term in query_terms if term in counts)
            if score:
                scored.append((score / math.sqrt(max(1, sum(counts.values()))), row))
        scored.sort(key=lambda item: item[0], reverse=True)
        retrieved_at = now_iso()
        return [
            {
                "label": f"R{index}",
                "source_kind": "private_knowledge",
                "scope": "session" if row["session_id"] else "user",
                "document_id": row["document_id"],
                "document_version": row["document_version"],
                "chunk_id": row["id"],
                "title": row["title"],
                "source_ref": row["source_ref"],
                "start_line": row["start_line"],
                "end_line": row["end_line"],
                "excerpt": row["text"],
                "content_hash": row["content_hash"],
                "document_hash": row["document_hash"],
                "retrieval_method": "lexical",
                "retrieved_at": retrieved_at,
                "cited": False,
                "available": True,
            }
            for index, (_, row) in enumerate(scored[:limit], 1)
        ]
