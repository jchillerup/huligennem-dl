#!/usr/bin/env python3
"""Check every archived episode: mp3 exists and its real audio length
(counted MP3 frames, not the header) matches length_in_seconds from the site.

Usage: uv run verify.py [--workers N]   # needs ffprobe
"""
import argparse, json, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from rich.progress import track

OUT = Path("archive")
TOLERANCE = 2.0  # seconds; site lengths are rounded


def real_seconds(mp3):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-count_packets",
         "-show_entries", "stream=nb_read_packets,sample_rate", "-of", "json", str(mp3)],
        capture_output=True, text=True, check=True).stdout
    s = json.loads(out)["streams"][0]
    rate = int(s["sample_rate"])
    per_frame = 1152 if rate >= 32000 else 576  # MPEG-1 vs MPEG-2/2.5 layer III
    return int(s["nb_read_packets"]) * per_frame / rate


def check(meta_path):
    mp3 = meta_path.with_suffix(".mp3")
    expected = json.loads(meta_path.read_text())["audio"].get("length_in_seconds")
    if not mp3.exists():
        return f"MISSING {mp3}"
    try:
        got = real_seconds(mp3)
    except Exception as e:
        return f"UNREADABLE {mp3} {e!r}"
    if expected and got < expected - TOLERANCE:
        return f"SHORT {mp3}: {got:.0f}s of {expected}s ({got / expected:.0%})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    metas = sorted(OUT.glob("audio/**/*.json"))
    with ThreadPoolExecutor(ap.parse_args().workers) as pool:
        problems = [p for p in track(pool.map(check, metas), total=len(metas),
                                     description="Verifying") if p]
    print(*problems, sep="\n")
    print(f"{len(metas)} episodes checked, {len(problems)} problems")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
