---
title: CLI Overview
description: Use the MailAtlas CLI to ingest, inspect, and export documents.
slug: docs/cli/overview
---

The CLI follows a simple workflow: ingest documents, list or inspect them, then export the format
you need. When you want MailAtlas to pull directly from a mailbox, use the manual `sync imap`
command to ingest one or more folders into the same local workspace.

Across all ingest paths, MailAtlas preserves extracted inline images and regular email attachments
as file references on the stored document.

Use [Quickstart](/docs/getting-started/quickstart/) when you want the fastest file-based walkthrough.
Use [Manual IMAP Sync](/docs/getting-started/manual-imap-sync/) when you want a step-by-step live-mailbox flow.

MailAtlas has two input modes:

- file ingest: `ingest eml` for `.eml` files and `ingest mbox` for `mbox` mailbox files already on disk
- mailbox sync: `sync imap` for fetching selected folders from a live mailbox over IMAP

## Core workflow

### Ingest `.eml` files

```bash
mailatlas ingest eml \
  data/fixtures/atlas-market-map.eml \
  data/fixtures/atlas-inline-chart.eml \
  --db .mailatlas/store.db \
  --workspace .mailatlas/workspace
```

This prints a JSON array of created document references.

### Ingest an `mbox` mailbox file

```bash
mailatlas ingest mbox data/fixtures/atlas-demo.mbox \
  --db .mailatlas/store.db \
  --workspace .mailatlas/workspace
```

This also prints a JSON array of created document references. An `mbox` file is a mailbox file on
disk, usually created by an export or stored locally by another tool. It is not live IMAP sync.

### Sync one or more IMAP folders from a live mailbox

```bash
export MAILATLAS_IMAP_HOST=imap.example.com
export MAILATLAS_IMAP_USERNAME=user@example.com
export MAILATLAS_IMAP_PASSWORD=app-password

mailatlas sync imap \
  --folder INBOX \
  --folder Newsletters \
  --db .mailatlas/store.db \
  --workspace .mailatlas/workspace
```

This prints a JSON sync summary grouped by folder, including fetched, ingested, and duplicate counts.

### List stored documents

```bash
mailatlas list \
  --db .mailatlas/store.db \
  --workspace .mailatlas/workspace
```

Use this when you need document IDs for the next commands.

### Inspect one stored document

```bash
mailatlas show <document-id> \
  --db .mailatlas/store.db \
  --workspace .mailatlas/workspace
```

This prints the full stored document as JSON, including metadata and extracted inline-image or
attachment references.

### Export one stored document

```bash
mailatlas export <document-id> \
  --format json \
  --out ./document.json \
  --db .mailatlas/store.db \
  --workspace .mailatlas/workspace
```

Supported formats are `json`, `markdown`, `html`, and `pdf`.

## Common flags

- `--db`: SQLite path
- `--workspace`: workspace root
- `--query`: optional substring search for `list`
- `--folder`: repeat for multi-folder IMAP sync; defaults to `INBOX`

## Parser cleaning flags

The ingest commands and `sync imap` accept parser-cleaning flags such as:

- `--strip-forwarded-headers`
- `--strip-boilerplate`
- `--strip-link-only-lines`
- `--stop-at-footer`
- `--strip-invisible-chars`
- `--normalize-whitespace`

See [Parser Cleaning](/docs/config/parser-cleaning/) for behavior and tradeoffs.

## Output behavior

- `ingest ...` prints created document refs as JSON.
- `sync imap` prints per-folder sync results as JSON.
- `list` prints stored document refs as JSON.
- `show` prints one stored document as JSON.
- `export --out ...` writes a file and prints the resolved output path.
- `export --format pdf` writes to `workspace/exports/<document-id>.pdf` if you omit `--out`.

## IMAP auth modes

- `--auth password` uses `--password` or `MAILATLAS_IMAP_PASSWORD`.
- `--auth xoauth2` uses `--access-token` or `MAILATLAS_IMAP_ACCESS_TOKEN`.
- Bring your own OAuth token. MailAtlas consumes an existing access token; it does not start a
  browser login flow or manage refresh tokens.
- MailAtlas stores only IMAP sync cursors in SQLite, not mailbox credentials.

PDF export uses Chrome or Chromium. Set `MAILATLAS_PDF_BROWSER` if MailAtlas cannot find the
browser executable.
