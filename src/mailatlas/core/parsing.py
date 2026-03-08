from __future__ import annotations

import hashlib
import re
import unicodedata
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

from .models import NormalizedDocument, ParsedAsset, ParserConfig


FORWARD_MARKERS = (
    "---------- forwarded message ---------",
    "begin forwarded message:",
)
HEADER_PREFIXES = ("from:", "date:", "subject:", "to:", "cc:", "bcc:", "reply-to:")
LINK_ONLY_RE = re.compile(r"^<?https?://\S+>?$", re.IGNORECASE)
LINE_DROP_PREFIXES = (
    "forwarded this email? subscribe here",
    "read in app",
    "upgrade to paid",
    "keep reading with a",
    "start trial",
    "a subscription gets you:",
    "subscriber-only posts and full archive",
    "post comments and join the community",
)
LINE_DROP_EXACT = {"like", "comment", "restack", "preview"}
FOOTER_MARKERS = ("unsubscribe", "©", "(c)", "copyright", "[image:")


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []

    def handle_data(self, data: str) -> None:
        normalized = data.strip()
        if normalized:
            self._chunks.append(normalized)

    def get_text(self) -> str:
        return "\n".join(self._chunks)


def _html_to_text(html: str) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(html)
    return parser.get_text()


def _clean_subject(subject: str | None) -> str:
    value = subject or "Untitled email"
    return re.sub(r"^(?:\s*(?:fwd?|fw):\s*)+", "", value, flags=re.IGNORECASE).strip() or "Untitled email"


def _parse_timestamp(header_value: str | None) -> str | None:
    if not header_value:
        return None
    try:
        parsed = parsedate_to_datetime(header_value)
    except (TypeError, ValueError, IndexError):
        return None
    return parsed.isoformat()


def _guess_thread_id(message: EmailMessage) -> str | None:
    return (
        message.get("Thread-Index")
        or message.get("X-GM-THRID")
        or message.get("Thread-Topic")
        or message.get("In-Reply-To")
        or message.get("References")
    )


def _extract_body(message: EmailMessage) -> tuple[str, str | None]:
    text_parts: list[str] = []
    html_parts: list[str] = []

    if message.is_multipart():
        for part in message.walk():
            content_disposition = str(part.get_content_disposition() or "")
            content_type = part.get_content_type()
            if "attachment" in content_disposition:
                continue

            if content_type == "text/plain":
                text_parts.append(part.get_content())
            elif content_type == "text/html":
                html_parts.append(part.get_content())
    else:
        content_type = message.get_content_type()
        payload = message.get_content()
        if content_type == "text/html":
            html_parts.append(payload)
        else:
            text_parts.append(payload)

    html_body = "\n".join(part for part in html_parts if part.strip()) or None
    text_body = "\n".join(part for part in text_parts if part.strip())

    if not text_body and html_body:
        text_body = _html_to_text(html_body)

    return text_body.strip(), html_body


def _extract_assets(message: EmailMessage) -> list[ParsedAsset]:
    assets: list[ParsedAsset] = []

    for part in message.walk():
        if part.is_multipart():
            continue

        disposition = str(part.get_content_disposition() or "")
        content_type = part.get_content_type()
        maintype = part.get_content_maintype()

        if maintype != "image" and "attachment" not in disposition and "inline" not in disposition:
            continue

        payload = part.get_payload(decode=True)
        if not payload:
            continue

        filename = part.get_filename() or f"asset-{len(assets) + 1}.{content_type.split('/')[-1]}"
        cid = part.get("Content-ID")
        if cid:
            cid = cid.strip("<>")

        assets.append(
            ParsedAsset(
                kind="inline" if "inline" in disposition or cid else "attachment",
                mime_type=content_type,
                filename=filename,
                cid=cid,
                sha256=hashlib.sha256(payload).hexdigest(),
                content_bytes=payload,
            )
        )

    return assets


