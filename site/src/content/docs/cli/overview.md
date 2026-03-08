---
title: CLI Overview
description: Learn the MailAtlas command surface.
slug: docs/cli/overview
---

## Commands

- `mailatlas ingest eml`
- `mailatlas ingest mbox`
- `mailatlas list`
- `mailatlas show`
- `mailatlas export`

## Common flags

- `--db`: SQLite path
- `--workspace`: workspace root
- parser-cleaning flags such as `--strip-forwarded-headers` and `--stop-at-footer`

## Example

```bash
mailatlas ingest mbox data/fixtures/atlas-demo.mbox \
  --db .mailatlas/store.db \
  --workspace .mailatlas/workspace
```

Export a stored document as a PDF:

```bash
mailatlas export <document-id> \
  --format pdf \
  --out ./document.pdf \
  --db .mailatlas/store.db \
  --workspace .mailatlas/workspace
```

PDF export uses Chrome or Chromium. Set `MAILATLAS_PDF_BROWSER` if MailAtlas cannot find the browser executable.
