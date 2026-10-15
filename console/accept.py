"""The questions asked before something VPinFE did not ship is let run.

A theme that is not from the VPinFE Theme List and an extension that is not included with
VPinFE both run code on this device, and VPinFE cannot check what it does. Each is asked
about here, in the same words wherever it is met, and answered with the Owner's yes: the
callers only go on to accept on a True.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from nicegui import ui

from common.i18n import t
from console import dialog as frame
from console import ext_mark, panel, verbs

__all__ = ["chips", "extension", "new_access", "theme"]


def chips(words: Sequence[str]) -> Callable[[], None]:
    def draw() -> None:
        with ui.element("div").classes("console-chips"):
            for word in words:
                ui.label(word).classes("console-tier console-tier--on")

    return draw


async def _ask(title: str, lines: Sequence[str], answer: str, *,
               rows: Sequence[tuple[Any, ...]] = (), closing: str = "") -> bool:
    with frame.opened(title, classes="console-confirm") as box:
        for line in lines:
            ui.label(line).classes("console-help px-3")
        if rows:
            panel.facts(ui, rows)
        if closing:
            ui.label(closing).classes("console-help px-3")
        with frame.footer():
            frame.cancel(lambda: box.submit(False))
            frame.answer(answer, lambda: box.submit(True), icon=verbs.ACCEPT)
    return bool(await box)


def _capability_rows(uses: Sequence[str], remote: Sequence[str]) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    if uses:
        rows.append((t("console.accept.uses"), chips(uses)))
    if remote:
        rows.append((t("console.accept.remote"), chips(remote)))
    return rows


async def theme(name: str, *, source: str = "", installing: bool = False) -> bool:
    """Whether to let this theme run. `source` is where it comes from, empty for one found
    in the themes folder; `installing` is a theme not here yet, whose answer also installs
    it."""
    where = (t("console.accept.theme_from", name=name, source=source) if source
             else t("console.accept.theme_found", name=name))
    return await _ask(
        t("console.accept.theme_install_title" if installing
          else "console.accept.theme_use_title"),
        [where, t("console.accept.theme_risk")],
        t("console.accept.accept_install" if installing else "console.accept.accept"),
        closing=t("console.accept.theme_install_trust" if installing
                  else "console.accept.theme_use_trust"))


async def extension(name: str, version: str, *, author: str, source: str, path: str,
                    uses: Sequence[str], remote: Sequence[str] = (), replaces: str = "",
                    replaces_version: str = "") -> bool:
    """Whether to let this extension run. `uses` is what it says it uses, in words;
    `remote` is what a Remote can open; `replaces` names the built-in it stands in for,
    and `replaces_version` the one that comes with VPinFE."""
    lines = [t("console.accept.ext_body", name=name)]
    if replaces:
        lines.append(t("console.accept.replaces_version", name=replaces,
                       version=replaces_version) if replaces_version
                     else t("console.accept.replaces", name=replaces))
    rows: list[tuple[Any, ...]] = [(t("console.ext_page.author"), author),
                                   (t("console.ext_page.version_label"), version)]
    if source:
        rows.append((t("console.ext_page.source"),
                     panel.link_out(ext_mark.source_shown(source), to=source, hint=source,
                                    rel="noopener noreferrer")))
    if path:
        rows.append((t("console.ext_page.folder_path"), panel.path_value(path)))
    rows += _capability_rows(uses or [t("word.none")], remote)
    return await _ask(t("console.accept.ext_title"), lines, t("console.accept.accept"),
                      rows=rows, closing=t("console.accept.ext_trust"))


async def new_access(name: str, version: str, author: str, added: Sequence[str],
                     remote: Sequence[str] = (), *, was: str = "") -> bool:
    """Whether to let a newer version of an accepted extension use `added`, and let a Remote
    open `remote`, which the version accepted did not say. `was` is that version, when it
    is known. The author is shown again so an update says whose it is."""
    rows: list[tuple[Any, ...]] = [(t("console.ext_page.author"), author)]
    if added or remote:
        rows.append((t("console.accept.new_capabilities"), chips([*added, *remote])))
    body = (t("console.accept.access_body", was=was, version=version) if was and was != version
            else t("console.accept.access_body_to", version=version))
    return await _ask(t("console.accept.access_title", name=name), [body],
                      t("console.accept.accept"), rows=rows,
                      closing=t("console.accept.access_stopped"))
