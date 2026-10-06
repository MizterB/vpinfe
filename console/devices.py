"""Devices: what each one is, and what it can be asked to do."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any

from nicegui import run, ui

from common import device_client, device_registry, install_identity, lifecycle
from common.host import action_ops, addresses
from common.i18n import t
from common.labels import humanize
from console import offload, renderers, verbs
from console.on_page import on_page

from . import browser_state, confirm, grid, panel, views, when
from . import settings as settings_page
from .api import ApiClient, ApiError

logger = logging.getLogger("vpinfe.console.devices")

# What a kind of device can do when nobody can ask it. A vpx_mobile device runs VPX and
# not VPinFE, so it declares nothing, ever - its abilities are known from the kind.
IMPLIED_BY_KIND: dict[str, set[str]] = {
    "vpx_mobile": {"launch"},
}

PRESENT, ABSENT, UNKNOWN = "present", "absent", "unknown"

# What the absence costs, which is what the chip's color means everywhere else in the
# Console: an unoffered capability is ordinary, one nothing has asked about is not.
_CHIP = {
    PRESENT: ("console.devices.available_2", "on"),
    ABSENT: ("console.devices.not_offered", "off"),
    UNKNOWN: ("console.devices.cannot_determined", "unknown"),
}

# A device there is no way to call back. Not the same as one that is down, and it says
# which: an install announces the port it answers on, and this one never did.
UNREACHABLE_NOTE = "console.devices.no_port"

# Why an install cannot replace itself, in the words a person reads. The API answers with
# the reason's name; the sentence for it belongs to whatever is showing it.
WHY_NOT = {
    "source_build": "console.devices.why_not.source",
    "non_release_build": "console.devices.why_not.non_release",
    "unsupported_architecture": "console.devices.why_not.architecture",
    "no_matching_asset": "console.devices.why_not.architecture",
    "asset_missing_file_name": "console.devices.why_not.release_incomplete",
    "asset_not_attached_to_release": "console.devices.why_not.release_incomplete",
    "macos_not_supported_yet": "console.devices.why_not.platform",
    "unsupported_platform": "console.devices.why_not.platform"
}

# How many records to ask for. Enough to see what led to something without handing over
# a 2MB file to a panel; the path is on the page for anyone who wants the rest.
LOG_LIMIT = 200

# What each level is worth noticing. Only the two that mean something went wrong get a
# hue - a column where every row is lit says nothing about any of them.
# Read by the Logs page too, so one install's log and another's are colored the same.
LOG_LEVELS = {
    "ERROR": "console-log-bad",
    "CRITICAL": "console-log-bad",
    "WARNING": "console-log-warn",
}


def level_class(level: str) -> str:
    # The digest colors a whole line and takes LOG_LEVELS directly, where INFO is not
    # set apart from DEBUG.
    return LOG_LEVELS.get(level) or ("console-log-info" if level == "INFO"
                                     else "console-log-plain")


# What a device's menu can offer, in the order it is drawn. The two that take the whole
# machine down are last, which is where `panel.verb_entries` puts a danger verb anyway.
MENU_ACTIONS = (
    (lifecycle.VPINFE, lifecycle.RESTART), (lifecycle.FRONTEND, lifecycle.RESTART),
    (lifecycle.VPINFE, lifecycle.STOP),
    (lifecycle.SYSTEM, lifecycle.RESTART), (lifecycle.SYSTEM, lifecycle.STOP),
)
QUIT = (lifecycle.VPINFE, lifecycle.STOP)
# What a lifecycle action costs, which is what decides whether it is asked about first.
_ASKED = {lifecycle.VPINFE, lifecycle.SYSTEM}

# What a probe found, as the mark on a rail row and the chip on the page. Green for
# answering, because that is the one a person scans the rail for.
_REACH = {
    device_client.ANSWERING: ("console.devices.answering", "on", "positive"),
    device_client.UNREACHABLE: ("console.devices.not_answering", "bad", "negative"),
    device_client.UNASKABLE: ("console.devices.cannot_asked", "unknown", "grey"),
}


def capability_state(device: dict[str, Any], capability: str,
                     local_device_id: str | None,
                     local_capabilities: set[str],
                     probed: dict[str, Any] | None = None) -> str:
    """One of three answers, never two.

    "Cannot be determined" is its own state on purpose. Collapsing it into "not offered"
    tells someone their hardware lacks a feature when the truth is that nothing has
    asked it - which is a worse error than saying nothing.
    """
    kind = device.get("kind", "vpinfe")
    if kind in IMPLIED_BY_KIND:
        return PRESENT if capability in IMPLIED_BY_KIND[kind] else ABSENT
    if device.get("device_id") == local_device_id:
        return PRESENT if capability in local_capabilities else ABSENT
    # What the probe already heard. A remote install declares its capabilities in the
    # same response the probe reads for its name and version, so this costs nothing -
    # and it used to be thrown away, which left every remote install answering
    # "cannot be determined" for all of them.
    if probed and probed.get("state") == device_client.ANSWERING:
        said = probed.get("capabilities")
        # None is a build that did not say, which is not the same as a build that
        # answered and offers nothing. Reading it as the latter put "Not offered" on
        # every row of a machine that offers all of them.
        if said is None:
            return UNKNOWN
        return PRESENT if capability in set(said) else ABSENT
    # Nothing has asked it, or it did not answer. Not the same as "does not offer it".
    return UNKNOWN


def device_label(device: dict[str, Any]) -> str:
    """What to call a device on screen.

    The name it reported, then the address it answered from - an unnamed install is
    still the one at a particular address, and "device" tells nobody which. The install
    itself falls back to its hostname, so a blank name here means it never reported one.
    """
    return (str(device.get("display_name") or "").strip()
            or str(device.get("address") or "").strip()
            or t("console.devices.device"))


def own_address() -> str:
    """What another machine would type to reach this one, or "" where nothing but
    loopback is on offer."""
    return next((host for host in addresses.hosts() if host != "localhost"), "")


def _connection_rows(context: dict[str, Any], address: str) -> list[tuple[Any, Any]]:
    """Whether it is there, when it last was, where, and since when this install has
    known it."""
    device = _of(context)
    reach = context.get("reach")
    rows: list[tuple[Any, Any]] = []

    found = _REACH.get(str((reach or {}).get("state") or ""))
    if found is None:
        rows.append((t("word.state"),
                     panel.state(t("console.devices.checking"), "unknown")))
    else:
        label, level, _color = found
        rows.append((t("word.state"), panel.state(t(label), level)))
        reason = str((reach or {}).get("reason") or "")
        if level != "on" and reason:
            rows.append(panel.note(reason))

    rows.append((t("word.last_seen"),
                 _when(str(device.get("last_reachable") or ""), t("word.never"))))
    rows.append((t("console.devices.address"), address or t("console.devices.not_known")))
    rows.append((t("console.devices.first_seen"),
                 _when(str(device.get("first_seen") or ""), t("console.devices.not_known"))))
    if is_local(context) or context.get("library") is None:
        rows.append(panel.note(t("console.devices.self_note")))
    return rows


def acts(library: Any, device: dict[str, Any], rerender: Callable[[], Any] | None,
         *, client: Any = None, offered: list[dict[str, Any]] | None = None,
         forgettable: bool = True,
         routed: dict[tuple[str, str], Callable[[], Any]] | None = None,
         led: tuple[tuple[str, str], str] | None = None) -> list[panel.Verb]:
    """What can be done to one device: what it says it performs, then Forget.

    `offered` is the device's own `/actions` answer, read where the page already reaches
    the device, because a menu has to open at once. `forgettable` is false for this
    install's own entry, which announces itself again at once.

    `routed` swaps a pair's handler for one that asks and reports for itself. `led` puts a
    pair first, with its note after the label.
    """
    entries = _menu_entries(offered or [])
    out = [_device_verb(device, client, entry, (routed or {}).get(_pair(entry)))
           for entry in entries]
    at = next((i for i, entry in enumerate(entries)
               if led is not None and _pair(entry) == led[0]), None)
    if at is not None and led is not None:
        first = out.pop(at)
        out.insert(0, replace(first, label=t("console.waiting.menu_lead",
                                             label=first.label, note=led[1])))
    if forgettable:
        out.append(panel.Verb(t("word.forget"),
                              lambda: _confirm_forget(library, device, rerender),
                              danger=True))
    return out


def _pair(entry: dict[str, Any]) -> tuple[str, str]:
    return str(entry.get("scope") or ""), str(entry.get("action") or "")


def usable(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What a device listed, less what it only listed to say nothing performs it - which
    is how an install from before the list was filtered says so."""
    return [entry for entry in entries
            if entry.get("available", True) or entry.get("reason_key") != action_ops.NOT_WIRED]


