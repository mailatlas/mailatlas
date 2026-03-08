---
title: Security and Privacy
description: What MailAtlas stores and what it does not do by default.
slug: docs/marketing/security-and-privacy
---

MailAtlas stores data on the filesystem and in SQLite by default.

## What it stores

- raw message bytes on disk
- parsed HTML and extracted assets on disk
- document metadata in SQLite

## What it does not do by default

- no hosted storage services
- no live mailbox sync
- no public sample data from private inboxes

## Practical rule

Treat the default filesystem plus SQLite store as your source data. Review exported files before sharing them outside your machine or repository.
