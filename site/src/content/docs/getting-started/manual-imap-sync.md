---
title: Manual IMAP Sync
description: Connect MailAtlas to a live mailbox and fetch selected IMAP folders into the local workspace.
slug: docs/getting-started/manual-imap-sync
---

Use this guide when the messages are still in a live mailbox and you want MailAtlas to fetch
selected folders over IMAP. If you already have `.eml` files or an `mbox` file on disk, use the
file-based [Quickstart](/docs/getting-started/quickstart/) instead.

This is a manual sync command, not a background connector. You run it when you want to pull from a
mailbox. MailAtlas stores sync cursors in SQLite so later runs can continue incrementally.

## Before you start

- You need an existing MailAtlas install.
- Choose one auth mode: password or OAuth access token.
- Decide which folders to fetch. `INBOX` is the default.
- MailAtlas stores IMAP sync state in SQLite. It does not persist mailbox credentials.
- Bring your own OAuth token if your provider requires OAuth. MailAtlas consumes the access token;
  it does not run a browser login flow or manage refresh tokens for you.

## 1. Set connection details

### Password auth

```bash
export MAILATLAS_IMAP_HOST=imap.example.com
export MAILATLAS_IMAP_USERNAME=user@example.com
export MAILATLAS_IMAP_PASSWORD=app-password
```

### OAuth token auth

```bash
export MAILATLAS_IMAP_HOST=imap.example.com
export MAILATLAS_IMAP_USERNAME=user@example.com
export MAILATLAS_IMAP_ACCESS_TOKEN=oauth-access-token
```

This is the recommended path when your provider or your application stack already uses OAuth. Keep
the token acquisition flow in your own auth layer or token broker, then pass the access token to
MailAtlas at runtime.

## 2. Sync one or more folders

```bash
mailatlas sync imap \
  --auth password \
  --folder INBOX \
  --folder Newsletters \
  --db .mailatlas/store.db \
  --workspace .mailatlas/workspace
```

If you are using OAuth, change `--auth password` to `--auth xoauth2`.

You can also pass `--access-token ...` directly on the command line instead of using an environment
variable, but env vars or another local secret source are usually easier to avoid shell history.

## 3. Read the sync summary

`sync imap` prints one JSON object that summarizes the run and then lists each folder result:

```json
{
  "status": "ok",
  "host": "imap.example.com",
  "port": 993,
  "username": "user@example.com",
  "auth": "password",
  "folder_count": 1,
  "error_count": 0,
  "fetched_count": 12,
  "ingested_count": 11,
  "duplicate_count": 1,
  "folders": [
    {
      "folder": "INBOX",
      "status": "ok",
      "uidvalidity": "11",
      "last_uid": 4812,
      "fetched_count": 12,
      "ingested_count": 11,
      "duplicate_count": 1,
      "document_refs": [
        {
          "id": "<document-id>",
          "subject": "Daily market digest",
          "source_kind": "imap",
          "created_at": "<timestamp>"
        }
      ],
      "error": null
    }
  ]
}
```

Use the returned `document_refs[].id` values with `mailatlas show` or `mailatlas export`.

## 4. Inspect or export stored documents

```bash
mailatlas list \
  --db .mailatlas/store.db \
  --workspace .mailatlas/workspace

mailatlas show <document-id> \
  --db .mailatlas/store.db \
  --workspace .mailatlas/workspace
```

## Incremental reruns

When you rerun the same folder sync against the same `--db`, MailAtlas uses stored IMAP cursor
state to fetch only newer messages when possible. If you point the command at a different database,
you start a fresh sync history.

## OAuth developer story

MailAtlas is OAuth-compatible, but it is not your OAuth client. The intended setup is:

- your product or local tooling obtains an access token
- MailAtlas receives that token with `MAILATLAS_IMAP_ACCESS_TOKEN` or `--access-token`
- MailAtlas uses XOAUTH2 to authenticate the IMAP session

This keeps provider-specific login UX, consent, token refresh, and secure token storage outside
MailAtlas itself.

## Parser cleaning during sync

`sync imap` accepts the same cleaning flags as file ingest, including:

- `--strip-forwarded-headers`
- `--strip-boilerplate`
- `--strip-link-only-lines`
- `--stop-at-footer`
- `--strip-invisible-chars`
- `--normalize-whitespace`

See [Parser Cleaning](/docs/config/parser-cleaning/) for behavior and tradeoffs.

## Next step

- Use [CLI Overview](/docs/cli/overview/) for the rest of the command surface.
- Use [Document Schema](/docs/concepts/document-schema/) to inspect the stored document schema.
- Use [Security and Privacy](/docs/marketing/security-and-privacy/) for storage and sharing guidance.
