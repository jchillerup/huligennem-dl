# huligennem

Archive every podcast episode from [HULiGENNEM](https://dererhuligennem.dk/), the Danish
children's radio station, together with all metadata, before the site potentially loses 
its funding at the end of 2026.

> **This code was written entirely by Claude** (Anthropic's AI model, Claude Opus 5.5, via
> Claude Code). That includes the research into how the site works, the scraper, its GUI
> and terminal interfaces, the verifier and this README. A human ([@jchillerup](https://github.com/jchillerup)) directed
> the work, ran the scraper and reported bugs, but did not write the code.

## What it does

- Fetches the metadata for every series, season and episode (about 80 series and
  2,400 episodes as of October 2026).
- Downloads every episode's MP3 and every poster image.
- Saves each episode's metadata as a `.json` file next to its `.mp3`.
- Mirrors the site's own storage paths, so the archive is easy to browse.

The full archive is about 100 GB, roughly 1,600 hours of audio.

## Download

Standalone apps for Windows and macOS (Apple Silicon) are on the
[Releases](../../releases) page; no Python needed. Double-click it and a window opens:

1. Choose the archive folder. The default is `huligennem-archive` in your home folder.
2. Tick the series you want, using "Select all" or "Select none" to start from.
3. Press **Start** and follow the progress bars.

You can close the window at any time. Press Start again later to continue where it
stopped, or to retry files that failed.

The builds are not code-signed, so both systems will warn the first time:

- **Windows:** SmartScreen says "Windows protected your PC". Click "More info", then
  "Run anyway".
- **macOS:** unzip `HULiGENNEM.app` and try to open it once. Go to System Settings →
  Privacy & Security and click "Open Anyway". Or, in Terminal, run
  `xattr -dr com.apple.quarantine HULiGENNEM.app`.

There is no build for Intel Macs, because DearPyGui, the GUI library, doesn't support
them. On an Intel Mac, use the command line below instead.

## Usage

Requires [uv](https://docs.astral.sh/uv/). `verify.py` also needs `ffprobe` (part of FFmpeg).

```sh
uv run scrape.py               # GUI: pick series and folder, then Start
uv run scrape.py --all         # archive everything into ./archive, console progress
uv run scrape.py --tui         # pick series in the terminal, then console progress
uv run scrape.py --all --out D # use folder D instead of ./archive
uv run scrape.py --all --no-media   # metadata only
uv run scrape.py --workers 8   # more parallel downloads (default 4), any mode
uv run verify.py               # check every mp3 is present and complete
```

**Choosing series in the terminal:** `--tui` opens a checklist of all series by title,
with buttons (and the keys `a`/`n`) to select all or none. Everything starts out selected.
Press "Archive selected" or `s` to start, or `q` to quit without downloading.

**Stopping and resuming:** stop at any time (Ctrl-C, or close the GUI window), then run
again to continue.
- Finished files are skipped.
- Interrupted downloads are kept as `*.part` and continue with HTTP range requests.

**Updating:** running the scraper again on a complete archive refreshes all metadata and
downloads only new episodes.

**Tests:** `uv run test_gui.py` and `uv run test_picker.py` drive both interfaces without a
display and with the network faked.

## Building executables

`.github/workflows/release.yml` builds the apps with PyInstaller on GitHub's Windows and
macOS runners. Push a tag to publish a release:

```sh
git tag v0.1.0 && git push origin v0.1.0
```

To build one locally for your own platform:

```sh
uv run --with pyinstaller pyinstaller --onefile --windowed --name huligennem scrape.py
```

## Archive layout

```
archive/
  serier/<series>.json                          raw page data per series
  audio/<series>/<season>/<episode>-XXXXX.mp3   seasonal/serial series
  audio/<series>/<season>/<episode>-XXXXX.json  episode + season + series metadata
  audio/<series>/<episode>-XXXXX.mp3            episodic series (no seasons)
  images/series/...                             series, season and episode posters
```

## How it works

The site is a Laravel and Inertia.js app, so no headless browser is needed:

- **Series list:** the paginated `/serier` overview lists every series with its title.
- **Series data:** requesting a series page with an `X-Inertia: true` header returns its
  data as JSON, including all seasons and episodes.
- **Files:** every media object has a `storage_path` and a `media_url` on
  `huligennem-production.imgix.net`. The MP3s are downloaded from there.
- **Spreaker:** the episodes are also on Spreaker (`audio.hosted_url`), which is a second
  source if imgix goes away first.

**How `verify.py` detects truncation:** it counts the MP3 frames with `ffprobe` and
compares the real duration with `length_in_seconds` from the site. It doesn't use the
duration in the file header, because the header still shows the full length after a file
is cut short.

## Etiquette and rights

- The scraper waits 0.2 s before every request and uses a few parallel downloads.
- `robots.txt` allows all crawling.
- The audio and images belong to HULiGENNEM and the creators. This tool is for
  preservation. Ask the rights holders before redistributing anything it downloads.

## License

The code is under the MIT license; see [LICENSE](LICENSE). The license does not cover any
archived content.
