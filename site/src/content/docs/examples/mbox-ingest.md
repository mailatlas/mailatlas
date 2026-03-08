---
title: Mbox Ingest
description: Import an `mbox` mailbox file from disk into the default MailAtlas store.
slug: docs/examples/mbox-ingest
---

```bash
mailatlas ingest mbox data/fixtures/atlas-demo.mbox \
  --db .mailatlas/store.db \
  --workspace .mailatlas/workspace
```

An `mbox` file is a mailbox file on disk, often created by an export or by another local mail
tool. MailAtlas iterates each message in that file, preserves provenance and metadata, and writes
deduplicated records into the default filesystem plus SQLite store.

If you want MailAtlas to connect to a live mailbox instead, use `mailatlas sync imap`.