def _extract_forwarded_chain(body_text: str) -> list[dict[str, str | None]]:
    entries: list[dict[str, str | None]] = []
    lines = [line.strip() for line in body_text.splitlines()]

    for index, line in enumerate(lines):
        if line.lower() not in FORWARD_MARKERS:
            continue

        payload: dict[str, str | None] = {"from": None, "date": None, "subject": None}
        for nested in lines[index + 1 : index + 8]:
            lowered = nested.lower()
            if lowered.startswith("from:"):
                payload["from"] = nested.split(":", 1)[1].strip()
            elif lowered.startswith("date:"):
                payload["date"] = nested.split(":", 1)[1].strip()
            elif lowered.startswith("subject:"):
                payload["subject"] = nested.split(":", 1)[1].strip()

        if any(payload.values()):
            entries.append(payload)

    return entries


def _strip_invisible_chars(text: str) -> str:
    cleaned_chars: list[str] = []
    for char in text:
        if char in {"\n", "\r", "\t"}:
            cleaned_chars.append(char)
            continue
        if char in {"\u00ad", "\u034f"}:
            continue
        category = unicodedata.category(char)
        if category == "Cf":
            continue
        cleaned_chars.append(char)
    return "".join(cleaned_chars)


def _remove_forwarded_headers(lines: list[str]) -> tuple[list[str], bool]:
    for index, line in enumerate(lines):
        if line.strip().lower() not in FORWARD_MARKERS:
            continue

        end_index = index + 1
        while end_index < len(lines):
            stripped = lines[end_index].strip()
            lowered = stripped.lower()
            if not stripped:
                end_index += 1
                break
            if lowered.startswith(HEADER_PREFIXES):
                end_index += 1
                continue
            break

        cleaned_lines = lines[:index] + lines[end_index:]
        return cleaned_lines, True

    return lines, False


def _filter_boilerplate_lines(lines: list[str], config: ParserConfig) -> tuple[list[str], dict[str, int]]:
    cleaned_lines: list[str] = []
    dropped_lines = 0
    stopped_at_footer = 0
    suppress_for_more = False

    for line in lines:
        stripped = line.strip()
        lowered = stripped.lower()

        if config.stop_at_footer and lowered.startswith(FOOTER_MARKERS):
            stopped_at_footer = 1
            break

        if config.strip_link_only_lines and LINK_ONLY_RE.match(stripped):
            dropped_lines += 1
            continue

        if config.strip_boilerplate:
            if suppress_for_more and lowered == "for more":
                dropped_lines += 1
                suppress_for_more = False
                continue

            if lowered.startswith(LINE_DROP_PREFIXES) or lowered in LINE_DROP_EXACT:
                dropped_lines += 1
                suppress_for_more = lowered.startswith("forwarded this email? subscribe here")
                continue

        suppress_for_more = False
        cleaned_lines.append(line)

    return cleaned_lines, {"dropped_line_count": dropped_lines, "stopped_at_footer": stopped_at_footer}


def _normalize_lines(lines: list[str]) -> list[str]:
    normalized_lines: list[str] = []
    blank_run = 0

    for line in lines:
        stripped = re.sub(r"[ \t]+", " ", line).strip()
        if not stripped:
            blank_run += 1
            if blank_run > 1:
                continue
            normalized_lines.append("")
            continue
        blank_run = 0
        normalized_lines.append(stripped)

    return normalized_lines


