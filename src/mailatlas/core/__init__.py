from .models import (
    DocumentRecord,
    DocumentRef,
    ImapFolderSyncResult,
    ImapSyncConfig,
    ImapSyncResult,
    NormalizedDocument,
    OutboundAttachment,
    OutboundMessage,
    OutboundMessageRecord,
    OutboundMessageRef,
    ParsedAsset,
    ParserConfig,
    SendConfig,
    SendResult,
    StoredAsset,
    StoredOutboundAttachment,
)
from .parsing import parse_eml
from .service import MailAtlas
from .storage import WorkspaceStore
from .gmail_auth import GMAIL_SEND_SCOPE, GmailAuthConfig, gmail_auth_logout, gmail_auth_status, run_gmail_auth_flow
from .mcp_tools import MailAtlasMcpTools, mcp_send_enabled, mcp_tool_names

__all__ = [
    "DocumentRecord",
    "DocumentRef",
    "ImapFolderSyncResult",
    "ImapSyncConfig",
    "ImapSyncResult",
    "MailAtlas",
    "MailAtlasMcpTools",
    "NormalizedDocument",
    "OutboundAttachment",
    "OutboundMessage",
    "OutboundMessageRecord",
    "OutboundMessageRef",
    "ParsedAsset",
    "ParserConfig",
    "SendConfig",
    "SendResult",
    "StoredAsset",
    "StoredOutboundAttachment",
    "WorkspaceStore",
    "GMAIL_SEND_SCOPE",
    "GmailAuthConfig",
    "gmail_auth_logout",
    "gmail_auth_status",
    "mcp_send_enabled",
    "mcp_tool_names",
    "parse_eml",
    "run_gmail_auth_flow",
]
