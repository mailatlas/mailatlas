from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"


def _run(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(args, cwd=cwd or ROOT, check=True)


def main() -> int:
    wheel = next(DIST.glob("mailatlas-*.whl"), None)
    sdist = next(DIST.glob("mailatlas-*.tar.gz"), None)
    if not wheel or not sdist:
        raise SystemExit("Build artifacts not found in dist/. Run `python -m build` first.")

    with tempfile.TemporaryDirectory() as temp_dir:
        venv_path = Path(temp_dir) / "venv"
        python_bin = venv_path / "bin" / "python"
        pip_bin = venv_path / "bin" / "pip"
        cli_bin = venv_path / "bin" / "mailatlas"
        shutil.copytree(ROOT / "data" / "fixtures", Path(temp_dir) / "fixtures")

        _run(sys.executable, "-m", "venv", venv_path.as_posix())
        _run(pip_bin.as_posix(), "install", wheel.as_posix())
        _run(python_bin.as_posix(), "-c", "import mailatlas")
        _run(cli_bin.as_posix(), "--help")
        _run(
            cli_bin.as_posix(),
            "ingest",
            str(Path(temp_dir) / "fixtures" / "atlas-market-map.eml"),
            "--root",
            str(Path(temp_dir) / ".mailatlas"),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
