#!/usr/bin/env python3
"""
autosync.py — dual-system audio sync, drop-in folder workflow.

WHAT IT DOES
  Drop this script into a folder that contains ONE video file and ONE OR MORE
  separate audio recordings (e.g. lav mics for each speaker). Run it. For each
  audio file it finds the exact time offset by cross-correlating that recording
  against the video's own (scratch/camera) audio, then:
    - aligns every audio track to the video timeline,
    - mixes them together at their natural levels (transparent peak limiter so
      overlaps don't clip),
    - mutes/removes the original camera audio,
    - keeps the video stream untouched (lossless copy, fast).
  No cuts. Output: <videoname>_synced.mp4 in the same folder.

USAGE
  Double-click  run.command          (macOS — processes the folder it lives in)
  or:           python3 autosync.py [folder]
                python3 autosync.py [folder] --dry-run     (detect + offsets only)

REQUIREMENTS
  - ffmpeg + ffprobe on PATH (brew install ffmpeg)
  - python3 (numpy/scipy are auto-installed into ~/.autosync_venv on first run)

NOTE
  The video MUST have an audio track (even rough camera sound) — that scratch
  audio is the reference everything is aligned to.
"""

import os
import sys
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

# ----------------------------------------------------------------------------
# 0. Make sure numpy/scipy are available; if not, build a managed venv and
#    re-exec this script inside it. Works from a plain `python3 autosync.py`.
# ----------------------------------------------------------------------------
def ensure_deps():
    try:
        import numpy  # noqa
        import scipy  # noqa
        return
    except ImportError:
        pass
    venv_dir = Path.home() / ".autosync_venv"
    vpy = venv_dir / "bin" / "python"
    # Are we ALREADY running inside the managed venv? Use sys.prefix, not the
    # executable path: a venv's bin/python is a symlink back to the base
    # interpreter, so resolving it would falsely match the system python.
    inside_managed = Path(sys.prefix).resolve() == venv_dir.resolve()
    if inside_managed:
        sys.exit("ERROR: numpy/scipy could not be installed in ~/.autosync_venv")
    if not vpy.exists():
        print("First run: setting up the numpy/scipy environment (one-time, ~30s)...",
              flush=True)
        subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
        subprocess.run([str(vpy), "-m", "pip", "install", "-q", "--upgrade",
                        "pip", "numpy", "scipy"], check=True)
    # Re-launch this exact script using the venv's interpreter.
    # Flush first — os.execv replaces the process and won't flush Python buffers.
    sys.stdout.flush()
    sys.stderr.flush()
    os.execv(str(vpy), [str(vpy), os.path.abspath(__file__), *sys.argv[1:]])


ensure_deps()

import numpy as np
from scipy.io import wavfile
from scipy.signal import correlate, correlation_lags
from scipy.ndimage import uniform_filter1d

# ----------------------------------------------------------------------------
# Config / constants
# ----------------------------------------------------------------------------
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".m4v", ".avi", ".webm", ".mts", ".m2ts"}
AUDIO_EXTS = {".m4a", ".wav", ".mp3", ".aac", ".flac", ".ogg", ".oga",
              ".caf", ".aif", ".aiff", ".wma", ".opus"}
ANALYSIS_SR = 16000      # sample rate used for the correlation analysis
ENV_RATE = 1000          # envelope rate -> 1 ms sync resolution
SMOOTH_MS = 10           # envelope smoothing window
CONF_WARN = 6.0          # warn below this peak/std sharpness


def have(tool):
    return shutil.which(tool) is not None


def ffprobe_json(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True)
    if out.returncode != 0:
        return None
    return json.loads(out.stdout)


def media_info(path):
    info = ffprobe_json(path)
    if not info:
        return None
    dur = float(info.get("format", {}).get("duration", 0) or 0)
    has_audio = any(s.get("codec_type") == "audio" for s in info.get("streams", []))
    has_video = any(s.get("codec_type") == "video" for s in info.get("streams", []))
    return {"duration": dur, "has_audio": has_audio, "has_video": has_video}


def extract_wav(src, dst, sr=ANALYSIS_SR, audio_index=0):
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(src),
         "-map", f"0:a:{audio_index}", "-ac", "1", "-ar", str(sr), str(dst)],
        check=True)


