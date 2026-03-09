from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from email.message import EmailMessage
from pathlib import Path

from mailatlas.adapters.imap import ImapSyncError
from mailatlas.core import ImapSyncConfig, MailAtlas, ParserConfig
from mailatlas.core.pdf import find_pdf_browser


def _root_parent_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--root",
        default=None,
        help="MailAtlas root directory. Defaults to MAILATLAS_HOME, project config, or ./.mailatlas.",
    )
    return parser


def _parse_root_setting(config_path: Path, *, pyproject: bool) -> str | None:
    text = config_path.read_text(encoding="utf-8")
    current_section: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1].strip()
            continue

        if not re.match(r"^root\s*=", line):
            continue

        if pyproject and current_section != "tool.mailatlas":
            continue
        if not pyproject and current_section not in {None, "mailatlas"}:
            continue

        _, _, remainder = line.partition("=")
        value = remainder.split("#", 1)[0].strip().strip("'\"")
        if value:
            return value

    return None


def _configured_root_from_directory(directory: Path) -> Path | None:
    config_path = directory / ".mailatlas.toml"
    if config_path.exists():
        root_value = _parse_root_setting(config_path, pyproject=False)
        if root_value:
            return (directory / root_value).expanduser().resolve()

    pyproject_path = directory / "pyproject.toml"
    if pyproject_path.exists():
        root_value = _parse_root_setting(pyproject_path, pyproject=True)
        if root_value:
            return (directory / root_value).expanduser().resolve()

    return None


def _resolve_root(root_value: str | None) -> Path:
    if root_value:
        return Path(root_value).expanduser().resolve()

    env_root = os.getenv("MAILATLAS_HOME")
    if env_root:
        return Path(env_root).expanduser().resolve()

    cwd = Path.cwd().resolve()
    for directory in [cwd, *cwd.parents]:
        configured = _configured_root_from_directory(directory)
        if configured is not None:
            return configured

    return (cwd / ".mailatlas").resolve()


def _workspace_paths_from_root(root: Path) -> tuple[Path, Path]:
    return root / "store.db", root


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


def _env_or_value(value: str | None, env_name: str, default: str | None = None) -> str | None:
    if value is not None:
        return value
    return os.environ.get(env_name, default)


def _imap_sync_config_from_args(args: argparse.Namespace) -> ImapSyncConfig:
    host = _env_or_value(args.host, "MAILATLAS_IMAP_HOST")
    port_raw = _env_or_value(str(args.port) if args.port is not None else None, "MAILATLAS_IMAP_PORT", "993")
    username = _env_or_value(args.username, "MAILATLAS_IMAP_USERNAME")
    password = _env_or_value(args.password, "MAILATLAS_IMAP_PASSWORD")
    access_token = _env_or_value(args.access_token, "MAILATLAS_IMAP_ACCESS_TOKEN")
    folders = tuple(args.folder or ["INBOX"])

    if password and access_token:
        raise ValueError("Choose either password auth or access-token auth, not both.")
    if access_token:
        auth = "xoauth2"
    elif password:
        auth = "password"
    else:
        raise ValueError("Provide either an IMAP password or an IMAP access token.")

    try:
        port = int(port_raw or "993")
    except ValueError as error:
        raise ValueError("IMAP port must be an integer.") from error

    return ImapSyncConfig(
        host=host or "",
        port=port,
        username=username or "",
        auth=auth,
        password=password,
        access_token=access_token,
        folders=folders,
        parser_config=_parser_config_from_args(args),
    )


def _infer_ingest_type(path_value: str | Path) -> str:
    suffix = Path(path_value).suffix.lower()
    if suffix == ".eml":
        return "eml"
    if suffix == ".mbox":
        return "mbox"
    raise ValueError(f"Could not infer input type for {path_value}. Use --type eml or --type mbox.")


