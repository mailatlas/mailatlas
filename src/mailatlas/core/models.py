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
