---
title: Mbox Ingest
description: Import a mailbox archive into the default MailAtlas store.
slug: docs/examples/mbox-ingest
---

```bash
mailatlas ingest mbox data/fixtures/atlas-demo.mbox \
  --db .mailatlas/store.db \
  --workspace .mailatlas/workspace
```

MailAtlas iterates each message in the archive, preserves provenance and metadata, and writes deduplicated records into the default filesystem plus SQLite store.
