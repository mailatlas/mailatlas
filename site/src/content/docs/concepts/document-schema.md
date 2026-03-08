---
title: Document Schema
description: Review the normalized document model persisted by MailAtlas.
slug: docs/concepts/document-schema
---

MailAtlas stores documents with these core fields:

- `id`
- `source_kind`
- `message_id`
- `thread_id`
- `subject`
- `sender_name`
- `sender_email`
- `author`
- `received_at`
- `published_at`
- `body_text`
- `body_html_path`
- `raw_path`
- `content_hash`
- `metadata`
- `created_at`

Assets are stored separately with:

- `id`
- `document_id`
- `ordinal`
- `kind`
- `mime_type`
- `file_path`
- `cid`
- `sha256`

## Metadata

`metadata` carries parser notes and provenance:

- `provenance.is_forwarded`
- `provenance.forwarded_chain`
- `cleaning.removed_forwarded_headers`
- `cleaning.dropped_line_count`
- `cleaning.stopped_at_footer`
- `parser_config.*`

This lets downstream code inspect what MailAtlas changed instead of treating cleaning as a black box.
