# Homebrew Packaging

MailAtlas should ship through a dedicated tap:

- tap repo: `chiragagrawal/homebrew-mailatlas`
- formula name: `mailatlas`

This repository contains:

- `mailatlas.rb`: the formula template
- `scripts/render_homebrew_formula.py`: the release helper that stamps version, owner, and SHA256

Recommended release flow:

1. Tag a release in the main repo.
2. Build the source distribution.
3. Render the formula with the matching version and SHA256.
4. Copy the rendered formula into the tap repo.
5. Run `brew audit --strict --formula ./mailatlas.rb` inside the tap repo.
