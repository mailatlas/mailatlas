# Contributing

The most useful contributions right now are parser quality improvements, fixture coverage,
packaging hardening, docs clarity, and integration examples that keep the ingestion core easy to
reason about.

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
- Route usage questions and bug reports through the guidance in [`SUPPORT.md`](./SUPPORT.md).

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

If you change README copy or anything under `site/src/content`, rebuild the docs site before
opening the PR:

```bash
cd site
npm run build
```

## Pull Requests

- Explain the user-visible behavior change.
- Note any schema, storage, or fixture changes explicitly.
- If the change affects docs, update the README or site in the same PR.

## Release Policy

MailAtlas is currently alpha.
Breaking changes are acceptable when they improve the ingestion core, but they should land with
tests, docs updates, and a short note in [`CHANGELOG.md`](./CHANGELOG.md).