def _menu_entries(offered: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_pair = {(str(entry.get("scope") or ""), str(entry.get("action") or "")): entry
               for entry in usable(offered)}
    return [by_pair[pair] for pair in MENU_ACTIONS if pair in by_pair]


def offers(offered: list[dict[str, Any]] | None, pair: tuple[str, str]) -> bool:
    """Whether the device's menu carries this pair."""
    return any(_pair(entry) == pair for entry in _menu_entries(offered or []))


def _device_verb(device: dict[str, Any], client: Any, entry: dict[str, Any],
                 routed: Callable[[], Any] | None = None) -> panel.Verb:
    """One of the device's lifecycle verbs, asked about first where it costs the machine
    something. One that can run but not now is offered and refused, with its reason."""
    scope = str(entry["scope"])
    action = str(entry["action"])
    label = lifecycle.label(scope, action)
    if not entry.get("available", True):
        return panel.Verb(label, danger=scope == lifecycle.SYSTEM,
                          hint=str(entry.get("reason") or ""))
    if routed is not None:
        return panel.Verb(label, routed, danger=scope == lifecycle.SYSTEM)

    @on_page
    async def go() -> None:
        if scope in _ASKED and not await confirm.ask(
                f"{label}?",
                detail=t("console.devices.quit_detail" if (scope, action) == QUIT
                         else "console.devices.happens_now",
                         device_label=device_label(device)),
                confirm=label, icon=verbs.STOP):
            return
        try:
            done = await offload.io(client.perform_action, scope, action)
        except Exception as exc:  # noqa: BLE001 - the reason belongs on the page
            ui.notify(t("said.action_failed"), caption=_why(exc), type="negative")
            return
        # A machine on its way down answers before it goes, so "performed" here means
        # the work was handed over rather than finished.
        ui.notify(label if done.get("performed")
                  else t("console.devices.not_happen", label=label),
                  type="positive" if done.get("performed") else "warning")

    return panel.Verb(label, go, danger=scope == lifecycle.SYSTEM)


async def load_actions(library: Any, device: dict[str, Any], local_device_id: str | None,
                       reach: dict[str, Any] | None) -> list[dict[str, Any]]:
    """What a device says it performs, or nothing from one that cannot say.

    Never raises: a device that is asleep, a phone, or an install from before the route
    existed gets its entry's own verbs and no more.
    """
    local = device.get("device_id") == local_device_id
    if device.get("kind") == device_registry.KIND_VPX_MOBILE:
        return []
    if not local and (reach or {}).get("state") != device_client.ANSWERING:
        return []
    client: Any = library if local else device_client.for_device(device, local_device_id)
    if client is None:
        return []
    try:
        return usable(await offload.io(client.actions))
    except device_client.TooOldError:
        return []
    except Exception:  # noqa: BLE001 - unreachable is a state, not a 500
        logger.info("Could not ask %s what it does", device_label(device), exc_info=True)
        return []


@on_page
async def _confirm_forget(library: Any, device: dict[str, Any],
                          rerender: Callable[[], None] | None) -> None:
    """Drop the entry, having said what that does and does not do."""
    name = device_label(device)
    if not await confirm.ask(
            t("console.devices.forget", name=(name)),
            detail=t("console.devices.forget_detail"),
            confirm=t("word.forget"), icon=verbs.FORGET):
        return
    try:
        await run.io_bound(library.forget_device, str(device.get("device_id") or ""))
    except Exception as exc:  # noqa: BLE001 - the reason belongs on the page
        ui.notify(t("console.devices.forget_failed"), caption=_why(exc),
                  type="negative")
        return
    ui.notify(t("console.devices.forgot", name=(name)), type="positive")
    if rerender is not None:
        rerender()


@on_page
async def _confirm_forget_all(library: Any, devices: list[dict[str, Any]],
                              rerender: Callable[[], None] | None) -> None:
    """The selection's Forget: one question for the lot, then each in turn."""
    if len(devices) == 1:
        await _confirm_forget(library, devices[0], rerender)
        return
    if not await confirm.ask(
            t("console.devices.forget_count", count=len(devices)),
            detail=t("console.devices.removes_entries_here"),
            confirm=t("word.forget"), icon=verbs.FORGET):
        return
    forgot = 0
    for device in devices:
        try:
            await run.io_bound(library.forget_device, str(device.get("device_id") or ""))
            forgot += 1
        except Exception as exc:  # noqa: BLE001 - the reason belongs on the page
            ui.notify(t("console.devices.forget_named_failed", name=device_label(device)),
                      caption=_why(exc), type="negative")
    if forgot:
        ui.notify(t("console.devices.forgot_count", count=forgot), type="positive")
    if rerender is not None:
        rerender()


def _software_rows(device: dict[str, Any], is_local: bool, client: Any,
                   update: dict[str, Any] | None,
                   check: Callable[[], Any] | None = None,
                   why: str = "") -> list[tuple[Any, Any]]:
    """What this device is running, and whether it can take what is published.

    A device with no answer gets an unknown - one that announced itself before ports were
    recorded cannot be reached, and one that is not answering has not said. Either way
    "up to date" would be a guess wearing a fact. `check` is Check now; `why` is what
    went wrong asking it.
    """
    rows: list[tuple[Any, Any]] = []
    if not update:
        rows.append((t("word.version"), panel.state(t("console.devices.not_known"),
                "unknown")))
        if why:
            rows.append(panel.note(why))
        elif not is_local and client is None:
            rows.append(panel.note(t(UNREACHABLE_NOTE)))
        return rows

    current = str(update.get("current_version") or "unknown")
    checked = str(update.get("checked_at") or "")
    if update.get("error"):
        rows.append((t("word.version"), panel.state(
            t("console.devices.check_failed"), "unknown", beside=current,
            hint=(t("console.devices.last_checked", when=when.ago(checked, inline=True))
                  if checked else t("console.devices.never_checked")))))
    elif update.get("update_available", False) is None:
        rows += _unweighed_rows(update, current)
    elif not update.get("update_available"):
        rows.append((t("word.version"), panel.state(current, "on")))
    else:
        rows += _available_rows(device, client, update, current)
    if check is not None:
        rows.append(settings_page.last_checked(checked, check))
    return rows


def _why_not(update: dict[str, Any]) -> tuple[Any, Any]:
    return panel.note(t(WHY_NOT.get(str(update.get("support_reason") or ""),
                                    "console.devices.update_self")))


def _unweighed_rows(update: dict[str, Any], current: str) -> list[tuple[Any, Any]]:
    """A build whose own version cannot be compared with the release, such as a source
    checkout's. The release is named, never offered."""
    latest = str(update.get("latest_version") or "")
    chip = (panel.state(t("console.devices.latest", latest=latest), "unknown", beside=current)
            if latest else panel.state(current, "unknown"))
    return [(t("word.version"), chip), _why_not(update)]


def _available_rows(device: dict[str, Any], client: Any, update: dict[str, Any],
                    current: str) -> list[tuple[Any, Any]]:
    latest = str(update.get("latest_version") or t("console.devices.newer_build"))
    rows: list[tuple[Any, Any]] = [(t("word.version"), panel.state(
        t("console.devices.available", latest=(latest)), "warn", beside=current))]
    if not update.get("update_supported"):
        rows.append(_why_not(update))
        return rows

    def update_action() -> None:
        with ui.element("div").classes("console-fact-edit"):
            panel.action(t("console.devices.update_3", latest=(latest)),
                         lambda: _confirm_update(client, device_label(device), update),
                         icon=verbs.UPDATE, inline=True,
                         hint=t("console.devices.update_3.help"))()

    rows.append(("", update_action))
    return rows


@on_page
async def _confirm_update(client: Any, name: str, update: dict[str, Any]) -> None:
    """Ask before replacing an install, naming which one it is.

    The name is the point of the question. An update replaces the machine it runs on,
    which may not be the one this page is open on - "Update to v3.1" does not say which
    one goes down, and by the time it has, saying so is too late.
    """
    latest = str(update.get("latest_version") or t("console.devices.published_build"))
    try:
        playing = await offload.io(client.play_state)
    except Exception as exc:  # noqa: BLE001 - a dialog that cannot say what it will do
        ui.notify(t("console.devices.activity_failed", name=name), caption=_why(exc),
                  type="negative")
        return

    running = str((playing or {}).get("game_name") or "") if (
        playing or {}).get("launching") else ""

    # Named, because "a table is running" is a fact the person asking may not have: the
    # Console is not necessarily open on the machine the table is on.
    lines = [t("console.devices.close_note", running=(running))] if running else []
    if not await confirm.ask(
            t("console.devices.update_2", name=(name), latest=(latest)),
            detail=t("console.devices.update_detail"),
            lines=lines,
            confirm=t("console.devices.stop_confirm") if running
            else t("console.devices.update"),
            icon=verbs.STOP if running else verbs.UPDATE,
            danger=bool(running)):
        return
    await _start_update(client, name, bool(running))


@on_page
async def _start_update(client: Any, name: str, stop_table: bool) -> None:
    try:
        await run.io_bound(lambda: client.perform_update(stop_table=stop_table))
    except Exception as exc:  # noqa: BLE001 - the reason belongs on the page
        ui.notify(t("console.devices.update_failed"), caption=_why(exc),
                  type="negative")
        return
    # Nothing to redraw towards. Updating this install takes the page's own server down;
    # updating another leaves it up but knowing nothing new until that device is back.
    ui.notify(t("console.devices.update_staged", name=(name)), type="positive")


def _hostname_placeholder(device: dict[str, Any]) -> str:
    """What it will be called if the field is left empty.

    The name it reports with nothing set is its hostname, so showing that is more use
    than the word "hostname" - it is the actual answer rather than a description of one.
    """
    return str(device.get("display_name") or "") \
        .strip() or t("console.devices.hostname")




# --- The grid ---------------------------------------------------------------

SCOPE = "console.devices.columns"

KIND_LABELS = {"vpinfe": "VPinFE", "vpx_mobile": "VPX Mobile"}

_KIND_CHOICES = [{"value": label, "label": label} for label in KIND_LABELS.values()]
_STATE_CHOICES = [{"value": text, "label": t(text)} for text, _l, _c in _REACH.values()]

COLUMNS: list[dict[str, Any]] = [
    # Never shown - it exists so every built-in view can sort this device to the top.
    # A column has to be declared to be sorted on, and this one is a fact about the row
    # rather than anything to read.
    grid.column("self", t("console.devices.device_2"), hide=True,
                help=t("console.devices.self.help")),
    grid.identifier("name", t("word.name"), 200, pinned="left",
                help=t("console.devices.name.help")),
    grid.column("kind", t("word.kind"), 120, **grid.choice_filter(_KIND_CHOICES),
                help=t("console.devices.kind.help")),
    grid.column("state", t("word.state"), 140, **grid.choice_filter(_STATE_CHOICES),
                help=t("console.devices.state.help")),
    grid.column("version", t("word.version"), 160,
                help=t("console.devices.version.help")),
    grid.column("browser", t("console.devices.browser"), 150,
                help=t("console.devices.browser.help"),
                **grid.choice_filter([{"value": key, "label": one["label"]}
                                      for key, one in browser_state.STATES.items()],
                                     formatted=True),
                **renderers.drawable("state", states=browser_state.STATES)),
    grid.column("address", t("console.devices.address"), 150,
                help=t("console.devices.address.help")),
    grid.column("last_seen", t("word.last_seen"), 170,
                help=t("console.devices.last_seen.help"),
                **when.cell("last_seen")),
    grid.list_column("features", t("console.devices.features"), 150,
                     help=t("console.devices.features.help"),
                     looks=renderers.FEATURE_LOOKS),
]

# `self` is out: it is a sort key, not a column somebody picks.
_ALL = [definition["field"] for definition in COLUMNS if definition["field"] != "self"]

# Every view leads with it, so the device you are on is the first row whatever else the
# view orders by - which is what "pinned" means here, and it survives re-sorting because
# a user's sort is added to this rather than replacing it.
_SELF_FIRST = {"colId": "self", "sort": "desc", "sortIndex": 0}

VIEWS: dict[str, list[str] | views.Preset] = {
    "console.devices.all_devices": views.Preset(
        columns=("name", "kind", "state", "version", "browser", "last_seen"),
        sort=(_SELF_FIRST,
              {"colId": "state", "sort": "asc", "sortIndex": 1},
              {"colId": "name", "sort": "asc", "sortIndex": 2}),
        help=t("console.devices.all_view.help")),
    "console.view.answering": views.Preset(
        columns=("name", "kind", "version", "browser", "address", "features"),
        sort=(_SELF_FIRST, {"colId": "name", "sort": "asc", "sortIndex": 1}),
        filters={"state": {"values": [_REACH[device_client.ANSWERING][0]]}},
        help=t("console.devices.answering_view.help")),
    "console.devices.not_answering": views.Preset(
        columns=("name", "kind", "state", "address", "last_seen"),
        sort=(_SELF_FIRST, {"colId": "last_seen", "sort": "asc", "sortIndex": 1}),
        filters={"state": {"values": [_REACH[device_client.UNREACHABLE][0],
                                      _REACH[device_client.UNASKABLE][0]]}},
        help=t("console.devices.unreached_view.help")),
    "console.view.everything": views.Preset(
        columns=tuple(_ALL),
        help=t("console.devices.everything_view.help")),
}


def rows(devices: list[dict[str, Any]],
         reach: dict[str, dict[str, Any]] | None = None,
         local_device_id: str | None = None) -> list[dict[str, Any]]:
    """One row per device, flattened for a grid.

    The probe's answer is folded in rather than fetched per row: it arrives once for
    the whole registry, and a column that asked per row would dial every machine again
    each time the grid redrew.
    """
    found = reach or {}
    out = []
    for device in devices:
        device_id = str(device.get("device_id") or "")
        probe = found.get(device_id) or {}
        state = _REACH.get(str(probe.get("state") or ""))
        out.append({
            "id": device_id,
            "self": device_id == (local_device_id or ""),
            "name": device_label(device),
            "kind": KIND_LABELS.get(str(device.get("kind") or "vpinfe"), "VPinFE"),
            # Blank until the probes land, rather than a word meaning "not yet": a
            # grid filter over "Checking" is a filter over how fast the page loaded.
            "state": state[0] if state else "",
            "version": str(probe.get("version") or ""),
            "browser": str(_browser_of(device, probe).get("state") or ""),
            "address": str(device.get("address") or ""),
            "last_seen": str(device.get("last_reachable") or ""),
            "features": settings_page.features_listed(device.get("features")),
        })
    return [when.said(row, "last_seen") for row in out]


def _browser_of(device: dict[str, Any], probe: dict[str, Any] | None) -> dict[str, Any]:
    return dict((probe or {}).get("browser") or device.get("browser") or {})


def _browser_rows(device: dict[str, Any],
                  probe: dict[str, Any] | None) -> list[tuple[Any, Any]]:
    found = _browser_of(device, probe)
    if not found:
        return []
    name = str(found.get("name") or "")
    rows: list[tuple[Any, Any]] = [(
        t("console.devices.browser"),
        browser_state.value(name, str(found.get("state") or ""), t("console.devices.not_known")))]
    checked = str(found.get("checked_at") or "")
    if checked and (probe or {}).get("state") != device_client.ANSWERING:
        rows.append(panel.note(t("console.devices.last_checked",
                                 when=when.ago(checked, inline=True))))
    return rows


def _when(stamp: str, missing: str) -> Any:
    """How long ago, in the words the grid uses, with the exact time on hover."""
    if not str(stamp or "").strip():
        return missing

    def draw() -> None:
        ui.label(when.ago(stamp)).classes("console-fact-value").tooltip(when.local(stamp))

    return draw


def build(found: list[dict[str, Any]], library: Any, state: dict[str, Any],
          on_select: Callable[[dict | None], Any],
          probe: Callable[[], Any] | None = None,
          local_device_id: str | None = None,
          rerender: Callable[[], None] | None = None) -> None:
    """Devices as a grid, so the selected row is what the workbench answers for.

    The same shape every other subject uses. Kind and reachability are columns rather
    than groups, which is what lets one question - "which of these is not answering" -
    be a sort, a filter and a saved view instead of a fixed arrangement.
    """
    # Deferred: `games` imports `workbench`, and `workbench` imports this module for
    # the device sections - so taking the view control at import time closes the loop.
    # Only `build` needs it, and by then every module is loaded.
    from .games import view_control

    built = rows(found, state.get("device_reach"), local_device_id)
    on_screen = {"rows": len(built)}
    selected: list[dict[str, Any]] = []

    def said() -> str:
        if selected:
            return grid.selection_said(table, len(selected), t(
                "console.devices.selected", picked=len(selected), shown=on_screen["rows"]))
        away = sum(1 for row in built if row["state"]
                   and row["state"] != _REACH[device_client.ANSWERING][0])
        if on_screen["rows"] != len(built):
            return t("console.devices.devices_2", shown=(on_screen["rows"]),
                     count=(len(built)))
        return t("console.devices.count_away", count=(len(built)), away=(away)) if away \
            else t("console.devices.devices", count=(len(built)))

    with ui.row().classes("w-full items-center gap-2 px-3 py-2 mb-2 shrink-0 "
                                  "console-panel console-grid-bar"):
        bar = panel.grid_bar()
        wire_views, _picker, showing, describe = view_control(library, SCOPE, VIEWS,
                                                    _ALL, COLUMNS, bar=bar)
        describe()
        with bar.top, panel.bar_end():
            search = panel.search(t("console.devices.search_devices"))
        with bar.bottom, panel.bar_end():
            count = ui.label(said()).classes("text-xs console-label")
            actions, bulk_menu = panel.selection_actions(
                t("console.devices.bulk_menu"))
            if probe is not None:
                panel.refresh(probe, t("console.devices.probe_all"))

    by_id = {row["id"]: row for row in built}
    grid.on_row_focus(SCOPE,
                      lambda event: on_select(by_id.get(grid.focused_row(event))))

    known = {str(one.get("device_id") or ""): one for one in found}

    def _fill_row_menu(row: dict | None) -> None:
        menu.clear()
        if not row:
            return
        device_id = str(row.get("id") or "")
        device = known.get(device_id)
        if device is None:
            return
        offered = acts(
            library, device, rerender,
            client=library if row.get("self")
            else device_client.for_device(device, local_device_id),
            offered=(state.get("device_actions") or {}).get(device_id),
            forgettable=not row.get("self"))
        panel.verb_menu(menu, str(row.get("name") or ""), offered)
        if not offered:
            # The browser opened it on the click; there is nothing to show yet.
            menu.close()

    async def on_header_context(col_id: str | None) -> None:
        await grid.header_menu(menu, table, COLUMNS, col_id)

    def on_select_rows(rows_selected: list[dict[str, Any]]) -> None:
        selected[:] = rows_selected
        actions.set_visibility(bool(rows_selected))
        count.text = said()

    def fill_bulk() -> None:
        chosen = [known[str(row.get("id") or "")] for row in grid.selection(table)
                  if str(row.get("id") or "") in known and not row.get("self")]
        bulk_menu.clear()
        with bulk_menu:
            panel.verb_entries([
                panel.Verb(t("word.clear_selection"),
                           lambda: table.run_grid_method("deselectAll")),
                panel.Verb(t("word.forget"),
                           lambda: _confirm_forget_all(library, chosen, rerender),
                           danger=True)])
        bulk_menu.open()

    actions.on_click(fill_bulk)
    mine = [local_device_id] if local_device_id else None

    with ui.element("div").classes("w-full grow min-h-0 flex flex-col"):
        table = grid.build(COLUMNS, built, SCOPE, on_select_rows,
                           on_context=_fill_row_menu,
                           on_header_context=on_header_context, view_of=showing,
                           rows_not_selectable=mine)
        menu = ui.context_menu()

        def keep_current() -> None:
            grid.transact(table, built,
                          {"update": [when.said(row, "last_seen") for row in built]}, by_id)

        # Inside the wrapper, so it goes when the grid does.
        ui.timer(60, keep_current)

    def landed(device_id: str) -> None:
        """One device's answer, into its row and the count."""
        device = known.get(device_id)
        if device is None:
            return
        grid.transact(table, built,
                      {"update": rows([device], state.get("device_reach"), local_device_id)},
                      by_id)
        count.text = said()

    state["device_landed"] = landed
    wire_views(table)
    search.on_value_change(
        lambda: table.run_grid_method("setGridOption", "quickFilterText",
                                      search.value or ""))

    async def counted() -> None:
        on_screen["rows"] = await table.run_grid_method("getDisplayedRowCount") or 0
        count.text = said()

    table.on("rowDataUpdated", counted)
    table.on("filterChanged", counted)


# --- Panel sections ---------------------------------------------------------
#
# One function per section of the workbench rail. They take the panel's context and
# hand back fact rows, because what a device is and what may be asked of it belongs
# with the device rather than with the panel that draws it.

def client_for(context: dict[str, Any]) -> Any:
    """Who answers for this device. This install's own client for itself, the client
    that reaches it for anything else - both expose the same calls, which is what lets
    one page draw either."""
    if is_local(context):
        return context.get("library")
    return device_client.for_device(_of(context), context.get("local_device_id"))


def _why(exc: Exception) -> str:
    """This install's API and an install too old for the route already speak in the
    catalog's words; anything else is a device that did not answer."""
    if isinstance(exc, (ApiError, device_client.TooOldError)):
        return str(exc)
    return t(device_client.why_not(exc))


def _of(context: dict[str, Any]) -> dict[str, Any]:
    return context.get("device") or {}


def is_local(context: dict[str, Any]) -> bool:
    return _of(context).get("device_id") == context.get("local_device_id")


def is_phone(context: dict[str, Any]) -> bool:
    return _of(context).get("kind") == device_registry.KIND_VPX_MOBILE


def serves(context: dict[str, Any], capability: str) -> bool:
    """False only where the device is known not to offer `capability`."""
    return capability_state(_of(context), capability, context.get("local_device_id"),
                            context.get("local_capabilities") or set(),
                            context.get("reach")) != ABSENT


async def detail_groups(context: dict[str, Any]) -> list[tuple[Any, Any]]:
    """What a device is, whether it is there, and where its settings are.

    Descriptive, then operational: what a thing is comes before what can be done to it.
    They are headings inside one section rather than rail entries of their own, because
    each holds three rows or fewer and a rail entry that opens one row is a click charged
    for nothing.
    """
    rows_out: list[tuple[Any, Any]] = [(panel.HEADING, t("word.identity"))]
    rows_out += await _identity_rows(context)
    rows_out.append((panel.HEADING, t("console.devices.connection")))
    # Read off the machine, so off the loop: this machine's own address is a name lookup.
    address = (await offload.io(own_address) if is_local(context)
               else str(_of(context).get("address") or ""))
    rows_out += _connection_rows(context, address)
    rows_out += await _playing_rows(context)
    if is_phone(context):
        # A phone is not an install: no software, no lifecycle, no settings of ours to
        # open. What it has instead is the one thing this end can act on - the games it
        # is carrying - so that heading takes the place of Settings rather than being
        # added beside it.
        rows_out.append((panel.HEADING, t("console.devices.carrying")))
        rows_out += await _carrying_rows(context)
    else:
        rows_out.append((panel.HEADING, t("console.devices.settings")))
        rows_out += settings_door(context)
    return rows_out


async def _playing_rows(context: dict[str, Any]) -> list[tuple[Any, Any]]:
    """The table being played there, with the way to close it. Nothing while none is,
    and nothing from a device that does not say it can close one or does not answer."""
    pair = {"scope": lifecycle.TABLE, "action": lifecycle.STOP}
    if not any(pair.items() <= entry.items() for entry in context.get("actions") or []):
        return []
    client = client_for(context)
    try:
        playing = await offload.io(client.play_state)
    except Exception:  # noqa: BLE001 - a row that cannot be read is not shown
        logger.info("Could not ask %s what it is playing", device_label(_of(context)),
                    exc_info=True)
        return []
    if not playing.get("launching"):
        return []
    name = str(playing.get("game_name") or "")

    @on_page
    async def close() -> None:
        try:
            await offload.io(client.perform_action, lifecycle.TABLE, lifecycle.STOP)
        except Exception as exc:  # noqa: BLE001 - the reason belongs on the page
            ui.notify(t("said.action_failed"), caption=_why(exc), type="negative")
            return
        await context["rebuild"]()

    def draw() -> None:
        with ui.element("div").classes("console-fact-edit"):
            if name:
                ui.label(name).classes("console-fact-value truncate min-w-0").tooltip(name)
            panel.action(t("console.devices.close_action"), close, icon=verbs.STOP,
                         inline=True, hint=t("action.table.stop.help"))()

    return [(t("console.devices.playing"), draw)]


async def _carrying_rows(context: dict[str, Any]) -> list[tuple[Any, Any]]:
    """What the device holds, asked of the device.

    Never remembered between visits: a phone is filled up and emptied by hand and taken
    out of the house, so anything recorded here would be a claim about a machine that
    has not been asked. That it takes a moment is the honest cost of the answer being
    true.
    """
    device = _of(context)
    library = context.get("library")
    try:
        held = await offload.io(ApiClient().device_games,
                                  str(device.get("device_id") or ""))
    except Exception as exc:
        return [panel.note(t("console.devices.carrying_failed"), hint=_why(exc))]

    @on_page
    async def forget(name: str) -> None:
        if not await confirm.ask(
                t("console.devices.remove", name=(name),
                        device_label=(device_label(device))),
                detail=t("console.devices.remove_detail"),
                confirm=t("word.remove"), icon=verbs.REMOVE, danger=True):
            return
        try:
            await run.io_bound(ApiClient().remove_from_device,
                               str(device.get("device_id") or ""), name)
        except Exception as exc:
            ui.notify(t("said.remove_failed"), caption=_why(exc), type="negative")
            return
        if library is not None:
            context["rerender"]()

    if not held:
        return [panel.note(t("console.devices.carrying_empty"))]

    def row(name: str) -> Callable[[], None]:
        def draw() -> None:
            with ui.element("div").classes("console-slot-actions"):
                ui.button(t("word.remove"),
                    icon=verbs.REMOVE, on_click=lambda _e=None: forget(name)) \
                    .props("flat dense no-caps size=sm") \
                    .classes("console-action console-action--inline")

        return draw

    return [(name, row(name)) for name in held]


# Why a device's settings are somewhere else. Said where somebody is looking for them,
# because "not here" without a reason reads as something missing.
SETTINGS_NOTE = "console.devices.settings_note"

# What is wrong when the door will not open. Both halves matter: one is a machine to go
# and switch on, the other is an entry with nothing to dial.
NO_DOOR = {
    device_client.UNREACHABLE: "console.devices.open_refused",
    device_client.UNASKABLE: UNREACHABLE_NOTE,
}


# Where this install's own settings are, which is a place in the Console already open.
SYSTEM_PATH = "/console?view=system"


def settings_url(device: dict[str, Any]) -> str:
    """That install's own Console, landing on System. Empty when there is nothing to
    dial - an entry written before ports were recorded has no port."""
    address = str(device.get("address") or "").strip()
    port = int(device.get("port") or 0)
    return f"http://{address}:{port}{SYSTEM_PATH}" if address and port else ""


def door_reason(device: dict[str, Any], reach: dict[str, Any] | None,
                is_local: bool) -> str:
    """Why the door will not open, or "" when it will.

    A machine that is not answering must not be offered as a live link: the tab opens on
    a connection error, which is a worse answer than being told here.
    """
    if is_local:
        return ""
    found = NO_DOOR.get(str((reach or {}).get("state") or ""))
    if found:
        return found
    return "" if settings_url(device) else UNREACHABLE_NOTE


def settings_door(context: dict[str, Any]) -> list[tuple[Any, Any]]:
    """The way into that install's own Console, or the reason there is not one.

    A door rather than a section. Drawing that install's settings here, from a schema
    fetched over HTTP, would mean this build deciding how another build's settings look -
    which is exactly where version skew bites.
    """
    device = _of(context)
    here = is_local(context)
    stopped = door_reason(device, context.get("reach"), here)

    def open_it() -> None:
        # In place for this install, a new tab for anything else: one is a place in the
        # Console you are already reading, and the other is a different machine's.
        ui.navigate.to(SYSTEM_PATH if here else settings_url(device),
                       new_tab=not here)

    def door() -> None:
        with ui.element("div").classes("console-fact-edit"):
            panel.action(t("console.devices.open_settings_here") if here
                    else t("console.devices.open_settings"),
                         open_it, icon="open_in_new", inline=True,
                         enabled=not stopped,
                         hint=t("console.devices.open_settings_here.help") if here
                         else t("console.devices.open_settings.help"))()

    return [("", door), panel.note(t(stopped) if stopped else t(SETTINGS_NOTE))]


async def _identity_rows(context: dict[str, Any]) -> list[tuple[Any, Any]]:
    """What it is called, and what it is for."""
    device = _of(context)
    # The library this name can be written through, which only the install serving the
    # page has. Without one the name is plain text.
    library = context.get("library") if is_local(context) else None

    # What the install has been told to call itself, which is not what it reports: the
    # reported name already fell back to the hostname, so showing that as the value
    # leaves nothing to tell a chosen name from a defaulted one.
    stored = ""
    if library is not None:
        try:
            values = await offload.io(library.config_values)
            stored = str(((values or {}).get("install") or {}).get("display_name") or "")
        except Exception:  # noqa: BLE001 - an unreadable name is an empty field, not a 500
            library = None

    @on_page
    async def rename(value: str) -> None:
        if library is None:
            return
        try:
            await run.io_bound(library.put_config,
                               {"install": {"display_name": value.strip()}})
        except Exception as exc:  # noqa: BLE001 - the reason belongs on the page
            ui.notify(t("console.devices.save_failed"), caption=_why(exc), type="negative")
            return
        rebuild = context.get("rebuild")
        if rebuild is not None:
            await rebuild()

    rows_out: list[tuple[Any, Any]] = [
        (t("word.name"),
         panel.field(stored, rename,
                     placeholder=_hostname_placeholder(device))
         if library is not None else device_label(device)),
    ]
    if not is_local(context):
        rows_out.append(panel.note(t("console.devices.name_note")))
    rows_out.append((t("console.devices.features"), _feature_chips(device.get("features"))))
    if device.get("features"):
        rows_out.append(panel.note(t("console.devices.features_note")))
    return rows_out


def _feature_chips(features: Any) -> Any:
    """Every feature a device may have, green where it has one and grey where not.

    A device that reported nothing at all reads "Not reported": grey says it was asked and
    does not have the feature, which is a different claim.
    """
    if not features:
        return t("console.devices.not_reported")
    has = settings_page.features_listed(features)
    known = install_identity.FEATURES
    shown = [*known, *(name for name in has if name not in known)]

    def draw() -> None:
        with ui.element("div").classes("console-chips"):
            for name in shown:
                ui.label(settings_page.feature_said(name)) \
                    .classes(f"console-tier console-tier--{'on' if name in has else 'off'}")

    return draw


async def ask_each(entries: list[dict[str, Any]],
                   probe: Callable[[str], dict[str, Any]],
                   landed: Callable[[str, dict[str, Any]], Awaitable[None]]) -> list[Exception]:
    """Ask every device at once, and hand each answer to `landed` as it arrives.

    Returns what went wrong with the asking itself. A device that does not answer is an
    answer, and lands like any other.
    """
    failed: list[Exception] = []

    async def one(entry: dict[str, Any]) -> None:
        device_id = str(entry.get("device_id") or "")
        try:
            found = await offload.io(probe, device_id)
        except Exception as exc:  # noqa: BLE001 - the caller decides whether to say so
            failed.append(exc)
            return
        await landed(device_id, found)

    await asyncio.gather(*(one(entry) for entry in entries))
    return failed


def update_checker(is_local: bool, client: Any) -> Any:
    """Whichever client can answer *this* device's update check.

    The local client is this process, and asking it to reach the network for a version
    it already knows would be this install phoning itself - so it does not offer the
    call at all. The Console does have a way to ask: its own API, which serves `/update`
    for exactly this. Without this the local device raised, the caller logged that a
    device could not be asked, and the one install that never learned it had an update
    was the one in front of you.
    """
    if is_local:
        from console.api import ApiClient

        return ApiClient().update_check
    return getattr(client, "update_check", None)


async def software_rows(context: dict[str, Any]) -> list[tuple[Any, Any]]:
    """What it is running. Asked of the device rather than read from the registry,
    which holds no version at all."""
    device = _of(context)
    client = client_for(context)
    update = context.get("update")
    ask = update_checker(is_local(context), client)
    why = ""
    if update is None and ask is not None:
        try:
            update = await offload.io(ask)
        except Exception as exc:  # noqa: BLE001 - unreachable is a state, not a 500
            logger.info("Could not ask %s what it is running",
                        device_label(device), exc_info=True)
            update, why = None, _why(exc)
        context["update"] = update
    return [*_software_rows(device, is_local(context), client, update,
                            _check_now(context, ask) if ask is not None else None, why),
            *_browser_rows(device, context.get("reach"))]


def _check_now(context: dict[str, Any], ask: Callable[..., Any]) -> Callable[[], Any]:
    @on_page
    async def now() -> None:
        checking = ui.notification(t("console.devices.checking_updates"), spinner=True,
                                   timeout=None)
        try:
            await offload.io(ask, True)
        except Exception as exc:  # noqa: BLE001 - the reason belongs on the page
            ui.notify(t("console.devices.ask_failed",
                        device_label=device_label(_of(context))),
                      caption=_why(exc), type="negative")
            return
        finally:
            checking.dismiss()
        rebuild = context.get("rebuild")
        if rebuild is not None:
            await rebuild()

    return now


def capability_rows(context: dict[str, Any]) -> list[tuple[Any, Any]]:
    device = _of(context)
    out: list[tuple[Any, Any]] = []
    for capability in context.get("device_capabilities") or []:
        state = capability_state(device, capability,
                                 context.get("local_device_id"),
                                 context.get("local_capabilities") or set(),
                                 context.get("reach"))
        text, level = _CHIP[state]
        text = t(text)
        out.append((humanize(capability), panel.state(text, level)))
    return out or [panel.intro(t("console.devices.no_features"))]


async def log_rows(context: dict[str, Any]) -> list[tuple[Any, Any]]:
    """The tail of that install's own log.

    Read from the machine that holds it, which is the only party that has it. Records
    rather than lines, so a traceback arrives under the message that caused it instead
    of as a dozen rows carrying no level of their own.
    """
    client = client_for(context)
    if client is None:
        return [panel.intro(t(UNREACHABLE_NOTE))]
    try:
        found = await offload.io(client.logs, LOG_LIMIT)
    except device_client.TooOldError:
        return [panel.intro(t(device_client.TOO_OLD))]
    except Exception as exc:  # noqa: BLE001 - unreachable is a state, not a 500
        logger.info("Could not read the log on %s", device_label(_of(context)),
                    exc_info=True)
        return [panel.intro(t("console.devices.log_failed"), hint=_why(exc))]

    records = list(found.get("records") or [])
    if not records:
        return [panel.intro(t("console.devices.log_empty"))]
    return [(panel.FULL, lambda: _log_lines(records, str(found.get("path") or "")))]


def _log_lines(records: list[dict[str, Any]], path: str) -> None:
    """Newest last, the way a log reads and the way `tail` shows one."""
    with ui.column().classes("w-full gap-0 console-log"):
        for record in records:
            with ui.row().classes("items-baseline gap-2 w-full no-wrap console-log-row"):
                ui.label(str(record.get("when") or "")).classes("console-log-when")
                level = str(record.get("level") or "")
                ui.label(level).classes("console-log-level " + level_class(level))
                ui.label(str(record.get("logger") or "")).classes("console-log-source")
            ui.label(str(record.get("message") or "")).classes("console-log-message")
    if path:
        ui.label(path).classes("console-log-path")
