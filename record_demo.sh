#!/bin/bash
# record_demo.sh
# Records a demo of the ProductHunt → Feishu sync and outputs assets/demo.gif
# Run once from the project directory: bash record_demo.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CAST_FILE="$SCRIPT_DIR/assets/demo.cast"
GIF_FILE="$SCRIPT_DIR/assets/demo.gif"

echo "🎬 Recording demo — this will run the actual sync once."
echo "   Output will be saved to assets/demo.gif"
echo ""

# Check dependencies
if ! command -v asciinema &>/dev/null; then
  echo "❌ asciinema not found. Install with: brew install asciinema"; exit 1
fi
if ! command -v agg &>/dev/null; then
  echo "❌ agg not found. Install with: brew install agg"; exit 1
fi

# Activate venv if present
if [ -f "$SCRIPT_DIR/venv/bin/activate" ]; then
  source "$SCRIPT_DIR/venv/bin/activate"
elif [ -f "$SCRIPT_DIR/.venv/bin/activate" ]; then
  source "$SCRIPT_DIR/.venv/bin/activate"
fi

# Record
COLUMNS=120 LINES=40 asciinema rec "$CAST_FILE" \
  --title "ProductHunt Weekly → Feishu Bitable Sync" \
  --command "python $SCRIPT_DIR/wokflow.py --once" \
  --overwrite

# Convert to GIF
echo ""
echo "🎨 Converting to GIF..."
agg --cols 120 --rows 40 --font-size 14 \
    --speed 1.5 \
    "$CAST_FILE" "$GIF_FILE"

echo ""
echo "✅ Done! GIF saved to: $GIF_FILE"
echo "   Now run: git add assets/demo.gif assets/demo.cast && git commit -m 'Add demo GIF' && git push"
