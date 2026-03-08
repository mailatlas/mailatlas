---
title: Python API
description: Use MailAtlas as a Python library inside larger workflows.
slug: docs/python/overview
---

## Main entry points

```python
from mailatlas import MailAtlas, ParserConfig, parse_eml
```

Use `MailAtlas(...)` when you want one configured object for storage-backed operations.

## Parse and ingest with a configured app

```python
from mailatlas import MailAtlas, ParserConfig

atlas = MailAtlas(
    db_path=".mailatlas/store.db",
    workspace_path=".mailatlas/workspace",
    parser_config=ParserConfig(strip_boilerplate=True, stop_at_footer=True),
)

document = atlas.parse_eml(
    "data/fixtures/atlas-founder-forward.eml",
)

refs = atlas.ingest_eml(
    ["data/fixtures/atlas-market-map.eml", "data/fixtures/atlas-inline-chart.eml"],
)

pdf_path = atlas.export_document(
    refs[0].id,
    format="pdf",
)
```

## Parse without storage

```python
from mailatlas import ParserConfig, parse_eml

document = parse_eml(
    "data/fixtures/atlas-founder-forward.eml",
    parser_config=ParserConfig(strip_boilerplate=True, stop_at_footer=True),
)
```

PDF export uses Chrome or Chromium under the hood. Set `MAILATLAS_PDF_BROWSER` if the browser executable is not on the default path.
