# MailAtlas

**MailAtlas turns email files and manually synced IMAP folders into cleaned text, HTML, assets, metadata, and exportable artifacts for applications.**

MailAtlas has two input paths:

- ingest email files already on disk with `ingest`
- connect to a live mailbox with `sync` and fetch selected folders manually

An `mbox` file is a mailbox file on disk. It is not the same thing as IMAP sync.

MailAtlas produces:

- cleaned body text
- normalized HTML snapshots when the message contains HTML
- extracted inline images and attachments
- document metadata and provenance
- JSON, Markdown, HTML, and PDF exports from stored documents
- manual, incremental IMAP sync into the same local store

MailAtlas is a library and CLI for parsing, storing, and exporting email for AI agents, retrieval
systems, analytics pipelines, and archival systems.

## Why MailAtlas

- Turn raw email into cleaned text, HTML, inline images, file attachments, and metadata.
- Preserve provenance, forwarded chains, inline images, and regular attachments.
- Apply configurable cleaning for boilerplate, wrappers, footer noise, and link-only lines.
- Export JSON, Markdown, HTML, and PDF artifacts from stored documents.
- Manually sync selected IMAP folders without storing mailbox credentials in the local store.
- Start with the built-in filesystem and SQLite store, then copy the resulting files and metadata into your own storage stack if needed.

## Project Status

MailAtlas is currently alpha. Expect the CLI, stored schema, and release tooling to keep
improving, but the repository is set up for public contribution with synthetic fixtures, CI, release
artifacts, and package smoke checks.

## Install

### `pip`

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install mailatlas
```

After that, use the `mailatlas` command directly.

If you want the optional API extra from PyPI:

```bash
python -m pip install "mailatlas[api]"
```

### `uv`

```bash
python3.12 -m pip install uv
uv tool install mailatlas
```

### `brew`

```bash
brew tap mailatlas/mailatlas
brew install mailatlas
```

If Homebrew resolves a different formula named `mailatlas`, use:

```bash
brew install mailatlas/mailatlas/mailatlas
```

### From source

Use a source checkout when you want to run the shipped fixtures, the demo API, or contribute to
the project:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

## Local Store

By default, MailAtlas writes to `.mailatlas` in the current directory:

- `store.db`
- `raw/`
- `html/`
- `assets/`
- `exports/`

Set `MAILATLAS_HOME` once if you want MailAtlas to reuse a different root automatically:

```bash
export MAILATLAS_HOME="$PWD/.mailatlas"
```

You can also override the root per command with `--root`.

## 60-Second Quickstart

Ingest the synthetic fixtures shipped with the repo:

```bash
export MAILATLAS_HOME="$PWD/.mailatlas"

mailatlas ingest \
  data/fixtures/atlas-market-map.eml \
  data/fixtures/atlas-founder-forward.eml \
  data/fixtures/atlas-inline-chart.eml
```

List the stored documents:

```bash
mailatlas list
```

Read one document as JSON:

```bash
mailatlas get <document-id>
```

Write the same document to a JSON file:

```bash
mailatlas get <document-id> \
  --format json \
  --out ./document.json
```

Export the same document as a PDF artifact:

```bash
mailatlas get <document-id> \
  --format pdf \
  --out ./document.pdf
```

PDF export uses Chrome or Chromium. Set `MAILATLAS_PDF_BROWSER` if the executable is not on the default path.

Run the demo API:

```bash
uvicorn app:api --reload --port 5001
```

The demo API is intended for a source checkout and requires the `.[api]` extra.

## Core Use Cases

- Build a retrieval corpus from mailbox exports.
- Feed agents cleaned email text without losing links to raw messages and attachments.
- Generate reviewable PDF artifacts from stored HTML or cleaned text fallback.
- Normalize inbound email for analytics, retention, or archival processing.
- Inspect and test parser behavior against known synthetic fixtures.

## CLI Examples

Auto-detect and ingest an `mbox` archive:

```bash
mailatlas ingest data/fixtures/atlas-demo.mbox
```

Manual IMAP sync is incremental by folder and stores only non-secret cursor state:

```bash
export MAILATLAS_IMAP_HOST=imap.example.com
export MAILATLAS_IMAP_USERNAME=user@example.com
export MAILATLAS_IMAP_ACCESS_TOKEN=oauth-access-token

mailatlas sync \
  --folder INBOX \
  --folder Newsletters
```

MailAtlas consumes the access token you already have. It does not run a browser login flow or act
as your OAuth client.

Parser cleanup is configurable:

```bash
mailatlas ingest data/fixtures/atlas-founder-forward.eml \
  --no-strip-forwarded-headers \
  --no-strip-boilerplate
```

## Python API Example

```python
from mailatlas import ImapSyncConfig, MailAtlas, ParserConfig

atlas = MailAtlas(
    db_path=".mailatlas/store.db",
    workspace_path=".mailatlas",
    parser_config=ParserConfig(strip_boilerplate=True, stop_at_footer=True),
)

parsed = atlas.parse_eml(
    "data/fixtures/atlas-founder-forward.eml",
)

refs = atlas.ingest_eml(
    ["data/fixtures/atlas-market-map.eml", "data/fixtures/atlas-inline-chart.eml"],
)

sync_result = atlas.sync_imap(
    ImapSyncConfig(
        host="imap.example.com",
        username="user@example.com",
        password="app-password",
        folders=("INBOX", "Newsletters"),
    )
)

pdf_path = atlas.export_document(
    refs[0].id,
    format="pdf",
)
```

## Default Storage Layout

MailAtlas writes ordinary files to the filesystem and indexes them in SQLite by default:

- `raw/` for original message bytes
- `html/` for normalized HTML bodies when present
- `assets/` for extracted inline and attached files
- `exports/` for JSON, Markdown, HTML, and PDF exports
- `store.db` for the SQLite index and IMAP sync cursors

These are ordinary files and metadata rows. If you are embedding MailAtlas inside a service, you
can move them into your own blob store and database. PDF export uses headless Chrome or Chromium
against the stored HTML snapshot when one exists, and falls back to generated HTML from cleaned text otherwise.

## MailAtlas vs Alternatives

| Option | What it does well | Where MailAtlas is stronger |
| --- | --- | --- |
| Inbox connectors | Convenient ad hoc question answering | Repeatable ingestion, exported files, and traceable source records |
| Generic parsers | Basic MIME parsing | Cleaned text, HTML snapshots, assets, metadata conventions |
| One-off scripts | Fast for a narrow task | Better repeatability, packaging, examples, docs, and release path |

## Docs And Examples

- [Installation guide](./site/src/content/docs/getting-started/installation.md)
- [Quickstart walkthrough](./site/src/content/docs/getting-started/quickstart.md)
- [Manual IMAP sync](./site/src/content/docs/getting-started/manual-imap-sync.md)
- [Workspace model](./site/src/content/docs/concepts/workspace-model.md)
- [Document schema](./site/src/content/docs/concepts/document-schema.md)
- [Parser cleaning config](./site/src/content/docs/config/parser-cleaning.md)
- [Why not connectors?](./site/src/content/docs/marketing/why-not-connectors.md)
- [Support](./SUPPORT.md)
- [Security policy](./SECURITY.md)
- [Changelog](./CHANGELOG.md)
- [Releasing](./RELEASING.md)
- [Code of Conduct](./CODE_OF_CONDUCT.md)
- [Contributing](./CONTRIBUTING.md)

## Development

Run the test suite:

```bash
python -m unittest discover -s tests -v
```

Build the docs site:

```bash
cd site
npm install
npm run build
```
