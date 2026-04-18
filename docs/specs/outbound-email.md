# MailAtlas Outbound Email Spec

Status: draft
Created: 2026-04-18

## Summary

MailAtlas should support outbound email as part of a complete local email I/O layer for AI agents
and data applications. The feature should let applications and agents compose, send, inspect, and
audit email through configured providers without turning MailAtlas into a hosted deliverability
service or inbox client.

The product boundary changes from:

> MailAtlas is not a sending platform.

to:

> MailAtlas is not a hosted deliverability service or inbox client. MailAtlas is a local library and
> CLI for email ingestion, inspection, export, sending through configured providers, and outbound
> audit trails.

## Core Job

MailAtlas gives software direct, inspectable access to email artifacts. With outbound support, the
same local workspace can hold both inbound documents and outbound send records.

Primary workflows:

- ingest or sync email into a local workspace
- inspect and export stored documents
- compose an outbound message from explicit fields or generated content
- send through a configured provider
- keep a local audit record of what was attempted, sent, or failed
- expose the same capabilities through MCP and an agent skill with safety gates

## Goals

- Add a stable Python API for composing and sending email.
- Add a `mailatlas send` CLI command.
- Support at least one dependency-free provider path first.
- Add a first-class Gmail provider that uses the Gmail API with OAuth and the `gmail.send` scope.
- Keep Gmail SMTP app passwords as an advanced compatibility path, not the recommended Gmail path.
- Store outbound attempts and results in the MailAtlas workspace.
- Avoid persisting provider secrets.
- Preserve enough outbound metadata for audit, retries, and agent reporting.
- Make MCP send operations draft-first and gated by explicit runtime configuration.
- Keep provider adapters narrow so Gmail, Cloudflare, SMTP, and future services can share one public model.

## Non-Goals

- MailAtlas will not become a hosted email service.
- MailAtlas will not manage DNS, SPF, DKIM, DMARC, reputation, or bounce processing.
- MailAtlas will not ask for or store Google account passwords.
- MailAtlas will not make Gmail app passwords the recommended Gmail integration path.
- MailAtlas will not run OAuth browser flows implicitly during `mailatlas send`.
- MailAtlas will not store OAuth refresh tokens in the MailAtlas workspace or SQLite database.
- MailAtlas will not operate a hosted OAuth callback, hosted token broker, or hosted credential vault.
- MailAtlas will not manage Google Cloud project creation, OAuth consent-screen publishing, or Google
  app verification for users.
- MailAtlas will not provide a background sending daemon in the first version.
- MailAtlas will not expose autonomous MCP sending by default.
- MailAtlas will not promise delivery status beyond what the provider returns synchronously.

## Public Surface

### Python API

New models:

```python
from mailatlas import (
    OutboundAttachment,
    OutboundMessage,
    OutboundMessageRecord,
    OutboundMessageRef,
    SendConfig,
    SendResult,
)
```

Proposed model shape:

```python
from dataclasses import dataclass, field
from pathlib import Path

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

@dataclass(frozen=True)
class SendConfig:
    provider: str
    dry_run: bool = False
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_starttls: bool = True
    smtp_ssl: bool = False
    cloudflare_account_id: str | None = None
    cloudflare_api_token: str | None = None
    cloudflare_api_base: str | None = None
    gmail_access_token: str | None = None
    gmail_api_base: str | None = None
    gmail_user_id: str = "me"

@dataclass(frozen=True)
class SendResult:
    id: str
    status: str
    provider: str
    provider_message_id: str | None = None
    error: str | None = None

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
    metadata: dict[str, object]
    created_at: str
    sent_at: str | None
    error: str | None
```

New `MailAtlas` methods:

```python
atlas.draft_email(message: OutboundMessage) -> SendResult
atlas.send_email(message: OutboundMessage, config: SendConfig) -> SendResult
atlas.list_outbound(query: str | None = None) -> list[OutboundMessageRef]
atlas.get_outbound(outbound_id: str) -> OutboundMessageRecord
```

`draft_email(...)` stores a local draft record and rendered `.eml` snapshot without contacting a
provider. `send_email(...)` validates, stores, sends, and updates the outbound record.

### CLI

Add a new top-level command:

```bash
mailatlas send \
  --to user@example.com \
  --from agent@example.com \
  --subject "Build complete" \
  --text "The build passed."
```

Body input:

```bash
mailatlas send --text "Plain body"
mailatlas send --text-file body.txt
mailatlas send --html-file body.html
```

