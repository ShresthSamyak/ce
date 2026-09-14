#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
    echo "Local environment missing. Run ./setup.sh first." >&2
    exit 1
fi
echo "Open http://127.0.0.1:8000 in this computer's browser."
exec .venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
