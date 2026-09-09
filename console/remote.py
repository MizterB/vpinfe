"""The remote: VPinFE in one hand.

A fourth posture, and the whole specification. Not the frontend, which is read across a
room; not the Console, which is a workbench at a desk. This is standing beside the
machine or sitting across from it - one thumb, screen lit for twenty seconds at a time.
Anything that does not fit that is not on this surface.

A second shell rather than a stylesheet, because the Console *is* a workbench - a
splitter with a list on one side and an inspector on the other - and a phone cannot hold
two panes. Below its own width the organizing idea is simply absent, so what would ship
is a shell missing the thing it is for. The client, the reads, the tokens and the fact
list are all shared; only the shape is new.

Three screens, and they read as a sequence: what is happening, pick something, drive it.
"""

from __future__ import annotations

import logging
from typing import Any

from nicegui import run, ui

from common import install_identity
from common.labels import humanize
from console import stars, theme
from console.api import ApiClient, local_base_url

logger = logging.getLogger("vpinfe.console.remote")

NOW, PLAY, CONTROL = "now", "play", "control"

SCREENS = (
    (NOW, "Now", "radio_button_checked"),
    (PLAY, "Play", "search"),
    (CONTROL, "Control", "gamepad"),
)


def base_url_of(device: dict[str, Any], local_device_id: str) -> str:
    """Where to send this target's requests.

    Loopback for the install serving this page, whatever address it recorded for itself:
    a machine's own registry entry holds the address other machines reach it on, and
    dialling that from here would leave the network to answer a question we can answer
    without it.
    """
    if device.get("device_id") == local_device_id:
        return local_base_url()
    address = str(device.get("address") or "").strip()
    port = int(device.get("port") or 0)
    return f"http://{address}:{port}" if address and port else ""


def targets(devices: list[dict[str, Any]], local_device_id: str) -> list[dict[str, Any]]:
    """The devices worth aiming at, which is the ones that play.

    A device with no frontend is a real device and belongs in the Console's list; it is
    not something a remote points at, and offering it would make the picker a list of
    machines rather than a list of answers to "where".
    """
    found = [one for one in devices
             if install_identity.FRONTEND in (one.get("features") or ())
             and base_url_of(one, local_device_id)]
    # This install first: it is the one the person is most likely to mean, and it is the
    # only one that is certainly there - it is serving the page.
    return sorted(found, key=lambda one: one.get("device_id") != local_device_id)


def target_name(device: dict[str, Any]) -> str:
    return str(device.get("display_name") or "").strip() or "This machine"


def last_played(games: list[dict[str, Any]]) -> dict[str, Any]:
    """The game played most recently, or nothing where none has been.

    Read off the library rather than from the frontend's own record of what it last
    launched: that one is per install and per window, and the question here is which
    game *this person* last had a game on.
    """
    played = [one for one in games if (one.get("user") or {}).get("last_played")]
    if not played:
        return {}
    return max(played, key=lambda one: str(one["user"]["last_played"]))


def _read_here() -> dict[str, Any]:
    """What this install knows about the network, made off the event loop.

    The Console consumes its own process over HTTP, so a page handler that asks the API
    a question while holding the loop deadlocks - uvicorn cannot answer a request it is
    blocked inside.
    """
    client = ApiClient()
    return {
        "devices": client.devices(),
        "local_device_id": str(client.discovery().get("install_id") or ""),
    }


def _read_target(client: ApiClient) -> dict[str, Any]:
    """What the chosen machine is doing and what it can play.

    Asked of the target rather than of this install, because that is the machine the
    launch is going to. Two installs can hold different libraries, and a list read from
    the wrong one offers games whose ids the target has never heard of.
    """
    return {
        "play": client.play_state(),
        "games": client.games(),
        "jobs": client.jobs(),
        "collections": client.collections(),
    }


