# Contributing

MailAtlas is still early. The most useful contributions right now are parser quality
improvements, fixture coverage, packaging hardening, and docs clarity.

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[api,ai]"
```

The editable install exposes `mailatlas` directly, so development commands should not need `PYTHONPATH=src`.

For the docs site:

```bash
cd site
npm install
```

## Development Workflow

- Keep fixtures synthetic and safe to publish.
- Prefer small, reviewable pull requests.
- Add or update tests when parser behavior changes.
- Keep the CLI and Python API examples in sync with docs.

## Tests

```bash
python -m unittest discover -s tests -v
```

For packaging smoke checks:

```bash
python -m pip install build
python -m build
python scripts/smoke_release.py
```

## Pull Requests

- Explain the user-visible behavior change.
- Note any schema, storage, or fixture changes explicitly.
- If the change affects docs, update the README or site in the same PR.

## Release Policy

MailAtlas will stay alpha until the public repo, docs site, and Homebrew tap are live.
Breaking changes are acceptable during the alpha window, but they should be called out in release notes.
