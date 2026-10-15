"""What extensions add to the Games and Tables menus.

Each extension's entries are one block after core's, in the grid's row menu, its selection
menu and the panel header's, because they are drawn from the one list of verbs each subject
has. The block is headed with the extension's name, bundled ones first, then the others,
each alphabetical.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from functools import partial
from typing import Any
from urllib.parse import quote

from nicegui import ui

from common.failures import why
from common.i18n import t
from manager.extensions import ext_lists, ext_mark
from manager.kit import confirm, offload, panel, verbs
from manager.kit.api import ApiClient
from manager.kit.on_page import on_page

Again = Callable[[], Awaitable[Any]]


def _in_order(extensions: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(extensions, key=lambda one: (
        not one.get("bundled"),
        str(one.get("display_name") or one.get("name") or "").casefold()))


@on_page
async def press(extension: dict[str, Any], verb: dict[str, Any],
                targets: list[dict[str, str]], again: Again) -> None:
    """Press one of an extension's entries on `targets`, asking first where it is a danger,
    and say what it answered."""
    label = str(verb["label"])
    if verb["danger"]:
        question = t(str(verb.get("confirm_key") or "") or "manager.community.verb.confirm",
                     label=label, count=len(targets))
        if not await confirm.ask(question, confirm=label, icon=verbs.ACCEPT):
            return
    try:
        said = await offload.io(
            ApiClient().ext_post,
            f"/ext/{extension['name']}/verbs/{verb['subject']}/{quote(str(verb['key']), safe='')}",
            {"targets": targets})
    except Exception as exc:  # noqa: BLE001 - the reason belongs on screen
        ui.notify(t("said.action_failed"), caption=why(exc), type="negative")
        return
    await ext_lists.told(said, again)


def offered(state: dict[str, Any], subject: str, targets: list[dict[str, str]],
            again: Again, *, public: list[dict[str, str]] | None = None) -> list[panel.Verb]:
    """The entries the running extensions have for `subject` (`game` or `table`) over
    `targets`, each `{"game_id", "table_id"}`, a block for each extension. `public` is the
    part of `targets` that is not a Private game: an entry that does not work on Private
    games is pressed on those alone, and not offered where none are left."""
    if not targets:
        return []
    out: list[panel.Verb] = []
    for extension in _in_order(state.get("extensions") or []):
        name = str(extension.get("display_name") or extension.get("name") or "")
        for verb in extension.get("library_verbs") or []:
            if verb["subject"] != subject:
                continue
            chosen = targets if public is None or verb.get("private_ok") else public
            if not chosen:
                continue
            out.append(panel.Verb(
                str(verb["label"]), run=partial(press, extension, verb, chosen, again),
                danger=bool(verb["danger"]), one=bool(verb["one"]), tip=str(verb["tip"]),
                block=name, block_mark=ext_mark.drawer(extension)))
    return out
