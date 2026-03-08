---
title: Workspace Model
description: Understand the default filesystem and SQLite layout used by MailAtlas.
slug: docs/concepts/workspace-model
---

MailAtlas writes to a simple default storage layout:

- files on disk for raw messages, HTML snapshots, assets, and exports
- SQLite for metadata, lookup, dedupe, run history, and IMAP sync cursors

This is the default implementation. It is not the main product value.

## Directory layout

- `raw/`: original message bytes
- `html/`: normalized HTML bodies rewritten with local asset references
- `assets/`: extracted inline images and attachments
- `exports/`: default destination for file-based outputs such as PDF exports when you do not pass `--out`
- `store.db`: SQLite index

## Why this shape

- You can inspect every stage of the pipeline.
- Assets stay next to the documents that reference them.
- SQLite is enough for document listing, lookup, dedupe, and run history.
- The stored files and metadata are ordinary outputs that can be copied into your own systems.

## What MailAtlas stores

- raw email bytes
- cleaned body text
- normalized HTML if the message has an HTML body
- extracted inline files and attachments
- document metadata and provenance
- exported artifacts on demand when you choose to write them to disk
- IMAP sync cursor state when you use manual mailbox sync

PDF export uses headless Chrome or Chromium against the stored HTML snapshot when one exists, and
falls back to generated HTML from cleaned text otherwise. Set `MAILATLAS_PDF_BROWSER` if the browser
executable is not on the default path.

## Dedupe

MailAtlas deduplicates by `message_id` when present and falls back to a normalized content hash otherwise.

## IMAP sync state

Manual IMAP sync stores per-folder cursor state in SQLite so later runs can fetch only new
messages. MailAtlas does not store mailbox passwords or OAuth access tokens in the workspace.
