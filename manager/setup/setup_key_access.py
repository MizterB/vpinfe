"""Setup's key access: whether this device lets VPinFE hear keys while a table runs.

It is a finding drawn above the Controls step, and only where keys cannot be heard. It never
stops Setup: the frontend's own keys and controllers work without it. A Mac is asked for
Input Monitoring, once per opening; a Wayland device is shown the command that adds its user
to the `input` group, which has to be run on that device and takes a restart.
"""

from __future__ import annotations

import getpass
import logging
import shlex
from dataclasses import dataclass

from nicegui import ui

from common.host import key_reader
from common.i18n import t
from manager.kit import offload

logger = logging.getLogger("vpinfe.manager.setup.setup_key_access")


@dataclass
class Asked:
    """Whether macOS has been asked in this opening of Setup."""
    done: bool = False


@dataclass(frozen=True)
class Finding:
    """What stops keys being heard here: the lines to read, and the command to run if
    there is one."""
    lines: tuple[str, ...]
    command: str = ""


def join_command(user: str | None) -> str:
    """The command that puts `user` in the group that can read this device's keyboards, with
    `<user>` left for the person to fill in when this device has no name for it."""
    return "sudo usermod -aG input " + (shlex.quote(user) if user else "<user>")


def _user() -> str | None:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 - a device with no name for its user gets the placeholder
        return None


async def look(asked: Asked) -> Finding | None:
    """The finding for this device, or None where keys are heard or nothing here can fix it."""
    try:
        heard = await offload.io(key_reader.hearing)
    except Exception:
        logger.warning("Could not tell whether keys can be heard", exc_info=True)
        return None
    said = dict(heard.reason or {})
    why = said.get("key")
    if why == key_reader.NO_INPUT_MONITORING:
        if not asked.done:
            asked.done = True
            try:
                await offload.io(key_reader.ask_listen_access)
            except Exception:
                logger.warning("Could not ask for Input Monitoring", exc_info=True)
        return Finding((key_reader.words(said), t("manager.setup.keys.restart")))
    if why == key_reader.NO_INPUT_GROUP:
        return Finding((t(key_reader.NO_INPUT_GROUP), t("manager.setup.keys.group_fix")),
                       command=join_command(_user()))
    return None


def draw(found: Finding) -> None:
    with ui.element("div").classes("manager-attention w-full mb-2"):
        ui.icon("error_outline").classes("manager-attention-icon")
        with ui.column().classes("gap-0 min-w-0 grow"):
            ui.label(t(key_reader.NOT_HEARD)).classes("manager-attention-line")
            for line in found.lines:
                ui.label(line).classes("manager-member-table")
            if found.command:
                ui.label(found.command).classes("manager-token select-all")
