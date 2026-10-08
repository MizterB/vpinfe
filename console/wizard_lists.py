"""The wizard fields for a long list of rows, and a picture drawn from the person's own files.

`checklist` is a list to tick and `settle` is a list of rows each answered with a VPS entry.
Both are for hundreds of rows, where `multi` is a closed dropdown; each hands the wizard a
control whose `value` is the answer, so `wizard._sync` reads them the way it reads any other.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from nicegui import background_tasks, ui

from common.i18n import t
from console import offload, panel, verbs, vps_match
from console.api import ApiClient
from console.data import Library
from console.on_page import on_page


class Answer(ui.element):
    """The box a list is drawn in. `value` is what the person has answered so far."""

    def __init__(self, value: Any) -> None:
        super().__init__("div")
        self.value = value


def _heading(question: str) -> None:
    ui.label(question).classes("console-card-title console-wizard-question")


def checklist(field: dict[str, Any], ticked: Sequence[str],
              on_change: Callable[[list[str]], None], *, question: str = "",
              on_control: Callable[[Any], None]) -> Callable[[], None]:
    """`rows` are `{key, name, note, groups}` and `chips` are `[group, label]`. A chip is
    drawn only when a row is in its group, and picks the rows to show. The answer is the
    keys ticked, in the rows' order."""
    rows = [one for one in field.get("rows") or [] if one.get("key")]
    present = {str(group) for one in rows for group in one.get("groups") or ()}
    chips = [(str(one[0]), str(one[1])) for one in field.get("chips") or []
             if str(one[0]) in present]

    def draw() -> None:
        ticks = {str(key) for key in ticked}
        shown: dict[str, ui.element] = {}
        boxes: dict[str, ui.checkbox] = {}
        looking = {"text": "", "group": ""}
        bulk = {"on": False}
        with ui.column().classes("w-full gap-2"):
            if question:
                _heading(question)
            with ui.row().classes("items-center gap-3 w-full no-wrap"):
                find = panel.search(t("console.wizard_lists.filter")).props("debounce=150")
                find.classes(remove="w-64", add="grow")
                find.on("keyup.enter.stop", lambda: None)
                if chips:
                    chosen = panel.segmented(
                        {"": t("word.all"), **dict(chips)}, "",
                        lambda event: look(group=str(event.value or "")))
                    chosen.props["aria-label"] = t("console.wizard_lists.show")
            with ui.row().classes("items-center gap-2 w-full no-wrap"):
                count = ui.label("").classes("console-help grow")
                panel.action(t("console.wizard_lists.select_all"),
                             lambda: setall(True), icon=verbs.ACCEPT,
                             hint=t("console.wizard_lists.select_all.hint"))()
                panel.action(t("console.wizard_lists.select_none"),
                             lambda: setall(False), icon=verbs.CLEAR,
                             hint=t("console.wizard_lists.select_none.hint"))()
            box = Answer([one["key"] for one in rows if str(one["key"]) in ticks]) \
                .classes("console-wizard-list")
            empty = ui.label(t("console.wizard_lists.no_match")).classes("console-help px-3")
            empty.set_visibility(False)
            with box:
                for one in rows:
                    key = str(one["key"])
                    row = ui.element("div").classes("console-wizard-listrow")
                    with row:
                        tick = ui.checkbox(value=key in ticks).props("dense")
                        with ui.column().classes("gap-0 min-w-0 grow") as words:
                            ui.label(str(one.get("name") or key)) \
                                .classes("console-source-name")
                            if one.get("note"):
                                ui.label(str(one["note"])).classes("console-help")
                    words.on("click", lambda tick=tick: tick.set_value(not tick.value))
                    tick.on_value_change(lambda event, key=key: wrote(key, bool(event.value)))
                    shown[key] = row
                    boxes[key] = tick
        on_control(box)

        def wrote(key: str, on: bool) -> None:
            (ticks.add if on else ticks.discard)(key)
            if not bulk["on"]:
                commit()

        def commit() -> None:
            box.value = [str(one["key"]) for one in rows if str(one["key"]) in ticks]
            count.set_text(t("console.wizard_lists.ticked", ticked=len(box.value),
                             total=len(rows)))
            on_change(box.value)

        def wanted(one: dict[str, Any]) -> bool:
            text = looking["text"].strip().casefold()
            if text and text not in str(one.get("name") or "").casefold():
                return False
            return not looking["group"] or looking["group"] in (one.get("groups") or ())

        def look(text: str | None = None, group: str | None = None) -> None:
            if text is not None:
                looking["text"] = text
            if group is not None:
                looking["group"] = group
            seen = 0
            for one in rows:
                here = wanted(one)
                shown[str(one["key"])].set_visibility(here)
                seen += here
            empty.set_visibility(not seen)

        def setall(on: bool) -> None:
            bulk["on"] = True
            try:
                for one in rows:
                    if wanted(one):
                        boxes[str(one["key"])].set_value(on)
            finally:
                bulk["on"] = False
            commit()

        find.on_value_change(lambda event: look(text=str(event.value or "")))
        count.set_text(t("console.wizard_lists.ticked", ticked=len(box.value),
                         total=len(rows)) if rows else "")
        empty.set_visibility(not rows)

    return draw


