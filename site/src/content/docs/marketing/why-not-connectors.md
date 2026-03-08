---
title: Why Not Connectors?
description: Understand the gap between inbox connectors and a reusable ingestion layer.
slug: docs/marketing/why-not-connectors
---

Inbox connectors are useful for searching or asking questions against a connected account.

MailAtlas is useful when you need structured email data that your application can store, inspect,
and reuse.

## Connector strengths

- fast setup
- interactive retrieval
- low-friction search inside chat

## MailAtlas strengths

- deterministic exports
- reusable cleaned text, HTML, metadata, assets, and PDF artifacts
- a default filesystem + SQLite implementation you can inspect or replace
- benchmarkable parser behavior
- a stable substrate for RAG, analytics, and archival tooling
