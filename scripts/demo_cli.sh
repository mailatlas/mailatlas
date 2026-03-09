#!/bin/zsh

set -euo pipefail

ROOT="${0:A:h:h}"
fixture="${1:-$ROOT/data/fixtures/atlas-inline-chart.eml}"
demo_root="${2:-/tmp/mailatlas-clean-cli-demo}"
cli_bin="${MAILATLAS_CLI:-}"
python_bin="${MAILATLAS_PYTHON:-}"

if [[ -z "$cli_bin" && -x "$ROOT/.venv/bin/mailatlas" ]]; then
  cli_bin="$ROOT/.venv/bin/mailatlas"
fi

if [[ -z "$cli_bin" ]]; then
  cli_bin="$(command -v mailatlas || true)"
fi

if [[ -z "$python_bin" && -x "$ROOT/.venv/bin/python" ]]; then
  python_bin="$ROOT/.venv/bin/python"
fi

if [[ -z "$python_bin" ]]; then
  python_bin="$(command -v python3 || true)"
fi

if [[ ! -x "$cli_bin" ]]; then
  echo "mailatlas CLI not found. Set MAILATLAS_CLI or install the package first." >&2
  exit 1
fi

if [[ ! -x "$python_bin" ]]; then
  echo "Python executable not found. Set MAILATLAS_PYTHON or install Python 3." >&2
  exit 1
fi

rm -rf "$demo_root"
mkdir -p "$demo_root/output"

root_path="$demo_root/.mailatlas"

ingest_json="$("$cli_bin" ingest --root "$root_path" "$fixture")"
doc_id="$(printf '%s' "$ingest_json" | "$python_bin" -c 'import json, sys; print(json.load(sys.stdin)["document_refs"][0]["id"])')"
list_json="$("$cli_bin" list --root "$root_path")"
json_path="$("$cli_bin" get "$doc_id" --format json --out "$demo_root/output/document.json" --root "$root_path")"
html_path="$("$cli_bin" get "$doc_id" --format html --out "$demo_root/output/document.html" --root "$root_path")"

echo "Ingest:"
echo "$ingest_json"
echo
echo "List:"
echo "$list_json"
echo
echo "JSON:"
echo "$json_path"
echo "HTML:"
echo "$html_path"

if [[ "${MAILATLAS_SKIP_PDF:-0}" == "1" ]]; then
  exit 0
fi

pdf_path="$("$cli_bin" get "$doc_id" --format pdf --out "$demo_root/output/document.pdf" --root "$root_path")"
echo "PDF:"
echo "$pdf_path"
