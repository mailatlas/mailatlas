---
title: EML Ingest
description: Ingest a set of `.eml` messages into the default MailAtlas store.
slug: docs/examples/eml-ingest
---

```bash
mailatlas ingest eml \
  data/fixtures/atlas-market-map.eml \
  data/fixtures/atlas-founder-forward.eml \
  --db .mailatlas/store.db \
  --workspace .mailatlas/workspace
```

This example is useful for:

- one-off fixture debugging
- stored message files on disk
- test-driven parser changes
