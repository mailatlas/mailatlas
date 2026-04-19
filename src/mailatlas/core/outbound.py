from __future__ import annotations

import mimetypes
import re
from dataclasses import replace
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid, parseaddr
from pathlib import Path
from typing import Any

from .models import OutboundAttachment, OutboundMessage, OutboundMessageRecord, SendResult


_EMAIL_RE = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")
_HEADER_NAME_RE = re.compile(r"^[A-Za-z0-9!#$%&'*+\-.^_`|~]+$")


class OutboundValidationError(ValueError):
    """Raised when an outbound message cannot be rendered safely."""


def _reject_crlf(label: str, value: str | None) -> None:
    if value is not None and ("\r" in value or "\n" in value):
        raise OutboundValidationError(f"{label} must not contain CR or LF characters.")


def _normalize_email(value: str, label: str) -> tuple[str | None, str]:
    cleaned = str(value).strip() if value is not None else ""
    _reject_crlf(label, cleaned)
    if not cleaned:
        raise OutboundValidationError(f"{label} is required.")

    display_name, address = parseaddr(cleaned)
    address = address.strip()
    if not address or not _EMAIL_RE.match(address):
        raise OutboundValidationError(f"{label} must be a valid email address.")
    return display_name.strip() or None, address


def _normalize_email_tuple(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    normalized: list[str] = []
    for index, value in enumerate(values, start=1):
        _, address = _normalize_email(value, f"{label}[{index}]")
        normalized.append(address)
    return tuple(normalized)


def _normalize_headers(headers: dict[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for name, value in headers.items():
        header_name = str(name).strip()
        header_value = str(value).strip()
        _reject_crlf("header name", header_name)
        _reject_crlf(f"header {header_name}", header_value)
        if not header_name or ":" in header_name or not _HEADER_NAME_RE.match(header_name):
            raise OutboundValidationError("Header names must be non-empty RFC field names.")
        normalized[header_name] = header_value
    return normalized


def _normalize_attachments(attachments: tuple[OutboundAttachment, ...]) -> tuple[OutboundAttachment, ...]:
    normalized: list[OutboundAttachment] = []
    for index, attachment in enumerate(attachments, start=1):
        path = Path(attachment.path).expanduser().resolve()
        if not path.exists() or not path.is_file():
            raise OutboundValidationError(f"Attachment {index} must be an existing file: {attachment.path}")

        filename = attachment.filename or path.name
        filename = Path(filename).name.strip()
        _reject_crlf("attachment filename", filename)
        if not filename:
            raise OutboundValidationError(f"Attachment {index} filename is required.")

        mime_type = attachment.mime_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        _reject_crlf("attachment MIME type", mime_type)
        if "/" not in mime_type:
            raise OutboundValidationError(f"Attachment {index} MIME type must include a slash.")

        normalized.append(OutboundAttachment(path=path, filename=filename, mime_type=mime_type))
    return tuple(normalized)


def normalize_outbound_message(message: OutboundMessage) -> OutboundMessage:
    display_from_name, from_email = _normalize_email(message.from_email, "from_email")
    from_name = str(message.from_name).strip() if message.from_name else display_from_name
    _reject_crlf("from_name", from_name)

    to = _normalize_email_tuple(message.to, "to")
    if not to:
        raise OutboundValidationError("At least one to recipient is required.")

    cc = _normalize_email_tuple(message.cc, "cc")
    bcc = _normalize_email_tuple(message.bcc, "bcc")
    reply_to = _normalize_email_tuple(message.reply_to, "reply_to")

    subject = str(message.subject).strip() if message.subject is not None else ""
    _reject_crlf("subject", subject)
    if not subject:
        raise OutboundValidationError("Subject is required.")

    text = str(message.text) if message.text is not None else None
    html = str(message.html) if message.html is not None else None
    if text is not None and not text.strip():
        text = None
    if html is not None and not html.strip():
        html = None
    if text is None and html is None:
        raise OutboundValidationError("At least one of text or html is required.")

    in_reply_to = message.in_reply_to.strip() if message.in_reply_to else None
    _reject_crlf("in_reply_to", in_reply_to)
    references = tuple(reference.strip() for reference in message.references if reference and reference.strip())
    for reference in references:
        _reject_crlf("references", reference)

    source_document_id = message.source_document_id.strip() if message.source_document_id else None
    _reject_crlf("source_document_id", source_document_id)
    idempotency_key = message.idempotency_key.strip() if message.idempotency_key else None
    _reject_crlf("idempotency_key", idempotency_key)

    return replace(
        message,
        from_email=from_email,
        from_name=from_name,
        to=to,
        cc=cc,
        bcc=bcc,
        reply_to=reply_to,
        subject=subject,
        text=text,
        html=html,
        in_reply_to=in_reply_to,
        references=references,
        headers=_normalize_headers(message.headers),
        attachments=_normalize_attachments(message.attachments),
        source_document_id=source_document_id,
        idempotency_key=idempotency_key,
    )


def build_outbound_mime(message: OutboundMessage, *, include_bcc: bool = False) -> EmailMessage:
    normalized = normalize_outbound_message(message)
    mime_message = EmailMessage()
    mime_message["From"] = (
        formataddr((normalized.from_name, normalized.from_email)) if normalized.from_name else normalized.from_email
    )
    mime_message["To"] = ", ".join(normalized.to)
    if normalized.cc:
        mime_message["Cc"] = ", ".join(normalized.cc)
    if include_bcc and normalized.bcc:
        mime_message["Bcc"] = ", ".join(normalized.bcc)
    if normalized.reply_to:
        mime_message["Reply-To"] = ", ".join(normalized.reply_to)
    mime_message["Subject"] = normalized.subject
    mime_message["Date"] = formatdate(localtime=False)
    mime_message["Message-ID"] = make_msgid(domain=normalized.from_email.split("@", 1)[1])
    if normalized.in_reply_to:
        mime_message["In-Reply-To"] = normalized.in_reply_to
    if normalized.references:
        mime_message["References"] = " ".join(normalized.references)
    for name, value in normalized.headers.items():
        mime_message[name] = value

    if normalized.text is not None and normalized.html is not None:
        mime_message.set_content(normalized.text)
        mime_message.add_alternative(normalized.html, subtype="html")
    elif normalized.html is not None:
        mime_message.set_content(normalized.html, subtype="html")
    else:
        mime_message.set_content(normalized.text or "")

    for attachment in normalized.attachments:
        maintype, subtype = (attachment.mime_type or "application/octet-stream").split("/", 1)
        mime_message.add_attachment(
            Path(attachment.path).read_bytes(),
            maintype=maintype,
            subtype=subtype,
            filename=attachment.filename,
        )

    return mime_message


def outbound_envelope_recipients(message: OutboundMessage) -> tuple[str, ...]:
    normalized = normalize_outbound_message(message)
    return (*normalized.to, *normalized.cc, *normalized.bcc)


def outbound_metadata(message: OutboundMessage, mime_message: EmailMessage) -> dict[str, Any]:
    normalized = normalize_outbound_message(message)
    metadata: dict[str, Any] = {
        "message_id": mime_message.get("Message-ID"),
        "headers": normalized.headers,
        "references": list(normalized.references),
    }
    if normalized.in_reply_to:
        metadata["in_reply_to"] = normalized.in_reply_to
    if normalized.attachments:
        metadata["attachments"] = [
            {
                "filename": attachment.filename,
                "mime_type": attachment.mime_type,
            }
            for attachment in normalized.attachments
        ]
    return metadata


def send_result_from_record(record: OutboundMessageRecord) -> SendResult:
    return SendResult(
        id=record.id,
        status=record.status,
        provider=record.provider,
        provider_message_id=record.provider_message_id,
        error=record.error,
    )
