class Mailatlas < Formula
  include Language::Python::Virtualenv

  desc "Local-first email ingestion for AI and data workflows"
  homepage "https://mailatlas.dev"
  url "https://github.com/chiragagrawal/mailatlas/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "REPLACE_AT_RELEASE"
  license "MIT"

  depends_on "python@3.12"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "mailatlas", shell_output("#{bin}/mailatlas --help")
  end
end
