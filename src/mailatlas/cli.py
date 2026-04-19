from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from email.message import EmailMessage
from pathlib import Path

from mailatlas.core import (
    GMAIL_READONLY_SCOPE,
    GMAIL_SEND_SCOPE,
    GmailAuthConfig,
    MailAtlas,
    OutboundAttachment,
    OutboundMessage,
    ParserConfig,
    ReceiveConfig,
    SendConfig,
    gmail_scopes_for_capabilities,
    gmail_auth_logout,
    gmail_auth_status,
    run_gmail_auth_flow,
)
from mailatlas.core.gmail_auth import create_gmail_token_store, load_valid_gmail_access_token
from mailatlas.core.pdf import find_pdf_browser
from mailatlas.receive import receive_watch


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


def _add_receive_config_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--provider", default=None, help="Receive provider or MAILATLAS_RECEIVE_PROVIDER. Defaults to gmail.")
    parser.add_argument("--account-id", default=None, help="Stable local receive account id.")
    parser.add_argument("--label", default=None, help="Gmail label to receive from or MAILATLAS_GMAIL_RECEIVE_LABEL. Defaults to INBOX.")
    parser.add_argument("--query", default=None, help="Optional Gmail search query or MAILATLAS_GMAIL_RECEIVE_QUERY.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum messages to fetch in one pass. Defaults to 50.")
    parser.add_argument("--full-sync", action="store_true", help="Ignore the incremental cursor and run an explicit full sync.")
    parser.add_argument(
        "--include-spam-trash",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Include Gmail spam and trash in receive list calls.",
    )
    parser.add_argument("--gmail-access-token", default=None, help="One-off Gmail OAuth access token or MAILATLAS_GMAIL_ACCESS_TOKEN.")
    parser.add_argument("--gmail-api-base", default=None, help="Gmail API base URL or MAILATLAS_GMAIL_API_BASE.")
    parser.add_argument("--gmail-user-id", default=None, help="Gmail API user id or MAILATLAS_GMAIL_USER_ID. Defaults to me.")
    parser.add_argument("--token-store", default=None, help="Gmail token store: auto, keychain, file, or a token file path.")
    parser.add_argument("--token-file", default=None, help="Path to stored Gmail OAuth token JSON.")
    _add_parser_config_arguments(parser)


