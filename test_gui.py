"""Headless check of the GUI logic, with the network faked. Run: uv run test_gui.py"""
import tempfile
from pathlib import Path

import dearpygui.dearpygui as dpg

import gui, scrape

SERIES = {"b-show": "Bravo – the “show”", "a-show": "alpha", "c-show": "Charlie"}


def fake_fetch_series(slug, out):
    return {f"audio/{slug}/ep.mp3": "url"}, {f"audio/{slug}/ep.mp3": 10.0}


def fake_download(path, url, out, report):
    report(500, 1000)
    report(500, 1000)
    (out / path).parent.mkdir(parents=True, exist_ok=True)
    (out / path).write_bytes(b"x" * 1000)


scrape.fetch_series, scrape.download = fake_fetch_series, fake_download
dpg.create_context()
with tempfile.TemporaryDirectory() as tmp:
    window = gui.ArchiverWindow(tmp, workers=2)
    window.load_series(SERIES)
    assert dpg.get_value("count") == "3 of 3 selected"
    assert dpg.get_item_label(window.checkboxes["b-show"]) == 'Bravo - the "show"'
    window.set_all(False)
    assert dpg.get_value("count") == "0 of 3 selected" and not dpg.get_item_configuration("start")["enabled"]
    window.set_all(True)
    dpg.set_value(window.checkboxes["c-show"], False)

    window.start()
    window.thread.join()
    assert sorted(p.parent.name for p in Path(tmp).glob("audio/*/ep.mp3")) == ["a-show", "b-show"]
    assert dpg.get_value("overall") == 1.0, dpg.get_value("overall")
    assert dpg.get_value("status").startswith("Done."), dpg.get_value("status")
    assert dpg.get_item_configuration("start")["enabled"]  # usable again after the run
dpg.destroy_context()
print("gui ok")
