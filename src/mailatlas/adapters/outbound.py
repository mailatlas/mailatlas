from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ProviderSendResult:
    status: str
    provider_message_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
