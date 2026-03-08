---
name: mailatlas-landing-docs
description: Update MailAtlas landing page copy, documentation content, docs information architecture, and README-facing product messaging in /Users/chiragagrawal/Documents/workspace/newsletter. Use when changing homepage positioning, clarifying product terminology, adding docs routes, tightening quickstarts/how-to/reference content, or rebuilding and previewing the docs site.
---

# MailAtlas Landing Docs

## Overview

Use this skill for public-facing MailAtlas messaging. Keep the landing page, docs site, and nearby
product copy aligned with the actual product surface and easy to scan.

## Build Context First

Read the current landing page and docs entry points before editing:

- `site/src/pages/index.astro`
- `site/src/content/docs/home.md`
- the specific docs pages being changed
- `README.md` if the change affects public product messaging

If the copy touches inputs, outputs, or capability boundaries, verify the implementation in:

- `src/mailatlas/cli.py`
- `src/mailatlas/core/models.py`
- `src/mailatlas/core/service.py`

Use the CLI help or existing verification venv when needed:

```bash
.tmp-verify-312b/bin/python -m mailatlas --help
.tmp-verify-312b/bin/python -m mailatlas sync imap --help
```

## Keep Product Language Precise

- Position MailAtlas as email ingestion for AI agents and data applications.
- Treat filesystem plus SQLite as the default implementation, not the product identity.
- Do not lead with `local-first`.
- Distinguish the input paths clearly:
  - `.eml` = one message file on disk
  - `mbox` = one mailbox file on disk
  - `sync imap` = live mailbox access for selected folders
- Describe OAuth for IMAP as bring-your-own-token. MailAtlas consumes an access token but does not
  own consent screens, browser login, or refresh-token storage.
- Do not call `mbox` an archive on the landing page if that wording could be confused with live
  mailbox sync.
- When attachment support is part of the product surface, name it explicitly. Do not hide regular
  email attachments behind the broader word `assets` in hero copy, quickstarts, or capability
  summaries.
- Do not imply background sync, hosted inbox search, managed storage, or a mailbox client unless
  the code actually supports it.

## Improve Structure Before Adding More Words

- Shorten the landing page headline before expanding the subhead.
- Show the product model when copy alone is carrying too much explanation.
- Prefer descriptive headings over generic headings like `Overview` or `Why teams use it`.
- Route docs by task:
  - quickstart for file-based first run
  - how-to for manual IMAP sync
  - reference for schema, workspace, and flags
  - explanation for positioning and tradeoffs
- Use docs home as a router, not a long bullet list.

## Write With Concrete Outputs

- Prefer specific outputs such as raw message, cleaned text, HTML, inline images, attachments,
  metadata, JSON, or PDF.
- Use short sentences and front-load the important noun or verb.
- Support phrases like `structured data` with a concrete stored shape or export example nearby.
- Use `assets` as storage terminology, not as the only user-facing label for attachments or inline
  images.
- Keep “fit” and “not fit” language crisp. MailAtlas is an ingestion layer, not inbox software.

## Validate Every Public Copy Change

Rebuild the site after changing landing page, docs, or README-facing product behavior:

```bash
cd site && npm run build
```

Preview the rendered site from `site/dist` instead of trusting source edits alone. If a local
server is needed, serve the built output:

```bash
python3 -m http.server 4323 --bind 127.0.0.1 -d site/dist
```

Inspect the actual pages after rebuild, not just the Markdown or Astro source.
If sandboxed local preview access is unreliable, inspect the generated `site/dist/*.html` output
directly to confirm the rendered copy.

## Known Docs-Site Quirk

Starlight currently emits duplicate-id warnings for pages with explicit `slug:` values. Keep the
`/docs/...` routes stable unless you are intentionally changing the route strategy. Do not remove
the explicit slugs casually.

## Report Clearly

- Mention the main pages changed.
- Call out terminology decisions explicitly when clarifying product behavior.
- Include the local preview URLs when the site is rebuilt.
- Note any residual warning or routing issue that remains unresolved.
