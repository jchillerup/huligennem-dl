# huligennem

Archive every podcast episode from [HULiGENNEM](https://dererhuligennem.dk/), the Danish
children's radio station, together with all metadata, before the site loses its funding at
the end of 2026.

> **This code was written entirely by Claude** (Anthropic's AI model, Claude Opus 5.5, via
> Claude Code). That includes the research into how the site works, the scraper, the
> verifier and this README. A human ([@jchillerup](https://github.com/jchillerup)) directed
> the work, ran the scraper and reported bugs, but did not write the code.

## What it does

- Fetches the metadata for every series, season and episode (about 80 series and
  2,400 episodes as of October 2026).
- Downloads every episode's MP3 and every poster image.
- Saves each episode's metadata as a `.json` file next to its `.mp3`.
- Mirrors the site's own storage paths, so the archive is easy to browse.

The full archive is about 100 GB, roughly 1,600 hours of audio.

## Usage

Requires [uv](https://docs.astral.sh/uv/). `verify.py` also needs `ffprobe` (part of FFmpeg).

```sh
uv run scrape.py               # metadata + all media into ./archive
uv run scrape.py --workers 8   # more parallel downloads (default 4)
uv run scrape.py --no-media    # metadata only
uv run verify.py               # check every mp3 is present and complete
```

**Stopping and resuming:** press Ctrl-C at any time, then run the same command again to
continue.
- Finished files are skipped.
- Interrupted downloads are kept as `*.part` and continue with HTTP range requests.

**Updating:** running the scraper again on a complete archive refreshes all metadata and
downloads only new episodes.

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

- **Series list:** `/series/sitemap.xml` lists every series.
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
