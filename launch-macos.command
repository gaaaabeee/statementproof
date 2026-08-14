#!/bin/bash
# Double-click this to start statementproof.
# It runs entirely on your machine; the only socket is a loopback server.
cd "$(dirname "$0")" || exit 1

PY=""
for c in ".venv/bin/python" "$(command -v python3)" "$(command -v python)"; do
  if [ -x "$c" ] && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.9+ is required. Install it from https://python.org and try again."
  read -r -p "Press return to close."
  exit 1
fi

if ! "$PY" -c "import pypdf" 2>/dev/null; then
  echo "Installing the one dependency (pypdf)…"
  "$PY" -m pip install --quiet -r requirements.txt || {
    echo "Could not install pypdf. Try: $PY -m pip install pypdf"
    read -r -p "Press return to close."; exit 1; }
fi

exec "$PY" -u -m statementproof.app
