# MailAtlas Marketing Plan

## Positioning

MailAtlas should be positioned as:

**Local-first email ingestion for AI and data workflows.**

Primary message:

**Connectors answer questions. MailAtlas turns email into a dataset.**

Supporting themes:

- local-first by default
- inspectable and reproducible
- provenance-aware
- built for `.eml` and `mbox`
- useful for RAG, agents, analytics, and archival pipelines

## Ideal Audience

Primary:

- AI engineers
- data engineers
- developer-tool builders working with mailbox exports or email-native corpora

Secondary:

- security and compliance teams
- self-hosted power users
- research teams building internal briefings from recurring email inputs

## SEO Targets

- email ingestion
- local-first email parser
- eml parser python
- mbox parser python
- email to json
- email dataset for ai

## Launch Assets

- polished GitHub README
- live docs site
- PyPI package
- Homebrew tap
- three example recipes
- one short demo GIF or screencast
- comparison page: MailAtlas vs connectors vs generic parsers

## Launch Sequence

### Prelaunch

- finish OSS review and synthetic fixtures
- finalize docs site and README
- verify package and release workflows
- prepare Homebrew tap repo
- create demo visuals from synthetic data only

### Launch Day

- publish `mailatlas` repo
- ship first tagged GitHub release
- publish PyPI package
- update Homebrew tap
- publish `mailatlas.dev`
- post release notes

### Distribution

- Show HN
- Lobsters
- Reddit: `r/Python`, `r/LocalLLaMA`, `r/selfhosted`
- X and LinkedIn
- direct outreach to 15-20 AI infra and data-tooling builders

## Content Angles

- How to turn `.eml` and `mbox` into structured JSON for AI workflows
- Why inbox connectors are not an ingestion layer
- Building a local-first email dataset pipeline in Python
- Preserving provenance and inline assets from messy mailbox data

## Success Metrics

Track the first 30 days with:

- GitHub stars from the target audience
- PyPI installs
- Brew installs
- docs traffic
- inbound issues and PRs
- real conversations with teams integrating MailAtlas into existing tooling
