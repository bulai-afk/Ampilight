#!/bin/bash
cd "$(dirname "$0")"
if [ -x "$HOME/.pyenv/versions/3.11.9/bin/python3" ]; then
  PY="$HOME/.pyenv/versions/3.11.9/bin/python3"
elif command -v python3.11 >/dev/null 2>&1; then
  PY="python3.11"
else
  PY="python3"
fi
exec "$PY" -m app