Attachments:

```bash
mailatlas send \
  --to user@example.com \
  --from agent@example.com \
  --subject "Report" \
  --text-file report-summary.txt \
  --attach report.pdf
```

Provider selection:

```bash
MAILATLAS_SEND_PROVIDER=smtp mailatlas send ...
MAILATLAS_SEND_PROVIDER=cloudflare mailatlas send ...
MAILATLAS_SEND_PROVIDER=gmail mailatlas send ...
```

Useful flags:

- `--provider`: override `MAILATLAS_SEND_PROVIDER`
- `--from`: sender address
- `--from-name`: display name
- `--to`: repeatable recipient
- `--cc`: repeatable recipient
- `--bcc`: repeatable envelope recipient
- `--reply-to`: repeatable reply-to address
- `--subject`: message subject
- `--text`: inline text body
- `--text-file`: text body file
- `--html-file`: HTML body file
- `--attach`: repeatable file attachment
- `--header`: repeatable `Name: value` header
- `--in-reply-to`: message id for replies
- `--references`: repeatable message id references
- `--source-document-id`: optional inbound document link
- `--idempotency-key`: caller-provided retry key
- `--dry-run`: build and store the message without sending
- `--gmail-access-token`: Gmail API OAuth access token for one-off sends
- `--gmail-user-id`: Gmail API user id; defaults to `me`

Recommended Gmail path:

```bash
MAILATLAS_SEND_PROVIDER=gmail \
MAILATLAS_GMAIL_ACCESS_TOKEN="$GMAIL_ACCESS_TOKEN" \
mailatlas send \
  --from user@gmail.com \
  --to user@gmail.com \
  --subject "Gmail API test" \
  --text "Sent with the Gmail API and gmail.send scope."
```

Gmail SMTP app-password compatibility path:

```bash
MAILATLAS_SEND_PROVIDER=smtp \
MAILATLAS_SMTP_HOST=smtp.gmail.com \
MAILATLAS_SMTP_PORT=587 \
MAILATLAS_SMTP_USERNAME=user@gmail.com \
MAILATLAS_SMTP_PASSWORD="$GOOGLE_APP_PASSWORD" \
mailatlas send \
  --from user@gmail.com \
  --to user@gmail.com \
  --subject "Gmail SMTP compatibility test" \
  --text "Sent with Gmail SMTP and an app password."
```

Public docs must describe Gmail SMTP app passwords as a local testing or compatibility option, not
the preferred Gmail integration.

The command prints JSON:

```json
{
  "status": "sent",
  "id": "<outbound-id>",
  "provider": "smtp",
  "provider_message_id": "<provider-id-or-null>",
  "error": null
}
```

### Environment Variables

Common:

- `MAILATLAS_SEND_PROVIDER`: `smtp`, `cloudflare`, or `gmail`

SMTP:

- `MAILATLAS_SMTP_HOST`
- `MAILATLAS_SMTP_PORT`
- `MAILATLAS_SMTP_USERNAME`
- `MAILATLAS_SMTP_PASSWORD`
- `MAILATLAS_SMTP_STARTTLS`
- `MAILATLAS_SMTP_SSL`

Cloudflare:

- `MAILATLAS_CLOUDFLARE_ACCOUNT_ID`
- `MAILATLAS_CLOUDFLARE_API_TOKEN`
- `MAILATLAS_CLOUDFLARE_API_BASE`

Gmail API:

- `MAILATLAS_GMAIL_ACCESS_TOKEN`
- `MAILATLAS_GMAIL_API_BASE`
- `MAILATLAS_GMAIL_USER_ID`

Future Gmail OAuth credential UX:

- `MAILATLAS_GMAIL_CLIENT_ID`
- `MAILATLAS_GMAIL_CLIENT_SECRET`
- `MAILATLAS_GMAIL_TOKEN_STORE`: `keychain`, `env`, or an explicit token file path
- `MAILATLAS_GMAIL_SCOPES`: defaults to `https://www.googleapis.com/auth/gmail.send`

MCP:

- `MAILATLAS_MCP_ALLOW_SEND`: send tools are disabled unless this is set to `1`

Secrets and OAuth tokens must only be read from environment variables, CLI arguments, explicit
`SendConfig` values, or a future explicit Gmail auth store. They must not be persisted in SQLite,
raw snapshots, logs, or JSON output. Future refresh-token storage must prefer the operating-system
keychain. If a keychain is unavailable, MailAtlas should require an explicit token path outside the
MailAtlas workspace and warn that the file is sensitive.