@ui.page("/remote", title="VPinFE Remote", reconnect_timeout=300)
async def remote_page(screen: str = "") -> None:
    """The remote. `screen` names which of the three, so a place can be linked to."""
    ui.dark_mode(True)
    theme.apply_colors(dark=True)
    theme.apply_flair()
    theme.apply_surface("remote")
    # The shell takes the viewport once and everything below it is flex, the same way
    # the Console's does - a pane that subtracts a fixed header height collapses the
    # moment that header changes.
    ui.query(".nicegui-content").classes("p-0 gap-0 h-screen")
    # A phone locking its screen is the most common disconnect there is, far more common
    # than anything a desk session sees, so the meta viewport matters as much as the
    # reconnect timeout above.
    ui.add_head_html(
        '<meta name="viewport" content="width=device-width, initial-scale=1, '
        'viewport-fit=cover">')

    with ui.column().classes("w-full h-full items-center justify-center gap-3") as loading:
        ui.spinner(size="lg").classes("text-primary")
        ui.label("Loading").classes("text-sm opacity-60")

    await ui.context.client.connected()
    loaded = await run.io_bound(_read_here)
    if ui.context.client.is_deleted:
        # Reading takes long enough that somebody can close the tab inside it, and there
        # is then nothing to draw on. Building anyway raises out of the page function and
        # logs a stack trace for somebody having changed their mind.
        return
    loading.delete()

    local_device_id = loaded["local_device_id"]
    aimable = targets(loaded["devices"], local_device_id)
    state: dict[str, Any] = {
        "screen": screen if screen in {key for key, *_ in SCREENS} else NOW,
        "target": aimable[0] if aimable else {},
        "play": {}, "games": [], "jobs": [], "collections": [],
        "find": "", "collection": "",
    }

    def client_for_target() -> ApiClient:
        """A client aimed at whichever target is chosen. The picker is a base URL."""
        return ApiClient(base_url_of(state["target"], local_device_id) or None)

    async def reread() -> None:
        """Ask the chosen machine again. Failure is a state, not a crash: a target that
        has gone away is the ordinary case for a page held in a hand."""
        if not state["target"]:
            return
        try:
            state.update(await run.io_bound(_read_target, client_for_target()))
            state["reachable"] = True
        except Exception as exc:
            logger.info("remote: %s did not answer: %s",
                        target_name(state["target"]), exc)
            state.update({"play": {}, "games": [], "jobs": [], "collections": [],
                          "reachable": False})

    def redraw() -> None:
        """Both, always. The bar says which screen you are on, so a redraw that rebuilt
        only the screen left the mark behind on the one you came from."""
        body.clear()
        tabs.clear()
        with body:
            _screen(state, client_for_target, redraw)
        with tabs:
            _tabs(state, redraw)

    async def aim(device: dict[str, Any]) -> None:
        """A different machine is a different library, a different state and a different
        base URL, so everything below the header is read again."""
        state.update({"target": device, "find": "", "collection": ""})
        await reread()
        redraw()

    # Header, then the screen, then the tabs, in that order and inside the shell: the
    # body has to be built here rather than earlier and reparented, because a NiceGUI
    # element belongs to whatever slot was open when it was made.
    with ui.column().classes("w-full h-full gap-0 remote-shell no-wrap"):
        _header(state, aimable, aim)
        body = ui.column().classes(
            "w-full grow min-h-0 gap-0 overflow-auto remote-body")
        tabs = ui.row().classes("w-full items-stretch gap-0 remote-tabs no-wrap")
    await reread()
    redraw()


def _header(state: dict[str, Any], aimable: list[dict[str, Any]],
            aim) -> None:
    """The target, on every screen, because every action's meaning depends on it.

    Drawn as a picker only when there is a choice to make. With one target it is the
    name alone - a select with one option is furniture, which is the same rule that
    keeps a chip off every row.
    """
    with ui.row().classes("w-full items-center gap-2 remote-header no-wrap"):
        ui.icon("sports_esports").classes("remote-mark")
        if len(aimable) > 1:
            names = {one["device_id"]: target_name(one) for one in aimable}
            by_id = {one["device_id"]: one for one in aimable}

            async def chosen(event) -> None:
                await aim(by_id.get(event.value, {}))

            ui.select(names, value=state["target"].get("device_id"),
                      on_change=chosen) \
                .props("dense borderless options-dense") \
                .classes("remote-target grow min-w-0")
        elif aimable:
            ui.label(target_name(state["target"])).classes("remote-target-name truncate")
        else:
            # Not an error: an install with no frontend feature is a library somebody
            # administers, and there is nothing here for a remote to drive.
            ui.label("Nothing to drive from here").classes("remote-target-name truncate")


