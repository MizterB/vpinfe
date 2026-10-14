"""An extension's own page: one subject drawn as a panel, with no grid.

The extension answers `read()` with a title, a line under it and sections of facts, fields
and rows, as a list's pane does for a row, and core draws them as it draws every other
panel. A field is written when it is set, and the answer to that write is the page drawn
again. The title menu is the page's acts, with the extension's Settings after them.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from nicegui import ui

from common.failures import why
from common.i18n import t
from console import busy, community, ext_row, offload, panel
from console.api import ApiClient
from console.on_page import on_page


def is_page(view: str) -> bool:
    return view.startswith(community.PAGE_PREFIX)


def pages(extensions: Sequence[dict[str, Any]]) -> list[tuple[dict, dict]]:
    """(extension, page) for every page a running extension declares."""
    return [(one, declared) for one in extensions
            if str(one.get("state") or "") == "loaded"
            for declared in one.get("pages") or []]


def find(view: str, extensions: Sequence[dict[str, Any]]) -> tuple[dict, dict] | None:
    return next(((one, declared) for one, declared in pages(extensions)
                 if community.page_view_key(str(one.get("name") or ""),
                                            str(declared.get("key") or "")) == view), None)


def route(extension: dict[str, Any], declared: dict[str, Any]) -> str:
    return f"/ext/{extension.get('name')}{declared['base']}"


def build(extension: dict[str, Any], declared: dict[str, Any], subject: Any = None,
          host: str = "") -> None:
    """`subject` is the page header's slot for the page's menu. `host` is where the Console
    was opened, which a link fact's `{host}` is filled with."""
    body = ui.column().classes("w-full grow min-h-0 gap-3 px-3 py-2")
    busy.fill(body, lambda: show(body, extension, declared, subject, host, None))


@on_page
async def show(body: Any, extension: dict[str, Any], declared: dict[str, Any],
               subject: Any, host: str, answer: dict[str, Any] | None) -> None:
    """The page from `answer` where the write that came just before it gave one, else read
    again. The menu is read again either way: an act can change what the next one is."""
    said = str(extension.get("display_name") or extension.get("name") or "")
    where = route(extension, declared)
    if answer is None:
        try:
            answer = dict(await offload.io(ApiClient().ext_get, where))
        except Exception as exc:  # noqa: BLE001 - the extension's words, or the API's
            if body.is_deleted:
                return
            body.clear()
            with body:
                panel.facts(ui, [panel.intro(t("console.community.read_failed", name=said),
                                             hint=why(exc))])
            await menu(subject, extension, declared, body, host)
            return
    if body.is_deleted:
        return

    async def redraw(new: dict[str, Any] | None) -> None:
        await show(body, extension, declared, subject, host, new)

    held = {"state": {"host": host}, "route": where, "redraw": redraw, "again": None}
    entries: list[tuple[Any, ...]] = [(panel.HEADING, str(answer.get("title") or ""))]
    if answer.get("under"):
        entries.append(panel.note(str(answer["under"])))
    for one in answer.get("sections") or []:
        if one.get("label"):
            entries.append((panel.HEADING, str(one["label"])))
        entries += ext_row.section_entries(one, held)
    body.clear()
    with body:
        if answer.get("picture"):
            ui.image(answer["picture"]).classes("console-pane-picture")
        panel.facts(ui, entries)
    await menu(subject, extension, declared, body, host)


async def menu(subject: Any, extension: dict[str, Any], declared: dict[str, Any],
               body: Any, host: str) -> None:
    """The page's acts, in the header, read now."""
    if subject is None or subject.is_deleted:
        return
    about = str(declared.get("about") or "")
    now = await offload.io(community.as_it_stands, extension)
    found = await offload.io(community.standing, str(extension.get("name") or ""), about)

    async def after_act() -> None:
        await show(body, extension, declared, subject, host, None)

    panel.subject_menu(subject, community.acts(
        now, found, lambda act: community.run_act(now, about, act, after_act)))