## Provider Adapters

### SMTP Adapter

The first implementation should use the Python standard library:

- `smtplib`
- `ssl`
- `email.message.EmailMessage`
- `mimetypes`

Required behavior:

- support SMTP over STARTTLS
- support SMTP over SSL
- support anonymous SMTP only when no username or password is configured
- support Gmail SMTP with app passwords as a documented compatibility path
- send BCC recipients in the SMTP envelope but omit the `Bcc` header from the MIME message
- return `sent` when `send_message` completes
- return `error` and persist the error message when the provider call fails

Gmail-specific positioning:

- Gmail SMTP app passwords are acceptable for local testing and compatibility.
- Gmail SMTP app passwords are not the recommended Gmail integration for public docs, agent
  workflows, or hosted applications.
- Docs must instruct users to revoke Gmail app passwords after tests when they do not need the
  compatibility path anymore.

### Gmail API Adapter

The Gmail adapter should use the Gmail API with no required third-party dependency. Use
`urllib.request` unless a project dependency is added deliberately.

Recommended authorization:

- Use OAuth 2.0 and the narrow `https://www.googleapis.com/auth/gmail.send` scope.
- Accept a caller-provided access token in `SendConfig` or `MAILATLAS_GMAIL_ACCESS_TOKEN` first.
- A later `mailatlas auth gmail` command may run an explicit installed-app OAuth flow and store a
  refresh token outside the MailAtlas workspace.

Required behavior:

- render the existing `OutboundMessage` model into an RFC 2822 MIME message
- base64url-encode the MIME bytes into the Gmail API `raw` field
- call `users.messages.send` at `POST /gmail/v1/users/{userId}/messages/send`
- default `userId` to `me`
- return `sent` when Gmail returns a successful `Message` response
- store Gmail's response `id`, `threadId`, and label metadata in `metadata_json` when returned
- expose Gmail's returned message `id` as `provider_message_id`
- return `error` and persist the error message when Gmail returns an HTTP error
- never persist the OAuth access token or refresh token

Gmail `from_email` rules:

- For personal Gmail, `from_email` must match the authenticated Gmail account or a Gmail-configured
  send-as alias.
- MailAtlas should surface Gmail's provider error when the authenticated account cannot use the
  requested `from_email`.

Gmail BCC rule:

- The Gmail API does not provide an SMTP-style envelope separate from the raw MIME payload.
- The local workspace raw snapshot must continue to omit the `Bcc` header.
- Until provider-only transient MIME rendering is implemented, Gmail sends with non-empty `bcc`
  should fail with a clear error explaining that Gmail API BCC support is not available yet.
- When Gmail API BCC support is implemented, it must use a provider-only transient MIME payload that
  includes `Bcc` only for Gmail delivery while preserving a Bcc-free local raw snapshot.

OAuth credential UX:

```bash
mailatlas auth gmail
mailatlas auth status gmail
mailatlas auth logout gmail
```

`mailatlas auth gmail` should be explicit and interactive. It should not run during `mailatlas send`
unless the user invokes an auth command first. The command should:

- request the `gmail.send` scope by default
- support caller-provided OAuth client id and secret
- store refresh tokens in the operating-system keychain when available
- avoid writing refresh tokens to `.mailatlas` or `store.db`
- print the signed-in Gmail address and granted scopes, not token values

### Cloudflare Adapter

The Cloudflare adapter should use Cloudflare Email Service's REST API with no required third-party
dependency. Use `urllib.request` unless a project dependency is added deliberately.

Required behavior:

- read account id and API token from `SendConfig` or environment variables
- send text, HTML, headers, and attachments if the current Cloudflare API supports them
- store provider response metadata in `metadata_json`
- expose provider message id or synchronous delivery status when Cloudflare returns it

Implementation note: verify the current official Cloudflare endpoint and response shape at build
time. The public beta API may change before general availability.

### Future Adapters

The adapter contract should allow later providers without changing `OutboundMessage`:

- Resend
- SendGrid
- Postmark
- local `.eml` drop directory

Do not add these providers until Gmail API, SMTP, and Cloudflare are stable.

## Storage

Add outbound storage to the existing workspace. Proposed paths:

