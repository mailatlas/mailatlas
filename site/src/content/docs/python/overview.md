---
title: Python API
description: Use MailAtlas as a Python library for parse-only or storage-backed workflows.
slug: docs/python/overview
---

## Main entry points

```python
from mailatlas import ImapSyncConfig, MailAtlas, ParserConfig, parse_eml
```

Use `parse_eml(...)` when you want parser output without storage. Use `MailAtlas(...)` when you
want one configured object for storage-backed ingest, IMAP sync, and export.

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

## Use `MailAtlas` for storage-backed workflows

```python
from mailatlas import ImapSyncConfig, MailAtlas, ParserConfig

atlas = MailAtlas(
    db_path=".mailatlas/store.db",
    workspace_path=".mailatlas/workspace",
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
```

This is the right entry point when you want stored raw messages, normalized HTML, extracted inline
images and attachments, document lookup through the default workspace, and optional IMAP folder
sync.

## What you get back

- `parse_eml(...)` returns one normalized document in memory.
- `ingest_eml(...)` returns document refs with IDs you can store or export later.
- `sync_imap(...)` returns per-folder sync results and document refs for that run.
- `export_document(...)` returns the exported content or output path depending on the format.

See [Document Schema](/docs/concepts/document-schema/) for the persisted record shape and
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

PDF export uses Chrome or Chromium under the hood. Set `MAILATLAS_PDF_BROWSER` if the browser
executable is not on the default path.
