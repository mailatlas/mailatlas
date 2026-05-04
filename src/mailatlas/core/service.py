from __future__ import annotations

import hashlib
import mailbox
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from mailatlas.adapters.cloudflare import send_cloudflare_message
from mailatlas.adapters.gmail import (
    GmailReceiveError,
    build_gmail_cursor,
    fetch_gmail_message,
    get_gmail_profile,
    gmail_source_uri,
    list_gmail_message_candidates,
    send_gmail_message,
)
from mailatlas.adapters.imap import ImapReceiveError, open_imap_session
from mailatlas.adapters.smtp import send_smtp_message

from .exports import export_document as export_document_content
from .gmail_auth import GMAIL_READONLY_SCOPE, create_gmail_token_store, load_valid_gmail_access_token
from .models import (
    DocumentRef,
    NormalizedDocument,
    OutboundMessage,
    OutboundMessageRecord,
    OutboundMessageRef,
    ParserConfig,
    ReceiveAccount,
    ReceiveConfig,
    ReceiveResult,
    ReceiveRun,
    SendConfig,
    SendResult,
    _ImapFolderReceiveResult,
    _ImapReceiveConfig,
    _ImapReceiveResult,
)
from .outbound import build_outbound_mime, normalize_outbound_message, outbound_metadata, send_result_from_record
from .parsing import parse_email_bytes, parse_eml as parse_eml_file
from .storage import DocumentSaveResult, WorkspaceStore


def _imap_source_path(host: str, port: int, folder: str, uid: int) -> str:
    encoded_folder = quote(folder, safe="")
    return f"imap://{host}:{port}/{encoded_folder}#uid={uid}"


def _receive_account_id(config: ReceiveConfig, email: str | None = None) -> str:
    if config.account_id:
        return config.account_id
    if config.provider == "imap":
        identity = config.imap_username or "unknown"
        host = config.imap_host or "unknown"
        folders = ",".join(config.imap_folders or ("INBOX",))
        return f"imap:{identity}:{host}:{folders}"

    identity = email or config.gmail_user_id or "me"
    label = config.gmail_label or "ALL"
    account_id = f"{config.provider}:{identity}:{label}"
    if config.gmail_query:
        query_hash = hashlib.sha256(config.gmail_query.encode("utf-8")).hexdigest()[:12]
        account_id = f"{account_id}:q-{query_hash}"
    return account_id


def _receive_account_email(config: ReceiveConfig, email: str | None = None) -> str | None:
    if config.provider == "imap":
        return config.imap_username
    return email


def _receive_account_label(config: ReceiveConfig) -> str | None:
    if config.provider == "imap":
        return ",".join(config.imap_folders or ("INBOX",))
    return config.gmail_label


def _receive_account_query(config: ReceiveConfig) -> str | None:
    if config.provider == "imap":
        return None
    return config.gmail_query


def _imap_config_from_receive_config(config: ReceiveConfig) -> _ImapReceiveConfig:
    return _ImapReceiveConfig(
        host=config.imap_host or "",
        port=config.imap_port,
        username=config.imap_username or "",
        auth=config.imap_auth or "password",
        password=config.imap_password,
        access_token=config.imap_access_token,
        folders=config.imap_folders,
        parser_config=config.parser_config,
    )


