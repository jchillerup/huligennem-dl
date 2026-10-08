"""Textual TUI for choosing which series to archive."""
from textual.app import App
from textual.containers import Horizontal
from textual.widgets import Button, Footer, Header, SelectionList


class Picker(App):
    TITLE = "HULiGENNEM archiver"
    CSS = """
    SelectionList { height: 1fr; }
    Horizontal { height: auto; }
    Button { margin: 0 1; }
    """
    BINDINGS = [("a", "all", "Select all"), ("n", "none", "Select none"),
                ("s", "start", "Archive selected"), ("q", "quit", "Quit")]

    def __init__(self, series):
        super().__init__()
        self.series = series

    def compose(self):
        yield Header()
        by_title = sorted(self.series.items(), key=lambda item: item[1].casefold())
        yield SelectionList(*[(title, slug, True) for slug, title in by_title])
        with Horizontal():
            yield Button("Select all", id="all")
            yield Button("Select none", id="none")
            yield Button("Archive selected", id="start", variant="primary")
        yield Footer()

    def on_mount(self):
        self.update_count()

    def on_selection_list_selected_changed(self):
        self.update_count()

    def update_count(self):
        n = len(self.query_one(SelectionList).selected)
        self.sub_title = f"{n} of {len(self.series)} series selected"

    async def on_button_pressed(self, event):
        await self.run_action(event.button.id)

    def action_all(self):
        self.query_one(SelectionList).select_all()

    def action_none(self):
        self.query_one(SelectionList).deselect_all()

    def action_start(self):
        self.exit(self.query_one(SelectionList).selected)


def pick(series):
    """Show the picker for {slug: title}; return chosen slugs, or None if quit."""
    return Picker(series).run()
