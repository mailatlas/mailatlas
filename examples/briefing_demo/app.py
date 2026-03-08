from __future__ import annotations

from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from mailatlas.ai import generate_brief
from mailatlas.core import MailAtlas, ParserConfig

DEFAULT_DB = ".mailatlas/store.db"
DEFAULT_WORKSPACE = ".mailatlas/workspace"

load_dotenv()

api = FastAPI(title="MailAtlas Demo API")


class WorkspaceRequest(BaseModel):
    db_path: str = DEFAULT_DB
    workspace_path: str = DEFAULT_WORKSPACE


class ParserConfigPayload(BaseModel):
    strip_forwarded_headers: bool = True
    strip_boilerplate: bool = True
    strip_link_only_lines: bool = True
    stop_at_footer: bool = True
    strip_invisible_chars: bool = True
    normalize_whitespace: bool = True

    def to_parser_config(self) -> ParserConfig:
        return ParserConfig(**self.model_dump())


class IngestEmlRequest(WorkspaceRequest):
    paths: list[str]
    parser_config: ParserConfigPayload | None = None


class IngestMboxRequest(WorkspaceRequest):
    path: str
    parser_config: ParserConfigPayload | None = None


class BriefGenerateRequest(WorkspaceRequest):
    document_ids: list[str] | None = None
    query: str | None = None
    output_path: str | None = None
    model_config: dict[str, Any] | None = None


def _atlas(
    db_path: str = DEFAULT_DB,
    workspace_path: str = DEFAULT_WORKSPACE,
    parser_config: ParserConfig | None = None,
) -> MailAtlas:
    return MailAtlas(db_path=db_path, workspace_path=workspace_path, parser_config=parser_config)


@api.get("/documents")
def documents(query: str | None = None, db_path: str = DEFAULT_DB, workspace_path: str = DEFAULT_WORKSPACE):
    refs = _atlas(db_path=db_path, workspace_path=workspace_path).list_documents(query=query)
    return [reference.to_dict() for reference in refs]


@api.get("/documents/{document_id}")
def document(document_id: str, db_path: str = DEFAULT_DB, workspace_path: str = DEFAULT_WORKSPACE):
    try:
        return _atlas(db_path=db_path, workspace_path=workspace_path).get_document(document_id).to_dict()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@api.get("/documents/{document_id}/export")
def export(document_id: str, format: str = "json", db_path: str = DEFAULT_DB, workspace_path: str = DEFAULT_WORKSPACE):
    try:
        return {"content": _atlas(db_path=db_path, workspace_path=workspace_path).export_document(document_id, format=format)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@api.post("/ingest/eml")
def ingest_paths(payload: IngestEmlRequest):
    refs = _atlas(
        db_path=payload.db_path,
        workspace_path=payload.workspace_path,
        parser_config=payload.parser_config.to_parser_config() if payload.parser_config else None,
    ).ingest_eml(payload.paths)
    return [reference.to_dict() for reference in refs]


@api.post("/ingest/mbox")
def ingest_archive(payload: IngestMboxRequest):
    refs = _atlas(
        db_path=payload.db_path,
        workspace_path=payload.workspace_path,
        parser_config=payload.parser_config.to_parser_config() if payload.parser_config else None,
    ).ingest_mbox(payload.path)
    return [reference.to_dict() for reference in refs]


@api.post("/brief/generate")
def brief(payload: BriefGenerateRequest):
    try:
        path = generate_brief(
            document_ids=payload.document_ids,
            query=payload.query,
            output_path=payload.output_path,
            model_config=payload.model_config,
            db_path=payload.db_path,
            workspace_path=payload.workspace_path,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"output_path": path}