def _ingest_results_from_args(atlas: MailAtlas, args: argparse.Namespace) -> list:
    if args.type == "eml":
        return atlas.ingest_eml_results(args.paths)
    if args.type == "mbox":
        results = []
        for path in args.paths:
            results.extend(atlas.ingest_mbox_results(path))
        return results

    eml_paths: list[str] = []
    mbox_paths: list[str] = []
    for path in args.paths:
        input_type = _infer_ingest_type(path)
        if input_type == "eml":
            eml_paths.append(path)
        else:
            mbox_paths.append(path)

    results = []
    if eml_paths:
        results.extend(atlas.ingest_eml_results(eml_paths))
    for path in mbox_paths:
        results.extend(atlas.ingest_mbox_results(path))
    return results


def _doctor_message() -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = "MailAtlas doctor check"
    message["From"] = "MailAtlas Doctor <doctor@mailatlas.dev>"
    message["To"] = "team@example.com"
    message["Date"] = "Mon, 04 Mar 2024 09:00:00 +0000"
    message["Message-ID"] = "<mailatlas-doctor@example.com>"
    message.set_content("Doctor check body.\n\nThis message verifies ingest, storage, and export paths.")
    return message


def _run_doctor(*, skip_pdf: bool, require_pdf: bool) -> tuple[dict[str, object], int]:
    with tempfile.TemporaryDirectory(prefix="mailatlas-doctor-") as temp_dir:
        doctor_root = Path(temp_dir) / ".mailatlas"
        db_path, workspace_path = _workspace_paths_from_root(doctor_root)
        atlas = MailAtlas(db_path=db_path, workspace_path=workspace_path)
        eml_path = Path(temp_dir) / "doctor.eml"
        eml_path.write_bytes(_doctor_message().as_bytes())

        results = atlas.ingest_eml_results([eml_path])
        document_ref = results[0].ref
        listed = atlas.list_documents()
        document = atlas.get_document(document_ref.id)
        json_export_path = Path(
            atlas.export_document(
                document_ref.id,
                format="json",
                out_path=Path(temp_dir) / "doctor-document.json",
            )
        )
        checks: dict[str, bool] = {
            "ingest": results[0].status == "ingested",
            "list": len(listed) == 1,
            "get": document.id == document_ref.id,
            "export_json": json_export_path.exists(),
        }

        payload: dict[str, object] = {
            "status": "ok",
            "root": doctor_root.as_posix(),
            "document_ref": document_ref.to_dict(),
            "checks": checks,
            "json_export": json_export_path.as_posix(),
            "pdf": {"status": "skipped"} if skip_pdf else None,
        }

        if not skip_pdf:
            try:
                browser = find_pdf_browser()
                pdf_export_path = Path(
                    atlas.export_document(
                        document_ref.id,
                        format="pdf",
                        out_path=Path(temp_dir) / "doctor-document.pdf",
                    )
                )
                checks["export_pdf"] = pdf_export_path.exists()
                payload["pdf"] = {
                    "status": "ok",
                    "browser": browser.as_posix(),
                    "path": pdf_export_path.as_posix(),
                }
            except RuntimeError as error:
                checks["export_pdf"] = False
                payload["pdf"] = {
                    "status": "unavailable",
                    "error": str(error),
                }
                if require_pdf:
                    payload["status"] = "error"
                else:
                    payload["status"] = "warn"

        return payload, 1 if payload["status"] == "error" else 0


