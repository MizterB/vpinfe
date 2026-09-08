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


def _read_remote() -> dict[str, Any]:
    """Every blocking call the first draw needs, made once off the event loop.

    The Console consumes its own process over HTTP, so a page handler that asks the API
    a question while holding the loop deadlocks - uvicorn cannot answer a request it is
    blocked inside.
    """
    client = ApiClient()
    return {
        "devices": client.devices(),
        "play": client.play_state(),
        "games": client.games(),
        "jobs": client.jobs(),
        "local_device_id": str(client.discovery().get("install_id") or ""),
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
    loaded = await run.io_bound(_read_remote)
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
        "play": loaded["play"],
        "games": loaded["games"],
        "jobs": loaded["jobs"],
    }

    def client_for_target() -> ApiClient:
        """A client aimed at whichever target is chosen. The picker is a base URL."""
        return ApiClient(base_url_of(state["target"], local_device_id) or None)

    def redraw() -> None:
        """Both, always. The bar says which screen you are on, so a redraw that rebuilt
        only the screen left the mark behind on the one you came from."""
        body.clear()
        tabs.clear()
        with body:
            _screen(state, client_for_target, redraw)
        with tabs:
            _tabs(state, redraw)

    # Header, then the screen, then the tabs, in that order and inside the shell: the
    # body has to be built here rather than earlier and reparented, because a NiceGUI
    # element belongs to whatever slot was open when it was made.
    with ui.column().classes("w-full h-full gap-0 remote-shell no-wrap"):
        _header(state, aimable, redraw)
        body = ui.column().classes(
            "w-full grow min-h-0 gap-0 overflow-auto remote-body")
        tabs = ui.row().classes("w-full items-stretch gap-0 remote-tabs no-wrap")
    redraw()


def _header(state: dict[str, Any], aimable: list[dict[str, Any]],
            redraw) -> None:
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

            def aim(event) -> None:
                state["target"] = by_id.get(event.value, {})
                redraw()

            ui.select(names, value=state["target"].get("device_id"),
                      on_change=aim) \
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
    if state["screen"] == NOW:
        _now(state, client_for_target, redraw)
    elif state["screen"] == PLAY:
        _placeholder("Play")
    else:
        _placeholder("Control")


def _placeholder(name: str) -> None:
    with ui.column().classes("w-full items-center justify-center grow gap-2 p-6"):
        ui.label(name).classes("remote-empty")


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