def envelope(wav_path):
    sr, x = wavfile.read(wav_path)
    if x.ndim > 1:
        x = x.mean(axis=1)
    x = x.astype(np.float64)
    env = np.abs(x)
    env = uniform_filter1d(env, size=max(1, sr // (1000 // SMOOTH_MS)))
    env = env[:: sr // ENV_RATE]
    env = env - env.mean()
    n = np.linalg.norm(env)
    if n > 0:
        env = env / n
    return env


def find_offset(ref_env, lav_env):
    """Returns (seconds, sharpness).
       seconds > 0  => audio started BEFORE the video (trim that much off front)
       seconds < 0  => audio started AFTER  the video (pad that much silence)."""
    corr = correlate(lav_env, ref_env, mode="full", method="fft")
    lags = correlation_lags(len(lav_env), len(ref_env), mode="full")
    k = int(np.argmax(corr))
    sharpness = float(corr[k] / (corr.std() + 1e-12))
    return lags[k] / ENV_RATE, sharpness


def find_files(folder):
    files = [p for p in sorted(folder.iterdir())
             if p.is_file() and not p.name.startswith(".")]
    videos = [p for p in files
              if p.suffix.lower() in VIDEO_EXTS and not p.stem.endswith("_synced")]
    audios = [p for p in files if p.suffix.lower() in AUDIO_EXTS]
    return videos, audios


def build_filter(audio_specs, vdur, limit):
    """audio_specs: list of (input_index, offset_seconds). Returns filtergraph
    string producing label [mix]."""
    parts, mix_labels = [], []
    for n, (idx, off) in enumerate(audio_specs):
        lab = f"a{n}"
        if off >= 0:
            parts.append(f"[{idx}:a]atrim=start={off:.4f},asetpts=PTS-STARTPTS[{lab}]")
        else:
            ms = int(round(-off * 1000))
            parts.append(f"[{idx}:a]adelay=delays={ms}:all=1[{lab}]")
        mix_labels.append(f"[{lab}]")

    if len(audio_specs) == 1:
        premix = mix_labels[0]
    else:
        parts.append(f'{"".join(mix_labels)}amix=inputs={len(audio_specs)}'
                     f':normalize=0:duration=longest[m]')
        premix = "[m]"

    fade_out_start = max(0.0, vdur - 0.06)
    parts.append(
        f"{premix}alimiter=limit={limit},"
        f"atrim=end={vdur:.4f},asetpts=PTS-STARTPTS,"
        f"afade=t=in:st=0:d=0.02,"
        f"afade=t=out:st={fade_out_start:.4f}:d=0.05,"
        f"aformat=channel_layouts=stereo[mix]")
    return ";".join(parts)


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Dual-system audio sync (drop-in folder workflow).")
    ap.add_argument("folder", nargs="?", default=str(Path(__file__).resolve().parent),
                    help="Folder with the video + audio files (default: this script's folder).")
    ap.add_argument("--video", help="Force a specific video file (name or path).")
    ap.add_argument("--out", help="Output path (default: <video>_synced.mp4 in the folder).")
    ap.add_argument("--limit", type=float, default=0.9, help="Peak limiter ceiling 0-1 (default 0.9).")
    ap.add_argument("--bitrate", default="256k", help="Output AAC bitrate (default 256k).")
    ap.add_argument("--reencode", action="store_true", help="Re-encode video instead of lossless copy.")
    ap.add_argument("--dry-run", action="store_true", help="Detect files + print offsets, render nothing.")
    ap.add_argument("--no-verify", action="store_true", help="Skip the final re-correlation check.")
    ap.add_argument("--setup", action="store_true",
                    help="Install/verify dependencies and exit (used by setup.command).")
    args = ap.parse_args()

    if args.setup:
        # ensure_deps() already ran at import, so numpy/scipy exist by now.
        import numpy as _np
        import scipy as _sp
        print(f"  Python libraries ready  (numpy {_np.__version__}, scipy {_sp.__version__})")
        print(f"  Interpreter             {sys.executable}")
        if have("ffmpeg") and have("ffprobe"):
            print("  ffmpeg / ffprobe        found")
        else:
            print("  ffmpeg / ffprobe        NOT FOUND  ->  brew install ffmpeg")
        return

    if not (have("ffmpeg") and have("ffprobe")):
        sys.exit("ERROR: ffmpeg/ffprobe not found on PATH. Install with: brew install ffmpeg")

    folder = Path(args.folder).expanduser().resolve()
    if not folder.is_dir():
        sys.exit(f"ERROR: not a folder: {folder}")

    print(f"\n  AutoSync — folder: {folder}")
    videos, audios = find_files(folder)

    if args.video:
        vp = Path(args.video)
        video = vp if vp.is_absolute() else folder / args.video
        if not video.exists():
            sys.exit(f"ERROR: --video not found: {video}")
    elif len(videos) == 1:
        video = videos[0]
    elif len(videos) == 0:
        sys.exit("ERROR: no video file found in the folder.")
    else:
        video = max(videos, key=lambda p: p.stat().st_size)
        print(f"  ! Multiple videos found; using the largest: {video.name}")
        print(f"    (use --video to pick another)")

    if not audios:
        sys.exit("ERROR: no separate audio files found to sync.")

    vinfo = media_info(video)
    if not vinfo or not vinfo["has_video"]:
        sys.exit(f"ERROR: could not read video: {video}")
    if not vinfo["has_audio"]:
        sys.exit("ERROR: the video has no audio track to use as the sync reference.\n"
                 "       Auto-sync needs the camera/scratch audio on the video.")
    vdur = vinfo["duration"]

    print(f"  Video : {video.name}  ({vdur:.2f}s)")
    print(f"  Audio : {', '.join(a.name for a in audios)}")
    print(f"  Analyzing sync offsets...\n")

    tmp = Path(tempfile.mkdtemp(prefix="autosync_"))
    try:
        ref_wav = tmp / "ref.wav"
        extract_wav(video, ref_wav)
        ref_env = envelope(ref_wav)

        offsets, low_conf = [], False
        for i, a in enumerate(audios):
            ainfo = media_info(a)
            if not ainfo or not ainfo["has_audio"]:
                print(f"    ! skipping (no audio stream): {a.name}")
                continue
            awav = tmp / f"a{i}.wav"
            extract_wav(a, awav)
            off, sharp = find_offset(ref_env, envelope(awav))
            tag = "trim front" if off >= 0 else "pad front"
            flag = "  <-- LOW CONFIDENCE" if sharp < CONF_WARN else ""
            if sharp < CONF_WARN:
                low_conf = True
            print(f"    {a.name:<32} offset {off:+.3f}s  ({tag} {abs(off):.3f}s)"
                  f"   confidence {sharp:4.1f}{flag}")
            offsets.append((a, off))

        if not offsets:
            sys.exit("ERROR: no usable audio tracks.")
        if low_conf:
            print("\n  ! One or more tracks matched weakly. They may not belong to this\n"
                  "    video, or are too quiet/short. Review the result.")

        if args.dry_run:
            print("\n  Dry run — nothing rendered.\n")
            return

        out = Path(args.out).expanduser() if args.out else folder / f"{video.stem}_synced.mp4"

        # ffmpeg inputs: 0 = video, 1..N = audio files (in offsets order)
        inputs = ["-i", str(video)]
        specs = []
        for n, (a, off) in enumerate(offsets):
            inputs += ["-i", str(a)]
            specs.append((n + 1, off))
        fc = build_filter(specs, vdur, args.limit)

        vcodec = (["-c:v", "libx264", "-preset", "medium", "-crf", "18"]
                  if args.reencode else ["-c:v", "copy"])

        cmd = (["ffmpeg", "-y", "-hide_banner", "-loglevel", "warning", "-stats"]
               + inputs
               + ["-filter_complex", fc,
                  "-map", "0:v:0", "-map", "[mix]"]
               + vcodec
               + ["-c:a", "aac", "-b:a", args.bitrate, "-ar", "48000",
                  "-shortest", "-movflags", "+faststart", str(out)])

        print(f"\n  Rendering -> {out.name}")
        subprocess.run(cmd, check=True)

        # ---- verification: re-correlate the OUTPUT against the reference ----
        residual_msg = ""
        if not args.no_verify:
            owav = tmp / "out.wav"
            extract_wav(out, owav)
            res, sharp = find_offset(ref_env, envelope(owav))
            residual_msg = f"   (sync residual {res*1000:+.0f} ms, confidence {sharp:.1f})"

        oinfo = media_info(out)
        print(f"\n  DONE  {out}")
        print(f"        {oinfo['duration']:.2f}s, camera audio removed,"
              f" {len(offsets)} track(s) synced & mixed.{residual_msg}\n")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
