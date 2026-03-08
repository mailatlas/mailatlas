# Releasing MailAtlas

This repository is set up to publish Python distributions from Git tags and to update a dedicated
Homebrew tap when the required external configuration exists.

## One-Time Setup

### PyPI

1. Create or claim the `mailatlas` project on PyPI.
2. In PyPI, add a GitHub Actions Trusted Publisher for this repository:
   - owner: your GitHub user or organization
   - repository: `mailatlas`
   - workflow: `.github/workflows/release.yml`
   - environment: `pypi`
3. In GitHub, create an environment named `pypi`.
4. Optional but recommended: repeat the same setup on TestPyPI before the first production release.

The release workflow uses `pypa/gh-action-pypi-publish` with OIDC, so no long-lived PyPI API token
is required once Trusted Publishing is configured.

### Homebrew

1. Create a tap repository named `homebrew-mailatlas` under the GitHub user or organization that
   should own the formula.
2. Add a `Formula/` directory in that tap repo.
3. In this repo, add a repository variable named `HOMEBREW_TAP_REPOSITORY` with the value
   `mailatlas/homebrew-mailatlas`.
4. In this repo, add a repository secret named `HOMEBREW_TAP_TOKEN` that can push to the tap repo.
   A fine-grained token with `Contents: Read and write` on the tap repository is sufficient.

When those are present, the release workflow will render `mailatlas.rb`, copy it into
`Formula/mailatlas.rb` in the tap repo, and push the update automatically.

## Per Release

1. Update [`CHANGELOG.md`](./CHANGELOG.md).
2. Confirm CI is green on `main`.
3. Tag the release as `vX.Y.Z` and push the tag.
4. Watch `.github/workflows/release.yml`:
   - build sdist and wheel
   - publish to PyPI
   - publish a GitHub release with the built artifacts
   - update the Homebrew tap if `HOMEBREW_TAP_REPOSITORY` and `HOMEBREW_TAP_TOKEN` are configured

## Post-Release Checks

- `python -m pip install mailatlas`
- `uv tool install mailatlas`
- `brew tap mailatlas/mailatlas`
- `brew install mailatlas`

If the tap publishes a formula that conflicts with an existing core formula, use the fully qualified
install name:

```bash
brew install mailatlas/mailatlas/mailatlas
```
