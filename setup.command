#!/bin/bash
# ============================================================
#  AutoSync — FIRST-TIME SETUP
#  Double-click this once. It installs everything AutoSync needs:
#    1. ffmpeg        (via Homebrew)
#    2. python3       (via Homebrew, if missing)
#    3. numpy/scipy   (into ~/.autosync_venv)
#  After this, just double-click run.command in any media folder.
# ============================================================
cd "$(dirname "$0")" || exit 1

echo "============================================================"
echo "  AutoSync — first-time setup"
echo "============================================================"
echo

# --- 1. Homebrew --------------------------------------------------
if ! command -v brew >/dev/null 2>&1; then
  # Apple Silicon installs to /opt/homebrew; pick it up if already there.
  [ -x /opt/homebrew/bin/brew ] && eval "$(/opt/homebrew/bin/brew shellenv)"
  [ -x /usr/local/bin/brew ]    && eval "$(/usr/local/bin/brew shellenv)"
fi

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is not installed (it's the macOS package manager AutoSync uses)."
  echo
  echo "Install it by copy-pasting this line into Terminal, then press Return:"
  echo
  echo '   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
  echo
  echo "When it finishes, double-click this setup.command again."
  echo
  read -r -p "Press Enter to close."
  exit 1
fi
echo "Homebrew              found"

# --- 2. ffmpeg ----------------------------------------------------
if command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1; then
  echo "ffmpeg / ffprobe      found"
else
  echo "ffmpeg                installing via Homebrew (this can take a few minutes)..."
  if ! brew install ffmpeg; then
    echo "ERROR: 'brew install ffmpeg' failed. See the messages above."
    read -r -p "Press Enter to close."
    exit 1
  fi
fi

# --- 3. python3 ---------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3               installing via Homebrew..."
  if ! brew install python; then
    echo "ERROR: 'brew install python' failed."
    read -r -p "Press Enter to close."
    exit 1
  fi
else
  echo "python3               found"
fi

# --- 4. Python libraries (numpy/scipy) ----------------------------
echo "Python libraries      preparing numpy/scipy (one-time)..."
if ! python3 autosync.py --setup; then
  echo "ERROR: could not set up the Python libraries."
  read -r -p "Press Enter to close."
  exit 1
fi

echo
echo "============================================================"
echo "  All set!"
echo
echo "  To sync a folder:"
echo "    1. Put your video + audio files together in a folder"
echo "       (along with autosync.py and run.command)."
echo "    2. Double-click run.command in that folder."
echo "============================================================"
echo
read -r -p "Press Enter to close."
