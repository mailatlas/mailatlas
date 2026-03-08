---
title: Parser Cleaning
description: Configure MailAtlas body cleaning behavior.
slug: docs/config/parser-cleaning
---

MailAtlas exposes a `ParserConfig` for high-noise email workflows.

## Available controls

- `strip_forwarded_headers`
- `strip_boilerplate`
- `strip_link_only_lines`
- `stop_at_footer`
- `strip_invisible_chars`
- `normalize_whitespace`

## Example

```python
from mailatlas import ParserConfig, parse_eml

document = parse_eml(
    "data/fixtures/atlas-founder-forward.eml",
    parser_config=ParserConfig(
        strip_forwarded_headers=True,
        strip_boilerplate=True,
        stop_at_footer=True,
    ),
)
```

## Why it matters

These controls make it easier to benchmark parser behavior on synthetic fixtures and adapt the output for different downstream use cases:

- preserve wrappers for forensic workflows
- remove boilerplate for cleaner exports and retrieval chunks
- stop at footers for cleaner RAG chunks
