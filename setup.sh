#!/bin/bash
# One-time setup on a Mac (Apple Silicon): Homebrew ffmpeg-full + Python 3.12, then a private venv.
set -euo pipefail
cd "$(dirname "$0")"
command -v brew >/dev/null || { echo "Install Homebrew first: https://brew.sh"; exit 1; }
# ffmpeg-full has libass, which burning captions into the video needs
[ -x /opt/homebrew/opt/ffmpeg-full/bin/ffmpeg ] || brew install ffmpeg-full
PY=$(command -v python3.12 || true)
[ -n "$PY" ] || { brew install python@3.12; PY=$(command -v python3.12); }
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
command -v claude >/dev/null || [ -x "$HOME/.local/bin/claude" ] || \
  echo "Note: install Claude Code (https://claude.com/claude-code) and sign in once; AutoCaption uses it to translate."
echo "Ready. Double-click AutoCaption.command (or run ./AutoCaption.command) to start."
