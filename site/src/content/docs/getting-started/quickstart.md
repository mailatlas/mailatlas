---
title: Quickstart
description: Run MailAtlas end to end with synthetic fixtures and inspect the output, including extracted attachments and inline assets.
slug: docs/getting-started/quickstart
---

MailAtlas ships with synthetic fixtures so you can verify the file-based ingest flow before
pointing it at your own email. The core path is ingest, list, inspect, and export JSON while
keeping raw email, HTML, and extracted attachments or inline assets linked together. PDF export is
optional.

This page uses `.eml` files already on disk. If you want MailAtlas to connect to a live mailbox,
use `mailatlas sync imap` instead.

## Before you start

- Use this page when your input already exists as files on disk.
- You need a working MailAtlas install and Python 3.12.
- You only need Chrome or Chromium if you plan to export PDF.
- By the end, you will ingest sample messages, inspect one stored document, and export JSON.

## 1. Ingest the sample `.eml` files

```bash
mailatlas ingest eml \
  data/fixtures/atlas-market-map.eml \
  data/fixtures/atlas-founder-forward.eml \
  data/fixtures/atlas-inline-chart.eml \
  --db .mailatlas/store.db \
  --workspace .mailatlas/workspace
```

MailAtlas prints a JSON array of created document references:

```json
[
  {
    "id": "<document-id>",
    "subject": "Regional freight signals tighten in the Midwest",
    "source_kind": "eml",
    "created_at": "<timestamp>"
  },
  {
    "id": "<document-id>",
    "subject": "Municipal grid storage tender opens sooner than expected",
    "source_kind": "eml",
    "created_at": "<timestamp>"
  },
  {
    "id": "<document-id>",
    "subject": "Port dwell times normalize after weather disruptions",
    "source_kind": "eml",
    "created_at": "<timestamp>"
  }
]
```

## 2. List the stored documents

```bash
mailatlas list \
  --db .mailatlas/store.db \
  --workspace .mailatlas/workspace
```

Use any returned `id` as `<document-id>` in the next steps.

## 3. Inspect one stored document

```bash
mailatlas show <document-id> \
  --db .mailatlas/store.db \
  --workspace .mailatlas/workspace
```

A stored document includes links back to the original email, any normalized HTML, and extracted
assets such as inline images or email attachments:

```json
{
  "subject": "Port dwell times normalize after weather disruptions",
  "body_html_path": "html/<document-id>.html",
  "raw_path": "raw/<document-id>.eml",
  "metadata": {
    "cleaning": {
      "dropped_line_count": 0
    },
    "provenance": {
      "is_forwarded": false
    }
  },
  "assets": [
    {
      "kind": "inline",
      "file_path": "assets/<document-id>/001-route-heatmap.svg"
    }
  ]
}
```

When MailAtlas extracts a regular file attachment, that same `assets` array uses
`"kind": "attachment"` and stores the file under `assets/<document-id>/...`.

## 4. Export a document as JSON

```bash
mailatlas export <document-id> \
  --format json \
  --out ./port-dwell.json \
  --db .mailatlas/store.db \
  --workspace .mailatlas/workspace
```

The command prints the output path you wrote, for example:

```text
/private/tmp/port-dwell.json
```

## 5. Optionally export the same document as PDF

```bash
mailatlas export <document-id> \
  --format pdf \
  --out ./port-dwell.pdf \
  --db .mailatlas/store.db \
  --workspace .mailatlas/workspace
```

PDF export uses Chrome or Chromium. Set `MAILATLAS_PDF_BROWSER` if the browser executable is not
on the default path.

## 6. Review the stored outputs

During ingest, MailAtlas writes:

- raw email bytes to `raw/`
- HTML snapshots to `html/` when the message has HTML
- extracted inline images and attachments to `assets/`
- metadata to `store.db`

Exports go where you tell MailAtlas to write them with `--out`. If you omit `--out` for a PDF
export, MailAtlas writes the PDF to `workspace/exports/<document-id>.pdf`.

## Next step

- Use [Manual IMAP Sync](/docs/getting-started/manual-imap-sync/) if you want to fetch from a live mailbox.
- Use [Document Schema](/docs/concepts/document-schema/) if you want the full stored document schema.