- `outbound/raw/<outbound-id>.eml`
- `outbound/text/<outbound-id>.txt`
- `outbound/html/<outbound-id>.html`
- `outbound/attachments/<outbound-id>/<ordinal>-<filename>`

Add SQLite tables:

```sql
CREATE TABLE IF NOT EXISTS outbound_messages (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    provider_message_id TEXT,
    idempotency_key TEXT,
    status TEXT NOT NULL,
    from_email TEXT NOT NULL,
    from_name TEXT,
    to_json TEXT NOT NULL,
    cc_json TEXT NOT NULL,
    bcc_json TEXT NOT NULL,
    reply_to_json TEXT NOT NULL,
    subject TEXT NOT NULL,
    text_path TEXT,
    html_path TEXT,
    raw_path TEXT NOT NULL,
    source_document_id TEXT,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    sent_at TEXT,
    error TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_outbound_idempotency_key
ON outbound_messages(idempotency_key)
WHERE idempotency_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS outbound_attachments (
    id TEXT PRIMARY KEY,
    outbound_id TEXT NOT NULL REFERENCES outbound_messages(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    file_path TEXT NOT NULL,
    sha256 TEXT NOT NULL
);
```

Statuses:

- `draft`: stored locally, never sent
- `dry_run`: rendered and validated, never sent
- `sending`: stored before provider call starts
- `sent`: provider accepted the message
- `queued`: provider accepted but did not report immediate send
- `error`: provider call failed or validation failed after storage

The first implementation can avoid `sending` if all sends are synchronous, but the schema should
allow it.

## Validation and Safety

Validation rules:

- `from_email`, at least one `to`, and `subject` are required.
- At least one of `text` or `html` is required.
- Header names and values must reject CR/LF injection.
- Recipient fields must reject empty or malformed addresses.
- Attachment paths must exist and be regular files.
- BCC recipients must not appear in raw MIME headers.
- `idempotency_key` must return the existing outbound record instead of sending again.

Agent safety rules:

- CLI sends only when the user invokes `mailatlas send`.
- Python sends only when application code calls `send_email(...)`.
- MCP send tools are disabled unless `MAILATLAS_MCP_ALLOW_SEND=1`.
- The agent skill should default to drafting and require explicit confirmation language before
  calling an enabled send tool.
- MCP tool responses must include recipient list, subject, provider, status, and outbound id.

Privacy rules:

- Do not store provider secrets.
- Do not print provider secrets.
- Do not store Gmail OAuth access tokens or refresh tokens in `store.db`.
- Do not store Gmail OAuth access tokens or refresh tokens under `.mailatlas`.
- Prefer the operating-system keychain for Gmail refresh tokens.
- Require explicit user action before creating or revoking Gmail OAuth credentials.
- Store BCC in SQLite for audit, but redact BCC from default list views.
- Treat outbound raw snapshots and attachments as sensitive workspace data.
- Treat Gmail API sent-message copies as provider-side records that may have different visibility
  from the local MailAtlas raw snapshot.

## MCP Surface

MCP should ship after core send support is implemented.

Read tools:

- `mailatlas_list_documents`
- `mailatlas_get_document`
- `mailatlas_export_document`
- `mailatlas_list_outbound`
- `mailatlas_get_outbound`

Write tools:

- `mailatlas_draft_email`
- `mailatlas_send_email`

Default behavior:

- Always expose draft tools.
- Expose `mailatlas_send_email` only when `MAILATLAS_MCP_ALLOW_SEND=1`.
- Return a clear disabled-tool error when send is unavailable.

The MCP server should describe send as a consequential action and should include a confirmation
hint in the tool description.

## Agent Skill

The MailAtlas agent skill should teach agents to:

- inspect local email documents before replying
- draft a message first
- attach exported artifacts only when needed
- send only when the runtime exposes `mailatlas_send_email`
- summarize what was sent with outbound id, recipients, subject, and provider
- avoid sending secrets, raw inbox exports, or attachments without explicit user intent

The skill should include examples for:

- "Draft a reply to this email"
- "Send me a status email when the build passes"
- "Export this document as PDF and attach it to an email"
- "List the emails MailAtlas sent today"
- "Send this from my personal Gmail account using Gmail API OAuth"

## Documentation Updates

When implemented, update:

