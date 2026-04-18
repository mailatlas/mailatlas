---
title: Workspace Model
description: Understand the default filesystem and SQLite layout used by MailAtlas.
slug: docs/concepts/workspace-model
---

MailAtlas writes to a simple default storage layout:

- files on disk for raw inbound messages, HTML snapshots, assets, exports, and outbound audit artifacts
- SQLite for metadata, lookup, dedupe, run history, IMAP sync cursors, and outbound send records

This is the built-in local storage layout. MailAtlas's main value is the parsed content and
exports, not the storage backend itself.

## Directory layout

- `raw/`: original message bytes
- `html/`: normalized HTML bodies rewritten with local asset references
- `assets/`: extracted inline images and attachments
- `exports/`: default destination for file-based outputs such as PDF exports when you do not pass `--out`
- `outbound/raw/`: rendered outbound `.eml` snapshots
- `outbound/text/`: outbound plain-text bodies
- `outbound/html/`: outbound HTML bodies
- `outbound/attachments/`: copied outbound attachments
- `store.db`: SQLite index

## Why this layout

- You can inspect every stage of the pipeline.
- Assets stay next to the documents that reference them.
- SQLite is enough for document listing, lookup, dedupe, and run history.
- The stored files and metadata are ordinary outputs that can be copied into your own storage or indexing systems.

## What MailAtlas stores

- raw email bytes
- cleaned body text
- normalized HTML if the message has an HTML body
- extracted inline files and attachments
- document metadata and provenance
- exported artifacts on demand when you choose to write them to disk
- IMAP sync cursor state when you use manual mailbox sync
- outbound draft, dry-run, send, queued, and error records when you use `draft_email(...)`,
  `send_email(...)`, or `mailatlas send`
- outbound BCC recipients in SQLite for audit, while omitting BCC from raw MIME headers

PDF export uses headless Chrome or Chromium against the stored HTML snapshot when one exists, and
falls back to generated HTML from cleaned text otherwise. Set `MAILATLAS_PDF_BROWSER` if the browser
executable is not on the default path.

## Dedupe

MailAtlas deduplicates by `message_id` when present and falls back to a normalized content hash otherwise.

## IMAP sync state

Manual IMAP sync stores per-folder cursor state in SQLite so later runs can fetch only new
messages. MailAtlas does not store mailbox passwords or OAuth access tokens in the workspace.

## Outbound records

Outbound storage adds two SQLite tables:

- `outbound_messages` for provider, status, recipient metadata, body paths, raw snapshot path,
  source document link, idempotency key, timestamps, and provider error details
- `outbound_attachments` for copied attachment paths, MIME types, and SHA-256 hashes

Provider secrets are not part of either table. Pass SMTP or Cloudflare credentials at runtime
through CLI flags, environment variables, or explicit Python `SendConfig` values.
