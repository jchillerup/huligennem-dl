#!/usr/bin/env python3
"""Archive all series/episodes from dererhuligennem.dk.

Files mirror the imgix storage paths under OUT/, e.g.
  audio/<serie>/[<season>/]<episode>-XXXX.mp3  + .json (episode metadata;
                                               episodic series have no season dir)
  images/series/...jpg                       (posters)
  serier/<slug>.json                         (raw page data per series)

Usage: uv run scrape.py [--no-media] [--workers N]

Metadata is fetched first (sequentially), then media downloads run on
N parallel workers (default 4).

Resumable: the filesystem is the progress log. Finished files have their
final name and are skipped; interrupted downloads stay as *.part and are
continued with an HTTP Range request. Ctrl-C any time, rerun to resume.
"""
import argparse, html, json, os, re, sys, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from rich.console import Group
from rich.live import Live
from rich.progress import (BarColumn, DownloadColumn, Progress, TaskProgressColumn,
                           TextColumn, TimeRemainingColumn, TransferSpeedColumn, track)

SITE = "https://dererhuligennem.dk"
OUT = Path("archive")
DELAY = 0.2  # seconds before each request, be polite
UA = "huligennem-archiver"


def get(url, headers={}):
    time.sleep(DELAY)
    req = urllib.request.Request(url, headers={"User-Agent": UA, **headers})
    return urllib.request.urlopen(req, timeout=60)


def inertia_version():
    page = get(SITE + "/").read().decode()
    data = re.search(r'data-page="([^"]*)"', page).group(1)
    return json.loads(html.unescape(data))["version"]


def series_slugs():
    xml = get(SITE + "/series/sitemap.xml").read().decode()
    return re.findall(r"<loc>" + re.escape(SITE) + r"/serier/([^<]+)</loc>", xml)


def media(obj):
    """Yield every (storage_path, media_url) anywhere in the JSON tree."""
    if isinstance(obj, dict):
        if obj.get("storage_path") and obj.get("media_url"):
            yield obj["storage_path"], obj["media_url"]
        for v in obj.values():
            yield from media(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from media(v)


def episodes(slug, data):
    """Yield (episode, season_info). Seasonal/serial series list seasons with
    nested episodes; episodic series list episodes directly (season_info None)."""
    for item in data:
        if "audio" in item:
            yield item, None
            continue
        eps = item.get("episodes") or []
        if len(eps) < (item.get("episodes_count") or 0):
            print(f"WARN {slug} season {item['id']}: {len(eps)} of {item['episodes_count']} episodes listed")
        info = {k: v for k, v in item.items() if k not in ("episodes", "serie")}
        for ep in eps:
            yield ep, info


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2))


def download(storage_path, url, report=lambda n, total: None):
    """report(nbytes, total) is called as bytes arrive (incl. already-had bytes);
    total is None when the server doesn't say."""
    dest = OUT / storage_path
    if dest.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    have = tmp.stat().st_size if tmp.exists() else 0
    try:
        r = get(url, {"Range": f"bytes={have}-"})
    except urllib.error.HTTPError as e:
        if e.code != 416:  # 416 = .part already complete, killed before rename
            raise
        report(have, have)
        return tmp.rename(dest)
    with r:
        if r.status != 206:  # server ignored Range, start over
            have = 0
        # Content-Range "bytes a-b/size" is the most reliable size; uncached
        # files may come back chunked with neither header (size unknown).
        size = re.search(r"/(\d+)$", r.headers.get("Content-Range", ""))
        length = r.headers.get("Content-Length")
        total = int(size[1]) if size else have + int(length) if length else None
        report(have, total)
        with open(tmp, "ab" if have else "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
                report(len(chunk), total)
    tmp.rename(dest)  # only complete files get the real name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-media", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    version = inertia_version()
    headers = {"X-Inertia": "true", "X-Inertia-Version": version,
               "X-Requested-With": "XMLHttpRequest"}
    failures, jobs, seconds = [], {}, {}
    for slug in track(series_slugs(), description="Fetching metadata"):
        try:
            props = json.load(get(f"{SITE}/serier/{slug}", headers))["props"]
        except Exception as e:
            failures.append((slug, repr(e)))
            continue
        serie, seasons = props["serie"], props["data"]
        write_json(OUT / "serier" / f"{slug}.json", {"serie": serie, "seasons": seasons})

        for ep, season_info in episodes(slug, seasons):
            audio = (ep.get("audio") or {}).get("storage_path")
            if not audio:
                print(f"WARN {slug} episode {ep['id']} has no audio")
                continue
            seconds[audio] = ep["audio"].get("length_in_seconds") or 0
            meta = {**ep, "season": season_info, "serie": serie}
            write_json((OUT / audio).with_suffix(".json"), meta)

        jobs.update(media(props))

    todo = {p: u for p, u in jobs.items() if not (OUT / p).exists()}
    print(f"{len(jobs)} media files, {len(todo)} to download")
    if args.no_media:
        return

    # Overall progress is weighted by audio duration: % of the archive's hours.
    overall = Progress(TextColumn("{task.description}"), BarColumn(), TaskProgressColumn(),
                       TextColumn("{task.completed:,.0f}/{task.total:,.0f} min"),
                       TimeRemainingColumn())
    files = Progress(TextColumn("  {task.description}", style="dim"), BarColumn(),
                     DownloadColumn(), TransferSpeedColumn())
    minutes = {p: s / 60 for p, s in seconds.items()}
    total_min = sum(minutes.values())
    done_min = sum(m for p, m in minutes.items() if p not in todo)
    archive = overall.add_task(f"Archive {len(jobs) - len(todo)}/{len(jobs)} files", total=total_min, completed=done_min)
    n_done = len(jobs) - len(todo)

    def fetch(path, url):
        tid = files.add_task(Path(path).name, total=None)
        credited = 0
        def report(n, total):
            nonlocal credited
            files.update(tid, total=total, advance=n)
            if total:
                share = minutes.get(path, 0) * n / total
                credited += share
                overall.advance(archive, share)
        try:
            download(path, url, report)
            overall.advance(archive, minutes.get(path, 0) - credited)  # sizeless downloads
        finally:
            files.remove_task(tid)

    with Live(Group(overall, files), refresh_per_second=4) as live:
        pool = ThreadPoolExecutor(args.workers)
        futures = {pool.submit(fetch, p, u): p for p, u in todo.items()}
        try:
            for fut in as_completed(futures):
                n_done += 1
                overall.update(archive, description=f"Archive {n_done}/{len(jobs)} files")
                if e := fut.exception():
                    failures.append((futures[fut], repr(e)))
                    live.console.print(f"[red]FAILED[/] {futures[fut]} {e!r}")
        except KeyboardInterrupt:
            live.stop()
            print("Interrupted; rerun to resume.")
            os._exit(130)  # skip waiting on workers; *.part files resume next run

    for what, err in failures:
        print("FAILED", what, err)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
