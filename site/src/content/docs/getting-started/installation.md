---
title: Installation
description: Install MailAtlas with pip, uv, or the prepared Homebrew release path.
slug: docs/getting-started/installation
---

## Python

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

The core toolkit does not require any cloud services. After the editable install, use `mailatlas ...` directly instead of `PYTHONPATH=src python -m ...`.

If you want the example API as well, install `.[api]`.

If you want PDF export, install Chrome or Chromium. MailAtlas uses a headless browser to render
stored HTML into PDFs and honors `MAILATLAS_PDF_BROWSER` as an override.

## uv

```bash
python3.12 -m pip install uv
uv tool install --from . mailatlas
```

## Homebrew

The repo includes the release plumbing and formula template for a dedicated tap:

```bash
brew tap chiragagrawal/mailatlas
brew install mailatlas
```

Until the public tap exists, use the Python install path above.

## Optional Demo API

```bash
uvicorn app:api --reload --port 5001
```

Environment variables live in the root `.env.example`.
