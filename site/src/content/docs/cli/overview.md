---
title: CLI Overview
description: Use the MailAtlas CLI to ingest, inspect, export, and sync documents.
slug: docs/cli/overview
---

The CLI follows a simple workflow: ingest documents, list them, read one document, and export the
format you need. When you want MailAtlas to pull directly from a mailbox, use `sync` to fetch one
or more folders into the same local store.

Across all ingest paths, MailAtlas preserves extracted inline images and regular email attachments
as file references on the stored document.

Use [Quickstart](/docs/getting-started/quickstart/) when you want the fastest file-based walkthrough.
Use [Manual IMAP Sync](/docs/getting-started/manual-imap-sync/) when you want a step-by-step live-mailbox flow.

## Root and defaults

MailAtlas stores data in one root directory. The default is `.mailatlas` in the current directory.

Resolution order:

- `--root`
- `MAILATLAS_HOME`
- project config from `.mailatlas.toml` or `pyproject.toml`
- fallback `.mailatlas`

The default root contains:

- `store.db`
- `raw/`
- `html/`
- `assets/`
- `exports/`

## Core workflow

### Ingest files from disk

```bash
mailatlas ingest \
  data/fixtures/atlas-market-map.eml \
  data/fixtures/atlas-inline-chart.eml
```

MailAtlas auto-detects `.eml` files and `mbox` archives. The command prints a JSON summary with
ingested and duplicate counts plus the resulting document refs.

### Sync one or more IMAP folders

```bash
export MAILATLAS_IMAP_HOST=imap.example.com
export MAILATLAS_IMAP_USERNAME=user@example.com
export MAILATLAS_IMAP_PASSWORD=app-password

mailatlas sync \
  --folder INBOX \
  --folder Newsletters
```

This prints a JSON sync summary grouped by folder, including fetched, ingested, and duplicate counts.

### List stored documents

```bash
mailatlas list
```

Use this when you need document IDs for the next commands.

### Read one stored document

```bash
mailatlas get <document-id>
```

This prints the full stored document as JSON, including metadata and extracted inline-image or
attachment references.

### Export one stored document

```bash
mailatlas get <document-id> \
  --format html \
  --out ./document.html
```

Supported formats are `json`, `markdown`, `html`, and `pdf`.

## Common flags

- `--root`: MailAtlas root directory
- `--query`: optional substring search for `list`
- `--folder`: repeat for multi-folder IMAP sync; defaults to `INBOX`
- `--type`: optional override for ingest auto-detection

## Parser cleaning flags

The `ingest` and `sync` commands accept parser-cleaning flags such as:

- `--strip-forwarded-headers`
- `--strip-boilerplate`
- `--strip-link-only-lines`
- `--stop-at-footer`
- `--strip-invisible-chars`
- `--normalize-whitespace`

See [Parser Cleaning](/docs/config/parser-cleaning/) for behavior and tradeoffs.

## Output behavior

- `ingest` prints a JSON summary with counts and created document refs.
- `sync` prints per-folder sync results as JSON.
- `list` prints stored document refs as JSON.
- `get` prints one stored document as JSON by default.
- `get --out ...` writes a file and prints the resolved output path.
- `get --format pdf` writes to `exports/<document-id>.pdf` if you omit `--out`.

## IMAP auth

- `--password` uses `MAILATLAS_IMAP_PASSWORD` when not passed directly.
- `--access-token` uses `MAILATLAS_IMAP_ACCESS_TOKEN` when not passed directly.
- MailAtlas infers password auth versus XOAUTH2 from the credential you provide.
- Bring your own OAuth token. MailAtlas consumes an existing access token; it does not start a
  browser login flow or manage refresh tokens.
- MailAtlas stores only IMAP sync cursors in SQLite, not mailbox credentials.

PDF export uses Chrome or Chromium. Set `MAILATLAS_PDF_BROWSER` if MailAtlas cannot find the
browser executable.