def settle(field: dict[str, Any], answered: dict[str, str],
           on_change: Callable[[dict[str, str]], None], *, client: ApiClient,
           question: str = "",
           on_control: Callable[[Any], None]) -> Callable[[], None]:
    """`rows` are `{key, name, candidate, vps_id, reason, settled}`. A row says its
    candidate, or Not found, and why in a few words; Change... opens the VPS picker. A
    settled row is behind Show all.

    The answer maps a row's key to the VPS id the person picked. A key absent was left as
    the source had it, and `""` is a row the person said is in no catalog."""
    rows = [one for one in field.get("rows") or [] if one.get("key")]
    unsettled = [one for one in rows if not one.get("settled")]

    def draw() -> None:
        library = Library(client)
        picks = {str(key): str(vps) for key, vps in answered.items()}
        named: dict[str, str] = {}
        lines: dict[str, ui.label] = {}
        holders: dict[str, ui.element] = {}
        every = {"on": False}
        with ui.column().classes("w-full gap-2"):
            if question:
                _heading(question)
            box = Answer(dict(picks)).classes("console-wizard-list")
            with ui.row().classes("items-center gap-2 w-full no-wrap"):
                summary = ui.label("").classes("console-help grow")
                with ui.row().classes("items-center") as reveal:
                    panel.action(t("console.wizard_lists.show_all", count=len(rows)),
                                 lambda: toggle(), icon=verbs.UNHIDE,
                                 hint=t("console.wizard_lists.show_all.hint"))()
                    panel.action(t("console.wizard_lists.hide_settled"),
                                 lambda: toggle(), icon=verbs.HIDE,
                                 hint=t("console.wizard_lists.hide_settled.hint"))()
                shows, hides = [one for one in reveal.default_slot.children
                                if isinstance(one, ui.button)]
            with box:
                for one in rows:
                    key = str(one["key"])
                    row = ui.element("div").classes("console-wizard-listrow")
                    with row:
                        with ui.column().classes("gap-0 min-w-0 grow"):
                            ui.label(str(one.get("name") or key)) \
                                .classes("console-source-name")
                            lines[key] = ui.label("").classes("console-help")
                        with ui.element("div").classes("shrink-0"):
                            panel.action(t("console.wizard_lists.change"),
                                         lambda one=one: change(one), icon=verbs.MATCH,
                                         hint=t("console.wizard_lists.change.hint"))()
                    holders[key] = row
        on_control(box)

        def saying(one: dict[str, Any]) -> str:
            key = str(one["key"])
            if key in picks:
                if not picks[key]:
                    return t("console.wizard_lists.not_matched")
                return named.get(key) or t("console.wizard_lists.picked")
            said = str(one.get("candidate") or "") or t("word.not_found")
            if not one.get("reason"):
                return said
            return t("console.wizard_lists.candidate_why", candidate=said,
                     reason=str(one["reason"]))

        def redraw(one: dict[str, Any]) -> None:
            lines[str(one["key"])].set_text(saying(one))

        def visible() -> None:
            for one in rows:
                holders[str(one["key"])].set_visibility(every["on"] or not one.get("settled"))
            settled = len(rows) - len(unsettled)
            summary.set_text(t("console.wizard_lists.all_settled", count=len(rows))
                             if rows and not unsettled else "")
            shows.set_visibility(not every["on"])
            hides.set_visibility(every["on"])
            reveal.set_visibility(bool(settled))

        def toggle() -> None:
            every["on"] = not every["on"]
            visible()

        @on_page
        async def change(one: dict[str, Any]) -> None:
            key = str(one["key"])
            game = {"name": str(one.get("name") or key),
                    "vps_id": picks[key] if key in picks else str(one.get("vps_id") or "")}
            found = await vps_match.ask(library, game)
            if found in (vps_match.CANCELLED, vps_match.STOPPED, None) \
                    or lines[key].is_deleted:
                return
            if found == "":
                picks.pop(key, None)
            elif found == vps_match.CLEARED:
                picks[key] = ""
            else:
                picks[key] = str(found)
                named.pop(key, None)
            box.value = dict(picks)
            redraw(one)
            on_change(box.value)
            if found not in ("", vps_match.CLEARED):
                await name_it(one)

        async def name_it(one: dict[str, Any]) -> None:
            key = str(one["key"])
            vps = picks.get(key)
            if not vps or key in named:
                return
            try:
                entry = await offload.io(library.vps_entry, vps)
            except Exception:  # noqa: BLE001
                return
            if picks.get(key) == vps and not lines[key].is_deleted:
                named[key] = str(entry.get("name") or "")
                redraw(one)

        for one in rows:
            redraw(one)
        visible()
        for one in rows:
            if picks.get(str(one["key"])):
                background_tasks.create(name_it(one), name="console-wizard-settle-named")

    return draw


def shots(paths: Sequence[str], url_for: Callable[[str], str]) -> None:
    """A few of the person's own images, small, in a row. The paths are the flow's, inside
    the folders it declared; a file that will not load leaves its frame empty."""
    with ui.element("div").classes("console-wizard-shots"):
        for path in paths:
            with ui.element("span").classes("console-wizard-shot"):
                image = ui.element("img")
                image.props["src"] = url_for(str(path))
                image.props["loading"] = "lazy"
                image.props["alt"] = ""

