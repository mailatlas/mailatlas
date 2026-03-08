---
title: MailAtlas Docs
description: Installation, quickstart, concepts, examples, and interface reference.
slug: docs
---

MailAtlas turns email archives into developer-friendly outputs: cleaned text, normalized HTML when
the message contains HTML, extracted assets, metadata, and exportable document artifacts.

The repo writes files to the filesystem and indexes documents in SQLite by default. That is the
reference implementation, not the product story. Treat it as a simple starting point you can
inspect, script against, or move into your own blob store and database.

## Start here

- [Installation](/docs/getting-started/installation/) for local setup and package entry points.
- [Quickstart](/docs/getting-started/quickstart/) for the end-to-end flow with synthetic fixtures.
- [Workspace model](/docs/concepts/workspace-model/) for the default storage layout.

## Core ideas

- MailAtlas is useful when email needs to become reusable application data.
- It keeps raw bytes, cleaned text, HTML, extracted files, and metadata together.
- Cleanup rules are explicit so the same parser behavior can be reused in indexing jobs and agents.
- It can export JSON, Markdown, HTML, and PDF from stored documents.

## Main interfaces

- [CLI overview](/docs/cli/overview/)
- [Python API overview](/docs/python/overview/)
- [Parser cleaning configuration](/docs/config/parser-cleaning/)

## Example workflows

- [Ingest `.eml` files](/docs/examples/eml-ingest/)
- [Ingest an `mbox` archive](/docs/examples/mbox-ingest/)
