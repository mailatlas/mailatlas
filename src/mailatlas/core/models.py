from __future__ import annotations

from dataclasses import asdict, dataclass, field
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
class ImapSyncConfig:
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
class ImapFolderSyncResult:
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
class ImapSyncResult:
    host: str
    port: int
    username: str
    auth: str
    folders: list[ImapFolderSyncResult] = field(default_factory=list)

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
