#!/usr/bin/env bash
# Double-click to launch the local transcriber.
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -d .venv ]]; then
  echo "First-time setup: creating Python virtualenv..."
  python3 -m venv .venv
  ./.venv/bin/pip install --quiet --upgrade pip
fi

echo "Installing/updating dependencies..."
./.venv/bin/pip install --quiet -r requirements.txt

if [[ ! -f .env ]]; then
  echo ""
  echo "  ERROR: .env file not found."
  echo "  Copy .env.example to .env and fill in your Azure Speech key + region."
  echo ""
  exit 1
fi

exec ./.venv/bin/python app.py
