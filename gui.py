"""DearPyGui window: choose series and archive folder, Start, watch progress."""
import os, threading
from pathlib import Path

import dearpygui.dearpygui as dpg

import scrape

# The built-in font covers Latin-1 only (æøå are fine), so swap typographic marks.
PLAIN = str.maketrans({"“": '"', "”": '"', "„": '"', "‘": "'", "’": "'",
                       "–": "-", "—": "-", "…": "..."})


class GuiProgress:
    """The ui object scrape.run_downloads reports to: an overall bar plus one
    bar per worker slot."""

    def __init__(self, workers, n_files, n_done, total_min, done_min):
        self.lock = threading.Lock()
        self.free, self.slots, self.got = list(range(workers)), {}, {}
        self.n_files, self.n_done = n_files, n_done
        self.total_min, self.done_min = total_min, done_min
        self.failures = []
        self.update_overall()

    def start(self, path):
        with self.lock:
            slot = self.slots[path] = self.free.pop()
            self.got[path] = 0
        dpg.set_value(f"slot{slot}", 0)
        dpg.configure_item(f"slot{slot}", show=True, overlay=Path(path).name)

    def bytes(self, path, n, total):
        self.got[path] += n
        mb = self.got[path] / 1e6
        size = f"{mb:.1f} / {total / 1e6:.1f} MB" if total else f"{mb:.1f} MB"
        slot = self.slots[path]
        dpg.set_value(f"slot{slot}", self.got[path] / total if total else 0)
        dpg.configure_item(f"slot{slot}", overlay=f"{Path(path).name}   {size}")

    def minutes(self, m):
        with self.lock:
            self.done_min += m
        self.update_overall()

    def end(self, path, error):
        with self.lock:
            slot = self.slots.pop(path, None)
            if slot is not None:
                self.free.append(slot)
            self.n_done += 1
            if error:
                self.failures.append((path, repr(error)))
        if slot is not None:
            dpg.configure_item(f"slot{slot}", show=False)
        self.update_overall()

    def update_overall(self):
        f = self.done_min / self.total_min if self.total_min else 1
        dpg.set_value("overall", f)
        dpg.configure_item("overall", overlay=f"{f:.1%}   {self.n_done}/{self.n_files} files")


class ArchiverWindow:
    def __init__(self, out, workers):
        self.workers, self.checkboxes, self.busy = workers, {}, False
        with dpg.window(tag="main"):
            dpg.add_text("Archive folder")
            with dpg.group(horizontal=True):
                dpg.add_input_text(tag="out", default_value=str(Path(out).resolve()), width=-100)
                dpg.add_button(label="Browse...", tag="browse",
                               callback=lambda: dpg.show_item("folder"))
            dpg.add_spacer(height=6)
            with dpg.group(horizontal=True):
                dpg.add_text("Series")
                dpg.add_button(label="Select all", tag="all", callback=lambda: self.set_all(True))
                dpg.add_button(label="Select none", tag="none", callback=lambda: self.set_all(False))
                dpg.add_text("", tag="count")
            with dpg.child_window(tag="list", height=-170):
                dpg.add_text("Loading series...")
            dpg.add_button(label="Start", tag="start", width=-1, height=30,
                           enabled=False, callback=self.start)
            dpg.add_progress_bar(tag="overall", width=-1, overlay="")
            for i in range(workers):
                dpg.add_progress_bar(tag=f"slot{i}", width=-1, show=False)
            dpg.add_text("", tag="status", wrap=0)
        dpg.add_file_dialog(tag="folder", directory_selector=True, show=False,
                            width=650, height=420, default_path=str(Path(out).resolve()),
                            callback=lambda s, data: dpg.set_value("out", data["file_path_name"]))

    def load_series(self, series):
        """Fill the checklist from {slug: title}, everything selected."""
        dpg.delete_item("list", children_only=True)
        for slug, title in sorted(series.items(), key=lambda item: item[1].casefold()):
            self.checkboxes[slug] = dpg.add_checkbox(
                label=title.translate(PLAIN), default_value=True, parent="list",
                callback=self.update_count)
        self.update_count()

    def selected(self):
        return [slug for slug, box in self.checkboxes.items() if dpg.get_value(box)]

    def set_all(self, value):
        for box in self.checkboxes.values():
            dpg.set_value(box, value)
        self.update_count()

    def update_count(self):
        n = len(self.selected())
        dpg.set_value("count", f"{n} of {len(self.checkboxes)} selected")
        dpg.configure_item("start", enabled=n > 0 and not self.busy)

    def set_busy(self, busy):
        self.busy = busy
        for tag in ("out", "browse", "all", "none", *self.checkboxes.values()):
            dpg.configure_item(tag, enabled=not busy)
        self.update_count()

    def start(self):
        self.set_busy(True)
        out = Path(dpg.get_value("out")).expanduser()
        self.thread = threading.Thread(target=self.archive, args=(self.selected(), out), daemon=True)
        self.thread.start()

    def archive(self, slugs, out):
        try:
            jobs, minutes, failures = {}, {}, []
            for i, slug in enumerate(slugs, 1):
                dpg.set_value("overall", i / len(slugs))
                dpg.configure_item("overall", overlay=f"Fetching metadata {i}/{len(slugs)}")
                try:
                    files, mins = scrape.fetch_series(slug, out)
                except Exception as e:
                    failures.append((slug, repr(e)))
                    continue
                jobs.update(files)
                minutes.update(mins)
            todo = {p: u for p, u in jobs.items() if not (out / p).exists()}
            dpg.set_value("status", f"Downloading {len(todo)} of {len(jobs)} files to {out}. "
                                    "You can close the window and resume later.")
            progress = GuiProgress(self.workers, len(jobs), len(jobs) - len(todo),
                                   sum(minutes.values()),
                                   sum(m for p, m in minutes.items() if p not in todo))
            scrape.run_downloads(todo, out, self.workers, minutes, progress)
            failures += progress.failures
            msg = f"Done. The archive is in {out}"
            if failures:
                msg += (f"\n{len(failures)} failed; press Start again to retry:\n"
                        + "\n".join(f"  {what}: {err}" for what, err in failures[:10]))
            dpg.set_value("status", msg)
        except Exception as e:
            dpg.set_value("status", f"Error: {e!r}")
        finally:
            self.set_busy(False)


def run_gui(out, workers):
    dpg.create_context()
    window = ArchiverWindow(out, workers)
    dpg.create_viewport(title="HULiGENNEM archiver", width=760, height=720)
    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.set_primary_window("main", True)

    def load():
        try:
            window.load_series(scrape.series_index())
        except Exception as e:
            dpg.set_value("status", f"Could not load the series list: {e!r}")
    threading.Thread(target=load, daemon=True).start()

    dpg.start_dearpygui()
    os._exit(0)  # don't wait for running downloads; *.part files resume next time
