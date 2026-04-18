---
title: MailAtlas Docs
description: Choose the right path for file ingest, IMAP sync, outbound email, integration, attachment handling, and storage details.
slug: docs
---

MailAtlas extracts cleaned text, HTML, assets, and metadata from email for use in your own
applications. It can also render and audit outbound email sent through providers you configure.
Pick the path based on where the email lives and what you need to do next.

<div class="docs-task-grid">
  <a class="docs-task-card" href="/docs/getting-started/quickstart/">
    <span class="docs-task-eyebrow">Start with files</span>
    <strong>Quickstart from <code>.eml</code> files</strong>
    <p>Run the shipped fixtures, inspect one stored document, and export JSON from a local store.</p>
  </a>
  <a class="docs-task-card" href="/docs/getting-started/manual-imap-sync/">
    <span class="docs-task-eyebrow">Live mailbox</span>
    <strong>Manual IMAP sync</strong>
    <p>Connect to a live mailbox, fetch selected folders, and rerun incrementally with stored cursors.</p>
  </a>
  <a class="docs-task-card" href="/docs/cli/overview/">
    <span class="docs-task-eyebrow">Command line</span>
    <strong>CLI overview</strong>
    <p>See the core commands for ingest, sync, inspect, export, and send.</p>
  </a>
  <a class="docs-task-card" href="/docs/python/overview/">
    <span class="docs-task-eyebrow">Embed it</span>
    <strong>Python API</strong>
    <p>Use parse-only calls or storage-backed APIs inside your own application code.</p>
  </a>
  <a class="docs-task-card" href="/docs/providers/gmail/">
    <span class="docs-task-eyebrow">Personal Gmail</span>
    <strong>Gmail provider</strong>
    <p>Send from Gmail with Gmail API OAuth and the narrow <code>gmail.send</code> scope.</p>
  </a>
  <a class="docs-task-card" href="/docs/concepts/document-schema/">
    <span class="docs-task-eyebrow">Inspect outputs</span>
    <strong>Document schema</strong>
    <p>Understand the normalized record structure, stored fields, and attachment or inline-asset references.</p>
  </a>
  <a class="docs-task-card" href="/docs/marketing/why-not-connectors/">
    <span class="docs-task-eyebrow">Decide if it fits</span>
    <strong>When to use MailAtlas</strong>
    <p>See where MailAtlas is a good fit and where another tool is more appropriate.</p>
  </a>
  <a class="docs-task-card" href="/docs/marketing/product-vision/">
    <span class="docs-task-eyebrow">Why it exists</span>
    <strong>Product vision</strong>
    <p>Read why MailAtlas treats mailbox access as an AI-agent interface instead of another inbox UI.</p>
  </a>
</div>

## Choose an email path

- `ingest`: use when you already have `.eml` files or an `mbox` mailbox file on disk.
- `sync`: use when MailAtlas should connect to a live mailbox and fetch selected folders incrementally.
- `send`: use when MailAtlas should render an outbound audit record and send through SMTP or Cloudflare Email Service.

An `mbox` file is a mailbox file on disk. It is not the same thing as IMAP sync. If the messages
are still in a live inbox and you want MailAtlas to read them directly, use `sync`.

## Know the terms

<div class="docs-term-grid">
  <div class="docs-term-card">
    <strong><code>.eml</code></strong>
    <p>A single email message file on disk.</p>
  </div>
  <div class="docs-term-card">
    <strong><code>mbox</code></strong>
    <p>A mailbox file on disk that can contain many messages.</p>
  </div>
  <div class="docs-term-card">
    <strong><code>sync</code></strong>
    <p>The live-mailbox path for fetching selected folders over IMAP.</p>
  </div>
  <div class="docs-term-card">
    <strong>root</strong>
    <p>The directory that holds raw email, HTML snapshots, extracted assets, exports, outbound records, and the SQLite index.</p>
  </div>
  <div class="docs-term-card">
    <strong>document</strong>
    <p>The normalized MailAtlas record you can inspect, search, and export later.</p>
  </div>
  <div class="docs-term-card">
    <strong>export</strong>
    <p>A derived JSON, Markdown, HTML, or PDF artifact written from a stored document.</p>
  </div>
  <div class="docs-term-card">
    <strong>outbound record</strong>
    <p>A local audit row plus rendered files for a draft, dry run, sent message, queued message, or failed send.</p>
  </div>
</div>

If you want copy-paste examples next, use [Ingest `.eml` files](/docs/examples/eml-ingest/) or
[Ingest an `mbox` mailbox file](/docs/examples/mbox-ingest/).
