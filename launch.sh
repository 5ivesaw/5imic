#!/usr/bin/env bash
# One-command source bootstrap. No sudo, no system Python modifications.
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3.10+ is required for the source launcher." >&2
  exit 1
fi
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
if ! .venv/bin/python -m pip show 5imic >/dev/null 2>&1; then
  .venv/bin/python -m pip install .
fi
exec .venv/bin/python -m fiveimic "$@"