def _tabs(state: dict[str, Any], redraw) -> None:
    """The three screens, at the bottom, where a thumb is.

    Not a nav rail and not a drawer: with three destinations and one hand, the whole map
    is worth the space it takes, and hiding it behind a button charges a tap to find out
    what the page can do.
    """
    for key, label, icon in SCREENS:
        def go(_event=None, key=key) -> None:
            state["screen"] = key
            redraw()

        here = state["screen"] == key
        with ui.column().on("click", go) \
                .classes("remote-tab" + (" remote-tab--here" if here else "")):
            ui.icon(icon).classes("remote-tab-icon")
            ui.label(label).classes("remote-tab-label")


def _screen(state: dict[str, Any], client_for_target, redraw) -> None:
    if not state["target"]:
        return _nothing("Nothing to drive from here")
    if state.get("reachable") is False:
        # Said before anything is pressed rather than as the answer to a press: a target
        # that is not there is a fact about the screen, not a failed request.
        return _nothing(f"{target_name(state['target'])} is not answering")
    if state["screen"] == NOW:
        _now(state, client_for_target, redraw)
    elif state["screen"] == PLAY:
        _play(state, client_for_target, redraw)
    else:
        _nothing("Control")


def _nothing(said: str) -> None:
    with ui.column().classes("w-full items-center justify-center grow gap-2 p-6"):
        ui.label(said).classes("remote-empty text-center")


def _now(state: dict[str, Any], client_for_target, redraw) -> None:
    """What this machine is doing, and the one thing worth doing about it.

    What is playing, what work is running and anything wanting attention are three
    answers to one question - what is this machine doing - so they are one screen. Split
    apart, this one has nothing to say most of the time.
    """
    play = state.get("play") or {}
    with ui.column().classes("w-full gap-3 p-3"):
        if play.get("launching"):
            _playing(play, state, client_for_target, redraw)
        else:
            _idle(state, redraw)
        _running_jobs(state)


def _playing(play: dict[str, Any], state: dict[str, Any], client_for_target,
             redraw) -> None:
    async def quit_table() -> None:
        try:
            await run.io_bound(client_for_target().stop_play)
        except Exception as exc:
            ui.notify(str(exc), type="negative")
            return
        state["play"] = await run.io_bound(client_for_target().play_state)
        redraw()

    with ui.column().classes("w-full gap-1 console-card"):
        ui.label("Playing").classes("console-card-title")
        ui.label(str(play.get("game_name") or "A table")).classes("remote-headline")
    ui.button("Quit table", on_click=quit_table) \
        .props("no-caps unelevated").classes("remote-action remote-action--danger")


def _idle(state: dict[str, Any], redraw) -> None:
    """Nothing is playing, so this offers the one thing worth doing about that.

    The last game played, with its rating. That is the moment somebody has an opinion
    about a table and the phone is already in their hand, and it is the only reason this
    screen has anything to say when the machine is quiet.
    """
    game = last_played(state.get("games") or [])
    if not game:
        with ui.column().classes("w-full gap-1 console-card"):
            ui.label("Nothing playing").classes("remote-headline")
        return

    async def rate(value: int) -> None:
        try:
            await run.io_bound(ApiClient().rate, game["id"], value)
        except Exception as exc:
            ui.notify(str(exc), type="negative")
            return
        game.setdefault("user", {})["rating"] = value
        redraw()

    with ui.column().classes("w-full gap-2 console-card"):
        ui.label("Last played").classes("console-card-title")
        ui.label(str(game.get("name") or "")).classes("remote-headline")
        stars.draw(int((game.get("user") or {}).get("rating") or 0), rate)()


