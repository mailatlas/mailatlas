# Contributing

The most useful contributions in this repository are parser quality improvements, storage and
export correctness, CLI behavior, packaging hardening, and tests that keep the core package easy to
reason about.

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
make bootstrap-python
```

The editable install exposes `mailatlas` directly, so development commands should not need `PYTHONPATH=src`.

## Development Workflow

- Prefer small, reviewable pull requests.
- Add or update tests when parser behavior changes.
- Keep core README examples in sync with the CLI and Python API.
- Prefer the root `Makefile` targets over ad hoc one-off commands so local and CI workflows stay aligned.
- Route usage questions and bug reports through the guidance in [`SUPPORT.md`](./SUPPORT.md).

Docs, examples, and the larger synthetic fixture corpus live in separate repositories:

- docs site: [`mailatlas/mailatlas.dev`](https://github.com/mailatlas/mailatlas.dev)
- examples: [`mailatlas/examples`](https://github.com/mailatlas/examples)
- sample data: [`mailatlas/sample-data`](https://github.com/mailatlas/sample-data)

## Tests

```bash
make test
```

For packaging smoke checks:

```bash
make smoke-release
```

For the end-to-end local self-check:

```bash
make doctor
```

## Pull Requests

- Explain the user-visible behavior change.
- Note any schema, storage, or fixture changes explicitly.
- If the change affects public docs, update the docs site repository in a companion PR.

## Release Policy

MailAtlas is currently alpha.
Breaking changes are acceptable when they improve the ingestion core, but they should land with
tests, README or docs updates, and a short note in [`CHANGELOG.md`](./CHANGELOG.md).
