#!/bin/zsh

set -euo pipefail

if [[ $# -lt 2 || $# -gt 4 ]]; then
  echo "usage: $0 OUTPUT_PATH URL [WINDOW_SIZE] [SCALE_FACTOR]" >&2
  exit 1
fi

output_path="$1"
url="$2"
window_size="${3:-1600,1600}"
scale_factor="${4:-2}"

exec "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless \
  --disable-gpu \
  --force-device-scale-factor="${scale_factor}" \
  --window-size="${window_size}" \
  --screenshot="${output_path}" \
  "${url}"
