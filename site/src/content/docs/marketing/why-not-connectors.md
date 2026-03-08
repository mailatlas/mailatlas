---
title: When to Use MailAtlas
description: Understand where MailAtlas fits and where another tool is a better choice.
slug: docs/marketing/why-not-connectors
---

MailAtlas is useful when email needs to become reusable application data that you can store,
inspect, and move through your own systems. It can start from email files on disk or from a manual
IMAP sync into the same workspace.

Inbox connectors are useful when you want fast search and question answering across a connected
account. Generic parsers are useful when you only need low-level MIME access.

## Use MailAtlas when

- you are ingesting stored `.eml` files, `mbox` mailbox files, or manually synced IMAP folders
- you need cleaned text plus links back to raw messages, HTML, and extracted assets
- you want deterministic inputs for RAG, analytics, auditing, or agent workflows
- you need reviewable outputs such as JSON, HTML, Markdown, or PDF

## Choose another tool when

- you need background mailbox sync, hosted storage, or a full mailbox client
- you want inbox search inside chat without managing your own ingestion layer
- you only need MIME decoding and do not care about normalized outputs or provenance

## What MailAtlas adds on top of parsing

- configurable cleaning instead of raw body extraction only
- normalized HTML snapshots and extracted asset references
- a default filesystem plus SQLite implementation you can inspect or replace
- repeatable exports and stored document IDs for downstream pipelines
