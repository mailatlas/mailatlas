---
title: Installation
description: Install MailAtlas locally and choose the right starting path.
slug: docs/getting-started/installation
---

MailAtlas is easiest to start from PyPI. Use `uv` or Homebrew if you prefer a tool-style install.
Chrome or Chromium is only required if you want PDF export.

After installation, you have two ways to bring email in:

- read files already on disk with `ingest eml` or `ingest mbox`
- connect to a live mailbox with `sync imap` and fetch selected folders

## Recommended path: Python

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install mailatlas
mailatlas --help
```

The core toolkit does not require any cloud services.

- Install `python -m pip install "mailatlas[api]"` only if you want the published API extra.
- Install `python -m pip install "mailatlas[ai]"` only if you want the published AI extra.
- Install Chrome or Chromium only if you want PDF export.
- Set `MAILATLAS_PDF_BROWSER` if the browser executable is not on the default path.

## Optional path: uv

```bash
python3.12 -m pip install uv
uv tool install mailatlas
```

## Optional path: Homebrew

```bash
brew tap mailatlas/mailatlas
brew install mailatlas
```

If Homebrew resolves a different formula named `mailatlas`, use
`brew install mailatlas/mailatlas/mailatlas`.

## From source

Use a source checkout when you want the shipped fixtures, the example API, or editable development:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

## Optional Demo API

From a source checkout:

```bash
python -m pip install -e ".[api]"
uvicorn app:api --reload --port 5001
```

Environment variables for the example API live in the root `.env.example`.

## Next step

- Use [Quickstart](/docs/getting-started/quickstart/) if your email is already on disk as `.eml` files.
- Use [Manual IMAP Sync](/docs/getting-started/manual-imap-sync/) if MailAtlas should connect to a live mailbox.
