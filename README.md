# MailAtlas

**MailAtlas turns email files and manually synced IMAP folders into cleaned text, HTML, assets, metadata, exportable artifacts, and local outbound email audit records for applications.**

MailAtlas has three local email I/O paths:

- ingest email files already on disk with `ingest`
- connect to a live mailbox with `sync` and fetch selected folders manually
- compose and send outbound email through providers you configure at runtime with `send`

An `mbox` file is a mailbox file on disk. It is not the same thing as IMAP sync.

MailAtlas produces:

- cleaned body text
- normalized HTML snapshots when the message contains HTML
- extracted inline images and attachments
- document metadata and provenance
- JSON, Markdown, HTML, and PDF exports from stored documents
- manual, incremental IMAP sync into the same local store
- outbound `.eml` snapshots, body files, attachment copies, provider status, and retry metadata

MailAtlas is a library and CLI for parsing, storing, exporting, sending through configured
providers, and auditing email for AI agents, retrieval systems, analytics pipelines, and archival
systems. It is not a hosted deliverability service or inbox client.

## Why MailAtlas

- Turn raw email into cleaned text, HTML, inline images, file attachments, and metadata.
- Preserve provenance, forwarded chains, inline images, and regular attachments.
- Apply configurable cleaning for boilerplate, wrappers, footer noise, and link-only lines.
- Export JSON, Markdown, HTML, and PDF artifacts from stored documents.
- Manually sync selected IMAP folders without storing mailbox credentials in the local store.
- Send through SMTP or Cloudflare Email Service using runtime credentials without storing provider secrets.
- Keep a local audit trail of outbound drafts, dry runs, sends, failures, BCC recipients, and attachments.
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
mailatlas doctor
```

If you want the optional API extra from PyPI:

```bash
python -m pip install "mailatlas[api]"
```

### `uv`

```bash
python3.12 -m pip install uv
uv tool install mailatlas
mailatlas doctor
```

### `brew`

```bash
brew tap mailatlas/mailatlas
brew install mailatlas
mailatlas doctor
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
make bootstrap-python
mailatlas doctor
```

If you are changing the docs site too:

```bash
make bootstrap-docs
```

Run `make help` to see the full local command surface.

## Verify The Install

```bash
mailatlas doctor
```

`mailatlas doctor` runs a temporary self-check that verifies ingest, storage, and JSON export. It
also checks PDF export when Chrome or Chromium is available, and reports a warning instead of
failing if the browser is missing.

## Local Store

By default, MailAtlas writes to `.mailatlas` in the current directory:

- `store.db`
- `raw/`
- `html/`
- `assets/`
- `exports/`
- `outbound/`

Set `MAILATLAS_HOME` once if you want MailAtlas to reuse a different root automatically:

```bash
export MAILATLAS_HOME="$PWD/.mailatlas"
```

You can also override the root per command with `--root`.

## Next Steps

- Use [Quickstart walkthrough](./site/src/content/docs/getting-started/quickstart.md) for the file-based path with the shipped fixtures.
- Use [Manual IMAP sync](./site/src/content/docs/getting-started/manual-imap-sync.md) when MailAtlas should connect to a live mailbox.
- Use [CLI overview](./site/src/content/docs/cli/overview.md) for the full command surface.

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

Render and audit an outbound message without contacting a provider:

```bash
mailatlas send \
  --dry-run \
  --from agent@example.com \
  --to user@example.com \
  --subject "Build complete" \
  --text "The build passed."
```

Send through SMTP by providing credentials at runtime:

```bash
export MAILATLAS_SEND_PROVIDER=smtp
export MAILATLAS_SMTP_HOST=smtp.example.com
export MAILATLAS_SMTP_USERNAME=agent@example.com
export MAILATLAS_SMTP_PASSWORD=app-password

mailatlas send \
  --from agent@example.com \
  --to user@example.com \
  --subject "Build complete" \
  --text "The build passed."
```

For personal Gmail addresses, prefer Gmail API OAuth instead of SMTP app passwords. Create a
Google OAuth desktop client, then authorize MailAtlas once:

```bash
mailatlas auth gmail \
  --client-id "$MAILATLAS_GMAIL_CLIENT_ID" \
  --client-secret "$MAILATLAS_GMAIL_CLIENT_SECRET" \
  --email user@gmail.com

mailatlas auth status gmail
```

Then send through the Gmail API:

```bash
mailatlas send \
  --provider gmail \
  --from user@gmail.com \
  --to user@gmail.com \
  --subject "Gmail API test" \
  --text "Sent with Gmail API OAuth."
```

MailAtlas stores Gmail OAuth tokens outside the workspace by default and never writes them to
`store.db`, raw snapshots, logs, or JSON send results. Revoke the local token with:

```bash
mailatlas auth logout gmail
```

## Python API Example

```python
from mailatlas import ImapSyncConfig, MailAtlas, OutboundMessage, ParserConfig, SendConfig

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

dry_run = atlas.send_email(
    OutboundMessage(
        from_email="agent@example.com",
        to=("user@example.com",),
        subject="Build complete",
        text="The build passed.",
        idempotency_key="build-123",
    ),
    SendConfig(provider="smtp", dry_run=True),
)

gmail_send = atlas.send_email(
    OutboundMessage(
        from_email="user@gmail.com",
        to=("user@gmail.com",),
        subject="Gmail API test",
        text="Sent with an OAuth access token.",
    ),
    SendConfig(provider="gmail", gmail_access_token="ya29..."),
)
```

## Default Storage Layout

MailAtlas writes ordinary files to the filesystem and indexes them in SQLite by default:

- `raw/` for original message bytes
- `html/` for normalized HTML bodies when present
- `assets/` for extracted inline and attached files
- `exports/` for JSON, HTML, and PDF file exports
- `outbound/raw/`, `outbound/text/`, `outbound/html/`, and `outbound/attachments/` for outbound audit artifacts
- `store.db` for the SQLite index, IMAP sync cursors, and outbound send records

These are ordinary files and metadata rows. If you are embedding MailAtlas inside a service, you
can move them into your own blob store and database. PDF export uses headless Chrome or Chromium
against the stored HTML snapshot when one exists, and falls back to generated HTML from cleaned text otherwise.
Markdown export prints to stdout by default with absolute local asset paths, or writes a
`document.md` plus copied `assets/` bundle when you pass `--out <directory>`.
Outbound provider secrets are read from CLI flags, environment variables, or explicit Python
`SendConfig` values at runtime. They are not written to SQLite, raw snapshots, logs, or JSON output.

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
- [CLI overview](./site/src/content/docs/cli/overview.md)
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

```bash
make test
make docs
make smoke-release
make demo-cli
make demo-parser
make doctor
```