def _running_jobs(state: dict[str, Any]) -> None:
    """Only what is still going. A finished job is not news on a screen this size, and
    a list that keeps yesterday's work is a list nobody reads."""
    for job in state.get("jobs") or []:
        if str(job.get("state") or "") != "running":
            continue
        with ui.column().classes("w-full gap-2 console-card"):
            ui.label("Running").classes("console-card-title")
            # The kind is a wire word - `library.scan` - and nothing on this surface
            # shows one. A percentage says more than the name does anyway, so the name
            # is the label and the bar is the answer.
            ui.label(humanize(str(job.get("kind") or "").replace(".", " "))) \
                .classes("remote-headline")
            ui.linear_progress(value=float(job.get("pct") or 0) / 100,
                               show_value=False).props("rounded")
            if job.get("message"):
                ui.label(str(job["message"])).classes("remote-note")


# What the list will draw before it asks you to narrow it. A phone renders every row it
# is given, and a library is longer than a screen by design - the answer to a long list
# is typing into it, not scrolling it.
SHOWN_AT_ONCE = 40


def matching(games: list[dict[str, Any]], said: str) -> list[dict[str, Any]]:
    """The games a typed word finds.

    Name, maker and year, because those are the three things somebody standing at a
    machine knows about it. Every word has to land somewhere, so "bally 1991" narrows
    rather than widening - which is what a person means by typing a second word.
    """
    words = said.lower().split()
    if not words:
        return games
    found = []
    for game in games:
        against = " ".join(str(game.get(key) or "")
                           for key in ("name", "manufacturer", "year")).lower()
        if all(word in against for word in words):
            found.append(game)
    return found


def in_collection(games: list[dict[str, Any]],
                  ids: set[str] | None) -> list[dict[str, Any]]:
    """Narrowed to one collection, or left alone where none is chosen."""
    return games if ids is None else [one for one in games if one.get("id") in ids]


def manual_collections(collections: list[dict[str, Any]]) -> list[str]:
    """The ones a game can simply be put in.

    A filter collection is a rule, and pinning a game against a rule is a curator's
    decision made with the rule in view. That is desk work, and the posture line falls
    where it falls everywhere else here.
    """
    return [str(one.get("name") or "") for one in collections
            if str(one.get("type") or "") == "manual" and one.get("name")]


def _play(state: dict[str, Any], client_for_target, redraw) -> None:
    """Find a game and start it.

    The search field is first because the library is longer than a screen, and a list
    longer than a screen is typed into rather than scrolled.
    """
    async def typed(event) -> None:
        state["find"] = str(event.value or "")
        redraw()

    async def narrow(event) -> None:
        state["collection"] = str(event.value or "")
        state["collection_ids"] = None
        if state["collection"]:
            try:
                found = await run.io_bound(client_for_target().collection_games,
                                           state["collection"])
                state["collection_ids"] = {str(one.get("id") or "") for one in found}
            except Exception as exc:
                ui.notify(str(exc), type="negative")
        redraw()

    with ui.column().classes("w-full gap-2 p-3"):
        ui.input(placeholder="Find a game", value=state.get("find") or "",
                 on_change=typed) \
            .props("dense outlined clearable inputmode=search").classes("w-full")
        named = [one.get("name") for one in state.get("collections") or []
                 if one.get("name")]
        if named:
            ui.select({"": "Whole library"} | {name: name for name in named},
                      value=state.get("collection") or "", on_change=narrow) \
                .props("dense outlined options-dense").classes("w-full")

    found = in_collection(matching(state.get("games") or [],
                                   state.get("find") or ""),
                          state.get("collection_ids"))
    _game_list(found, state, client_for_target, redraw)


def _game_list(found: list[dict[str, Any]], state: dict[str, Any],
               client_for_target, redraw) -> None:
    if not found:
        return _nothing("Nothing by that name")
    with ui.column().classes("w-full gap-0"):
        for game in found[:SHOWN_AT_ONCE]:
            _game_row(game, state, client_for_target, redraw)
        left = len(found) - SHOWN_AT_ONCE
        if left > 0:
            # The count, not a "load more": what is wanted is one game, and typing two
            # more letters reaches it faster than paging to it does.
            ui.label(f"{left} more - keep typing").classes("remote-note p-3")


