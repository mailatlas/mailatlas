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
- IMAP sync cursor state in SQLite when you use `sync`
- outbound raw `.eml` snapshots, body files, copied attachments, provider status, and recipient metadata when you use `send`
- exported artifacts wherever you tell MailAtlas to write them

## What it does not do by default

- no hosted storage services
- no hosted or background mailbox sync
- no automatic publication of private inbox data
- no autonomous background sending
- no persistence of SMTP passwords, Cloudflare API tokens, IMAP passwords, or OAuth access tokens

## PDF export note

PDF export uses a local Chrome or Chromium process to render stored HTML. Set
`MAILATLAS_PDF_BROWSER` if you need to override the browser executable path.

## Practical guidance

- Treat the default filesystem plus SQLite store as source data, not as a scrubbed sharing format.
- Treat saved IMAP sync state as operational metadata only; MailAtlas does not persist mailbox secrets there.
- Treat outbound records, BCC recipients, raw `.eml` snapshots, and copied attachments as sensitive workspace data.
- If you use OAuth for IMAP, obtain and store tokens in your own auth layer or secret source, then
  pass them to MailAtlas at runtime.
- If you send email, pass provider credentials through runtime configuration such as environment
  variables, CLI flags, or explicit Python `SendConfig` values. MailAtlas does not write those
  secrets to SQLite, raw snapshots, logs, or JSON output.
- For personal Gmail, prefer Gmail API OAuth with the `gmail.send` scope over SMTP app passwords.
  `mailatlas auth gmail` stores OAuth tokens outside the MailAtlas workspace by default and never in
  `store.db`.
- Review exported JSON, HTML, Markdown, and PDF artifacts before sending them outside your machine or repository.
- Review outbound drafts and dry runs before sending generated or agent-authored email.
- Use synthetic fixtures for demos when you do not want real inbox content in screenshots, examples, or tests.
