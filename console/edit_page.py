"""One text file in a window of its own, to keep beside VPX or a forum post while the
Console is on something else. No rail: the Console is the other window."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from nicegui import ui

from common.failures import why
from common.games import asset_lens
from common.i18n import t
from console import appearance, offload, report_groups, text_editor, workbench
from console import panel as panel_parts
from console.api import ApiClient
from console.data import Library


@ui.page(text_editor.ADDRESS, title=t("console.edit.page_title"), reconnect_timeout=300)
async def edit_page(game: str = "", kind: str = "", path: str = "") -> None:
    """The file `path` of the game `game`, of the asset kind `kind`."""
    appearance.apply_mode(appearance.configured_mode())
    panel_parts.install_fact_tooltips()
    ui.query(".nicegui-content").classes("p-0 gap-0 h-screen")
    state: dict[str, Any] = {}
    ui.on(text_editor.DARK_EVENT, text_editor.wire())
    ui.on(text_editor.RETURN_EVENT, lambda: text_editor.shown_again(state))
    await ui.context.client.connected()

    with ui.column().classes("w-full h-screen p-3 gap-2 no-wrap"):
        client = ApiClient()
        library = Library(client)
        try:
            if not text_editor.edits(kind):
                raise ValueError(t("console.edit.not_text"))
            owner = await offload.io(client.game, game)
            found = await offload.io(library.asset_text, game, path)
            locked, help_ = await workbench.text_lock(library, kind, found)
        except Exception as exc:  # noqa: BLE001 - the reason belongs on screen
            ui.label(t("console.edit.unavailable")).classes("console-dialog-title")
            ui.notify(t("console.edit.unavailable"), caption=why(exc), type="negative")
            return
        label = asset_lens.label_of(kind)
        name = str(owner.get("name") or game)
        ui.page_title(t("console.edit.title", game=name, what=label))
        with ui.row().classes("items-baseline gap-2 w-full no-wrap"):
            ui.label(label).classes("console-dialog-title")
            panel_parts.link(name, to="/console?" + urlencode({"view": "games", "game": game}),
                             window=report_groups.CONSOLE_WINDOW, classes="truncate")()
        context = {"state": state, "library": library, "game_id": game, "kind": kind,
                   "game": owner, "windowed": True}
        text_editor.editor(context, path, label, found, locked, help_)
    ui.run_javascript(text_editor.ASK_BEFORE_UNLOAD)
    ui.run_javascript(text_editor.LISTEN_FOR_RETURN)
