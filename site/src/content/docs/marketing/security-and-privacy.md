---
title: Security and Privacy
description: Understand what MailAtlas stores locally and what to review before sharing outputs.
slug: docs/marketing/security-and-privacy
---

MailAtlas stores data on the filesystem and in SQLite by default. The core CLI commands and Python
APIs operate on files you point at or on IMAP folders you sync explicitly; they do not require a hosted
MailAtlas service.

## What it stores

- raw message bytes on disk
- normalized HTML and extracted assets on disk
- document metadata and parser notes in SQLite
- IMAP sync cursor state in SQLite when you use `sync imap`
- exported artifacts wherever you tell MailAtlas to write them

## What it does not do by default

- no hosted storage services
- no hosted or background mailbox sync
- no automatic publication of private inbox data

## PDF export note

PDF export uses a local Chrome or Chromium process to render stored HTML. Set
`MAILATLAS_PDF_BROWSER` if you need to override the browser executable path.

## Practical guidance

- Treat the default filesystem plus SQLite store as source data, not as a scrubbed sharing format.
- Treat saved IMAP sync state as operational metadata only; MailAtlas does not persist mailbox secrets there.
- If you use OAuth for IMAP, obtain and store tokens in your own auth layer or secret source, then
  pass them to MailAtlas at runtime.
- Review exported JSON, HTML, Markdown, and PDF artifacts before sending them outside your machine or repository.
- Use synthetic fixtures for demos when you do not want real inbox content in screenshots, examples, or tests.
