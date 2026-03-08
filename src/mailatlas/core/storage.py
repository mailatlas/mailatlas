from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .models import DocumentRecord, DocumentRef, ImapSyncState, NormalizedDocument, StoredAsset


PARSER_VERSION = "v1"


@dataclass(frozen=True)
class DocumentSaveResult:
    ref: DocumentRef
    status: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return cleaned or "asset"


def _rewrite_inline_asset_references(html_body: str, html_file: Path, assets: list[StoredAsset], workspace_path: Path) -> str:
    rewritten = html_body
    for asset in assets:
        if not asset.cid:
            continue
        asset_path = workspace_path / asset.file_path
        relative_path = os.path.relpath(asset_path, html_file.parent)
        rewritten = re.sub(
            rf'(["\'])cid:{re.escape(asset.cid)}(["\'])',
            rf'\1{relative_path}\2',
            rewritten,
            flags=re.IGNORECASE,
        )
    return rewritten


class WorkspaceStore:
    def __init__(self, db_path: str | Path, workspace_path: str | Path):
        self.db_path = Path(db_path).expanduser().resolve()
        self.workspace_path = Path(workspace_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.raw_dir = self.workspace_path / "raw"
        self.html_dir = self.workspace_path / "html"
        self.assets_dir = self.workspace_path / "assets"
        self.exports_dir = self.workspace_path / "exports"
        self.briefs_dir = self.workspace_path / "briefs"

        self.workspace_path.mkdir(parents=True, exist_ok=True)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.html_dir.mkdir(parents=True, exist_ok=True)
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        self.exports_dir.mkdir(parents=True, exist_ok=True)
        self.briefs_dir.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    source_kind TEXT NOT NULL,
                    message_id TEXT,
                    thread_id TEXT,
                    subject TEXT NOT NULL,
                    sender_name TEXT,
                    sender_email TEXT,
                    author TEXT,
                    received_at TEXT,
                    published_at TEXT,
                    body_text TEXT NOT NULL,
                    body_html_path TEXT,
                    raw_path TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_documents_message_id ON documents(message_id);
                CREATE INDEX IF NOT EXISTS idx_documents_content_hash ON documents(content_hash);
                CREATE INDEX IF NOT EXISTS idx_documents_subject ON documents(subject);

                CREATE TABLE IF NOT EXISTS assets (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    ordinal INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    cid TEXT,
                    sha256 TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS imports (
                    id TEXT PRIMARY KEY,
                    source_kind TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    parser_version TEXT NOT NULL,
                    imported_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error TEXT
                );

                CREATE TABLE IF NOT EXISTS brief_runs (
                    id TEXT PRIMARY KEY,
                    output_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    model_config_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS brief_run_documents (
                    brief_run_id TEXT NOT NULL REFERENCES brief_runs(id) ON DELETE CASCADE,
                    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    PRIMARY KEY (brief_run_id, document_id)
                );

                CREATE TABLE IF NOT EXISTS imap_sync_state (
                    host TEXT NOT NULL,
                    port INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    folder TEXT NOT NULL,
                    uidvalidity TEXT,
                    last_uid INTEGER NOT NULL DEFAULT 0,
                    last_synced_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error TEXT,
                    PRIMARY KEY (host, port, username, folder)
                );
                """
            )

    def _record_import(self, source_kind: str, source_path: str, status: str, error: str | None = None) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO imports (id, source_kind, source_path, parser_version, imported_at, status, error)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (str(uuid.uuid4()), source_kind, source_path, PARSER_VERSION, _utc_now(), status, error),
            )

    def _find_existing(self, document: NormalizedDocument) -> DocumentRecord | None:
        query = "SELECT * FROM documents WHERE content_hash = ? LIMIT 1"
        params: tuple[str, ...] = (document.content_hash,)
        if document.message_id:
            query = "SELECT * FROM documents WHERE message_id = ? LIMIT 1"
            params = (document.message_id,)

        with self._connect() as connection:
            row = connection.execute(query, params).fetchone()
            if not row:
                return None
        return self.get_document(row["id"])

    def save_document_result(self, document: NormalizedDocument, source_path: str) -> DocumentSaveResult:
        existing = self._find_existing(document)
        if existing:
            self._record_import(document.source_kind, source_path, "duplicate")
            return DocumentSaveResult(
                ref=DocumentRef(
                    id=existing.id,
                    subject=existing.subject,
                    source_kind=existing.source_kind,
                    created_at=existing.created_at,
                ),
                status="duplicate",
            )

        document_id = str(uuid.uuid4())
        created_at = _utc_now()
        raw_extension = ".eml" if document.source_kind in {"eml", "imap"} else ".bin"
        raw_relative = Path("raw") / f"{document_id}{raw_extension}"
        raw_target = self.workspace_path / raw_relative
        raw_target.write_bytes(document.raw_bytes)

        stored_assets: list[StoredAsset] = []
        asset_root = self.assets_dir / document_id
        asset_root.mkdir(parents=True, exist_ok=True)

        for ordinal, asset in enumerate(document.assets, start=1):
            filename = _safe_filename(asset.filename)
            relative_path = Path("assets") / document_id / f"{ordinal:03d}-{filename}"
            target_path = self.workspace_path / relative_path
            target_path.write_bytes(asset.content_bytes)
            stored_assets.append(
                StoredAsset(
                    id=str(uuid.uuid4()),
                    document_id=document_id,
                    ordinal=ordinal,
                    kind=asset.kind,
                    mime_type=asset.mime_type,
                    file_path=relative_path.as_posix(),
                    cid=asset.cid,
                    sha256=asset.sha256,
                )
            )

        html_relative: str | None = None
        if document.body_html:
            html_path = self.html_dir / f"{document_id}.html"
            html_relative = Path("html") / f"{document_id}.html"
            html_path.write_text(
                _rewrite_inline_asset_references(document.body_html, html_path, stored_assets, self.workspace_path),
                encoding="utf-8",
            )

        metadata = dict(document.metadata)
        metadata["provenance"] = document.provenance

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO documents (
                    id, source_kind, message_id, thread_id, subject, sender_name, sender_email, author,
                    received_at, published_at, body_text, body_html_path, raw_path, content_hash, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    document.source_kind,
                    document.message_id,
                    document.thread_id,
                    document.subject,
                    document.sender_name,
                    document.sender_email,
                    document.author,
                    document.received_at,
                    document.published_at,
                    document.body_text,
                    html_relative.as_posix() if html_relative else None,
                    raw_relative.as_posix(),
                    document.content_hash,
                    json.dumps(metadata),
                    created_at,
                ),
            )
            connection.executemany(
                """
                INSERT INTO assets (id, document_id, ordinal, kind, mime_type, file_path, cid, sha256)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        asset.id,
                        asset.document_id,
                        asset.ordinal,
                        asset.kind,
                        asset.mime_type,
                        asset.file_path,
                        asset.cid,
                        asset.sha256,
                    )
                    for asset in stored_assets
                ],
            )

        self._record_import(document.source_kind, source_path, "ingested")
        return DocumentSaveResult(
            ref=DocumentRef(id=document_id, subject=document.subject, source_kind=document.source_kind, created_at=created_at),
            status="ingested",
        )

    def save_document(self, document: NormalizedDocument, source_path: str) -> DocumentRef:
        return self.save_document_result(document, source_path).ref

    def get_document(self, document_id: str) -> DocumentRecord:
        with self._connect() as connection:
            document_row = connection.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
            if not document_row:
                raise KeyError(f"Document not found: {document_id}")
            asset_rows = connection.execute(
                "SELECT * FROM assets WHERE document_id = ? ORDER BY ordinal ASC",
                (document_id,),
            ).fetchall()

        return DocumentRecord(
            id=document_row["id"],
            source_kind=document_row["source_kind"],
            message_id=document_row["message_id"],
            thread_id=document_row["thread_id"],
            subject=document_row["subject"],
            sender_name=document_row["sender_name"],
            sender_email=document_row["sender_email"],
            author=document_row["author"],
            received_at=document_row["received_at"],
            published_at=document_row["published_at"],
            body_text=document_row["body_text"],
            body_html_path=document_row["body_html_path"],
            raw_path=document_row["raw_path"],
            content_hash=document_row["content_hash"],
            metadata=json.loads(document_row["metadata_json"]),
            created_at=document_row["created_at"],
            assets=[
                StoredAsset(
                    id=row["id"],
                    document_id=row["document_id"],
                    ordinal=row["ordinal"],
                    kind=row["kind"],
                    mime_type=row["mime_type"],
                    file_path=row["file_path"],
                    cid=row["cid"],
                    sha256=row["sha256"],
                )
                for row in asset_rows
            ],
        )

    def list_documents(self, query: str | None = None) -> list[DocumentRef]:
        with self._connect() as connection:
            if query:
                pattern = f"%{query}%"
                rows = connection.execute(
                    """
                    SELECT id, subject, source_kind, created_at
                    FROM documents
                    WHERE subject LIKE ? OR sender_name LIKE ? OR sender_email LIKE ? OR author LIKE ? OR body_text LIKE ?
                    ORDER BY COALESCE(received_at, created_at) DESC, created_at DESC
                    """,
                    (pattern, pattern, pattern, pattern, pattern),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT id, subject, source_kind, created_at
                    FROM documents
                    ORDER BY COALESCE(received_at, created_at) DESC, created_at DESC
                    """
                ).fetchall()

        return [
            DocumentRef(id=row["id"], subject=row["subject"], source_kind=row["source_kind"], created_at=row["created_at"])
            for row in rows
        ]

    def resolve_path(self, relative_path: str | None) -> Path | None:
        if not relative_path:
            return None
        return self.workspace_path / relative_path

    def save_export(self, document_id: str, format_name: str, content: str) -> Path:
        target = self.exports_dir / f"{document_id}.{format_name}"
        target.write_text(content, encoding="utf-8")
        return target

    def save_brief_run(self, output_path: str, document_ids: list[str], model_config: dict[str, str]) -> str:
        brief_run_id = str(uuid.uuid4())
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO brief_runs (id, output_path, created_at, model_config_json)
                VALUES (?, ?, ?, ?)
                """,
                (brief_run_id, output_path, _utc_now(), json.dumps(model_config)),
            )
            connection.executemany(
                """
                INSERT INTO brief_run_documents (brief_run_id, document_id)
                VALUES (?, ?)
                """,
                [(brief_run_id, document_id) for document_id in document_ids],
            )
        return brief_run_id

    def get_imap_sync_state(self, host: str, port: int, username: str, folder: str) -> ImapSyncState | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT host, port, username, folder, uidvalidity, last_uid, last_synced_at, status, error
                FROM imap_sync_state
                WHERE host = ? AND port = ? AND username = ? AND folder = ?
                """,
                (host, port, username, folder),
            ).fetchone()

        if not row:
            return None

        return ImapSyncState(
            host=row["host"],
            port=row["port"],
            username=row["username"],
            folder=row["folder"],
            uidvalidity=row["uidvalidity"],
            last_uid=int(row["last_uid"] or 0),
            last_synced_at=row["last_synced_at"],
            status=row["status"],
            error=row["error"],
        )

    def save_imap_sync_state(
        self,
        host: str,
        port: int,
        username: str,
        folder: str,
        uidvalidity: str | None,
        last_uid: int,
        status: str,
        error: str | None = None,
    ) -> ImapSyncState:
        last_synced_at = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO imap_sync_state (
                    host, port, username, folder, uidvalidity, last_uid, last_synced_at, status, error
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(host, port, username, folder)
                DO UPDATE SET
                    uidvalidity = excluded.uidvalidity,
                    last_uid = excluded.last_uid,
                    last_synced_at = excluded.last_synced_at,
                    status = excluded.status,
                    error = excluded.error
                """,
                (host, port, username, folder, uidvalidity, last_uid, last_synced_at, status, error),
            )

        return ImapSyncState(
            host=host,
            port=port,
            username=username,
            folder=folder,
            uidvalidity=uidvalidity,
            last_uid=last_uid,
            last_synced_at=last_synced_at,
            status=status,
            error=error,
        )
