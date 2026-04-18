---
title: Python API
description: Use MailAtlas as a Python library for parse-only calls, storage-backed usage, and outbound email.
slug: docs/python/overview
---

## Main entry points

```python
from mailatlas import ImapSyncConfig, MailAtlas, OutboundMessage, ParserConfig, SendConfig, parse_eml
```

Use `parse_eml(...)` when you want parser output without storage. Use `MailAtlas(...)` when you
want one configured object for storage-backed ingest, IMAP sync, export, outbound drafts, and sends.

Parsed and stored documents can include extracted inline images and regular email attachments in
their `assets` collection.

## Parse without storage first

```python
from mailatlas import ParserConfig, parse_eml

document = parse_eml(
    "data/fixtures/atlas-founder-forward.eml",
    parser_config=ParserConfig(strip_boilerplate=True, stop_at_footer=True),
)
```

This is the fastest way to inspect parser behavior inside tests, experiments, or data pipelines
that do not need the default workspace.

## Use `MailAtlas` for storage-backed usage

```python
from mailatlas import ImapSyncConfig, MailAtlas, OutboundMessage, ParserConfig, SendConfig

atlas = MailAtlas(
    db_path=".mailatlas/store.db",
    workspace_path=".mailatlas",
    parser_config=ParserConfig(strip_boilerplate=True, stop_at_footer=True),
)

document = atlas.parse_eml(
    "data/fixtures/atlas-founder-forward.eml",
)

refs = atlas.ingest_eml(
    ["data/fixtures/atlas-market-map.eml", "data/fixtures/atlas-inline-chart.eml"],
)

sync_result = atlas.sync_imap(
    ImapSyncConfig(
        host="imap.example.com",
        username="user@example.com",
        access_token="oauth-access-token",
        auth="xoauth2",
        folders=("INBOX", "Newsletters"),
    )
)

pdf_path = atlas.export_document(
    refs[0].id,
    format="pdf",
)

send_result = atlas.send_email(
    OutboundMessage(
        from_email="agent@example.com",
        to=("user@example.com",),
        subject="Build complete",
        text="The build passed.",
        idempotency_key="build-123",
    ),
    SendConfig(provider="smtp", dry_run=True),
)
```

This is the right entry point when you want stored raw messages, normalized HTML, extracted inline
images and attachments, document lookup through the default workspace, and optional IMAP folder
sync. It also lets your application create outbound audit records and send through providers it
configures explicitly.

## What you get back

- `parse_eml(...)` returns one normalized document in memory.
- `ingest_eml(...)` returns document refs with IDs you can store or export later.
- `sync_imap(...)` returns per-folder sync results and document refs for that run.
- `export_document(...)` returns the exported content or output path depending on the format.
- `draft_email(...)` stores a local outbound draft and rendered `.eml` snapshot.
- `send_email(...)` stores a local outbound attempt, sends through the configured provider unless
  `dry_run=True`, and returns a `SendResult`.
- `list_outbound(...)` and `get_outbound(...)` expose outbound audit records.

See [Document Schema](/docs/concepts/document-schema/) for the persisted record structure and
[Workspace Model](/docs/concepts/workspace-model/) for the default storage layout.

## Parser configuration

Use `ParserConfig(...)` when you need to tune forwarded-header stripping, boilerplate removal,
footer stopping, link-only line removal, or whitespace cleanup.

## Manual IMAP sync

Use `ImapSyncConfig(...)` when you want MailAtlas to connect to an IMAP mailbox over TLS, fetch one
or more folders incrementally, and store only non-secret sync cursor state in SQLite.

Treat MailAtlas as the OAuth consumer rather than the OAuth client: your app or local tooling
should obtain the access token, then pass it into `ImapSyncConfig(access_token=..., auth="xoauth2")`.

Use `atlas.ingest_mbox(...)` instead when you already have an `mbox` mailbox file on disk. `mbox`
is a file format; IMAP sync is the live mailbox access path. For a CLI walkthrough of mailbox sync,
see [Manual IMAP Sync](/docs/getting-started/manual-imap-sync/).

## Outbound email

Create messages with explicit fields. MailAtlas validates sender and recipient addresses, rejects
header injection, copies attachments into the outbound audit area, and omits BCC from the MIME
headers while preserving it in SQLite for audit.

```python
from mailatlas import MailAtlas, OutboundAttachment, OutboundMessage, SendConfig

atlas = MailAtlas()

result = atlas.send_email(
    OutboundMessage(
        from_email="agent@example.com",
        from_name="Build Agent",
        to=("user@example.com",),
        cc=("team@example.com",),
        bcc=("archive@example.com",),
        subject="Report",
        text="Report attached.",
        attachments=(OutboundAttachment("report.pdf"),),
        idempotency_key="report-2026-04-18",
    ),
    SendConfig(
        provider="smtp",
        smtp_host="smtp.example.com",
        smtp_username="agent@example.com",
        smtp_password="app-password",
    ),
)
```

Provider secrets belong in your application config, CLI flags, or environment variables at runtime.
MailAtlas does not persist SMTP passwords or Cloudflare API tokens in SQLite, raw snapshots, or JSON
output.

For Gmail, prefer the Gmail API provider with an OAuth access token scoped to
`https://www.googleapis.com/auth/gmail.send`:

```python
from mailatlas import MailAtlas, OutboundMessage, SendConfig

atlas = MailAtlas()

result = atlas.send_email(
    OutboundMessage(
        from_email="user@gmail.com",
        to=("user@gmail.com",),
        subject="Gmail API test",
        text="Sent with Gmail API OAuth.",
    ),
    SendConfig(
        provider="gmail",
        gmail_access_token="ya29...",
    ),
)
```

The CLI can store and refresh Gmail OAuth tokens for local testing with `mailatlas auth gmail`.
Library callers can also provide fresh access tokens directly through `SendConfig`.

PDF export uses Chrome or Chromium under the hood. Set `MAILATLAS_PDF_BROWSER` if the browser
executable is not on the default path.
