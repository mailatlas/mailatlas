#!/bin/zsh

set -euo pipefail

ROOT="${0:A:h:h}"
fixture="${1:-$ROOT/data/fixtures/atlas-inline-chart.eml}"
demo_root="${2:-/tmp/mailatlas-parser-demo}"
python_bin="${MAILATLAS_PYTHON:-$ROOT/.tmp-verify-312b/bin/python}"

if [[ ! -x "$python_bin" ]]; then
  python_bin="$(command -v python3)"
fi

if [[ ! -x "$python_bin" ]]; then
  echo "Python executable not found. Set MAILATLAS_PYTHON or install Python 3." >&2
  exit 1
fi

rm -rf "$demo_root"
mkdir -p "$demo_root"

"$python_bin" -c '
import json
import sys
from pathlib import Path

from mailatlas import ParserConfig, parse_eml

fixture = Path(sys.argv[1])
demo_root = Path(sys.argv[2])
document = parse_eml(fixture, parser_config=ParserConfig())
output_path = demo_root / "parsed.json"
output_path.write_text(json.dumps(document.to_dict(), indent=2), encoding="utf-8")

summary = {
    "subject": document.subject,
    "sender_email": document.sender_email,
    "author": document.author,
    "asset_count": len(document.assets),
    "has_html": document.body_html is not None,
    "output_path": output_path.as_posix(),
}
print(json.dumps(summary, indent=2))
' "$fixture" "$demo_root"
