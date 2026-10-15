
"""Five stars, one control, wherever a rating is set.

Drawn twice and it cannot be drawn once: a grid cell is rendered by AG Grid in the
browser, a panel row is built from elements on the server. So both live here, answering
to the same constants, and `tests/manager` asserts they still agree on what they draw.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from nicegui import run, ui

from common.failures import why
from common.i18n import t
from manager import grid
from manager.on_page import on_page

MOST = 5
# The character *is* the control. In a tooltip it measures zero and cannot be clicked,
# and a scripted click passes on it anyway - `docs/conventions.md` has why.
CLEAR = "×"

BOX = "manager-stars"
STAR = "manager-star"
LIT = "manager-star--on"
CLEAR_CLASS = "manager-star-clear"

# One delegated listener, not a handler per cell: a renderer runs again on every scroll
# and NiceGUI strips inline handlers off raw HTML. Capture phase, because AG Grid's own
# handler sits between the cell and the document.
CLICK_JS = f"""
if (!window.__hubStars) {{
  window.__hubStars = true;
  document.addEventListener('click', (e) => {{
    const star = e.target.closest && e.target.closest('.{BOX} [data-value]');
    if (!star) return;
    e.stopPropagation();
    const box = star.closest('.{BOX}');
    emitEvent('hub_rate', {{game: box.dataset.game, table: box.dataset.table,
                           value: Number(star.dataset.value)}});
  }}, true);
}}
"""


def renderer(subject: str, *, on_table: bool = False) -> str:
    """The grid's cell, as JavaScript. Only a rated row carries the clear, or an unrated
    library reads as a column of dismissals.

    `on_table` draws the game's rating on a table's row."""
    game = "(row.game_id || '')" if on_table or subject == "table" else "row.id"
    table = "row.id" if subject == "table" else "''"
    return (
        "params => {"
        " const row = params.data || {}; const held = Number(params.value) || 0;"
        f" let out = '<span class=\"{BOX}\" data-game=\"' + " + game
        + " + '\" data-table=\"' + " + table + " + '\">';"
        f" for (let n = 1; n <= {MOST}; n++) {{"
        f"  out += '<span class=\"{STAR}' + (n <= held ? ' {LIT}' : '')"
        "  + '\" data-value=\"' + n + '\" title=\"' + n + ' of 5\"></span>';"
        " }"
        f" if (held) {{ out += '<span class=\"{CLEAR_CLASS}\" data-value=\"0\"'"
        f"  + ' title=\"Clear rating\">{CLEAR}</span>'; }}"
        " return out + '</span>'; }"
    )


def draw(value: int, on_pick: Callable[[int], Any]) -> Callable[[], None]:
    """The panel's, as elements. A star sets and the clear unsets - one control doing
    both made a click on the lit star mean either, depending on a number the reader was
    not looking at."""
    def build() -> None:
        with ui.element("div").classes(BOX):
            for n in range(1, MOST + 1):
                lit = f" {LIT}" if n <= value else ""
                ui.element("span").classes(f"{STAR}{lit}") \
                    .on("click", lambda _, n=n: on_pick(n)) \
                    .tooltip(t("manager.stars.5", n=(n)))
            if value:
                ui.label(CLEAR).classes(CLEAR_CLASS) \
                    .on("click", lambda _: on_pick(0)) \
                    .tooltip(t("manager.stars.clear_rating"))

    return build


def game_rater(held: list[dict[str, Any]], rows_by_id: dict[str, Any],
               grid_of: Callable[[], Any], library: Any,
               game_field: str = "rating") -> Callable[[list[str], int], Any]:
    """Rate games, then repaint every row of them that changed, under `game_field`.

    A failed write says so and stops: the games saved before it stay repainted, and the
    answer is whether every one was saved. Written through `library`, which holds the rows
    the other grid is drawn from next. `grid_of` rather than the grid, because a caller
    wires this before the grid exists.
    """
    @on_page
    async def rate_games(game_ids: list[str], value: int) -> bool:
        saved: set[str] = set()
        try:
            for game_id in game_ids:
                await run.io_bound(library.set_game_rating, game_id, value)
                saved.add(game_id)
        except Exception as exc:
            ui.notify(t("manager.stars.save_failed"), caption=why(exc),
                      type="negative")
        changed = [{**row, game_field: value} for row in held
                   if (row.get("game_id") or row["id"]) in saved]
        if changed:
            grid.transact(grid_of(), held, {"update": changed}, rows_by_id)
        return len(saved) == len(game_ids)

    return rate_games


def rating_handler(held: list[dict[str, Any]], rows_by_id: dict[str, Any],
                   grid_of: Callable[[], Any], library: Any,
                   game_field: str = "rating") -> Callable[[Any], Any]:
    """One handler for both grids: write it, then repaint only the rows that changed - a
    whole-grid refresh costs the scroll position and the selection for one number.

    A game's rating goes through `game_rater`; a table's repaints its own row.
    """
    rate_games = game_rater(held, rows_by_id, grid_of, library, game_field)

    @on_page
    async def rate(event: Any) -> None:
        args = event.args if isinstance(event.args, dict) else {}
        game_id = str(args.get("game") or "")
        table_id = str(args.get("table") or "")
        value = int(args.get("value") or 0)
        if not game_id:
            return
        if not table_id:
            await rate_games([game_id], value)
            return
        try:
            await run.io_bound(library.set_table_rating, game_id, table_id, value)
        except Exception as exc:
            ui.notify(t("manager.stars.save_failed"), caption=why(exc),
                      type="negative")
            return
        row = rows_by_id.get(table_id)
        if row is not None:
            grid.transact(grid_of(), held, {"update": [{**row, "rating": value}]},
                          rows_by_id)

    return rate
