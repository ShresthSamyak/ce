#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
if ! command -v python3.12 >/dev/null 2>&1; then
    echo "Python 3.12 is required. Install python3.12 and python3.12-venv." >&2
    exit 1
fi
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r backend/requirements.txt
echo "Setup complete. Run ./run.sh."
