# Contributing

The most useful contributions right now are parser quality improvements, fixture coverage,
packaging hardening, docs clarity, and integration examples that keep the ingestion core easy to
reason about.

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
make bootstrap-python
```

The editable install exposes `mailatlas` directly, so development commands should not need `PYTHONPATH=src`.

If you are changing the docs site too:

```bash
make bootstrap-docs
```

## Development Workflow

- Keep fixtures synthetic and safe to publish.
- Prefer small, reviewable pull requests.
- Add or update tests when parser behavior changes.
- Keep the CLI and Python API examples in sync with docs.
- Prefer the root `Makefile` targets over ad hoc one-off commands so local and CI workflows stay aligned.
- Route usage questions and bug reports through the guidance in [`SUPPORT.md`](./SUPPORT.md).

## Tests

```bash
make test
```

For packaging smoke checks:

```bash
make smoke-release
```

If you change README copy or anything under `site/src/content`, rebuild the docs site before
opening the PR:

```bash
make docs
```

For the end-to-end local self-check and demo flows:

```bash
make doctor
make demo-cli
make demo-parser
```

## Pull Requests

- Explain the user-visible behavior change.
- Note any schema, storage, or fixture changes explicitly.
- If the change affects docs, update the README or site in the same PR.

## Release Policy

MailAtlas is currently alpha.
Breaking changes are acceptable when they improve the ingestion core, but they should land with
tests, docs updates, and a short note in [`CHANGELOG.md`](./CHANGELOG.md).
