#!/usr/bin/env python3
"""Archive all series/episodes from dererhuligennem.dk.

Files mirror the imgix storage paths under the output folder, e.g.
  audio/<serie>/[<season>/]<episode>-XXXX.mp3  + .json (episode metadata;
                                               episodic series have no season dir)
  images/series/...jpg                       (posters)
  serier/<slug>.json                         (raw page data per series)

Usage: uv run scrape.py [--all | --tui] [--out DIR] [--no-media] [--workers N]

No mode flag opens the GUI (pick series and folder, then Start).
--all archives everything with console progress; --tui picks series in the
terminal first.

Metadata is fetched first (sequentially), then media downloads run on
N parallel workers (default 4).

Resumable: the filesystem is the progress log. Finished files have their
final name and are skipped; interrupted downloads stay as *.part and are
continued with an HTTP Range request. Stop any time, rerun to resume.
"""
import argparse, functools, html, json, os, re, sys, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from rich.console import Group
from rich.live import Live
from rich.progress import (BarColumn, DownloadColumn, Progress, TaskProgressColumn,
                           TextColumn, TimeRemainingColumn, TransferSpeedColumn, track)

SITE = "https://dererhuligennem.dk"
DELAY = 0.2  # seconds before each request, be polite
UA = "huligennem-archiver"
FROZEN = getattr(sys, "frozen", False)  # running as a PyInstaller executable
# A double-clicked app starts in an arbitrary folder (/ on macOS), so use home.
DEFAULT_OUT = Path.home() / "huligennem-archive" if FROZEN else Path("archive")


def get(url, headers={}):
    time.sleep(DELAY)
    req = urllib.request.Request(url, headers={"User-Agent": UA, **headers})
    return urllib.request.urlopen(req, timeout=60)


@functools.cache
def inertia_version():
    page = get(SITE + "/").read().decode()
    data = re.search(r'data-page="([^"]*)"', page).group(1)
    return json.loads(html.unescape(data))["version"]


def inertia(url):
    """A page's data as JSON (Inertia.js answers with props instead of HTML)."""
    headers = {"X-Inertia": "true", "X-Inertia-Version": inertia_version(),
               "X-Requested-With": "XMLHttpRequest"}
    return json.load(get(url, headers))["props"]


def series_index():
    """{slug: title} for every series, from the paginated /serier listing."""
    out, url = {}, SITE + "/serier"
    while url:
        page = inertia(url)["series"]
        out.update((s["slug"], s["title"]) for s in page["data"])
        url = page["next_page_url"]
    return out


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


def download(storage_path, url, out, report=lambda n, total: None):
    """report(nbytes, total) is called as bytes arrive (incl. already-had bytes);
    total is None when the server doesn't say."""
    dest = out / storage_path
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


def fetch_series(slug, out):
    """Fetch one series and write its metadata files.
    Returns ({storage_path: url} for all its media, {audio path: minutes})."""
    props = inertia(f"{SITE}/serier/{slug}")
    serie, seasons = props["serie"], props["data"]
    write_json(out / "serier" / f"{slug}.json", {"serie": serie, "seasons": seasons})
    minutes = {}
    for ep, season_info in episodes(slug, seasons):
        audio = (ep.get("audio") or {}).get("storage_path")
        if not audio:
            print(f"WARN {slug} episode {ep['id']} has no audio")
            continue
        minutes[audio] = (ep["audio"].get("length_in_seconds") or 0) / 60
        write_json((out / audio).with_suffix(".json"), {**ep, "season": season_info, "serie": serie})
    return dict(media(props)), minutes


