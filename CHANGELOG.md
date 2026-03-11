# Changelog

All notable changes to MailAtlas are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning stays
semantic, but the project is still in alpha and may ship breaking changes between minor releases.

## [Unreleased]

## [0.2.0]

### Added

- Markdown export bundles for AI-oriented review workflows.
- `mailatlas doctor` and a simpler local developer command surface via `make`.
- Release hardening for artifact staging and Homebrew formula rendering.
- `SUPPORT.md`, issue-template routing, and Dependabot configuration for public repo maintenance.
- `RELEASING.md` with PyPI Trusted Publishing and Homebrew tap setup instructions.

### Changed

- Simplified the public CLI to the core commands: `ingest`, `list`, `get`, and `sync`.
- Unified local storage around the `.mailatlas` root model with `MAILATLAS_HOME` and `--root`.
- Refreshed the README, installation docs, quickstart, IMAP guide, examples, and landing page to
  match the current alpha product.
- Tightened CI with high-coverage test enforcement and end-to-end checks for documented CLI
  behavior.
- Simplified the local developer workflow.
- README, contribution docs, installation docs, and packaging notes now describe the current alpha
  release posture without pre-launch wording.
- Package metadata now links directly to the changelog, support policy, code of conduct, and
  security policy.
- The tag-based release workflow now publishes to PyPI and can update a dedicated Homebrew tap
  when the required GitHub variable and secret are configured.

### Removed

- The experimental `brief` feature and its AI-provider surface from the public product.
- The broken GitHub Pages deploy workflow from the repository.

## [0.1.0]

### Added

- Initial alpha release of the MailAtlas CLI, Python API, docs site, synthetic fixtures, and
  release packaging helpers.
