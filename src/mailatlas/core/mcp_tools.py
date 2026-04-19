from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .gmail_auth import FileTokenStore, load_valid_gmail_access_token
from .models import OutboundAttachment, OutboundMessage, SendConfig
from .service import MailAtlas


def mcp_send_enabled() -> bool:
    return os.environ.get("MAILATLAS_MCP_ALLOW_SEND", "").strip() == "1"


def mcp_tool_names(*, allow_send: bool | None = None) -> tuple[str, ...]:
    send_allowed = mcp_send_enabled() if allow_send is None else allow_send
    names = [
        "mailatlas_list_documents",
        "mailatlas_get_document",
        "mailatlas_export_document",
        "mailatlas_list_outbound",
        "mailatlas_get_outbound",
        "mailatlas_draft_email",
    ]
    if send_allowed:
        names.append("mailatlas_send_email")
    return tuple(names)


def _as_tuple(value: str | list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value if str(item).strip())


def _env_or_value(value: str | None, env_name: str, default: str | None = None) -> str | None:
    if value is not None and str(value).strip():
        return str(value).strip()
    env_value = os.environ.get(env_name)
    if env_value is not None and env_value.strip():
        return env_value.strip()
    return default


def _env_bool(env_name: str, default: bool) -> bool:
    raw_value = os.environ.get(env_name)
    if raw_value is None or not raw_value.strip():
        return default
    value = raw_value.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{env_name} must be true or false.")


def _smtp_port(value: int | str | None) -> int:
    raw_value = _env_or_value(str(value) if value is not None else None, "MAILATLAS_SMTP_PORT", "587")
    try:
        return int(raw_value or "587")
    except ValueError as error:
        raise ValueError("SMTP port must be an integer.") from error


def _outbound_message(
    *,
    from_email: str,
    to: str | list[str] | tuple[str, ...],
    subject: str,
    text: str | None = None,
    html: str | None = None,
    from_name: str | None = None,
    cc: str | list[str] | tuple[str, ...] | None = None,
    bcc: str | list[str] | tuple[str, ...] | None = None,
    reply_to: str | list[str] | tuple[str, ...] | None = None,
    in_reply_to: str | None = None,
    references: str | list[str] | tuple[str, ...] | None = None,
    headers: dict[str, str] | None = None,
    attachments: list[str] | tuple[str, ...] | None = None,
    source_document_id: str | None = None,
    idempotency_key: str | None = None,
) -> OutboundMessage:
    return OutboundMessage(
        from_email=from_email,
        from_name=from_name,
        to=_as_tuple(to),
        cc=_as_tuple(cc),
        bcc=_as_tuple(bcc),
        reply_to=_as_tuple(reply_to),
        subject=subject,
        text=text,
        html=html,
        headers=dict(headers or {}),
        in_reply_to=in_reply_to,
        references=_as_tuple(references),
        source_document_id=source_document_id,
        idempotency_key=idempotency_key,
        attachments=tuple(OutboundAttachment(path=path) for path in (attachments or ())),
    )


def _send_result_payload(result, message: OutboundMessage) -> dict[str, Any]:
    return {
        **result.to_dict(),
        "from_email": message.from_email,
        "to": list(message.to),
        "cc": list(message.cc),
        "subject": message.subject,
    }


