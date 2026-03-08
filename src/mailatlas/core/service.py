from __future__ import annotations

import mailbox
from pathlib import Path

from .exports import export_document as export_document_content
from .models import DocumentRef, NormalizedDocument, ParserConfig
from .parsing import parse_email_bytes, parse_eml as parse_eml_file
from .storage import WorkspaceStore


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
