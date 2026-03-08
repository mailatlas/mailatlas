from __future__ import annotations

import argparse
import json
from pathlib import Path

from mailatlas.ai import generate_brief
from mailatlas.core import MailAtlas, ParserConfig


def _workspace_defaults() -> tuple[str, str]:
    return ".mailatlas/store.db", ".mailatlas/workspace"


def _add_workspace_arguments(parser: argparse.ArgumentParser) -> None:
    db_default, workspace_default = _workspace_defaults()
    parser.add_argument("--db", default=db_default, help="SQLite database path.")
    parser.add_argument("--workspace", default=workspace_default, help="Workspace directory path.")


def _add_parser_config_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--strip-forwarded-headers",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Remove forwarded wrapper header lines from body_text.",
    )
    parser.add_argument(
        "--strip-boilerplate",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Remove common newsletter CTA and reaction boilerplate lines.",
    )
    parser.add_argument(
        "--strip-link-only-lines",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Remove lines that contain only a URL.",
    )
    parser.add_argument(
        "--stop-at-footer",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Stop body_text collection when a footer marker like unsubscribe is reached.",
    )
    parser.add_argument(
        "--strip-invisible-chars",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Remove zero-width and formatting characters from body_text.",
    )
    parser.add_argument(
        "--normalize-whitespace",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Collapse repeated blank lines and trim line whitespace.",
    )


def _parser_config_from_args(args: argparse.Namespace) -> ParserConfig:
    return ParserConfig(
        strip_forwarded_headers=args.strip_forwarded_headers,
        strip_boilerplate=args.strip_boilerplate,
        strip_link_only_lines=args.strip_link_only_lines,
        stop_at_footer=args.stop_at_footer,
        strip_invisible_chars=args.strip_invisible_chars,
        normalize_whitespace=args.normalize_whitespace,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mailatlas", description="Local-first toolkit for structured email ingestion.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest", help="Ingest content into the local workspace.")
    ingest_subparsers = ingest_parser.add_subparsers(dest="ingest_command", required=True)

    ingest_eml_parser = ingest_subparsers.add_parser("eml", help="Ingest .eml files.")
    ingest_eml_parser.add_argument("paths", nargs="+", help="EML file paths to ingest.")
    _add_workspace_arguments(ingest_eml_parser)
    _add_parser_config_arguments(ingest_eml_parser)

    ingest_mbox_parser = ingest_subparsers.add_parser("mbox", help="Ingest an mbox archive.")
    ingest_mbox_parser.add_argument("path", help="Path to an mbox file.")
    _add_workspace_arguments(ingest_mbox_parser)
    _add_parser_config_arguments(ingest_mbox_parser)

    show_parser = subparsers.add_parser("show", help="Show a stored document as JSON.")
    show_parser.add_argument("document_id", help="Document identifier.")
    show_parser.add_argument("--format", choices=["json"], default="json", help="Output format.")
    _add_workspace_arguments(show_parser)

    export_parser = subparsers.add_parser("export", help="Export a stored document.")
    export_parser.add_argument("document_id", help="Document identifier.")
    export_parser.add_argument(
        "--format",
        choices=["json", "markdown", "html", "pdf"],
        default="json",
        help="Export format.",
    )
    export_parser.add_argument("--out", default=None, help="Optional path to write the export.")
    _add_workspace_arguments(export_parser)

    list_parser = subparsers.add_parser("list", help="List stored documents.")
    list_parser.add_argument("--query", default=None, help="Optional substring query.")
    _add_workspace_arguments(list_parser)

    brief_parser = subparsers.add_parser("brief", help="Generate a briefing from stored documents.")
    brief_subparsers = brief_parser.add_subparsers(dest="brief_command", required=True)

    brief_generate_parser = brief_subparsers.add_parser("generate", help="Generate a briefing.")
    brief_generate_parser.add_argument("--query", default=None, help="Optional substring query for document selection.")
    brief_generate_parser.add_argument("--ids", nargs="*", default=None, help="Explicit document identifiers.")
    brief_generate_parser.add_argument("--out", default=None, help="Output HTML path.")
    brief_generate_parser.add_argument("--provider", default="fallback", help="Brief provider: fallback, openai, anthropic, google.")
    _add_workspace_arguments(brief_generate_parser)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    parser_config = _parser_config_from_args(args) if args.command == "ingest" else None
    atlas = MailAtlas(db_path=args.db, workspace_path=args.workspace, parser_config=parser_config)

    if args.command == "ingest" and args.ingest_command == "eml":
        refs = atlas.ingest_eml(args.paths)
        print(json.dumps([reference.to_dict() for reference in refs], indent=2))
        return 0

    if args.command == "ingest" and args.ingest_command == "mbox":
        refs = atlas.ingest_mbox(args.path)
        print(json.dumps([reference.to_dict() for reference in refs], indent=2))
        return 0

    if args.command == "show":
        document = atlas.get_document(args.document_id)
        print(json.dumps(document.to_dict(), indent=2))
        return 0

    if args.command == "export":
        result = atlas.export_document(
            args.document_id,
            format=args.format,
            out_path=args.out,
        )
        print(result)
        return 0

    if args.command == "list":
        refs = atlas.list_documents(query=args.query)
        print(json.dumps([reference.to_dict() for reference in refs], indent=2))
        return 0

    if args.command == "brief" and args.brief_command == "generate":
        output_path = generate_brief(
            document_ids=args.ids or None,
            query=args.query,
            output_path=args.out,
            model_config={"provider": args.provider},
            db_path=args.db,
            workspace_path=args.workspace,
        )
        print(output_path)
        return 0

    parser.error("Unsupported command")
    return 1
