#!/bin/bash
cd "$(dirname "$0")"
if [ -x "$HOME/.pyenv/versions/3.11.9/bin/python3" ]; then
  PY="$HOME/.pyenv/versions/3.11.9/bin/python3"
else
  PY="python3"
fi
"$PY" -u board_status.py
echo
read -r -p "Enter, чтобы закрыть окно..."
