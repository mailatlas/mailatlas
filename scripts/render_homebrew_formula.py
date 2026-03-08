from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


FORMULA_TEMPLATE = """class Mailatlas < Formula
  include Language::Python::Virtualenv

  desc "Local-first email ingestion for AI and data workflows"
  homepage "https://mailatlas.dev"
  url "https://github.com/{owner}/mailatlas/archive/refs/tags/v{version}.tar.gz"
  sha256 "{sha256}"
  license "MIT"

  depends_on "python@3.12"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "mailatlas", shell_output("#{{bin}}/mailatlas --help")
  end
end
"""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(65536):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Render the MailAtlas Homebrew formula for a tagged release.")
    parser.add_argument("--owner", required=True, help="GitHub owner for the release tarball URL.")
    parser.add_argument("--version", required=True, help="Release version without the leading v.")
    parser.add_argument("--sdist", required=True, help="Path to the source distribution tarball.")
    parser.add_argument("--output", required=True, help="Where to write the rendered formula.")
    args = parser.parse_args()

    sdist_path = Path(args.sdist).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        FORMULA_TEMPLATE.format(owner=args.owner, version=args.version, sha256=_sha256(sdist_path)),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
