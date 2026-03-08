from __future__ import annotations

import mailbox
from pathlib import Path
from urllib.parse import quote

from mailatlas.adapters.imap import open_imap_session

from .exports import export_document as export_document_content
from .models import DocumentRef, ImapFolderSyncResult, ImapSyncConfig, ImapSyncResult, NormalizedDocument, ParserConfig
from .parsing import parse_email_bytes, parse_eml as parse_eml_file
from .storage import WorkspaceStore


def _imap_source_path(host: str, port: int, folder: str, uid: int) -> str:
    encoded_folder = quote(folder, safe="")
    return f"imap://{host}:{port}/{encoded_folder}#uid={uid}"


class MailAtlas:
    def __init__(
        self,
        db_path: str | Path = ".mailatlas/store.db",
        workspace_path: str | Path = ".mailatlas/workspace",
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

    def ingest_eml(
        self,
        paths: list[str | Path],
        parser_config: ParserConfig | None = None,
    ) -> list[DocumentRef]:
        effective_parser_config = parser_config or self.parser_config
        results: list[DocumentRef] = []

        for path in paths:
            resolved = Path(path).expanduser().resolve()
            parsed = parse_eml_file(resolved, parser_config=effective_parser_config)
            results.append(self.store.save_document(parsed, resolved.as_posix()))

        return results

    def ingest_mbox(
        self,
        path: str | Path,
        parser_config: ParserConfig | None = None,
    ) -> list[DocumentRef]:
        effective_parser_config = parser_config or self.parser_config
        resolved = Path(path).expanduser().resolve()
        results: list[DocumentRef] = []
        archive = mailbox.mbox(resolved)
        try:
            for index, message in enumerate(archive):
                raw_bytes = message.as_bytes()
                parsed = parse_email_bytes(raw_bytes, source_kind="mbox", parser_config=effective_parser_config)
                results.append(self.store.save_document(parsed, f"{resolved.as_posix()}#{index}"))
        finally:
            archive.close()

        return results

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
