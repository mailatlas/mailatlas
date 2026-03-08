---
title: Glossary
description: Definitions for the terms used across MailAtlas docs.
slug: docs/concepts/glossary
---

## `.eml`

A single email message file on disk. Use `ingest` when you already have one or more of these files locally.

## `mbox`

A mailbox file on disk that can contain many messages. Use `ingest` when you already have an
`mbox` file locally. This is not the same thing as IMAP sync.

## `sync`

The MailAtlas command for connecting to a live mailbox over IMAP and fetching selected folders into
the local store. This is the live-mailbox path.

## root

The directory that holds raw email, normalized HTML, extracted assets, exports, and `store.db`.

## document

The normalized MailAtlas record stored in SQLite and linked to files in the local root.

## asset

A file extracted from a message, such as an inline image or another stored artifact associated with
the document.

## export

A derived JSON, Markdown, HTML, or PDF artifact written from a stored document.
