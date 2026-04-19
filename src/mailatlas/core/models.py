from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ParsedAsset:
    kind: str
    mime_type: str
    filename: str
    sha256: str
    cid: str | None = None
    content_bytes: bytes = field(default=b"", repr=False)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("content_bytes", None)
        return payload


@dataclass(frozen=True)
class ParserConfig:
    strip_forwarded_headers: bool = True
    strip_boilerplate: bool = True
    strip_link_only_lines: bool = True
    stop_at_footer: bool = True
    strip_invisible_chars: bool = True
    normalize_whitespace: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "ParserConfig":
        if not value:
            return cls()
        return cls(**value)


@dataclass(frozen=True)
class _ImapReceiveConfig:
    host: str
    username: str
    port: int = 993
    auth: str = "password"
    password: str | None = field(default=None, repr=False)
    access_token: str | None = field(default=None, repr=False)
    folders: tuple[str, ...] = ("INBOX",)
    parser_config: ParserConfig = field(default_factory=ParserConfig)

    def __post_init__(self) -> None:
        normalized_host = self.host.strip()
        normalized_username = self.username.strip()
        normalized_auth = self.auth.strip().lower()
        normalized_folders = tuple(folder.strip() for folder in self.folders if folder and folder.strip()) or ("INBOX",)

        if not normalized_host:
            raise ValueError("IMAP host is required.")
        if not normalized_username:
            raise ValueError("IMAP username is required.")
        if normalized_auth not in {"password", "xoauth2"}:
            raise ValueError("IMAP auth must be 'password' or 'xoauth2'.")
        if normalized_auth == "password" and not self.password:
            raise ValueError("IMAP password is required for password auth.")
        if normalized_auth == "xoauth2" and not self.access_token:
            raise ValueError("IMAP access token is required for xoauth2 auth.")

        object.__setattr__(self, "host", normalized_host)
        object.__setattr__(self, "username", normalized_username)
        object.__setattr__(self, "auth", normalized_auth)
        object.__setattr__(self, "folders", normalized_folders)

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "auth": self.auth,
            "folders": list(self.folders),
            "parser_config": self.parser_config.to_dict(),
        }


def _string_tuple(value: str | tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(value)


@dataclass(frozen=True)
class OutboundAttachment:
    path: str | Path
    filename: str | None = None
    mime_type: str | None = None


@dataclass(frozen=True)
class OutboundMessage:
    from_email: str
    to: tuple[str, ...]
    subject: str
    text: str | None = None
    html: str | None = None
    from_name: str | None = None
    cc: tuple[str, ...] = ()
    bcc: tuple[str, ...] = ()
    reply_to: tuple[str, ...] = ()
    in_reply_to: str | None = None
    references: tuple[str, ...] = ()
    headers: dict[str, str] = field(default_factory=dict)
    attachments: tuple[OutboundAttachment, ...] = ()
    source_document_id: str | None = None
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "from_email", str(self.from_email).strip() if self.from_email is not None else "")
        object.__setattr__(self, "to", _string_tuple(self.to))
        object.__setattr__(self, "cc", _string_tuple(self.cc))
        object.__setattr__(self, "bcc", _string_tuple(self.bcc))
        object.__setattr__(self, "reply_to", _string_tuple(self.reply_to))
        object.__setattr__(self, "references", _string_tuple(self.references))
        object.__setattr__(self, "headers", dict(self.headers))
        object.__setattr__(self, "attachments", tuple(self.attachments))


@dataclass(frozen=True)
class SendConfig:
    provider: str
    dry_run: bool = False
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = field(default=None, repr=False)
    smtp_password: str | None = field(default=None, repr=False)
    smtp_starttls: bool = True
    smtp_ssl: bool = False
    cloudflare_account_id: str | None = None
    cloudflare_api_token: str | None = field(default=None, repr=False)
    cloudflare_api_base: str | None = None
    gmail_access_token: str | None = field(default=None, repr=False)
    gmail_api_base: str | None = None
    gmail_user_id: str = "me"

    def __post_init__(self) -> None:
        provider = self.provider.strip().lower()
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "smtp_host", self.smtp_host.strip() if self.smtp_host else None)
        object.__setattr__(self, "cloudflare_account_id", self.cloudflare_account_id.strip() if self.cloudflare_account_id else None)
        object.__setattr__(self, "cloudflare_api_base", self.cloudflare_api_base.rstrip("/") if self.cloudflare_api_base else None)
        object.__setattr__(self, "gmail_api_base", self.gmail_api_base.rstrip("/") if self.gmail_api_base else None)
        object.__setattr__(self, "gmail_user_id", self.gmail_user_id.strip() if self.gmail_user_id else "me")

        if provider not in {"smtp", "cloudflare", "gmail"}:
            raise ValueError("Send provider must be 'smtp', 'cloudflare', or 'gmail'.")
        if self.smtp_port < 1 or self.smtp_port > 65535:
            raise ValueError("SMTP port must be between 1 and 65535.")
        if self.smtp_starttls and self.smtp_ssl:
            raise ValueError("Choose either SMTP STARTTLS or SMTP SSL, not both.")


