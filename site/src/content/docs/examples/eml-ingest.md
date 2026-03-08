---
title: EML Ingest
description: Ingest a set of `.eml` messages into the default MailAtlas store.
slug: docs/examples/eml-ingest
---

```bash
mailatlas ingest \
  data/fixtures/atlas-market-map.eml \
  data/fixtures/atlas-founder-forward.eml
```

This example is useful for:

- one-off fixture debugging
- stored message files on disk
- test-driven parser changes
