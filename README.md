# MailAtlas

**MailAtlas turns email files and live mailboxes into cleaned text, HTML, assets, metadata, exportable artifacts, and local outbound email audit records for applications.**

MailAtlas has local email I/O paths:

- ingest email files already on disk with `ingest`
- receive Gmail or IMAP messages into the local workspace with `receive`
- keep a live mailbox current with `receive watch`
- compose and send outbound email through providers you configure at runtime with `send`
- expose local documents, outbound audit records, drafts, and gated receive/send actions through an
  optional MCP server

An `mbox` file is a mailbox file on disk. It is not the same thing as IMAP receive.

MailAtlas produces:

- cleaned body text
- normalized HTML snapshots when the message contains HTML
- extracted inline images and attachments
- document metadata and provenance
- JSON, Markdown, HTML, and PDF exports from stored documents
- Gmail API receive with local cursors and no mailbox mutation
- incremental IMAP receive into the same local store
- outbound `.eml` snapshots, body files, attachment copies, provider status, and retry metadata

MailAtlas is a library and CLI for parsing, receiving, storing, exporting, sending through
configured providers, and auditing email for AI agents, retrieval systems, analytics pipelines,
and archival systems. It is not a hosted deliverability service, inbox client, or cloud mailbox
connector.

## Why MailAtlas

- Turn raw email into cleaned text, HTML, inline images, file attachments, and metadata.
- Preserve provenance, forwarded chains, inline images, and regular attachments.
- Apply configurable cleaning for boilerplate, wrappers, footer noise, and link-only lines.
- Export JSON, Markdown, HTML, and PDF artifacts from stored documents.
- Receive Gmail messages with a read-only OAuth token and store them in the same local workspace.
- Receive selected IMAP folders without storing mailbox credentials in the local store.
- Send through SMTP or Cloudflare Email Service using runtime credentials without storing provider secrets.
- Keep a local audit trail of outbound drafts, dry runs, sends, failures, BCC recipients, and attachments.
- Start with the built-in filesystem and SQLite store, then copy the resulting files and metadata into your own storage stack if needed.

## Project Status

MailAtlas is currently alpha. Expect the CLI, stored schema, and release tooling to keep
improving, but the repository is set up for public contribution with CI, release artifacts, package
smoke checks, and a separate synthetic sample-data corpus.

## Install

### `pip`

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install mailatlas
mailatlas doctor
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

Use a source checkout when you want to work on the core package or contribute to the project:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
make bootstrap-python
mailatlas doctor
```

Run `make help` to see the local package command surface.

### MCP server

Install the optional MCP extra when you want an MCP-compatible client to inspect MailAtlas data or
draft email:

```bash
python -m pip install "mailatlas[mcp]"
mailatlas mcp --root .mailatlas
```

The MCP server exposes read tools for stored documents and outbound audit records, plus
`mailatlas_draft_email`. The live `mailatlas_send_email` tool and mailbox receive tools are hidden
unless you explicitly opt in.

`mailatlas_list_documents` and `mailatlas_list_outbound` accept `limit` and `offset` pagination
arguments. They return `count` and `has_more` alongside the page of results.

For MCP clients that accept server configuration as JSON, put MailAtlas settings in the server entry
instead of exporting shell variables globally:

```json
{
  "mcpServers": {
    "mailatlas": {
      "command": "mailatlas",
      "args": ["mcp", "--root", ".mailatlas", "--allow-receive"],
      "env": {
        "MAILATLAS_GMAIL_TOKEN_STORE": "auto"
      }
    }
  }
}
```

Use `--allow-send` only when the MCP client should be able to send live email:

```bash
mailatlas mcp --root .mailatlas --allow-send
```

Use the same provider environment variables as `mailatlas send` for SMTP, Cloudflare, or Gmail.
Provider secrets are consumed at runtime and are not written to the local store.

Mailbox receive tools are also hidden by default. Enable them only when the MCP client should be able
to contact a provider and write private email into the local workspace:

```bash
mailatlas mcp --root .mailatlas --allow-receive
```

The older process environment switches still work for MCP client configs that prefer `env` over
arguments: `MAILATLAS_MCP_ALLOW_SEND=1`, `MAILATLAS_MCP_ALLOW_RECEIVE=1`, and
`MAILATLAS_MCP_RECEIVE_ON_READ=1`. Set `MAILATLAS_MCP_RECEIVE_ON_READ=1` only if read tools should
run one receive pass before listing documents. Without that setting, MCP read tools use only messages
already stored locally.

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
- receive account, cursor, and run rows in `store.db`

Set `MAILATLAS_HOME` once if you want MailAtlas to reuse a different root automatically:

```bash
export MAILATLAS_HOME="$PWD/.mailatlas"
```

You can also override the root per command with `--root`.

## Next Steps

- Use the [Quickstart walkthrough](https://mailatlas.dev/docs/getting-started/quickstart/) for the file-based path.
- Use [IMAP Receive](https://mailatlas.dev/docs/getting-started/manual-imap-sync/) when MailAtlas should connect to a live mailbox.
- Use the [CLI overview](https://mailatlas.dev/docs/cli/overview/) for the full command surface.
- Use [mailatlas/sample-data](https://github.com/mailatlas/sample-data) for synthetic `.eml` and `.mbox` fixtures.
- Use [mailatlas/examples](https://github.com/mailatlas/examples) for runnable demos and integration examples.

## Core Use Cases

- Build a retrieval corpus from mailbox exports.
- Feed agents cleaned email text without losing links to raw messages and attachments.
- Generate reviewable PDF artifacts from stored HTML or cleaned text fallback.
- Normalize inbound email for analytics, retention, or archival processing.
- Inspect and test parser behavior against known synthetic fixtures.

## CLI Examples

Auto-detect and ingest an `mbox` archive:

```bash
git clone https://github.com/mailatlas/sample-data
mailatlas ingest sample-data/fixtures/mbox/atlas-demo.mbox
```

IMAP receive is incremental by folder and stores only non-secret cursor state:

```bash
export MAILATLAS_IMAP_HOST=imap.example.com
export MAILATLAS_IMAP_USERNAME=user@example.com
export MAILATLAS_IMAP_ACCESS_TOKEN=oauth-access-token