@dataclass(frozen=True)
class SendResult:
    id: str
    status: str
    provider: str
    provider_message_id: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReceiveConfig:
    provider: str = "gmail"
    account_id: str | None = None
    gmail_access_token: str | None = field(default=None, repr=False)
    gmail_api_base: str | None = None
    gmail_user_id: str = "me"
    gmail_label: str = "INBOX"
    gmail_query: str | None = None
    gmail_include_spam_trash: bool = False
    token_store: str | None = None
    token_file: str | None = None
    limit: int = 50
    full_sync: bool = False
    imap_host: str | None = None
    imap_port: int = 993
    imap_username: str | None = None
    imap_auth: str | None = None
    imap_password: str | None = field(default=None, repr=False)
    imap_access_token: str | None = field(default=None, repr=False)
    imap_folders: str | tuple[str, ...] | list[str] = ("INBOX",)
    parser_config: ParserConfig = field(default_factory=ParserConfig)

    def __post_init__(self) -> None:
        provider = self.provider.strip().lower()
        account_id = self.account_id.strip() if self.account_id else None
        gmail_api_base = self.gmail_api_base.rstrip("/") if self.gmail_api_base else None
        gmail_user_id = self.gmail_user_id.strip() if self.gmail_user_id else "me"
        gmail_label = self.gmail_label.strip() if self.gmail_label else "INBOX"
        gmail_query = self.gmail_query.strip() if self.gmail_query and self.gmail_query.strip() else None
        token_store = self.token_store.strip() if self.token_store and self.token_store.strip() else None
        token_file = self.token_file.strip() if self.token_file and self.token_file.strip() else None
        imap_host = self.imap_host.strip() if self.imap_host and self.imap_host.strip() else None
        imap_username = self.imap_username.strip() if self.imap_username and self.imap_username.strip() else None
        imap_auth = self.imap_auth.strip().lower() if self.imap_auth and self.imap_auth.strip() else None
        imap_folders = tuple(folder.strip() for folder in _string_tuple(self.imap_folders) if folder and folder.strip()) or ("INBOX",)

        if provider not in {"gmail", "imap"}:
            raise ValueError("Receive provider must be 'gmail' or 'imap'.")
        if self.limit < 1 or self.limit > 500:
            raise ValueError("Receive limit must be between 1 and 500.")
        if self.imap_port < 1 or self.imap_port > 65535:
            raise ValueError("IMAP port must be between 1 and 65535.")
        if imap_auth is not None and imap_auth not in {"password", "xoauth2"}:
            raise ValueError("IMAP auth must be 'password' or 'xoauth2'.")
        if self.imap_password and self.imap_access_token:
            raise ValueError("Choose either IMAP password auth or IMAP access-token auth, not both.")
        if imap_auth is None:
            imap_auth = "xoauth2" if self.imap_access_token else "password"

        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "account_id", account_id)
        object.__setattr__(self, "gmail_api_base", gmail_api_base)
        object.__setattr__(self, "gmail_user_id", gmail_user_id)
        object.__setattr__(self, "gmail_label", gmail_label)
        object.__setattr__(self, "gmail_query", gmail_query)
        object.__setattr__(self, "token_store", token_store)
        object.__setattr__(self, "token_file", token_file)
        object.__setattr__(self, "imap_host", imap_host)
        object.__setattr__(self, "imap_username", imap_username)
        object.__setattr__(self, "imap_auth", imap_auth)
        object.__setattr__(self, "imap_folders", imap_folders)

    def to_safe_dict(self) -> dict[str, Any]:
        payload = {
            "provider": self.provider,
            "account_id": self.account_id,
            "limit": self.limit,
            "full_sync": self.full_sync,
            "parser_config": self.parser_config.to_dict(),
        }
        if self.provider == "imap":
            payload.update(
                {
                    "imap_host": self.imap_host,
                    "imap_port": self.imap_port,
                    "imap_username": self.imap_username,
                    "imap_auth": self.imap_auth,
                    "imap_folders": list(self.imap_folders),
                }
            )
        else:
            payload.update(
                {
                    "gmail_api_base": self.gmail_api_base,
                    "gmail_user_id": self.gmail_user_id,
                    "gmail_label": self.gmail_label,
                    "gmail_query": self.gmail_query,
                    "gmail_include_spam_trash": self.gmail_include_spam_trash,
                    "token_store": self.token_store,
                    "token_file": self.token_file,
                }
            )
        return payload