- `README.md`: product description, CLI examples, storage layout, use cases
- `site/src/content/docs/cli/overview.md`: `send`, future `auth gmail`, and environment variables
- `site/src/content/docs/python/overview.md`: outbound API example
- `site/src/content/docs/concepts/workspace-model.md`: outbound directories and tables
- `site/src/content/docs/marketing/security-and-privacy.md`: outbound records, secrets, BCC, attachments
- `site/src/content/docs/marketing/product-vision.md`: update "not a sending platform" boundary
- `site/src/content/docs/marketing/roadmap.md`: mark outbound support as current or next
- `site/src/content/docs/getting-started/outbound-email.md`: provider-agnostic outbound quickstart
- `site/src/content/docs/providers/gmail.md`: Gmail API OAuth setup, `gmail.send` scope, send-as
  rules, local token handling, troubleshooting, and why app passwords are not recommended
- `site/src/content/docs/providers/smtp.md`: generic SMTP setup, STARTTLS versus SSL, anonymous
  SMTP, Gmail SMTP app-password compatibility, and revocation guidance
- `site/src/content/docs/providers/cloudflare-email-service.md`: Cloudflare Email Service domain
  setup, API token requirements, sender-domain constraints, limits, and response statuses
- `site/src/content/docs/config/outbound-auth.md`: environment variables, secret handling,
  OS-keychain token storage, explicit token-file fallback, and CI/testing guidance
- `site/src/content/docs/examples/gmail-send.md`: Gmail API send example with OAuth token input
- `site/src/content/docs/examples/outbound-dry-run.md`: dry-run audit workflow and how to inspect
  `outbound/` files and SQLite rows
- `site/src/content/docs/examples/smtp-capture.md`: local SMTP capture test with Mailpit or a
  similar development SMTP server
- `site/src/content/docs/python/gmail-send.md`: Python API example for `SendConfig(provider="gmail")`

Recommended documentation narrative:

- Lead with dry-run and local audit records.
- For personal Gmail addresses, recommend Gmail API OAuth with `gmail.send`.
- Document Gmail SMTP app passwords only as an advanced compatibility path.
- For custom domains on Cloudflare, recommend Cloudflare Email Service only after sender-domain
  setup is complete.
- Explain that MailAtlas is not a deliverability service and does not manage DNS, reputation, or
  provider account setup.

Do not update public docs before tests cover the documented CLI and Python workflows.

## Test Plan

Core tests:

- validate required fields
- reject malformed addresses
- reject header injection
- reject missing attachments
- build plain text MIME
- build multipart text plus HTML MIME
- build MIME with attachments
- omit BCC from raw MIME headers
- preserve BCC in stored audit metadata
- reuse existing record for repeated `idempotency_key`

Storage tests:

- create outbound tables automatically
- store raw `.eml`, body files, and copied attachments
- list outbound records
- get one outbound record
- update status from `sending` to `sent`, `queued`, or `error`
- never persist provider secrets

Provider tests:

- mock `smtplib.SMTP`
- mock `smtplib.SMTP_SSL`
- verify STARTTLS path
- verify SMTP envelope includes BCC
- verify SMTP auth is called only when credentials exist
- mock Cloudflare HTTP success
- mock Cloudflare HTTP error
- verify Cloudflare token is not persisted or printed
- mock Gmail API HTTP success
- mock Gmail API HTTP error
- verify Gmail sends base64url encoded MIME in the `raw` field
- verify Gmail uses `Authorization: Bearer <token>` without persisting or printing the token
- verify Gmail response `id` becomes `provider_message_id`
- verify Gmail response `threadId` is stored in `metadata_json`
- verify Gmail rejects BCC with a clear error until provider-only transient BCC MIME is implemented
- after Gmail BCC support is implemented, verify workspace raw snapshots omit `Bcc` while the
  provider-only Gmail payload includes it
- verify Gmail `from_email` mismatch errors are returned clearly

CLI tests:

- `send --dry-run` writes a local outbound record and returns JSON
- env defaults are honored
- CLI flags override env defaults
- missing provider config returns non-zero
- conflicting body options return non-zero
- repeated `--to`, `--cc`, `--bcc`, and `--attach` work
- `send --provider gmail` reads `MAILATLAS_GMAIL_ACCESS_TOKEN`
- `send --provider gmail` returns non-zero when no token is available
- future `auth gmail` prints account/scopes but never token values
- future `auth logout gmail` revokes or removes locally stored credentials

MCP tests:

- send tool hidden or disabled by default
- draft tool remains available
- send tool works only with `MAILATLAS_MCP_ALLOW_SEND=1`
- tool result includes outbound id and provider status