def _build_parser() -> argparse.ArgumentParser:
    root_parent = _root_parent_parser()
    parser = argparse.ArgumentParser(
        prog="mailatlas",
        description="Email ingestion for AI agents and data applications.",
        parents=[root_parent],
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser(
        "ingest",
        help="Ingest one or more email sources from disk.",
        parents=[root_parent],
    )
    ingest_parser.add_argument("paths", nargs="+", help="Paths to .eml files or mbox archives.")
    ingest_parser.add_argument(
        "--type",
        choices=["auto", "eml", "mbox"],
        default="auto",
        help="Override automatic input-type detection.",
    )
    _add_parser_config_arguments(ingest_parser)

    get_parser = subparsers.add_parser(
        "get",
        help="Read or export a stored document.",
        parents=[root_parent],
    )
    get_parser.add_argument("document_id", help="Document identifier.")
    get_parser.add_argument(
        "--format",
        choices=["json", "markdown", "html", "pdf"],
        default="json",
        help="Output format.",
    )
    get_parser.add_argument(
        "--out",
        default=None,
        help="Optional output destination. Markdown expects a bundle directory; other formats write a file path.",
    )

    list_parser = subparsers.add_parser("list", help="List stored documents.", parents=[root_parent])
    list_parser.add_argument("--query", default=None, help="Optional substring query.")

    sync_parser = subparsers.add_parser(
        "sync",
        help="Sync one or more IMAP folders.",
        parents=[root_parent],
    )
    sync_parser.add_argument("--host", default=None, help="IMAP hostname or use MAILATLAS_IMAP_HOST.")
    sync_parser.add_argument("--port", type=int, default=None, help="IMAP TLS port or use MAILATLAS_IMAP_PORT.")
    sync_parser.add_argument("--username", default=None, help="IMAP username or use MAILATLAS_IMAP_USERNAME.")
    sync_parser.add_argument("--password", default=None, help="IMAP password or use MAILATLAS_IMAP_PASSWORD.")
    sync_parser.add_argument(
        "--access-token",
        default=None,
        help="OAuth access token or use MAILATLAS_IMAP_ACCESS_TOKEN.",
    )
    sync_parser.add_argument(
        "--folder",
        action="append",
        default=None,
        help="Folder to sync. Repeat for multiple folders. Defaults to INBOX.",
    )
    _add_parser_config_arguments(sync_parser)

    doctor_parser = subparsers.add_parser("doctor", help="Run a local self-check.", parents=[root_parent])
    doctor_parser.add_argument(
        "--skip-pdf",
        action="store_true",
        help="Skip the optional PDF export check.",
    )
    doctor_parser.add_argument(
        "--require-pdf",
        action="store_true",
        help="Fail if PDF export is unavailable.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "doctor":
        if args.skip_pdf and args.require_pdf:
            print("--skip-pdf and --require-pdf cannot be used together.", file=sys.stderr)
            return 1
        try:
            payload, exit_code = _run_doctor(skip_pdf=args.skip_pdf, require_pdf=args.require_pdf)
        except (OSError, RuntimeError, ValueError) as error:
            print(str(error), file=sys.stderr)
            return 1

        print(json.dumps(payload, indent=2))
        return exit_code

    root = _resolve_root(args.root)
    db_path, workspace_path = _workspace_paths_from_root(root)
    parser_config = _parser_config_from_args(args) if args.command == "ingest" else None
    atlas = MailAtlas(db_path=db_path, workspace_path=workspace_path, parser_config=parser_config)

    if args.command == "ingest":
        try:
            results = _ingest_results_from_args(atlas, args)
        except ValueError as error:
            print(str(error), file=sys.stderr)
            return 1

        print(
            json.dumps(
                {
                    "status": "ok",
                    "ingested_count": sum(1 for result in results if result.status == "ingested"),
                    "duplicate_count": sum(1 for result in results if result.status == "duplicate"),
                    "document_refs": [result.ref.to_dict() for result in results],
                },
                indent=2,
            )
        )
        return 0

    if args.command == "list":
        refs = atlas.list_documents(query=args.query)
        print(json.dumps([reference.to_dict() for reference in refs], indent=2))
        return 0

    if args.command == "get":
        try:
            if args.out or args.format == "pdf":
                print(atlas.export_document(args.document_id, format=args.format, out_path=args.out))
            elif args.format == "json":
                print(json.dumps(atlas.get_document(args.document_id).to_dict(), indent=2))
            else:
                sys.stdout.write(atlas.export_document(args.document_id, format=args.format))
        except (KeyError, RuntimeError, ValueError) as error:
            print(str(error), file=sys.stderr)
            return 1
        return 0

    if args.command == "sync":
        try:
            result = atlas.sync_imap(_imap_sync_config_from_args(args))
        except (ImapSyncError, ValueError) as error:
            print(str(error), file=sys.stderr)
            return 1

        print(json.dumps(result.to_dict(), indent=2))
        return 1 if result.has_errors() else 0

    parser.error("Unsupported command")
    return 1