@dataclass(frozen=True)
class ReceiveResult:
    status: str
    provider: str
    account_id: str
    fetched_count: int
    ingested_count: int
    duplicate_count: int
    error_count: int
    document_ids: tuple[str, ...]
    cursor: dict[str, object]
    run_id: str
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["document_ids"] = list(self.document_ids)
        if not self.details:
            payload.pop("details", None)
        return payload


@dataclass(frozen=True)
class ReceiveAccount:
    id: str
    provider: str
    email: str | None
    label: str | None
    query: str | None
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReceiveCursor:
    account_id: str
    provider: str
    cursor_json: dict[str, object]
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReceiveRun:
    id: str
    account_id: str
    provider: str
    status: str
    started_at: str
    finished_at: str | None
    fetched_count: int
    ingested_count: int
    duplicate_count: int
    error_count: int
    error: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OutboundMessageRef:
    id: str
    status: str
    provider: str
    from_email: str
    to: tuple[str, ...]
    subject: str
    created_at: str
    sent_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["to"] = list(self.to)
        return payload


@dataclass(frozen=True)
class StoredOutboundAttachment:
    id: str
    outbound_id: str
    ordinal: int
    filename: str
    mime_type: str
    file_path: str
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OutboundMessageRecord:
    id: str
    status: str
    provider: str
    provider_message_id: str | None
    from_email: str
    from_name: str | None
    to: tuple[str, ...]
    cc: tuple[str, ...]
    bcc: tuple[str, ...]
    reply_to: tuple[str, ...]
    subject: str
    text_path: str | None
    html_path: str | None
    raw_path: str
    source_document_id: str | None
    metadata: dict[str, Any]
    created_at: str
    sent_at: str | None
    error: str | None
    attachments: tuple[StoredOutboundAttachment, ...] = ()

    def to_dict(self, *, include_bcc: bool = True) -> dict[str, Any]:
        payload = asdict(self)
        payload["to"] = list(self.to)
        payload["cc"] = list(self.cc)
        payload["reply_to"] = list(self.reply_to)
        payload["attachments"] = [attachment.to_dict() for attachment in self.attachments]
        payload["bcc"] = list(self.bcc) if include_bcc else []
        return payload


@dataclass
class NormalizedDocument:
    source_kind: str
    message_id: str | None
    thread_id: str | None
    subject: str
    sender_name: str | None
    sender_email: str | None
    author: str | None
    received_at: str | None
    published_at: str | None
    body_text: str
    body_html: str | None
    content_hash: str
    metadata: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    assets: list[ParsedAsset] = field(default_factory=list)
    raw_bytes: bytes = field(default=b"", repr=False)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["assets"] = [asset.to_dict() for asset in self.assets]
        payload.pop("raw_bytes", None)
        return payload


@dataclass
class StoredAsset:
    id: str
    document_id: str
    ordinal: int
    kind: str
    mime_type: str
    file_path: str
    cid: str | None
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DocumentRecord:
    id: str
    source_kind: str
    message_id: str | None
    thread_id: str | None
    subject: str
    sender_name: str | None
    sender_email: str | None
    author: str | None
    received_at: str | None
    published_at: str | None
    body_text: str
    body_html_path: str | None
    raw_path: str
    content_hash: str
    metadata: dict[str, Any]
    created_at: str
    assets: list[StoredAsset] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["assets"] = [asset.to_dict() for asset in self.assets]
        return payload


@dataclass
class DocumentRef:
    id: str
    subject: str
    source_kind: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ImapSyncState:
    host: str
    port: int
    username: str
    folder: str
    uidvalidity: str | None
    last_uid: int
    last_synced_at: str
    status: str
    error: str | None


@dataclass
class _ImapFolderReceiveResult:
    folder: str
    status: str
    uidvalidity: str | None
    last_uid: int
    fetched_count: int
    ingested_count: int
    duplicate_count: int
    document_refs: list[DocumentRef] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["document_refs"] = [reference.to_dict() for reference in self.document_refs]
        return payload


@dataclass
class _ImapReceiveResult:
    host: str
    port: int
    username: str
    auth: str
    folders: list[_ImapFolderReceiveResult] = field(default_factory=list)

    @property
    def status(self) -> str:
        return "error" if self.has_errors() else "ok"

    def has_errors(self) -> bool:
        return any(folder.status == "error" for folder in self.folders)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "auth": self.auth,
            "folder_count": len(self.folders),
            "error_count": sum(1 for folder in self.folders if folder.status == "error"),
            "fetched_count": sum(folder.fetched_count for folder in self.folders),
            "ingested_count": sum(folder.ingested_count for folder in self.folders),
            "duplicate_count": sum(folder.duplicate_count for folder in self.folders),
            "folders": [folder.to_dict() for folder in self.folders],
        }