def _game_row(game: dict[str, Any], state: dict[str, Any], client_for_target,
              redraw) -> None:
    """One game, and a tap opens it rather than starting it.

    Never tap-to-launch. A mis-tap that opens a sheet costs a tap to undo; a mis-tap
    that starts a table takes the machine away from whoever is on it.
    """
    def open_sheet(_event=None) -> None:
        _game_sheet(game, state, client_for_target, redraw)

    with ui.row().on("click", open_sheet) \
            .classes("w-full items-center gap-2 no-wrap remote-row"):
        with ui.column().classes("grow min-w-0 gap-0"):
            ui.label(str(game.get("name") or "")).classes("remote-row-name truncate")
            made = " ".join(str(game.get(key) or "")
                            for key in ("manufacturer", "year")).strip()
            if made:
                ui.label(made).classes("remote-note truncate")
        if (game.get("user") or {}).get("favorite"):
            ui.icon("favorite").classes("remote-row-mark")


def _game_sheet(game: dict[str, Any], state: dict[str, Any], client_for_target,
                redraw) -> None:
    """One game, everything that can be done to it from here, and Launch at the foot.

    A sheet from the bottom rather than a screen of its own: what is being decided is
    about the row you just touched, and pushing a screen would take the list away to
    answer a question about one line of it.
    """
    with ui.dialog().props("position=bottom") as sheet, \
            ui.card().classes("w-full remote-sheet"):
        ui.label(str(game.get("name") or "")).classes("remote-headline")
        made = " ".join(str(game.get(key) or "")
                        for key in ("manufacturer", "year")).strip()
        if made:
            ui.label(made).classes("remote-note")

        async def write(call, *args) -> None:
            try:
                await run.io_bound(call, *args)
            except Exception as exc:
                ui.notify(str(exc), type="negative")
                return False
            return True

        async def rate(value: int) -> None:
            if await write(ApiClient().rate, game["id"], value):
                game.setdefault("user", {})["rating"] = value
                sheet.close()
                redraw()

        stars.draw(int((game.get("user") or {}).get("rating") or 0), rate)()

        held = bool((game.get("user") or {}).get("favorite"))

        async def favor() -> None:
            if await write(ApiClient().set_favorite, game["id"], not held):
                game.setdefault("user", {})["favorite"] = not held
                sheet.close()
                redraw()

        ui.button("Favorite" if not held else "Remove favorite",
                  icon="favorite" if not held else "favorite_border",
                  on_click=favor) \
            .props("no-caps flat").classes("remote-action")

        _add_to_collection(game, state, sheet, write)

        async def launch() -> None:
            if await write(client_for_target().launch, game["id"]):
                sheet.close()
                state["screen"] = NOW
                state["play"] = await run.io_bound(client_for_target().play_state)
                redraw()

        ui.button("Launch", icon="play_arrow", on_click=launch) \
            .props("no-caps unelevated color=primary") \
            .classes("remote-action remote-action--primary")
    sheet.open()


def _add_to_collection(game: dict[str, Any], state: dict[str, Any], sheet,
                       write) -> None:
    """Put it in a list you keep.

    Shown disabled with the reason rather than hidden when there is nowhere to put it:
    an action that vanishes leaves somebody wondering whether this surface can do it at
    all, and the answer is that it can once there is a list to add to.
    """
    named = manual_collections(state.get("collections") or [])
    if not named:
        ui.button("Add to collection", icon="playlist_add") \
            .props("no-caps flat disable").classes("remote-action") \
            .tooltip("No lists of your own yet - a filter collection follows a rule "
                     "rather than holding what you put in it")
        return

    async def add(name: str) -> None:
        if await write(ApiClient().add_to_collection, name, game["id"]):
            ui.notify(f"Added to {name}", type="positive")
            sheet.close()

    with ui.button("Add to collection", icon="playlist_add") \
            .props("no-caps flat").classes("remote-action"):
        with ui.menu():
            for name in named:
                ui.menu_item(name, on_click=lambda _e=None, name=name: add(name))
