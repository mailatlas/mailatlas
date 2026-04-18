---
title: Roadmap
description: Near-term roadmap for MailAtlas email parsing, storage, and export features.
slug: docs/marketing/roadmap
---

## Now

- improve cleaning for common email layouts and newsletter HTML
- strengthen attachment and inline asset extraction across more real-world fixtures
- support outbound drafts, dry runs, SMTP sends, Cloudflare Email Service sends, and local audit records
- tighten the docs and examples around quickstart, export behavior, and integration paths

## Next

- improve exported document structure for retrieval and indexing systems
- expand CLI and Python reference coverage for common tasks
- add MCP tools for outbound draft/read flows, with send gated by explicit runtime configuration
- add more fixture-backed examples that show stored HTML and asset extraction

## Later

- background or scheduled mailbox sync beyond manual IMAP runs
- broader mailbox adapter coverage beyond IMAP
- additional outbound providers such as Resend, SendGrid, Postmark, or local `.eml` drop directories
- packaging and distribution paths that reduce local setup friction as release channels mature
