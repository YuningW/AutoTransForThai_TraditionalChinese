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
# Free, open-source (SIL OFL) Traditional Chinese caption fonts, installed for this user only
G=https://github.com/google/fonts/raw/main/ofl
mkdir -p "$HOME/Library/Fonts"
for u in "$G/huninn/Huninn-Regular.ttf" "$G/lxgwwenkaitc/LXGWWenKaiTC-Regular.ttf" "$G/lxgwwenkaitc/LXGWWenKaiTC-Bold.ttf" \
         "$G/iansui/Iansui-Regular.ttf" "$G/chironheihk/ChironHeiHK%5Bwght%5D.ttf" "$G/notoseriftc/NotoSerifTC%5Bwght%5D.ttf" \
         "$G/cactusclassicalserif/CactusClassicalSerif-Regular.ttf" \
         "https://github.com/Chenyu-otf/chenyuluoyan_thin/releases/download/v2.0/ChenYuluoyan-2.0-Thin.ttf" \
         "$G/chirongoroundtc/ChironGoRoundTC%5Bwght%5D.ttf" "$G/lxgwmarkergothic/LXGWMarkerGothic-Regular.ttf" \
         "$G/chocolateclassicalsans/ChocolateClassicalSans-Regular.ttf" "$G/wdxllubrifonttc/WDXLLubrifontTC-Regular.ttf" \
         "https://github.com/max32002/JasonHandWritingFonts/raw/main/tw/JasonHandwriting1-Regular.ttf" \
         "https://raw.githubusercontent.com/ACh-K/Cubic-11/main/fonts/ttf/Cubic_11.ttf"; do
  f="$HOME/Library/Fonts/$(basename "$u" | sed 's/%5B/[/;s/%5D/]/')"
  [ -f "$f" ] || curl -sfL -o "$f" "$u" || echo "Couldn't download $(basename "$f") (optional)"
done
# 源泉圓體 comes as a zip of weights: keep regular and bold
if [ ! -f "$HOME/Library/Fonts/GenSenRounded2TW-R.otf" ]; then
  t=$(mktemp -d)
  curl -sfL -o "$t/g.zip" https://github.com/ButTaiwan/gensen-font/releases/download/v2.100/GenSenRounded2TW-otf.zip &&
    unzip -q -o -j "$t/g.zip" "*GenSenRounded2TW-R.otf" "*GenSenRounded2TW-B.otf" -d "$HOME/Library/Fonts" ||
    echo "Couldn't download GenSen Rounded (optional)"
  rm -rf "$t"
fi
command -v claude >/dev/null || [ -x "$HOME/.local/bin/claude" ] || \
  echo "Note: install Claude Code (https://claude.com/claude-code) and sign in once; AutoCaption uses it to translate."
echo "Ready. Double-click AutoCaption.command (or run ./AutoCaption.command) to start."
