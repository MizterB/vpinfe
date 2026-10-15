"""The questions asked before something VPinFE did not ship is let run.

A theme that is not from the VPinFE Theme List and an extension that is not included with
VPinFE both run code on this device, and VPinFE cannot check what it does. Each is asked
about here, in the same words wherever it is met, and answered with the Owner's yes: the
callers only go on to accept on a True.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from nicegui import ui

from common.i18n import t
from console import dialog as frame
from console import panel, verbs

__all__ = ["chips", "extension", "new_access", "theme"]


def chips(words: Sequence[str]) -> Callable[[], None]:
    def draw() -> None:
        with ui.element("div").classes("console-chips"):
            for word in words:
                ui.label(word).classes("console-tier console-tier--on")

    return draw


async def _ask(title: str, lines: Sequence[str], answer: str, *,
               uses: tuple[str, Sequence[str]] | None = None, remote: Sequence[str] = (),
               closing: str = "") -> bool:
    with frame.opened(title, classes="console-confirm") as box:
        for line in lines:
            ui.label(line).classes("console-help px-3")
        if uses is not None:
            panel.facts(ui, [(uses[0], chips(uses[1]))])
        if remote:
            panel.facts(ui, [(t("console.accept.remote"), chips(remote))])
        if closing:
            ui.label(closing).classes("console-help px-3")
        with frame.footer():
            frame.cancel(lambda: box.submit(False))
            frame.answer(answer, lambda: box.submit(True), icon=verbs.ACCEPT)
    return bool(await box)


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


async def extension(name: str, version: str, folder: str, uses: Sequence[str], *,
                    remote: Sequence[str] = (), replaces: str = "") -> bool:
    """Whether to let this extension run. `uses` is what it says it uses, in words;
    `remote` is what a Remote can open; `replaces` names the built-in it stands in for."""
    lines = [t("console.accept.ext_body", name=name, version=version, folder=folder)]
    if replaces:
        lines.append(t("console.accept.replaces", name=replaces))
    return await _ask(
        t("console.accept.ext_title"), lines, t("console.accept.accept"),
        uses=(t("console.accept.uses"), uses), remote=remote,
        closing=t("console.accept.ext_trust"))


async def new_access(name: str, version: str, added: Sequence[str],
                     remote: Sequence[str] = ()) -> bool:
    """Whether to let a newer version of an accepted extension use `added`, and let a Remote
    open `remote`, which the version accepted did not say."""
    with frame.opened(t("console.accept.access_title", name=name),
                      classes="console-confirm") as box:
        ui.label(t("console.accept.access_body", version=version)).classes("console-help px-3")
        if added:
            panel.facts(ui, [(t("console.accept.uses"), chips(added))])
        if remote:
            panel.facts(ui, [(t("console.accept.remote"), chips(remote))])
        ui.label(t("console.accept.access_stopped")).classes("console-help px-3")
        with frame.footer():
            frame.cancel(lambda: box.submit(False))
            frame.answer(t("console.accept.accept"), lambda: box.submit(True),
                         icon=verbs.ACCEPT)
    return bool(await box)