def run_downloads(todo, out, workers, minutes, ui):
    """Download {path: url} on parallel workers, reporting to ui (console or GUI):
    ui.start(path), ui.bytes(path, n, total), ui.minutes(m) to advance the
    overall bar (weighted by audio duration), ui.end(path, error or None)."""
    def fetch(path, url):
        ui.start(path)
        credited = 0
        def report(n, total):
            nonlocal credited
            ui.bytes(path, n, total)
            if total:
                share = minutes.get(path, 0) * n / total
                credited += share
                ui.minutes(share)
        download(path, url, out, report)
        ui.minutes(minutes.get(path, 0) - credited)  # sizeless downloads

    pool = ThreadPoolExecutor(workers)
    futures = {pool.submit(fetch, p, u): p for p, u in todo.items()}
    for fut in as_completed(futures):
        ui.end(futures[fut], fut.exception())


class ConsoleUI:
    """rich progress: one overall bar plus one bar per active download."""

    def __init__(self, n_files, n_done, total_min, done_min):
        self.overall = Progress(TextColumn("{task.description}"), BarColumn(), TaskProgressColumn(),
                                TextColumn("{task.completed:,.0f}/{task.total:,.0f} min"),
                                TimeRemainingColumn())
        self.files = Progress(TextColumn("  {task.description}", style="dim"), BarColumn(),
                              DownloadColumn(), TransferSpeedColumn())
        self.n_files, self.n_done = n_files, n_done
        self.archive = self.overall.add_task(self.label(), total=total_min, completed=done_min)
        self.tasks, self.failures = {}, []
        self.live = Live(Group(self.overall, self.files), refresh_per_second=4)

    def label(self):
        return f"Archive {self.n_done}/{self.n_files} files"

    def start(self, path):
        self.tasks[path] = self.files.add_task(Path(path).name, total=None)

    def bytes(self, path, n, total):
        self.files.update(self.tasks[path], total=total, advance=n)

    def minutes(self, m):
        self.overall.advance(self.archive, m)

    def end(self, path, error):
        if path in self.tasks:
            self.files.remove_task(self.tasks.pop(path))
        self.n_done += 1
        self.overall.update(self.archive, description=self.label())
        if error:
            self.failures.append((path, repr(error)))
            self.live.console.print(f"[red]FAILED[/] {path} {error!r}")


def main():
    ap = argparse.ArgumentParser(description="Archive dererhuligennem.dk. "
                                 "Without --all or --tui, opens the GUI.")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--all", action="store_true", help="archive every series, console only")
    mode.add_argument("--tui", action="store_true", help="pick series in the terminal first")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"archive folder (default: {DEFAULT_OUT})")
    ap.add_argument("--no-media", action="store_true", help="metadata only (--all/--tui)")
    ap.add_argument("--workers", type=int, default=4, help="parallel downloads (default: 4)")
    args = ap.parse_args()
    if not (args.all or args.tui):
        from gui import run_gui  # only load DearPyGui when needed
        return run_gui(args.out, args.workers)

    out = args.out
    print(f"Archiving to {out.resolve()}")
    series = series_index()
    if args.tui:
        from picker import pick  # only load Textual when needed
        chosen = pick(series)
        if not chosen:
            print("Nothing selected.")
            return
        series = {slug: series[slug] for slug in chosen}

    failures, jobs, minutes = [], {}, {}
    for slug in track(series, description="Fetching metadata"):
        try:
            files, mins = fetch_series(slug, out)
        except Exception as e:
            failures.append((slug, repr(e)))
            continue
        jobs.update(files)
        minutes.update(mins)

    todo = {p: u for p, u in jobs.items() if not (out / p).exists()}
    print(f"{len(jobs)} media files, {len(todo)} to download")
    if not args.no_media:
        done_min = sum(m for p, m in minutes.items() if p not in todo)
        ui = ConsoleUI(len(jobs), len(jobs) - len(todo), sum(minutes.values()), done_min)
        with ui.live:
            try:
                run_downloads(todo, out, args.workers, minutes, ui)
            except KeyboardInterrupt:
                ui.live.stop()
                print("Interrupted; rerun to resume.")
                os._exit(130)  # skip waiting on workers; *.part files resume next run
        failures += ui.failures

    for what, err in failures:
        print("FAILED", what, err)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
