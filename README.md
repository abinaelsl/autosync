# AutoSync

Drop-in **dual-system audio/video sync**. Point it at a folder containing a video
and one or more separately-recorded audio tracks (e.g. a lav mic per speaker) and
it automatically:

- finds each recording's exact time offset by **cross-correlating it against the
  video's own camera/scratch audio**,
- aligns every track to the video timeline,
- **mixes them at their natural levels** with a transparent peak limiter so
  overlaps don't clip,
- **mutes the original camera audio**,
- keeps the video stream **untouched** (lossless copy — fast),
- **self-verifies** the result by re-correlating the finished file.

No cuts. No manual clapper-finding. Output: `<videoname>_synced.mp4`.

## Quick start (the easy way)

1. Make a folder and put inside it:
   - your **video** (e.g. `C0191.MP4`)
   - each **audio recording** (e.g. `abi.m4a`, `anh.m4a`) — one or more
   - `autosync.py`
   - `run.command`
2. Double-click **`run.command`**.
3. You get `<videoname>_synced.mp4` in that folder.

> First run installs `numpy`/`scipy` into `~/.autosync_venv` automatically
> (one-time, needs internet). After that it's instant.

## Command line

```bash
python3 autosync.py /path/to/folder
python3 autosync.py /path/to/folder --dry-run          # show offsets, render nothing
python3 autosync.py /path/to/folder --video C0191.MP4  # if >1 video present
```

| Flag | Default | Purpose |
|------|---------|---------|
| `--limit` | `0.9` | Peak-protection ceiling (0–1). Lower = safer. |
| `--bitrate` | `256k` | Output AAC bitrate. |
| `--reencode` | off | Re-encode the video instead of a lossless copy (only if copy misbehaves). |
| `--no-verify` | off | Skip the final sync self-check. |

## How the sync works

Each external recording and the video's built-in audio capture the **same room**,
so their loudness envelopes share the same transient structure. AutoSync rectifies
and smooths each signal into a 1 ms-resolution envelope, then takes the FFT
cross-correlation between each recording and the video reference. The lag at the
correlation peak **is** the offset. A peak/noise sharpness score is reported as a
confidence value, and weak matches are flagged.

Positive offset → the recorder started **before** the camera (front is trimmed).
Negative offset → it started **after** (silence is padded in front).

## Requirements

- **ffmpeg** + **ffprobe** on `PATH` — `brew install ffmpeg`
- **python3** (numpy/scipy auto-installed on first run)

## Notes & limitations

- The video **must** contain an audio track — that scratch audio is the reference
  everything is matched against.
- The external recordings must share audible content with the camera audio
  (same take) for a match to be found.
- Re-runs are safe: the tool ignores its own `*_synced.mp4` output when scanning.
