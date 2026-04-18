---
title: When to Use MailAtlas
description: Understand where MailAtlas fits and where another tool is a better choice.
slug: docs/marketing/why-not-connectors
---

MailAtlas is useful when you need to parse email into stored records, exported files, and outbound
audit trails under your control. It can start from email files on disk or from a manual IMAP sync
into the same workspace, then send outbound email through providers you configure.

Inbox connectors are useful when you want fast search and question answering across a connected
account. Generic parsers are useful when you only need low-level MIME access.

## Use MailAtlas when

- you are ingesting stored `.eml` files, `mbox` mailbox files, or manually synced IMAP folders
- you need cleaned text plus links back to raw messages, HTML, and extracted assets
- you want repeatable parsed outputs for retrieval systems, analytics, auditing, or agent tooling
- you need reviewable outputs such as JSON, HTML, Markdown, or PDF
- you need outbound email records for drafts, dry runs, provider sends, failures, and retries

## Use a different tool when

- you need background mailbox sync, hosted storage, managed deliverability, or a full mailbox client
- you want inbox search inside chat without managing your own ingestion layer
- you only need MIME decoding and do not care about normalized outputs or provenance

## What MailAtlas adds on top of parsing

- configurable cleaning instead of raw body extraction only
- normalized HTML snapshots and extracted asset references
- a default filesystem plus SQLite implementation you can inspect or replace
- repeatable exports and stable document IDs for other services, scripts, or batch jobs
- outbound MIME snapshots, body files, copied attachments, and provider status without persisting provider secrets
