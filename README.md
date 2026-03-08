# MailAtlas

**MailAtlas turns email files and manually synced IMAP folders into cleaned text, HTML, assets, metadata, and exportable artifacts for applications.**

MailAtlas has two input paths:

- ingest email files already on disk with `ingest eml` and `ingest mbox`
- connect to a live mailbox with `sync imap` and fetch selected folders manually

An `mbox` file is a mailbox file on disk. It is not the same thing as IMAP sync.

MailAtlas produces:

- cleaned body text
- normalized HTML snapshots when the message contains HTML
- extracted inline images and attachments
- document metadata and provenance
- JSON, Markdown, HTML, and PDF exports from stored documents
- manual, incremental IMAP sync into the same local store

It is built for engineers who need email to become reusable application data for retrieval, agents,
analytics, or archival systems.

## Why MailAtlas

- Turn raw email into cleaned text, HTML, assets, and metadata.
- Preserve provenance, forwarded chains, and inline images.
- Apply configurable cleaning for boilerplate, wrappers, footer noise, and link-only lines.
- Export JSON, Markdown, HTML, and PDF artifacts from stored documents.
- Manually sync selected IMAP folders without storing mailbox credentials in the workspace.
- Start with the built-in filesystem + SQLite defaults, then move the outputs into your own systems if needed.

## Install

### `pip`

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

After that, use the `mailatlas` command directly. You should not need `PYTHONPATH=src`.

If you want the example API as well:

```bash
python -m pip install -e ".[api]"
```

### `uv`

```bash
python3.12 -m pip install uv
uv tool install --from . mailatlas
```

### `brew`

The tap workflow is prepared in [`packaging/homebrew`](./packaging/homebrew), but the public tap should wait until the repo and first tagged release exist.

Expected release path:

```bash
brew tap chiragagrawal/mailatlas
brew install mailatlas
```

## 60-Second Quickstart

Ingest the synthetic `.eml` fixtures shipped with the repo:

```bash
mailatlas ingest eml \
  data/fixtures/atlas-market-map.eml \
  data/fixtures/atlas-founder-forward.eml \
  data/fixtures/atlas-inline-chart.eml \
  --db .mailatlas/store.db \
  --workspace .mailatlas/workspace
```

List the stored documents:

```bash
mailatlas list \
  --db .mailatlas/store.db \
  --workspace .mailatlas/workspace
```

Export one document as JSON:

```bash
mailatlas export <document-id> \
  --format json \
  --out ./document.json \
  --db .mailatlas/store.db \
  --workspace .mailatlas/workspace
```

Export the same document as a PDF artifact:

```bash
mailatlas export <document-id> \
  --format pdf \
  --out ./document.pdf \
  --db .mailatlas/store.db \
  --workspace .mailatlas/workspace
```

PDF export uses Chrome or Chromium. Set `MAILATLAS_PDF_BROWSER` if the executable is not on the default path.

Run the demo API:

```bash
uvicorn app:api --reload --port 5001
```

The demo API requires the `.[api]` extra.

## Core Use Cases

- Build a retrieval corpus from mailbox exports.
- Feed agents cleaned email text without losing links to raw messages and attachments.
- Generate reviewable PDF artifacts from stored HTML or cleaned text fallback.
- Normalize inbound email for analytics, retention, or archival workflows.
- Inspect and test parser behavior against known synthetic fixtures.

## CLI Example

```bash
mailatlas ingest mbox data/fixtures/atlas-demo.mbox \
  --db .mailatlas/store.db \
  --workspace .mailatlas/workspace
```

Manual IMAP sync is incremental by folder and stores only non-secret cursor state:

```bash
export MAILATLAS_IMAP_HOST=imap.example.com
export MAILATLAS_IMAP_USERNAME=user@example.com
export MAILATLAS_IMAP_PASSWORD=app-password

mailatlas sync imap \
  --folder INBOX \
  --folder Newsletters \
  --db .mailatlas/store.db \
  --workspace .mailatlas/workspace
```

Parser cleanup is configurable:

```bash
mailatlas ingest eml data/fixtures/atlas-founder-forward.eml \
  --no-strip-forwarded-headers \
  --no-strip-boilerplate \
  --db .mailatlas/store.db \
  --workspace .mailatlas/workspace
```

## Python API Example

```python
from mailatlas import ImapSyncConfig, MailAtlas, ParserConfig

atlas = MailAtlas(
    db_path=".mailatlas/store.db",
    workspace_path=".mailatlas/workspace",
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
| Inbox connectors | Convenient ad hoc question answering | Deterministic ingestion, reusable outputs, traceable source data |
| Generic parsers | Basic MIME parsing | Cleaned text, HTML snapshots, assets, metadata conventions |
| One-off scripts | Fast for a narrow task | Better repeatability, packaging, examples, docs, and release path |

## Docs And Examples

- [Installation guide](./site/src/content/docs/getting-started/installation.md)
- [Quickstart walkthrough](./site/src/content/docs/getting-started/quickstart.md)
- [Workspace model](./site/src/content/docs/concepts/workspace-model.md)
- [Document schema](./site/src/content/docs/concepts/document-schema.md)
- [Parser cleaning config](./site/src/content/docs/config/parser-cleaning.md)
- [Why not connectors?](./site/src/content/docs/marketing/why-not-connectors.md)
- [Marketing plan](./MARKETING_PLAN.md)
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
