#!/bin/bash
# Double-click this file in Finder to sync the audio in THIS folder.
# It processes whatever folder this file lives in.
cd "$(dirname "$0")" || exit 1

echo "======================================================"
echo "  AutoSync — syncing audio in: $(pwd)"
echo "======================================================"

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo
  echo "ffmpeg is not installed. Install it first with:"
  echo "    brew install ffmpeg"
  echo
  read -r -p "Press Enter to close."
  exit 1
fi

python3 autosync.py "$(pwd)"
status=$?

echo
if [ $status -eq 0 ]; then
  echo "Finished. Your *_synced.mp4 is in this folder."
else
  echo "Something went wrong (exit $status). See the messages above."
fi
read -r -p "Press Enter to close."
