# Homebrew Packaging

This repository includes the tooling needed to publish MailAtlas through the dedicated tap repo:

- tap repo: `mailatlas/homebrew-mailatlas`
- formula name: `mailatlas`
- tap install path: `brew tap mailatlas/mailatlas`

This repository contains:

- `mailatlas.rb`: the formula template
- `scripts/render_homebrew_formula.py`: the release helper that stamps version, owner, and SHA256

Until that tap exists, the supported install paths are the `pip` and `uv` flows in the main
README.

Recommended release flow:

1. Create the tap repo as `homebrew-mailatlas` so `brew tap mailatlas/mailatlas` works.
2. Set `HOMEBREW_TAP_REPOSITORY=mailatlas/homebrew-mailatlas` as a repository variable in the main repo.
3. Set `HOMEBREW_TAP_TOKEN` as a repository secret in the main repo.
4. Tag a release in the main repo.
5. Let `.github/workflows/release.yml` build the source distribution, render `release-assets/mailatlas.rb`, and push `Formula/mailatlas.rb` into the tap repo.
6. Run `brew audit --strict --formula ./Formula/mailatlas.rb` inside the tap repo.