Docs tests:

- docs build passes after adding outbound provider pages
- Gmail docs do not present app passwords as the primary recommendation
- Gmail docs mention the `gmail.send` scope and do not recommend broader scopes for send-only use
- security docs state that OAuth tokens and app passwords are never stored in `store.db`
- CLI docs include dry-run, Gmail API, SMTP compatibility, and Cloudflare examples

## Implementation Phases

### Phase 1: Local Outbound Model

- Add outbound dataclasses.
- Add MIME composition.
- Add outbound storage tables and file layout.
- Add `draft_email`, `list_outbound`, and `get_outbound`.
- Add core and storage tests.

### Phase 2: SMTP Sending

- Add SMTP adapter.
- Add `send_email`.
- Add `mailatlas send`.
- Add CLI and provider tests.
- Update internal spec if implementation differs.

### Phase 3: Public Docs

- Update README and docs only after Phase 2 tests pass.
- Keep messaging precise: local sending through configured providers, not hosted deliverability.

### Phase 4: Cloudflare Adapter

- Add Cloudflare provider config.
- Verify official REST endpoint and response shape.
- Add tests for success and error responses.
- Add docs recipe for Cloudflare Email Service.

### Phase 5: Gmail API Provider

- Add `gmail` as a `SendConfig.provider` value.
- Add Gmail access-token fields to `SendConfig`.
- Implement Gmail API `users.messages.send` using base64url-encoded MIME.
- Require OAuth access tokens instead of Gmail app passwords for the recommended Gmail path.
- Request or document the `https://www.googleapis.com/auth/gmail.send` scope.
- Store Gmail message id, thread id, and response metadata.
- Reject Gmail BCC clearly until provider-only transient BCC MIME is implemented.
- Add provider tests for success, error, token handling, BCC behavior, and metadata.
- Add docs that position Gmail API OAuth as the recommended personal Gmail path.

### Phase 6: Gmail OAuth Credential UX

- Add `mailatlas auth gmail`.
- Add `mailatlas auth status gmail`.
- Add `mailatlas auth logout gmail`.
- Store refresh tokens in the operating-system keychain when available.
- Support explicit token-file fallback outside `.mailatlas` when a keychain is unavailable.
- Avoid storing token values in SQLite, raw snapshots, logs, or JSON output.
- Add tests for token-store selection, status output, logout, and no-token leakage.

### Phase 7: MCP Server

- Add read tools.
- Add draft/send tools with gating.
- Add MCP tests and usage docs.
- Expose Gmail sends through the same gated send tool only when Gmail credentials are available.

### Phase 8: Agent Skill

- Publish a MailAtlas skill that teaches safe read, draft, send, and audit flows.
- Include examples that use MCP where available and CLI fallback where MCP is absent.
- Teach Gmail API OAuth as the recommended personal Gmail path and SMTP app passwords as a
  compatibility-only path.

## Open Questions

- Should `mailatlas send` support a saved draft id, for example `mailatlas send --draft <id>`?
- Should default outbound storage include full body text, or should users be able to store metadata
  only for sensitive environments?
- Should Cloudflare be Phase 2 instead of SMTP because it is more agent-native?
- Should Gmail API become the primary documented provider because personal Gmail testing is common?
- Should `mailatlas auth gmail` ship before `provider=gmail`, or should the first Gmail provider
  accept only caller-provided access tokens?
- Should MailAtlas provide a first-party Google OAuth client for local users, or require users to
  bring their own OAuth client id and secret?
- Which OS keychain libraries are acceptable dependencies for refresh-token storage?
- Should Gmail BCC support be delayed until provider-only transient MIME rendering exists?
- Should reply helpers infer recipients from `source_document_id`, or should all recipients remain
  explicit in the first version?
- Should `send_email(...)` return `queued` for providers that accept asynchronously, even when the
  provider HTTP response says success?

## Reference Links To Verify Before Implementation

- Gmail API sending guide: <https://developers.google.com/workspace/gmail/api/guides/sending>
- Gmail `users.messages.send` reference: <https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/send>
- Gmail API scopes: <https://developers.google.com/workspace/gmail/api/auth/scopes>
- Gmail SMTP XOAUTH2 protocol: <https://developers.google.com/workspace/gmail/imap/xoauth2-protocol>
- Cloudflare Email Service REST API: <https://developers.cloudflare.com/email-service/api/send-emails/rest-api/>