mailatlas receive \
  --provider imap \
  --folder INBOX \
  --folder Newsletters
```

MailAtlas consumes the access token you already have. It does not run a browser login flow or act
as your OAuth client.

Run foreground polling when you want IMAP folders to stay current:

```bash
mailatlas receive watch \
  --provider imap \
  --folder INBOX \
  --interval 60
```

Parser cleanup is configurable:

```bash
mailatlas ingest sample-data/fixtures/eml/atlas-founder-forward.eml \
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
Google OAuth desktop client, then authorize MailAtlas once. The default Gmail auth capability is
send-only for compatibility:

```bash
python -m pip install "mailatlas[keychain]"

mailatlas auth gmail \
  --client-id "$MAILATLAS_GMAIL_CLIENT_ID" \
  --client-secret "$MAILATLAS_GMAIL_CLIENT_SECRET" \
  --email user@gmail.com

mailatlas auth status gmail
```

To receive Gmail, request the read-only receive capability:

```bash
mailatlas auth gmail \
  --client-id "$MAILATLAS_GMAIL_CLIENT_ID" \
  --client-secret "$MAILATLAS_GMAIL_CLIENT_SECRET" \
  --email user@gmail.com \
  --capability receive
```

Use `--capability send,receive` when the same local token should support both Gmail send and Gmail
receive.

Then send through the Gmail API:

```bash
mailatlas send \
  --provider gmail \
  --from user@gmail.com \
  --to user@gmail.com \
  --subject "Gmail API test" \
  --text "Sent with Gmail API OAuth."
```

Receive a bounded Gmail pass into the local workspace:

```bash
mailatlas receive \
  --provider gmail \
  --label INBOX \
  --limit 50
```

Run foreground polling when you want the workspace to stay current:

```bash
mailatlas receive watch \
  --provider gmail \
  --label INBOX \
  --interval 60
```

Inspect local receive accounts, cursors, and recent runs:

```bash
mailatlas receive status
```

MailAtlas stores Gmail OAuth tokens outside the workspace by default and never writes them to
`store.db`, raw snapshots, logs, or JSON send/receive results. Received raw messages, normalized
bodies, assets, and exports are local private data. Revoke the local token with:

```bash
mailatlas auth logout gmail
```

When the `keychain` extra is installed, local CLI auth stores Gmail OAuth token material in the
operating system keychain by default. Without that extra, MailAtlas falls back to a user config
token file. Use `--token-file` for throwaway tests, `--token-store file` to force the config file,
or `--token-store keychain` to require keychain storage. `MAILATLAS_GMAIL_TOKEN_FILE` selects a
file store when no token store is passed explicitly.

Backend applications should store Gmail refresh tokens in their own encrypted credential store and
pass short-lived access tokens to `SendConfig(provider="gmail", gmail_access_token="...")` or
`ReceiveConfig(gmail_access_token="...")`.

## Python API Example

```python
from mailatlas import MailAtlas, OutboundMessage, ParserConfig, ReceiveConfig, SendConfig

atlas = MailAtlas(
    db_path=".mailatlas/store.db",
    workspace_path=".mailatlas",
    parser_config=ParserConfig(strip_boilerplate=True, stop_at_footer=True),
)

parsed = atlas.parse_eml(
    "sample-data/fixtures/eml/atlas-founder-forward.eml",
)

refs = atlas.ingest_eml(
    [
        "sample-data/fixtures/eml/atlas-market-map.eml",
        "sample-data/fixtures/eml/atlas-inline-chart.eml",
    ],
)

imap_receive_result = atlas.receive(
    ReceiveConfig(
        provider="imap",
        imap_host="imap.example.com",
        imap_username="user@example.com",
        imap_password="app-password",
        imap_folders=("INBOX", "Newsletters"),
    )
)

receive_result = atlas.receive(
    ReceiveConfig(
        gmail_access_token="ya29...",
        gmail_label="INBOX",
        limit=50,
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
- `store.db` for the SQLite index, receive accounts, receive cursors, receive runs, IMAP receive cursors, and outbound send records

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

- [Documentation](https://mailatlas.dev/docs)
- [Installation guide](https://mailatlas.dev/docs/getting-started/installation/)
- [Quickstart walkthrough](https://mailatlas.dev/docs/getting-started/quickstart/)
- [IMAP Receive](https://mailatlas.dev/docs/getting-started/manual-imap-sync/)
- [CLI overview](https://mailatlas.dev/docs/cli/overview/)
- [Examples repository](https://github.com/mailatlas/examples)
- [Sample data repository](https://github.com/mailatlas/sample-data)
- [Support](./SUPPORT.md)
- [Security policy](./SECURITY.md)
- [Changelog](./CHANGELOG.md)
- [Releasing](./docs/maintainers/releasing.md)
- [Code of Conduct](./CODE_OF_CONDUCT.md)
- [Contributing](./CONTRIBUTING.md)

## Development

```bash
make test
make smoke-release
make doctor
```