def _clean_body_text(body_text: str, config: ParserConfig, forwarded_chain: list[dict[str, str | None]]) -> tuple[str, dict[str, int | bool]]:
    cleaned = body_text.replace("\r\n", "\n").replace("\r", "\n")
    notes: dict[str, int | bool] = {
        "removed_forwarded_headers": False,
        "dropped_line_count": 0,
        "stopped_at_footer": 0,
    }

    if config.strip_invisible_chars:
        cleaned = _strip_invisible_chars(cleaned)

    lines = cleaned.split("\n")

    if config.strip_forwarded_headers and forwarded_chain:
        lines, removed = _remove_forwarded_headers(lines)
        notes["removed_forwarded_headers"] = removed

    lines, filter_notes = _filter_boilerplate_lines(lines, config)
    notes["dropped_line_count"] = filter_notes["dropped_line_count"]
    notes["stopped_at_footer"] = filter_notes["stopped_at_footer"]

    if config.normalize_whitespace:
        lines = _normalize_lines(lines)

    return "\n".join(lines).strip(), notes


def _compute_author(sender_name: str | None, sender_email: str | None, forwarded_chain: list[dict[str, str | None]]) -> str | None:
    if forwarded_chain:
        forwarded_from = forwarded_chain[-1].get("from")
        if forwarded_from:
            return forwarded_from
    return sender_name or sender_email


def _compute_published_at(received_at: str | None, forwarded_chain: list[dict[str, str | None]]) -> str | None:
    if forwarded_chain:
        forwarded_date = _parse_timestamp(forwarded_chain[-1].get("date"))
        if forwarded_date:
            return forwarded_date
    return received_at


def _build_content_hash(
    subject: str,
    sender_email: str | None,
    body_text: str,
    html_body: str | None,
    assets: list[ParsedAsset],
) -> str:
    digest = hashlib.sha256()
    digest.update(subject.encode("utf-8"))
    digest.update((sender_email or "").encode("utf-8"))
    digest.update(body_text.encode("utf-8"))
    if html_body:
        digest.update(html_body.encode("utf-8"))
    for asset in assets:
        digest.update(asset.sha256.encode("utf-8"))
    return digest.hexdigest()


def parse_email_bytes(raw_bytes: bytes, source_kind: str = "eml", parser_config: ParserConfig | None = None) -> NormalizedDocument:
    config = parser_config or ParserConfig()
    message = BytesParser(policy=policy.default).parsebytes(raw_bytes)
    subject = _clean_subject(message.get("Subject"))
    sender_name, sender_email = parseaddr(message.get("From", ""))
    body_text, body_html = _extract_body(message)
    assets = _extract_assets(message)
    forwarded_chain = _extract_forwarded_chain(body_text)
    received_at = _parse_timestamp(message.get("Date"))
    cleaned_body_text, cleaning_notes = _clean_body_text(unescape(body_text), config, forwarded_chain)
    content_hash = _build_content_hash(subject, sender_email, cleaned_body_text, body_html, assets)

    metadata = {
        "headers": {
            "to": message.get("To"),
            "cc": message.get("Cc"),
            "bcc": message.get("Bcc"),
            "reply_to": message.get("Reply-To"),
            "content_type": message.get_content_type(),
        },
        "parser_config": config.to_dict(),
        "cleaning": cleaning_notes,
    }
    provenance = {
        "is_forwarded": bool(forwarded_chain),
        "forwarded_chain": forwarded_chain,
    }

    return NormalizedDocument(
        source_kind=source_kind,
        message_id=message.get("Message-ID"),
        thread_id=_guess_thread_id(message),
        subject=subject,
        sender_name=sender_name or None,
        sender_email=sender_email or None,
        author=_compute_author(sender_name or None, sender_email or None, forwarded_chain),
        received_at=received_at,
        published_at=_compute_published_at(received_at, forwarded_chain),
        body_text=cleaned_body_text,
        body_html=body_html,
        content_hash=content_hash,
        metadata=metadata,
        provenance=provenance,
        assets=assets,
        raw_bytes=raw_bytes,
    )


def parse_eml(path: str | Path, parser_config: ParserConfig | None = None) -> NormalizedDocument:
    resolved = Path(path).expanduser().resolve()
    return parse_email_bytes(resolved.read_bytes(), source_kind="eml", parser_config=parser_config)
