---
title: Installation
description: Install MailAtlas locally and choose the right starting path.
slug: docs/getting-started/installation
---

MailAtlas is easiest to start with an editable Python install. Use `uv` if you prefer a CLI-style
tool install. Chrome or Chromium is only required if you want PDF export.

After installation, you have two ways to bring email in:

- read files already on disk with `ingest eml` or `ingest mbox`
- connect to a live mailbox with `sync imap` and fetch selected folders

## Recommended path: Python

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
mailatlas --help
```

The core toolkit does not require any cloud services. After the editable install, use
`mailatlas ...` directly instead of `PYTHONPATH=src python -m ...`.

- Install `python -m pip install -e ".[api]"` only if you want the example API.
- Install Chrome or Chromium only if you want PDF export.
- Set `MAILATLAS_PDF_BROWSER` if the browser executable is not on the default path.

## Optional path: uv

```bash
python3.12 -m pip install uv
uv tool install --from . mailatlas
```

## Optional Demo API

```bash
python -m pip install -e ".[api]"
uvicorn app:api --reload --port 5001
```

Environment variables live in the root `.env.example`.

## Planned distribution

The Homebrew tap is planned after the first public release path is in place. Until then, use the
Python or `uv` install above.

## Next step

- Use [Quickstart](/docs/getting-started/quickstart/) if your email is already on disk as `.eml` files.
- Use [Manual IMAP Sync](/docs/getting-started/manual-imap-sync/) if MailAtlas should connect to a live mailbox.
