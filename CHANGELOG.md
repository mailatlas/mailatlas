# Changelog

All notable changes to MailAtlas are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning stays
semantic, but the project is still in alpha and may ship breaking changes between minor releases.

## [Unreleased]

### Added

- `SUPPORT.md`, issue-template routing, and Dependabot configuration for public repo maintenance.
- `RELEASING.md` with PyPI Trusted Publishing and Homebrew tap setup instructions.

### Changed

- README, contribution docs, installation docs, and packaging notes now describe the current alpha
  release posture without pre-launch wording.
- CI now validates the core package on Python 3.11 and 3.12 and builds the docs site on pull
  requests.
- Package metadata now links directly to the changelog, support policy, code of conduct, and
  security policy.
- The tag-based release workflow now publishes to PyPI and can update a dedicated Homebrew tap
  when the required GitHub variable and secret are configured.

## [0.1.0]

### Added

- Initial alpha release of the MailAtlas CLI, Python API, docs site, synthetic fixtures, and
  release packaging helpers.
