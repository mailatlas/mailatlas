---
title: Installation
description: Install MailAtlas locally and choose the right starting path.
slug: docs/getting-started/installation
---

MailAtlas is easiest to start from PyPI. Use `uv` or Homebrew if you prefer a tool-style install.
Chrome or Chromium is only required if you want PDF export.

After installation, you have two ways to bring email in:

- read files already on disk with `ingest`
- connect to a live mailbox with `sync` and fetch selected folders

## Recommended path: Python

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install mailatlas
mailatlas doctor
```

The core toolkit does not require any cloud services.

- Install `python -m pip install "mailatlas[api]"` only if you want the published API extra.
- Install Chrome or Chromium only if you want PDF export.
- Set `MAILATLAS_PDF_BROWSER` if the browser executable is not on the default path.
- `mailatlas doctor` runs a temporary self-check for ingest, storage, and export.

## Optional path: uv

```bash
python3.12 -m pip install uv
uv tool install mailatlas
mailatlas doctor
```

## Optional path: Homebrew

```bash
brew tap mailatlas/mailatlas
brew install mailatlas
mailatlas doctor
```

If Homebrew resolves a different formula named `mailatlas`, use
`brew install mailatlas/mailatlas/mailatlas`.

## From source

Use a source checkout when you want the shipped fixtures, the demo API, or editable development:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
make bootstrap-python
mailatlas doctor
```

If you are changing the docs site too:

```bash
make bootstrap-docs
```

## Optional Demo API

From a source checkout:

```bash
uvicorn app:api --reload --port 5001
```

Run `make help` to see the rest of the local developer commands.

## Next step

- Use [Quickstart](/docs/getting-started/quickstart/) if your email is already on disk as `.eml` files.
- Use [Manual IMAP Sync](/docs/getting-started/manual-imap-sync/) if MailAtlas should connect to a live mailbox.
