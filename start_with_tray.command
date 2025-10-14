#!/usr/bin/env bash

set -o pipefail
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

PYTHON_BIN="python3"
if [[ -f ".venv/bin/activate" ]]; then
  # Activate local virtual environment when available.
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
  PYTHON_BIN="python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "Python 3 is required but not installed." >&2
  if [[ -t 0 ]]; then
    read -rp "Press Enter to close..." _
  fi
  exit 1
fi

"${PYTHON_BIN}" main.py
STATUS=$?

if [[ -t 0 ]]; then
  echo
  read -rp "Press Enter to close..." _
fi

exit "$STATUS"
