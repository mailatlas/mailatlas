from __future__ import annotations

import mailbox
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from mailatlas.adapters.cloudflare import send_cloudflare_message
from mailatlas.adapters.gmail import send_gmail_message
from mailatlas.adapters.imap import open_imap_session
from mailatlas.adapters.smtp import send_smtp_message

from .exports import export_document as export_document_content
from .models import (
    DocumentRef,
    ImapFolderSyncResult,
    ImapSyncConfig,
    ImapSyncResult,
    NormalizedDocument,
    OutboundMessage,
    OutboundMessageRecord,
    OutboundMessageRef,
    ParserConfig,
    SendConfig,
    SendResult,
)
from .outbound import build_outbound_mime, normalize_outbound_message, outbound_metadata, send_result_from_record
from .parsing import parse_email_bytes, parse_eml as parse_eml_file
from .storage import DocumentSaveResult, WorkspaceStore


def _imap_source_path(host: str, port: int, folder: str, uid: int) -> str:
    encoded_folder = quote(folder, safe="")
    return f"imap://{host}:{port}/{encoded_folder}#uid={uid}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MailAtlas:
    def __init__(
        self,
        db_path: str | Path = ".mailatlas/store.db",
        workspace_path: str | Path = ".mailatlas",
        parser_config: ParserConfig | None = None,
    ):
        self.db_path = Path(db_path).expanduser().resolve()
        self.workspace_path = Path(workspace_path).expanduser().resolve()
        self.parser_config = parser_config or ParserConfig()
        self.store = WorkspaceStore(self.db_path, self.workspace_path)

    def parse_eml(
        self,
        path: str | Path,
        parser_config: ParserConfig | None = None,
    ) -> NormalizedDocument:
        return parse_eml_file(path, parser_config=parser_config or self.parser_config)

    def ingest_eml_results(
        self,
        paths: list[str | Path],
        parser_config: ParserConfig | None = None,
    ) -> list[DocumentSaveResult]:
        effective_parser_config = parser_config or self.parser_config
        results: list[DocumentSaveResult] = []

        for path in paths:
            resolved = Path(path).expanduser().resolve()
            parsed = parse_eml_file(resolved, parser_config=effective_parser_config)
            results.append(self.store.save_document_result(parsed, resolved.as_posix()))

        return results

    def ingest_eml(
        self,
        paths: list[str | Path],
        parser_config: ParserConfig | None = None,
    ) -> list[DocumentRef]:
        return [result.ref for result in self.ingest_eml_results(paths, parser_config=parser_config)]

    def ingest_mbox_results(
        self,
        path: str | Path,
        parser_config: ParserConfig | None = None,
    ) -> list[DocumentSaveResult]:
        effective_parser_config = parser_config or self.parser_config
        resolved = Path(path).expanduser().resolve()
        results: list[DocumentSaveResult] = []
        archive = mailbox.mbox(resolved)
        try:
            for index, message in enumerate(archive):
                raw_bytes = message.as_bytes()
                parsed = parse_email_bytes(raw_bytes, source_kind="mbox", parser_config=effective_parser_config)
                results.append(self.store.save_document_result(parsed, f"{resolved.as_posix()}#{index}"))
        finally:
            archive.close()

        return results

    def ingest_mbox(
        self,
        path: str | Path,
        parser_config: ParserConfig | None = None,
    ) -> list[DocumentRef]:
        return [result.ref for result in self.ingest_mbox_results(path, parser_config=parser_config)]

    def sync_imap(self, config: ImapSyncConfig) -> ImapSyncResult:
        results: list[ImapFolderSyncResult] = []

        with open_imap_session(config) as session:
            for folder in config.folders:
                existing_state = self.store.get_imap_sync_state(config.host, config.port, config.username, folder)
                previous_uidvalidity = existing_state.uidvalidity if existing_state else None
                previous_last_uid = existing_state.last_uid if existing_state else 0

                try:
                    uidvalidity = session.select_folder(folder)
                    start_uid = 0 if previous_uidvalidity and previous_uidvalidity != uidvalidity else previous_last_uid
                    available_uids = session.list_uids()
                    target_uids = [uid for uid in available_uids if uid > start_uid]

                    refs: list[DocumentRef] = []
                    ingested_count = 0
                    duplicate_count = 0
                    last_uid = start_uid

                    for uid in target_uids:
                        raw_bytes = session.fetch_message(uid)
                        parsed = parse_email_bytes(raw_bytes, source_kind="imap", parser_config=config.parser_config)
                        parsed.metadata = {
                            **parsed.metadata,
                            "source": {
                                "kind": "imap",
                                "host": config.host,
                                "folder": folder,
                                "uid": uid,
                                "uidvalidity": uidvalidity,
                            },
                        }
                        saved = self.store.save_document_result(
                            parsed,
                            _imap_source_path(config.host, config.port, folder, uid),
                        )
                        refs.append(saved.ref)
                        if saved.status == "duplicate":
                            duplicate_count += 1
                        else:
                            ingested_count += 1
                        last_uid = uid

                    state = self.store.save_imap_sync_state(
                        config.host,
                        config.port,
                        config.username,
                        folder,
                        uidvalidity=uidvalidity,
                        last_uid=last_uid,
                        status="ok",
                    )
                    results.append(
                        ImapFolderSyncResult(
                            folder=folder,
                            status="ok",
                            uidvalidity=state.uidvalidity,
                            last_uid=state.last_uid,
                            fetched_count=len(target_uids),
                            ingested_count=ingested_count,
                            duplicate_count=duplicate_count,
                            document_refs=refs,
                        )
                    )
                except Exception as error:
                    state = self.store.save_imap_sync_state(
                        config.host,
                        config.port,
                        config.username,
                        folder,
                        uidvalidity=previous_uidvalidity,
                        last_uid=previous_last_uid,
                        status="error",
                        error=str(error),
                    )
                    results.append(
                        ImapFolderSyncResult(
                            folder=folder,
                            status="error",
                            uidvalidity=state.uidvalidity,
                            last_uid=state.last_uid,
                            fetched_count=0,
                            ingested_count=0,
                            duplicate_count=0,
                            error=str(error),
                        )
                    )

        return ImapSyncResult(
            host=config.host,
            port=config.port,
            username=config.username,
            auth=config.auth,
            folders=results,
        )

    def get_document(self, document_id: str):
        return self.store.get_document(document_id)

    def list_documents(self, query: str | None = None) -> list[DocumentRef]:
        return self.store.list_documents(query=query)

    def export_document(
        self,
        document_id: str,
        format: str = "json",
        out_path: str | Path | None = None,
    ) -> str:
        return export_document_content(
            document_id,
            format=format,
            db_path=self.db_path,
            workspace_path=self.workspace_path,
            out_path=out_path,
        )

    def _idempotent_outbound_result(self, message: OutboundMessage) -> SendResult | None:
        idempotency_key = message.idempotency_key.strip() if message.idempotency_key else None
        existing = self.store.find_outbound_by_idempotency_key(idempotency_key)
        return send_result_from_record(existing) if existing else None

    def _render_outbound(self, message: OutboundMessage):
        normalized = normalize_outbound_message(message)
        mime_message = build_outbound_mime(normalized)
        raw_bytes = mime_message.as_bytes()
        metadata = outbound_metadata(normalized, mime_message)
        return normalized, mime_message, raw_bytes, metadata

    def draft_email(self, message: OutboundMessage) -> SendResult:
        existing = self._idempotent_outbound_result(message)
        if existing:
            return existing

        normalized, _, raw_bytes, metadata = self._render_outbound(message)
        record = self.store.save_outbound_message(
            normalized,
            provider="local",
            status="draft",
            raw_bytes=raw_bytes,
            metadata=metadata,
        )
        return send_result_from_record(record)

    def send_email(self, message: OutboundMessage, config: SendConfig) -> SendResult:
        existing = self._idempotent_outbound_result(message)
        if existing:
            return existing

        normalized, mime_message, raw_bytes, metadata = self._render_outbound(message)
        if config.dry_run:
            record = self.store.save_outbound_message(
                normalized,
                provider=config.provider,
                status="dry_run",
                raw_bytes=raw_bytes,
                metadata=metadata,
            )
            return send_result_from_record(record)

        record = self.store.save_outbound_message(
            normalized,
            provider=config.provider,
            status="sending",
            raw_bytes=raw_bytes,
            metadata=metadata,
        )

        if config.provider == "smtp":
            provider_result = send_smtp_message(normalized, mime_message, config)
        elif config.provider == "cloudflare":
            provider_result = send_cloudflare_message(normalized, config)
        elif config.provider == "gmail":
            provider_result = send_gmail_message(normalized, mime_message, config)
        else:
            provider_result = None

        if provider_result is None:
            updated = self.store.update_outbound_message(
                record.id,
                status="error",
                error=f"Unsupported send provider: {config.provider}",
            )
            return send_result_from_record(updated)

        updated = self.store.update_outbound_message(
            record.id,
            status=provider_result.status,
            provider_message_id=provider_result.provider_message_id,
            metadata=provider_result.metadata,
            sent_at=_utc_now() if provider_result.status in {"sent", "queued"} else None,
            error=provider_result.error,
        )
        return send_result_from_record(updated)

    def list_outbound(self, query: str | None = None) -> list[OutboundMessageRef]:
        return self.store.list_outbound(query=query)

    def get_outbound(self, outbound_id: str) -> OutboundMessageRecord:
        return self.store.get_outbound(outbound_id)