def _imap_receive_cursor(receive_result: _ImapReceiveResult) -> dict[str, object]:
    return {
        "host": receive_result.host,
        "port": receive_result.port,
        "username": receive_result.username,
        "folders": [
            {
                "folder": folder.folder,
                "status": folder.status,
                "uidvalidity": folder.uidvalidity,
                "last_uid": folder.last_uid,
                "error": folder.error,
            }
            for folder in receive_result.folders
        ],
    }


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

    def _receive_imap_folders(self, config: _ImapReceiveConfig) -> _ImapReceiveResult:
        results: list[_ImapFolderReceiveResult] = []

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
                        _ImapFolderReceiveResult(
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
                        _ImapFolderReceiveResult(
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

        return _ImapReceiveResult(
            host=config.host,
            port=config.port,
            username=config.username,
            auth=config.auth,
            folders=results,
        )

    def _receive_not_configured_result(self, config: ReceiveConfig, error: str) -> ReceiveResult:
        account_id = _receive_account_id(config)
        self.store.save_receive_account(
            account_id=account_id,
            provider=config.provider,
            email=_receive_account_email(config),
            label=_receive_account_label(config),
            query=_receive_account_query(config),
            config=config.to_safe_dict(),
        )
        run = self.store.start_receive_run(account_id, config.provider)
        self.store.finish_receive_run(
            run.id,
            status="not_configured",
            fetched_count=0,
            ingested_count=0,
            duplicate_count=0,
            error_count=1,
            error=error,
        )
        return ReceiveResult(
            status="not_configured",
            provider=config.provider,
            account_id=account_id,
            fetched_count=0,
            ingested_count=0,
            duplicate_count=0,
            error_count=1,
            document_ids=(),
            cursor={},
            run_id=run.id,
            error=error,
        )

    def _receive_imap(self, config: ReceiveConfig) -> ReceiveResult:
        account_id = _receive_account_id(config)
        self.store.save_receive_account(
            account_id=account_id,
            provider=config.provider,
            email=_receive_account_email(config),
            label=_receive_account_label(config),
            query=_receive_account_query(config),
            config=config.to_safe_dict(),
        )
        run = self.store.start_receive_run(account_id, config.provider)

        try:
            imap_result = self._receive_imap_folders(_imap_config_from_receive_config(config))
        except ValueError as error:
            self.store.finish_receive_run(
                run.id,
                status="not_configured",
                fetched_count=0,
                ingested_count=0,
                duplicate_count=0,
                error_count=1,
                error=str(error),
            )
            return ReceiveResult(
                status="not_configured",
                provider=config.provider,
                account_id=account_id,
                fetched_count=0,
                ingested_count=0,
                duplicate_count=0,
                error_count=1,
                document_ids=(),
                cursor={},
                run_id=run.id,
                error=str(error),
            )
        except ImapReceiveError as error:
            self.store.finish_receive_run(
                run.id,
                status="error",
                fetched_count=0,
                ingested_count=0,
                duplicate_count=0,
                error_count=1,
                error=str(error),
            )
            return ReceiveResult(
                status="error",
                provider=config.provider,
                account_id=account_id,
                fetched_count=0,
                ingested_count=0,
                duplicate_count=0,
                error_count=1,
                document_ids=(),
                cursor={},
                run_id=run.id,
                error=str(error),
            )

        document_ids: list[str] = []
        for folder in imap_result.folders:
            for reference in folder.document_refs:
                document_ids.append(reference.id)
                self.store.add_receive_run_document(
                    run.id,
                    reference.id,
                    status=folder.status,
                    provider_message_id=f"{folder.folder}:{reference.id}",
                    error=folder.error,
                )

        fetched_count = sum(folder.fetched_count for folder in imap_result.folders)
        ingested_count = sum(folder.ingested_count for folder in imap_result.folders)
        duplicate_count = sum(folder.duplicate_count for folder in imap_result.folders)
        error_count = sum(1 for folder in imap_result.folders if folder.status == "error")
        last_error = next((folder.error for folder in imap_result.folders if folder.error), None)
        if error_count:
            status = "partial" if ingested_count or duplicate_count else "error"
        elif fetched_count and not ingested_count:
            status = "duplicate"
        else:
            status = "ok"

        cursor = _imap_receive_cursor(imap_result)
        self.store.save_receive_cursor(account_id, config.provider, cursor)
        self.store.finish_receive_run(
            run.id,
            status=status,
            fetched_count=fetched_count,
            ingested_count=ingested_count,
            duplicate_count=duplicate_count,
            error_count=error_count,
            error=last_error,
        )
        return ReceiveResult(
            status=status,
            provider=config.provider,
            account_id=account_id,
            fetched_count=fetched_count,
            ingested_count=ingested_count,
            duplicate_count=duplicate_count,
            error_count=error_count,
            document_ids=tuple(document_ids),
            cursor=cursor,
            run_id=run.id,
            error=last_error,
            details=imap_result.to_dict(),
        )

    def _receive_provider_error_result(
        self,
        config: ReceiveConfig,
        *,
        account_id: str,
        run_id: str,
        status: str,
        error: str,
        cursor: dict[str, object] | None = None,
    ) -> ReceiveResult:
        self.store.finish_receive_run(
            run_id,
            status=status,
            fetched_count=0,
            ingested_count=0,
            duplicate_count=0,
            error_count=1,
            error=error,
        )
        return ReceiveResult(
            status=status,
            provider=config.provider,
            account_id=account_id,
            fetched_count=0,
            ingested_count=0,
            duplicate_count=0,
            error_count=1,
            document_ids=(),
            cursor=cursor or {},
            run_id=run_id,
            error=error,
        )

    def receive(self, config: ReceiveConfig) -> ReceiveResult:
        if config.provider == "imap":
            return self._receive_imap(config)

        try:
            access_token = config.gmail_access_token or load_valid_gmail_access_token(
                store=create_gmail_token_store(config.token_file, token_store=config.token_store),
                required_scopes=(GMAIL_READONLY_SCOPE,),
            )
        except (OSError, RuntimeError, ValueError) as error:
            return self._receive_not_configured_result(config, str(error))

        profile_email: str | None = None
        profile_history_id: str | None = None
        try:
            profile = get_gmail_profile(config, access_token)
            profile_email = profile.get("email")
            profile_history_id = profile.get("history_id")
        except GmailReceiveError as error:
            account_id = _receive_account_id(config)
            self.store.save_receive_account(
                account_id=account_id,
                provider=config.provider,
                email=_receive_account_email(config),
                label=_receive_account_label(config),
                query=_receive_account_query(config),
                config=config.to_safe_dict(),
            )
            run = self.store.start_receive_run(account_id, config.provider)
            return self._receive_provider_error_result(
                config,
                account_id=account_id,
                run_id=run.id,
                status=error.status,
                error=str(error),
            )

        account_id = _receive_account_id(config, profile_email)
        self.store.save_receive_account(
            account_id=account_id,
            provider=config.provider,
            email=_receive_account_email(config, profile_email),
            label=_receive_account_label(config),
            query=_receive_account_query(config),
            config=config.to_safe_dict(),
        )
        run = self.store.start_receive_run(account_id, config.provider)
        existing_cursor = self.store.get_receive_cursor(account_id)
        cursor_json = dict(existing_cursor.cursor_json) if existing_cursor else {}

        try:
            candidates = list_gmail_message_candidates(config, access_token, cursor=cursor_json)
        except GmailReceiveError as error:
            return self._receive_provider_error_result(
                config,
                account_id=account_id,
                run_id=run.id,
                status=error.status,
                error=str(error),
                cursor=cursor_json,
            )

        fetched_messages = []
        document_ids: list[str] = []
        ingested_count = 0
        duplicate_count = 0
        error_count = 0
        last_error: str | None = None

        for candidate in candidates:
            try:
                message = fetch_gmail_message(config, access_token, candidate.id)
                fetched_messages.append(message)
                parsed = parse_email_bytes(message.raw_bytes, source_kind="gmail", parser_config=config.parser_config)
                source_uri = gmail_source_uri(config, message.id)
                parsed.metadata = {
                    **parsed.metadata,
                    "source_kind": "gmail",
                    "source_uri": source_uri,
                    "provider": "gmail",
                    "gmail": {
                        "message_id": message.id,
                        "thread_id": message.thread_id,
                        "history_id": message.history_id,
                        "internal_date": message.internal_date,
                        "label_ids": list(message.label_ids),
                        "account_id": account_id,
                    },
                    "source": {
                        "kind": "gmail",
                        "uri": source_uri,
                        "provider_message_id": message.id,
                    },
                }
                saved = self.store.save_document_result(parsed, source_uri)
                document_ids.append(saved.ref.id)
                if saved.status == "duplicate":
                    duplicate_count += 1
                else:
                    ingested_count += 1
                self.store.add_receive_run_document(
                    run.id,
                    saved.ref.id,
                    status=saved.status,
                    provider_message_id=message.id,
                )
            except Exception as error:
                error_count += 1
                last_error = str(error)

        fetched_count = len(candidates)
        if error_count:
            status = "partial" if ingested_count or duplicate_count else "error"
        elif fetched_count and not ingested_count:
            status = "duplicate"
        else:
            status = "ok"

        new_cursor = cursor_json
        if error_count == 0:
            new_cursor = build_gmail_cursor(
                fetched_messages,
                profile_history_id=profile_history_id,
                existing_cursor=cursor_json,
            )
            self.store.save_receive_cursor(account_id, config.provider, new_cursor)

        self.store.finish_receive_run(
            run.id,
            status=status,
            fetched_count=fetched_count,
            ingested_count=ingested_count,
            duplicate_count=duplicate_count,
            error_count=error_count,
            error=last_error,
        )
        return ReceiveResult(
            status=status,
            provider=config.provider,
            account_id=account_id,
            fetched_count=fetched_count,
            ingested_count=ingested_count,
            duplicate_count=duplicate_count,
            error_count=error_count,
            document_ids=tuple(document_ids),
            cursor=new_cursor,
            run_id=run.id,
            error=last_error,
        )

    def receive_status(self, account_id: str | None = None) -> dict[str, object]:
        accounts = [
            account
            for account in self.store.list_receive_accounts()
            if account_id is None or account.id == account_id
        ]
        cursors = []
        for account in accounts:
            cursor = self.store.get_receive_cursor(account.id)
            if cursor:
                cursors.append(cursor.to_dict())
        runs = self.store.list_receive_runs(account_id=account_id, limit=20)
        last_error = next((run.error for run in runs if run.error), None)
        return {
            "status": "ok",
            "accounts": [account.to_dict() for account in accounts],
            "cursors": cursors,
            "recent_runs": [run.to_dict() for run in runs],
            "last_error": last_error,
        }

    def list_receive_accounts(self) -> list[ReceiveAccount]:
        return self.store.list_receive_accounts()

    def list_receive_runs(self, account_id: str | None = None, limit: int = 20) -> list[ReceiveRun]:
        return self.store.list_receive_runs(account_id=account_id, limit=limit)

    def get_document(self, document_id: str):
        return self.store.get_document(document_id)

    def list_documents(self, query: str | None = None, limit: int | None = None, offset: int = 0) -> list[DocumentRef]:
        return self.store.list_documents(query=query, limit=limit, offset=offset)

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

    def list_outbound(self, query: str | None = None, limit: int | None = None, offset: int = 0) -> list[OutboundMessageRef]:
        return self.store.list_outbound(query=query, limit=limit, offset=offset)

    def get_outbound(self, outbound_id: str) -> OutboundMessageRecord:
        return self.store.get_outbound(outbound_id)
