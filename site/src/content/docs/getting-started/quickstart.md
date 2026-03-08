---
title: Quickstart
description: Run MailAtlas end to end with synthetic fixtures.
slug: docs/getting-started/quickstart
---

## 1. Ingest the sample `.eml` files

```bash
mailatlas ingest eml \
  data/fixtures/atlas-market-map.eml \
  data/fixtures/atlas-founder-forward.eml \
  data/fixtures/atlas-inline-chart.eml \
  --db .mailatlas/store.db \
  --workspace .mailatlas/workspace
```

## 2. Inspect the document list

```bash
mailatlas list \
  --db .mailatlas/store.db \
  --workspace .mailatlas/workspace
```

## 3. Export a document as JSON

```bash
mailatlas export <document-id> \
  --format json \
  --out ./document.json \
  --db .mailatlas/store.db \
  --workspace .mailatlas/workspace
```

## 4. Export a document as PDF

```bash
mailatlas export <document-id> \
  --format pdf \
  --out ./document.pdf \
  --db .mailatlas/store.db \
  --workspace .mailatlas/workspace
```

PDF export uses Chrome or Chromium. Set `MAILATLAS_PDF_BROWSER` if the browser executable is not on the default path.

## 5. Review the stored outputs

MailAtlas writes:

- raw email bytes to `raw/`
- HTML snapshots to `html/` when the message has HTML
- extracted assets to `assets/`
- generated exports to `exports/`
- metadata to `store.db`