class MailAtlasMcpTools:
    def __init__(self, *, root: str | Path | None = None, allow_send: bool | None = None):
        self.root = Path(root or os.environ.get("MAILATLAS_HOME") or ".mailatlas").expanduser().resolve()
        self.atlas = MailAtlas(db_path=self.root / "store.db", workspace_path=self.root)
        self.allow_send = mcp_send_enabled() if allow_send is None else allow_send

    def list_documents(self, query: str | None = None) -> dict[str, Any]:
        refs = self.atlas.list_documents(query=query)
        return {"documents": [ref.to_dict() for ref in refs]}

    def get_document(self, document_id: str) -> dict[str, Any]:
        return self.atlas.get_document(document_id).to_dict()

    def export_document(self, document_id: str, format: str = "json", out_path: str | None = None) -> dict[str, Any]:
        content = self.atlas.export_document(document_id, format=format, out_path=out_path)
        key = "path" if out_path or format == "pdf" else "content"
        return {"document_id": document_id, "format": format, key: content}

    def list_outbound(self, query: str | None = None) -> dict[str, Any]:
        refs = self.atlas.list_outbound(query=query)
        return {"outbound": [ref.to_dict() for ref in refs]}

    def get_outbound(self, outbound_id: str, include_bcc: bool = False) -> dict[str, Any]:
        return self.atlas.get_outbound(outbound_id).to_dict(include_bcc=include_bcc)

    def draft_email(self, **kwargs: Any) -> dict[str, Any]:
        message = _outbound_message(**kwargs)
        result = self.atlas.draft_email(message)
        return _send_result_payload(result, message)

    def send_email(
        self,
        *,
        provider: str | None = None,
        dry_run: bool = False,
        smtp_host: str | None = None,
        smtp_port: int | str | None = None,
        smtp_username: str | None = None,
        smtp_password: str | None = None,
        smtp_starttls: bool | None = None,
        smtp_ssl: bool | None = None,
        cloudflare_account_id: str | None = None,
        cloudflare_api_token: str | None = None,
        cloudflare_api_base: str | None = None,
        gmail_access_token: str | None = None,
        gmail_api_base: str | None = None,
        gmail_user_id: str | None = None,
        gmail_token_file: str | None = None,
        **message_kwargs: Any,
    ) -> dict[str, Any]:
        message = _outbound_message(**message_kwargs)
        effective_provider = (_env_or_value(provider, "MAILATLAS_SEND_PROVIDER", "smtp") or "smtp").lower()
        if not self.allow_send:
            return {
                "status": "disabled",
                "provider": effective_provider,
                "from_email": message.from_email,
                "to": list(message.to),
                "cc": list(message.cc),
                "subject": message.subject,
                "error": "MCP send is disabled. Set MAILATLAS_MCP_ALLOW_SEND=1 to enable mailatlas_send_email.",
            }

        effective_gmail_access_token = _env_or_value(gmail_access_token, "MAILATLAS_GMAIL_ACCESS_TOKEN")
        if effective_provider == "gmail" and not dry_run and not effective_gmail_access_token:
            effective_gmail_access_token = load_valid_gmail_access_token(store=FileTokenStore(gmail_token_file))

        config = SendConfig(
            provider=effective_provider,
            dry_run=dry_run,
            smtp_host=_env_or_value(smtp_host, "MAILATLAS_SMTP_HOST"),
            smtp_port=_smtp_port(smtp_port),
            smtp_username=_env_or_value(smtp_username, "MAILATLAS_SMTP_USERNAME"),
            smtp_password=_env_or_value(smtp_password, "MAILATLAS_SMTP_PASSWORD"),
            smtp_starttls=smtp_starttls if smtp_starttls is not None else _env_bool("MAILATLAS_SMTP_STARTTLS", True),
            smtp_ssl=smtp_ssl if smtp_ssl is not None else _env_bool("MAILATLAS_SMTP_SSL", False),
            cloudflare_account_id=_env_or_value(cloudflare_account_id, "MAILATLAS_CLOUDFLARE_ACCOUNT_ID"),
            cloudflare_api_token=_env_or_value(cloudflare_api_token, "MAILATLAS_CLOUDFLARE_API_TOKEN"),
            cloudflare_api_base=_env_or_value(cloudflare_api_base, "MAILATLAS_CLOUDFLARE_API_BASE"),
            gmail_access_token=effective_gmail_access_token,
            gmail_api_base=_env_or_value(gmail_api_base, "MAILATLAS_GMAIL_API_BASE"),
            gmail_user_id=_env_or_value(gmail_user_id, "MAILATLAS_GMAIL_USER_ID", "me") or "me",
        )
        result = self.atlas.send_email(message, config)
        return _send_result_payload(result, message)
