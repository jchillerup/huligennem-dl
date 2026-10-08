"""Headless check of the series picker. Run: uv run test_picker.py"""
import asyncio

from textual.widgets import SelectionList

from picker import Picker

SERIES = {"b-show": "Bravo", "a-show": "alpha", "c-show": "Charlie"}


async def main():
    app = Picker(SERIES)
    async with app.run_test() as pilot:
        sel = app.query_one(SelectionList)
        assert sorted(sel.selected) == sorted(SERIES)  # everything preselected
        await pilot.click("#none")
        assert sel.selected == [] and app.sub_title == "0 of 3 series selected"
        await pilot.click("#all")
        assert len(sel.selected) == 3
        await pilot.press("n")                         # keyboard: select none
        sel.select("c-show")
        await pilot.click("#start")
    assert app.return_value == ["c-show"], app.return_value
    print("picker ok")


asyncio.run(main())