def _add_imap_config_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default=None, help="IMAP hostname or use MAILATLAS_IMAP_HOST.")
    parser.add_argument("--port", type=int, default=None, help="IMAP TLS port or use MAILATLAS_IMAP_PORT.")
    parser.add_argument("--username", default=None, help="IMAP username or use MAILATLAS_IMAP_USERNAME.")
    parser.add_argument("--password", default=None, help="IMAP password or use MAILATLAS_IMAP_PASSWORD.")
    parser.add_argument(
        "--access-token",
        default=None,
        help="IMAP OAuth access token or use MAILATLAS_IMAP_ACCESS_TOKEN.",
    )
    parser.add_argument(
        "--folder",
        action="append",
        default=None,
        help="IMAP folder to receive. Repeat for multiple folders. Defaults to INBOX.",
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


def _env_bool(env_name: str, default: bool) -> bool:
    raw_value = os.environ.get(env_name)
    if raw_value is None:
        return default
    value = raw_value.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{env_name} must be true or false.")


def _value_or_env_bool(value: bool | None, env_name: str, default: bool) -> bool:
    if value is not None:
        return value
    return _env_bool(env_name, default)


def _send_config_from_args(args: argparse.Namespace) -> SendConfig:
    provider = _env_or_value(args.provider, "MAILATLAS_SEND_PROVIDER", "smtp")
    provider = (provider or "smtp").strip().lower()
    smtp_port_raw = _env_or_value(str(args.smtp_port) if args.smtp_port is not None else None, "MAILATLAS_SMTP_PORT", "587")
    try:
        smtp_port = int(smtp_port_raw or "587")
    except ValueError as error:
        raise ValueError("SMTP port must be an integer.") from error

    gmail_access_token = _env_or_value(args.gmail_access_token, "MAILATLAS_GMAIL_ACCESS_TOKEN")
    if provider == "gmail" and not args.dry_run and not gmail_access_token:
        gmail_access_token = load_valid_gmail_access_token(
            store=create_gmail_token_store(args.gmail_token_file, token_store=args.gmail_token_store)
        )

    return SendConfig(
        provider=provider,
        dry_run=args.dry_run,
        smtp_host=_env_or_value(args.smtp_host, "MAILATLAS_SMTP_HOST"),
        smtp_port=smtp_port,
        smtp_username=_env_or_value(args.smtp_username, "MAILATLAS_SMTP_USERNAME"),
        smtp_password=_env_or_value(args.smtp_password, "MAILATLAS_SMTP_PASSWORD"),
        smtp_starttls=_value_or_env_bool(args.smtp_starttls, "MAILATLAS_SMTP_STARTTLS", True),
        smtp_ssl=_value_or_env_bool(args.smtp_ssl, "MAILATLAS_SMTP_SSL", False),
        cloudflare_account_id=_env_or_value(args.cloudflare_account_id, "MAILATLAS_CLOUDFLARE_ACCOUNT_ID"),
        cloudflare_api_token=_env_or_value(args.cloudflare_api_token, "MAILATLAS_CLOUDFLARE_API_TOKEN"),
        cloudflare_api_base=_env_or_value(args.cloudflare_api_base, "MAILATLAS_CLOUDFLARE_API_BASE"),
        gmail_access_token=gmail_access_token,
        gmail_api_base=_env_or_value(args.gmail_api_base, "MAILATLAS_GMAIL_API_BASE"),
        gmail_user_id=_env_or_value(args.gmail_user_id, "MAILATLAS_GMAIL_USER_ID", "me") or "me",
    )


def _int_from_env_or_value(value: int | str | None, env_name: str, default: int) -> int:
    raw_value = str(value) if value is not None else os.environ.get(env_name, str(default))
    try:
        return int(raw_value or str(default))
    except ValueError as error:
        raise ValueError(f"{env_name} must be an integer.") from error


def _receive_config_from_args(args: argparse.Namespace) -> ReceiveConfig:
    provider = _env_or_value(args.provider, "MAILATLAS_RECEIVE_PROVIDER", "gmail") or "gmail"
    limit = _int_from_env_or_value(args.limit, "MAILATLAS_GMAIL_RECEIVE_LIMIT", 50)
    imap_password = _env_or_value(getattr(args, "password", None), "MAILATLAS_IMAP_PASSWORD")
    imap_access_token = _env_or_value(getattr(args, "access_token", None), "MAILATLAS_IMAP_ACCESS_TOKEN")
    return ReceiveConfig(
        provider=provider,
        account_id=args.account_id,
        gmail_access_token=_env_or_value(args.gmail_access_token, "MAILATLAS_GMAIL_ACCESS_TOKEN"),
        gmail_api_base=_env_or_value(args.gmail_api_base, "MAILATLAS_GMAIL_API_BASE"),
        gmail_user_id=_env_or_value(args.gmail_user_id, "MAILATLAS_GMAIL_USER_ID", "me") or "me",
        gmail_label=_env_or_value(args.label, "MAILATLAS_GMAIL_RECEIVE_LABEL", "INBOX") or "INBOX",
        gmail_query=_env_or_value(args.query, "MAILATLAS_GMAIL_RECEIVE_QUERY"),
        gmail_include_spam_trash=_value_or_env_bool(args.include_spam_trash, "MAILATLAS_GMAIL_INCLUDE_SPAM_TRASH", False),
        token_store=_env_or_value(args.token_store, "MAILATLAS_GMAIL_TOKEN_STORE"),
        token_file=_env_or_value(args.token_file, "MAILATLAS_GMAIL_TOKEN_FILE"),
        limit=limit,
        full_sync=bool(args.full_sync),
        imap_host=_env_or_value(getattr(args, "host", None), "MAILATLAS_IMAP_HOST"),
        imap_port=_int_from_env_or_value(getattr(args, "port", None), "MAILATLAS_IMAP_PORT", 993),
        imap_username=_env_or_value(getattr(args, "username", None), "MAILATLAS_IMAP_USERNAME"),
        imap_auth="xoauth2" if imap_access_token else "password",
        imap_password=imap_password,
        imap_access_token=imap_access_token,
        imap_folders=tuple(getattr(args, "folder", None) or ["INBOX"]),
        parser_config=_parser_config_from_args(args),
    )


def _receive_exit_code(status: str) -> int:
    return 1 if status in {"error", "partial", "not_configured", "cursor_reset_required"} else 0


def _gmail_auth_scopes_from_args(args: argparse.Namespace) -> tuple[str, ...]:
    capability_values: list[str] = []
    for raw_value in args.capability or []:
        capability_values.extend(value.strip() for value in raw_value.split(",") if value.strip())

    scopes: list[str] = []
    if args.scope:
        scopes.extend(args.scope)
    if capability_values:
        scopes.extend(gmail_scopes_for_capabilities(capability_values))
    if not scopes:
        scopes.append(GMAIL_SEND_SCOPE)

    return tuple(dict.fromkeys(scopes))


def _gmail_auth_config_from_args(args: argparse.Namespace) -> GmailAuthConfig:
    client_id = _env_or_value(args.client_id, "MAILATLAS_GMAIL_CLIENT_ID")
    if not client_id:
        raise ValueError("Gmail OAuth client id is required. Pass --client-id or set MAILATLAS_GMAIL_CLIENT_ID.")
    scopes = _gmail_auth_scopes_from_args(args)
    timeout = int(_env_or_value(str(args.timeout) if args.timeout is not None else None, "MAILATLAS_GMAIL_AUTH_TIMEOUT", "300") or "300")
    return GmailAuthConfig(
        client_id=client_id,
        client_secret=_env_or_value(args.client_secret, "MAILATLAS_GMAIL_CLIENT_SECRET"),
        email=_env_or_value(args.email, "MAILATLAS_GMAIL_EMAIL"),
        scopes=scopes,
        timeout_seconds=timeout,
    )


def _headers_from_args(header_values: list[str] | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    for header in header_values or []:
        name, separator, value = header.partition(":")
        if not separator:
            raise ValueError("--header must use 'Name: value' format.")
        headers[name.strip()] = value.strip()
    return headers


def _outbound_message_from_args(args: argparse.Namespace) -> OutboundMessage:
    text = args.text
    if args.text_file:
        text = Path(args.text_file).expanduser().read_text(encoding="utf-8")

    html = None
    if args.html_file:
        html = Path(args.html_file).expanduser().read_text(encoding="utf-8")

    return OutboundMessage(
        from_email=args.from_email,
        from_name=args.from_name,
        to=tuple(args.to or ()),
        cc=tuple(args.cc or ()),
        bcc=tuple(args.bcc or ()),
        reply_to=tuple(args.reply_to or ()),
        subject=args.subject,
        text=text,
        html=html,
        headers=_headers_from_args(args.header),
        in_reply_to=args.in_reply_to,
        references=tuple(args.references or ()),
        source_document_id=args.source_document_id,
        idempotency_key=args.idempotency_key,
        attachments=tuple(OutboundAttachment(path=path) for path in (args.attach or ())),
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
        description="Local email ingestion, mailbox receive, export, sending, and audit trails for AI agents and data applications.",
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

    receive_parser = subparsers.add_parser(
        "receive",
        help="Receive mailbox messages into the local workspace.",
        parents=[root_parent],
    )
    _add_receive_config_arguments(receive_parser)
    _add_imap_config_arguments(receive_parser)
    receive_subparsers = receive_parser.add_subparsers(dest="receive_command")

    receive_watch_parser = receive_subparsers.add_parser(
        "watch",
        help="Run foreground background receive polling.",
        parents=[root_parent],
    )
    _add_receive_config_arguments(receive_watch_parser)
    _add_imap_config_arguments(receive_watch_parser)
    receive_watch_parser.add_argument("--interval", type=int, default=None, help="Polling interval in seconds. Defaults to 60.")
    receive_watch_parser.add_argument("--max-runs", type=int, default=None, help="Optional watch run limit for scripts and tests.")

    receive_status_parser = receive_subparsers.add_parser(
        "status",
        help="Show receive accounts, cursors, and recent runs.",
        parents=[root_parent],
    )
    receive_status_parser.add_argument("--account-id", default=None, help="Optional receive account id to inspect.")

    send_parser = subparsers.add_parser(
        "send",
        help="Compose, send, and audit an outbound email.",
        parents=[root_parent],
    )
    send_parser.add_argument("--provider", default=None, help="Send provider or MAILATLAS_SEND_PROVIDER.")
    send_parser.add_argument("--from", dest="from_email", required=True, help="Sender email address.")
    send_parser.add_argument("--from-name", default=None, help="Optional sender display name.")
    send_parser.add_argument("--to", action="append", default=None, required=True, help="Recipient address. Repeat for multiple recipients.")
    send_parser.add_argument("--cc", action="append", default=None, help="CC recipient. Repeat for multiple recipients.")
    send_parser.add_argument("--bcc", action="append", default=None, help="BCC recipient. Stored for audit but omitted from MIME headers.")
    send_parser.add_argument("--reply-to", action="append", default=None, help="Reply-To address. Repeat for multiple addresses.")
    send_parser.add_argument("--subject", required=True, help="Message subject.")
    body_group = send_parser.add_mutually_exclusive_group()
    body_group.add_argument("--text", default=None, help="Inline plain-text body.")
    body_group.add_argument("--text-file", default=None, help="Path to a plain-text body file.")
    send_parser.add_argument("--html-file", default=None, help="Path to an HTML body file.")
    send_parser.add_argument("--attach", action="append", default=None, help="Attachment path. Repeat for multiple attachments.")
    send_parser.add_argument("--header", action="append", default=None, help="Custom header in 'Name: value' format.")
    send_parser.add_argument("--in-reply-to", default=None, help="Message ID this email replies to.")
    send_parser.add_argument("--references", action="append", default=None, help="Message ID reference. Repeat for multiple references.")
    send_parser.add_argument("--source-document-id", default=None, help="Optional inbound document link.")
    send_parser.add_argument("--idempotency-key", default=None, help="Caller-provided retry key.")
    send_parser.add_argument("--dry-run", action="store_true", help="Render and store the message without contacting a provider.")
    send_parser.add_argument("--smtp-host", default=None, help="SMTP hostname or MAILATLAS_SMTP_HOST.")
    send_parser.add_argument("--smtp-port", type=int, default=None, help="SMTP port or MAILATLAS_SMTP_PORT.")
    send_parser.add_argument("--smtp-username", default=None, help="SMTP username or MAILATLAS_SMTP_USERNAME.")
    send_parser.add_argument("--smtp-password", default=None, help="SMTP password or MAILATLAS_SMTP_PASSWORD.")
    send_parser.add_argument("--smtp-starttls", dest="smtp_starttls", action="store_true", default=None, help="Use SMTP STARTTLS.")
    send_parser.add_argument("--no-smtp-starttls", dest="smtp_starttls", action="store_false", help="Disable SMTP STARTTLS.")
    send_parser.add_argument("--smtp-ssl", dest="smtp_ssl", action="store_true", default=None, help="Use SMTP over SSL.")
    send_parser.add_argument("--no-smtp-ssl", dest="smtp_ssl", action="store_false", help="Disable SMTP over SSL.")
    send_parser.add_argument("--cloudflare-account-id", default=None, help="Cloudflare account id or MAILATLAS_CLOUDFLARE_ACCOUNT_ID.")
    send_parser.add_argument("--cloudflare-api-token", default=None, help="Cloudflare API token or MAILATLAS_CLOUDFLARE_API_TOKEN.")
    send_parser.add_argument("--cloudflare-api-base", default=None, help="Cloudflare API base URL or MAILATLAS_CLOUDFLARE_API_BASE.")
    send_parser.add_argument("--gmail-access-token", default=None, help="Gmail OAuth access token or MAILATLAS_GMAIL_ACCESS_TOKEN.")
    send_parser.add_argument("--gmail-api-base", default=None, help="Gmail API base URL or MAILATLAS_GMAIL_API_BASE.")
    send_parser.add_argument("--gmail-user-id", default=None, help="Gmail API user id or MAILATLAS_GMAIL_USER_ID. Defaults to me.")
    send_parser.add_argument("--gmail-token-file", default=None, help="Path to stored Gmail OAuth token JSON.")
    send_parser.add_argument("--gmail-token-store", default=None, help="Gmail token store: auto, keychain, file, or a token file path.")

    auth_parser = subparsers.add_parser(
        "auth",
        help="Manage provider authentication.",
    )
    auth_subparsers = auth_parser.add_subparsers(dest="auth_command", required=True)
    gmail_auth_parser = auth_subparsers.add_parser("gmail", help="Authorize Gmail API sending.")
    gmail_auth_parser.add_argument("--client-id", default=None, help="Google OAuth client id or MAILATLAS_GMAIL_CLIENT_ID.")
    gmail_auth_parser.add_argument("--client-secret", default=None, help="Google OAuth client secret or MAILATLAS_GMAIL_CLIENT_SECRET.")
    gmail_auth_parser.add_argument("--email", default=None, help="Gmail address hint stored for status output.")
    gmail_auth_parser.add_argument("--scope", action="append", default=None, help=f"OAuth scope. Defaults to {GMAIL_SEND_SCOPE}.")
    gmail_auth_parser.add_argument(
        "--capability",
        action="append",
        default=None,
        help=f"Gmail capability to request: send, receive, or comma-separated send,receive. Receive uses {GMAIL_READONLY_SCOPE}.",
    )
    gmail_auth_parser.add_argument("--token-file", default=None, help="Path to store Gmail OAuth token JSON.")
    gmail_auth_parser.add_argument("--token-store", default=None, help="Gmail token store: auto, keychain, file, or a token file path.")
    gmail_auth_parser.add_argument("--timeout", type=int, default=None, help="Seconds to wait for the local OAuth callback.")
    gmail_auth_parser.add_argument("--no-browser", action="store_true", help="Print the OAuth URL instead of opening a browser.")

    auth_status_parser = auth_subparsers.add_parser("status", help="Show provider auth status.")
    auth_status_parser.add_argument("provider", choices=["gmail"], help="Provider to inspect.")
    auth_status_parser.add_argument("--token-file", default=None, help="Path to stored Gmail OAuth token JSON.")
    auth_status_parser.add_argument("--token-store", default=None, help="Gmail token store: auto, keychain, file, or a token file path.")

    auth_logout_parser = auth_subparsers.add_parser("logout", help="Remove stored provider auth.")
    auth_logout_parser.add_argument("provider", choices=["gmail"], help="Provider to remove.")
    auth_logout_parser.add_argument("--token-file", default=None, help="Path to stored Gmail OAuth token JSON.")
    auth_logout_parser.add_argument("--token-store", default=None, help="Gmail token store: auto, keychain, file, or a token file path.")

    mcp_parser = subparsers.add_parser(
        "mcp",
        help="Run the MailAtlas MCP server.",
        parents=[root_parent],
    )
    mcp_parser.add_argument("--transport", choices=["stdio"], default="stdio", help="MCP transport. Defaults to stdio.")

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

    if args.command == "auth":
        try:
            store = create_gmail_token_store(getattr(args, "token_file", None), token_store=getattr(args, "token_store", None))
            if args.auth_command == "gmail":
                result = run_gmail_auth_flow(
                    _gmail_auth_config_from_args(args),
                    store=store,
                    open_browser=not args.no_browser,
                    notify=lambda url: print(f"Open this URL to authorize Gmail access:\n{url}", file=sys.stderr),
                )
            elif args.auth_command == "status" and args.provider == "gmail":
                result = gmail_auth_status(store=store)
            elif args.auth_command == "logout" and args.provider == "gmail":
                result = gmail_auth_logout(store=store)
            else:
                parser.error("Unsupported auth command")
        except (OSError, RuntimeError, TimeoutError, ValueError) as error:
            print(str(error), file=sys.stderr)
            return 1

        print(json.dumps(result.to_dict(), indent=2))
        return 0

    root = _resolve_root(args.root)
    db_path, workspace_path = _workspace_paths_from_root(root)
    parser_config = _parser_config_from_args(args) if args.command == "ingest" else None
    atlas = MailAtlas(db_path=db_path, workspace_path=workspace_path, parser_config=parser_config)

    if args.command == "receive":
        try:
            if args.receive_command == "status":
                print(json.dumps(atlas.receive_status(account_id=args.account_id), indent=2))
                return 0

            config = _receive_config_from_args(args)
            if args.receive_command == "watch":
                interval = _int_from_env_or_value(args.interval, "MAILATLAS_RECEIVE_INTERVAL_SECONDS", 60)
                max_runs = args.max_runs
                if max_runs is None and os.environ.get("MAILATLAS_RECEIVE_MAX_RUNS"):
                    max_runs = _int_from_env_or_value(None, "MAILATLAS_RECEIVE_MAX_RUNS", 0)

                results = receive_watch(
                    atlas,
                    config,
                    interval_seconds=interval,
                    stop_after=max_runs,
                    on_result=lambda result: print(json.dumps(result.to_dict(), separators=(",", ":")), flush=True),
                )
                return _receive_exit_code(results[-1].status) if results else 0

            result = atlas.receive(config)
        except (OSError, RuntimeError, ValueError) as error:
            print(str(error), file=sys.stderr)
            return 1

        print(json.dumps(result.to_dict(), indent=2))
        return _receive_exit_code(result.status)

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

    if args.command == "send":
        try:
            result = atlas.send_email(_outbound_message_from_args(args), _send_config_from_args(args))
        except (OSError, RuntimeError, ValueError) as error:
            print(str(error), file=sys.stderr)
            return 1

        print(json.dumps(result.to_dict(), indent=2))
        return 1 if result.status == "error" else 0

    if args.command == "mcp":
        try:
            from mailatlas.mcp_server import run_mcp_server

            return run_mcp_server(root=_resolve_root(args.root), transport=args.transport)
        except RuntimeError as error:
            print(str(error), file=sys.stderr)
            return 1

    parser.error("Unsupported command")
    return 1
