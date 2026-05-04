from __future__ import annotations

import json
import hashlib
import mimetypes
import os
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .models import (
    DocumentRecord,
    DocumentRef,
    ImapSyncState,
    NormalizedDocument,
    OutboundMessage,
    OutboundMessageRecord,
    OutboundMessageRef,
    ReceiveAccount,
    ReceiveCursor,
    ReceiveRun,
    StoredAsset,
    StoredOutboundAttachment,
)


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
        self.outbound_dir = self.workspace_path / "outbound"
        self.outbound_raw_dir = self.outbound_dir / "raw"
        self.outbound_text_dir = self.outbound_dir / "text"
        self.outbound_html_dir = self.outbound_dir / "html"
        self.outbound_attachments_dir = self.outbound_dir / "attachments"

        self.workspace_path.mkdir(parents=True, exist_ok=True)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.html_dir.mkdir(parents=True, exist_ok=True)
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        self.exports_dir.mkdir(parents=True, exist_ok=True)
        self.outbound_raw_dir.mkdir(parents=True, exist_ok=True)
        self.outbound_text_dir.mkdir(parents=True, exist_ok=True)
        self.outbound_html_dir.mkdir(parents=True, exist_ok=True)
        self.outbound_attachments_dir.mkdir(parents=True, exist_ok=True)
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

                CREATE TABLE IF NOT EXISTS outbound_messages (
                    id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    provider_message_id TEXT,
                    idempotency_key TEXT,
                    status TEXT NOT NULL,
                    from_email TEXT NOT NULL,
                    from_name TEXT,
                    to_json TEXT NOT NULL,
                    cc_json TEXT NOT NULL,
                    bcc_json TEXT NOT NULL,
                    reply_to_json TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    text_path TEXT,
                    html_path TEXT,
                    raw_path TEXT NOT NULL,
                    source_document_id TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    sent_at TEXT,
                    error TEXT
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_outbound_idempotency_key
                ON outbound_messages(idempotency_key)
                WHERE idempotency_key IS NOT NULL;

                CREATE INDEX IF NOT EXISTS idx_outbound_created_at ON outbound_messages(created_at);
                CREATE INDEX IF NOT EXISTS idx_outbound_subject ON outbound_messages(subject);

                CREATE TABLE IF NOT EXISTS outbound_attachments (
                    id TEXT PRIMARY KEY,
                    outbound_id TEXT NOT NULL REFERENCES outbound_messages(id) ON DELETE CASCADE,
                    ordinal INTEGER NOT NULL,
                    filename TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    sha256 TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS receive_accounts (
                    id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    email TEXT,
                    label TEXT,
                    query TEXT,
                    config_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS receive_cursors (
                    account_id TEXT PRIMARY KEY REFERENCES receive_accounts(id) ON DELETE CASCADE,
                    provider TEXT NOT NULL,
                    cursor_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS receive_runs (
                    id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL REFERENCES receive_accounts(id) ON DELETE CASCADE,
                    provider TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    fetched_count INTEGER NOT NULL DEFAULT 0,
                    ingested_count INTEGER NOT NULL DEFAULT 0,
                    duplicate_count INTEGER NOT NULL DEFAULT 0,
                    error_count INTEGER NOT NULL DEFAULT 0,
                    error TEXT
                );

                CREATE TABLE IF NOT EXISTS receive_run_documents (
                    run_id TEXT NOT NULL REFERENCES receive_runs(id) ON DELETE CASCADE,
                    document_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    provider_message_id TEXT,
                    error TEXT,
                    PRIMARY KEY (run_id, document_id)
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
        raw_extension = ".eml" if document.source_kind in {"eml", "imap", "gmail"} else ".bin"
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

    def list_documents(self, query: str | None = None, limit: int | None = None, offset: int = 0) -> list[DocumentRef]:
        limit_clause = ""
        params: list[object] = []
        if limit is not None:
            limit_clause = "LIMIT ? OFFSET ?"
            params.extend([limit, offset])

        with self._connect() as connection:
            if query:
                pattern = f"%{query}%"
                query_params: list[object] = [pattern, pattern, pattern, pattern, pattern, *params]
                rows = connection.execute(
                    f"""
                    SELECT id, subject, source_kind, created_at
                    FROM documents
                    WHERE subject LIKE ? OR sender_name LIKE ? OR sender_email LIKE ? OR author LIKE ? OR body_text LIKE ?
                    ORDER BY COALESCE(received_at, created_at) DESC, created_at DESC, id DESC
                    {limit_clause}
                    """,
                    query_params,
                ).fetchall()
            else:
                rows = connection.execute(
                    f"""
                    SELECT id, subject, source_kind, created_at
                    FROM documents
                    ORDER BY COALESCE(received_at, created_at) DESC, created_at DESC, id DESC
                    {limit_clause}
                    """,
                    params,
                ).fetchall()

        return [
            DocumentRef(id=row["id"], subject=row["subject"], source_kind=row["source_kind"], created_at=row["created_at"])
            for row in rows
        ]

    def _outbound_record_from_rows(
        self,
        message_row: sqlite3.Row,
        attachment_rows: list[sqlite3.Row],
    ) -> OutboundMessageRecord:
        return OutboundMessageRecord(
            id=message_row["id"],
            status=message_row["status"],
            provider=message_row["provider"],
            provider_message_id=message_row["provider_message_id"],
            from_email=message_row["from_email"],
            from_name=message_row["from_name"],
            to=tuple(json.loads(message_row["to_json"])),
            cc=tuple(json.loads(message_row["cc_json"])),
            bcc=tuple(json.loads(message_row["bcc_json"])),
            reply_to=tuple(json.loads(message_row["reply_to_json"])),
            subject=message_row["subject"],
            text_path=message_row["text_path"],
            html_path=message_row["html_path"],
            raw_path=message_row["raw_path"],
            source_document_id=message_row["source_document_id"],
            metadata=json.loads(message_row["metadata_json"]),
            created_at=message_row["created_at"],
            sent_at=message_row["sent_at"],
            error=message_row["error"],
            attachments=tuple(
                StoredOutboundAttachment(
                    id=row["id"],
                    outbound_id=row["outbound_id"],
                    ordinal=row["ordinal"],
                    filename=row["filename"],
                    mime_type=row["mime_type"],
                    file_path=row["file_path"],
                    sha256=row["sha256"],
                )
                for row in attachment_rows
            ),
        )

    def _outbound_ref_from_row(self, row: sqlite3.Row) -> OutboundMessageRef:
        return OutboundMessageRef(
            id=row["id"],
            status=row["status"],
            provider=row["provider"],
            from_email=row["from_email"],
            to=tuple(json.loads(row["to_json"])),
            subject=row["subject"],
            created_at=row["created_at"],
            sent_at=row["sent_at"],
        )

    def save_outbound_message(
        self,
        message: OutboundMessage,
        *,
        provider: str,
        status: str,
        raw_bytes: bytes,
        metadata: dict[str, object] | None = None,
        provider_message_id: str | None = None,
        sent_at: str | None = None,
        error: str | None = None,
    ) -> OutboundMessageRecord:
        outbound_id = str(uuid.uuid4())
        created_at = _utc_now()

        raw_relative = Path("outbound") / "raw" / f"{outbound_id}.eml"
        raw_target = self.workspace_path / raw_relative
        raw_target.write_bytes(raw_bytes)

        text_relative: str | None = None
        if message.text is not None:
            text_relative_path = Path("outbound") / "text" / f"{outbound_id}.txt"
            (self.workspace_path / text_relative_path).write_text(message.text, encoding="utf-8")
            text_relative = text_relative_path.as_posix()

        html_relative: str | None = None
        if message.html is not None:
            html_relative_path = Path("outbound") / "html" / f"{outbound_id}.html"
            (self.workspace_path / html_relative_path).write_text(message.html, encoding="utf-8")
            html_relative = html_relative_path.as_posix()

        attachment_records: list[StoredOutboundAttachment] = []
        if message.attachments:
            attachment_root = self.outbound_attachments_dir / outbound_id
            attachment_root.mkdir(parents=True, exist_ok=True)

        for ordinal, attachment in enumerate(message.attachments, start=1):
            source_path = Path(attachment.path)
            filename = _safe_filename(attachment.filename or source_path.name)
            relative_path = Path("outbound") / "attachments" / outbound_id / f"{ordinal:03d}-{filename}"
            target_path = self.workspace_path / relative_path
            content = source_path.read_bytes()
            target_path.write_bytes(content)
            attachment_records.append(
                StoredOutboundAttachment(
                    id=str(uuid.uuid4()),
                    outbound_id=outbound_id,
                    ordinal=ordinal,
                    filename=filename,
                    mime_type=attachment.mime_type or mimetypes.guess_type(filename)[0] or "application/octet-stream",
                    file_path=relative_path.as_posix(),
                    sha256=hashlib.sha256(content).hexdigest(),
                )
            )

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO outbound_messages (
                    id, provider, provider_message_id, idempotency_key, status, from_email, from_name,
                    to_json, cc_json, bcc_json, reply_to_json, subject, text_path, html_path, raw_path,
                    source_document_id, metadata_json, created_at, sent_at, error
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    outbound_id,
                    provider,
                    provider_message_id,
                    message.idempotency_key,
                    status,
                    message.from_email,
                    message.from_name,
                    json.dumps(list(message.to)),
                    json.dumps(list(message.cc)),
                    json.dumps(list(message.bcc)),
                    json.dumps(list(message.reply_to)),
                    message.subject,
                    text_relative,
                    html_relative,
                    raw_relative.as_posix(),
                    message.source_document_id,
                    json.dumps(metadata or {}),
                    created_at,
                    sent_at,
                    error,
                ),
            )
            connection.executemany(
                """
                INSERT INTO outbound_attachments (id, outbound_id, ordinal, filename, mime_type, file_path, sha256)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        attachment.id,
                        attachment.outbound_id,
                        attachment.ordinal,
                        attachment.filename,
                        attachment.mime_type,
                        attachment.file_path,
                        attachment.sha256,
                    )
                    for attachment in attachment_records
                ],
            )

        return self.get_outbound(outbound_id)

    def get_outbound(self, outbound_id: str) -> OutboundMessageRecord:
        with self._connect() as connection:
            message_row = connection.execute("SELECT * FROM outbound_messages WHERE id = ?", (outbound_id,)).fetchone()
            if not message_row:
                raise KeyError(f"Outbound message not found: {outbound_id}")
            attachment_rows = connection.execute(
                """
                SELECT * FROM outbound_attachments
                WHERE outbound_id = ?
                ORDER BY ordinal ASC
                """,
                (outbound_id,),
            ).fetchall()

        return self._outbound_record_from_rows(message_row, list(attachment_rows))

    def find_outbound_by_idempotency_key(self, idempotency_key: str | None) -> OutboundMessageRecord | None:
        if not idempotency_key:
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id FROM outbound_messages WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        if not row:
            return None
        return self.get_outbound(row["id"])

    def list_outbound(self, query: str | None = None, limit: int | None = None, offset: int = 0) -> list[OutboundMessageRef]:
        limit_clause = ""
        params: list[object] = []
        if limit is not None:
            limit_clause = "LIMIT ? OFFSET ?"
            params.extend([limit, offset])

        with self._connect() as connection:
            if query:
                pattern = f"%{query}%"
                query_params: list[object] = [pattern, pattern, pattern, pattern, *params]
                rows = connection.execute(
                    f"""
                    SELECT id, status, provider, from_email, to_json, subject, created_at, sent_at
                    FROM outbound_messages
                    WHERE subject LIKE ? OR from_email LIKE ? OR to_json LIKE ? OR cc_json LIKE ?
                    ORDER BY created_at DESC, id DESC
                    {limit_clause}
                    """,
                    query_params,
                ).fetchall()
            else:
                rows = connection.execute(
                    f"""
                    SELECT id, status, provider, from_email, to_json, subject, created_at, sent_at
                    FROM outbound_messages
                    ORDER BY created_at DESC, id DESC
                    {limit_clause}
                    """,
                    params,
                ).fetchall()

        return [self._outbound_ref_from_row(row) for row in rows]

    def _receive_account_from_row(self, row: sqlite3.Row) -> ReceiveAccount:
        return ReceiveAccount(
            id=row["id"],
            provider=row["provider"],
            email=row["email"],
            label=row["label"],
            query=row["query"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _receive_run_from_row(self, row: sqlite3.Row) -> ReceiveRun:
        return ReceiveRun(
            id=row["id"],
            account_id=row["account_id"],
            provider=row["provider"],
            status=row["status"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            fetched_count=int(row["fetched_count"] or 0),
            ingested_count=int(row["ingested_count"] or 0),
            duplicate_count=int(row["duplicate_count"] or 0),
            error_count=int(row["error_count"] or 0),
            error=row["error"],
        )

    def save_receive_account(
        self,
        *,
        account_id: str,
        provider: str,
        email: str | None,
        label: str | None,
        query: str | None,
        config: dict[str, object],
    ) -> ReceiveAccount:
        now = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO receive_accounts (id, provider, email, label, query, config_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id)
                DO UPDATE SET
                    provider = excluded.provider,
                    email = excluded.email,
                    label = excluded.label,
                    query = excluded.query,
                    config_json = excluded.config_json,
                    updated_at = excluded.updated_at
                """,
                (account_id, provider, email, label, query, json.dumps(config), now, now),
            )
        return self.get_receive_account(account_id)

    def get_receive_account(self, account_id: str) -> ReceiveAccount:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, provider, email, label, query, created_at, updated_at
                FROM receive_accounts
                WHERE id = ?
                """,
                (account_id,),
            ).fetchone()
        if not row:
            raise KeyError(f"Receive account not found: {account_id}")
        return self._receive_account_from_row(row)

    def list_receive_accounts(self) -> list[ReceiveAccount]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, provider, email, label, query, created_at, updated_at
                FROM receive_accounts
                ORDER BY updated_at DESC, created_at DESC
                """
            ).fetchall()
        return [self._receive_account_from_row(row) for row in rows]

    def get_receive_cursor(self, account_id: str) -> ReceiveCursor | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT account_id, provider, cursor_json, updated_at
                FROM receive_cursors
                WHERE account_id = ?
                """,
                (account_id,),
            ).fetchone()
        if not row:
            return None
        return ReceiveCursor(
            account_id=row["account_id"],
            provider=row["provider"],
            cursor_json=json.loads(row["cursor_json"]),
            updated_at=row["updated_at"],
        )

    def save_receive_cursor(self, account_id: str, provider: str, cursor: dict[str, object]) -> ReceiveCursor:
        updated_at = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO receive_cursors (account_id, provider, cursor_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(account_id)
                DO UPDATE SET
                    provider = excluded.provider,
                    cursor_json = excluded.cursor_json,
                    updated_at = excluded.updated_at
                """,
                (account_id, provider, json.dumps(cursor), updated_at),
            )
        saved = self.get_receive_cursor(account_id)
        if saved is None:
            raise KeyError(f"Receive cursor not found after save: {account_id}")
        return saved

    def start_receive_run(self, account_id: str, provider: str) -> ReceiveRun:
        run_id = str(uuid.uuid4())
        started_at = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO receive_runs (
                    id, account_id, provider, status, started_at, fetched_count,
                    ingested_count, duplicate_count, error_count
                )
                VALUES (?, ?, ?, ?, ?, 0, 0, 0, 0)
                """,
                (run_id, account_id, provider, "running", started_at),
            )
        return self.get_receive_run(run_id)

    def get_receive_run(self, run_id: str) -> ReceiveRun:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, account_id, provider, status, started_at, finished_at,
                       fetched_count, ingested_count, duplicate_count, error_count, error
                FROM receive_runs
                WHERE id = ?
                """,
                (run_id,),
            ).fetchone()
        if not row:
            raise KeyError(f"Receive run not found: {run_id}")
        return self._receive_run_from_row(row)

    def finish_receive_run(
        self,
        run_id: str,
        *,
        status: str,
        fetched_count: int,
        ingested_count: int,
        duplicate_count: int,
        error_count: int,
        error: str | None = None,
    ) -> ReceiveRun:
        finished_at = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE receive_runs
                SET status = ?,
                    finished_at = ?,
                    fetched_count = ?,
                    ingested_count = ?,
                    duplicate_count = ?,
                    error_count = ?,
                    error = ?
                WHERE id = ?
                """,
                (status, finished_at, fetched_count, ingested_count, duplicate_count, error_count, error, run_id),
            )
        return self.get_receive_run(run_id)

    def add_receive_run_document(
        self,
        run_id: str,
        document_id: str,
        *,
        status: str,
        provider_message_id: str | None = None,
        error: str | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO receive_run_documents (run_id, document_id, status, provider_message_id, error)
                VALUES (?, ?, ?, ?, ?)
                """,
                (run_id, document_id, status, provider_message_id, error),
            )

    def list_receive_runs(self, account_id: str | None = None, limit: int = 20) -> list[ReceiveRun]:
        normalized_limit = max(1, min(int(limit), 100))
        with self._connect() as connection:
            if account_id:
                rows = connection.execute(
                    """
                    SELECT id, account_id, provider, status, started_at, finished_at,
                           fetched_count, ingested_count, duplicate_count, error_count, error
                    FROM receive_runs
                    WHERE account_id = ?
                    ORDER BY started_at DESC
                    LIMIT ?
                    """,
                    (account_id, normalized_limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT id, account_id, provider, status, started_at, finished_at,
                           fetched_count, ingested_count, duplicate_count, error_count, error
                    FROM receive_runs
                    ORDER BY started_at DESC
                    LIMIT ?
                    """,
                    (normalized_limit,),
                ).fetchall()
        return [self._receive_run_from_row(row) for row in rows]

    def update_outbound_message(
        self,
        outbound_id: str,
        *,
        status: str,
        provider_message_id: str | None = None,
        metadata: dict[str, object] | None = None,
        sent_at: str | None = None,
        error: str | None = None,
    ) -> OutboundMessageRecord:
        current = self.get_outbound(outbound_id)
        merged_metadata = dict(current.metadata)
        if metadata:
            merged_metadata.update(metadata)

        with self._connect() as connection:
            connection.execute(
                """
                UPDATE outbound_messages
                SET status = ?,
                    provider_message_id = ?,
                    metadata_json = ?,
                    sent_at = ?,
                    error = ?
                WHERE id = ?
                """,
                (
                    status,
                    provider_message_id if provider_message_id is not None else current.provider_message_id,
                    json.dumps(merged_metadata),
                    sent_at if sent_at is not None else current.sent_at,
                    error,
                    outbound_id,
                ),
            )

        return self.get_outbound(outbound_id)

    def resolve_path(self, relative_path: str | None) -> Path | None:
        if not relative_path:
            return None
        return self.workspace_path / relative_path

    def save_export(self, document_id: str, format_name: str, content: str) -> Path:
        target = self.exports_dir / f"{document_id}.{format_name}"
        target.write_text(content, encoding="utf-8")
        return target

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
