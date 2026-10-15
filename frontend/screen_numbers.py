"""A window on each screen saying its number and name, for a few seconds.

What tells a person which screen the Manager means when its sizes are alike. Each window
is placed the way every frontend window is, so it lands where the frontend would open one.
The playfield's also draws an arrow pointing up in the page's own frame, before any turn
the frontend gives its UI, so which way it points on the cabinet is which turn is needed.
"""

from __future__ import annotations

import html
import logging
import threading
import time
from collections.abc import Sequence
from typing import Any
from urllib.parse import quote

from common.config import paths
from common.config.config_access import SettingsConfig, cfg_get
from common.i18n import t
from frontend.chromium_manager import ChromiumManager

logger = logging.getLogger("vpinfe.frontend.screen_numbers")

SECONDS = 8

_showing = threading.Lock()

_ARROW = ('<svg viewBox="0 0 100 100" class="arrow"><path d="M50 8 L88 52 H62 V92 H38 V52 H12 Z" '
          'fill="currentColor"/></svg>')


def page(number: int, name: str, size: str, *, arrow: bool = False) -> str:
    """The page one screen shows. `name` is empty for a screen that has none."""
    named = f'<div class="name">{html.escape(name)}</div>' if name else ""
    return (
        "<!doctype html><meta charset=utf-8><title>VPinFE</title><style>"
        "html,body{margin:0;height:100%;background:#0f0722;color:#fff;overflow:hidden;"
        "font-family:system-ui,sans-serif;cursor:none}"
        "body{display:flex;flex-direction:column;align-items:center;justify-content:center;"
        "gap:2vmin;box-sizing:border-box;border:1.2vmin solid #00d9ff}"
        ".number{font-size:45vmin;font-weight:700;line-height:1}"
        ".name{font-size:7vmin;font-weight:600}.size{font-size:4vmin;color:#cbb8ea}"
        ".arrow{position:absolute;top:5vmin;width:18vmin;height:18vmin;color:#00d9ff}"
        "</style>"
        f"{_ARROW if arrow else ''}"
        f'<div class="number">{number}</div>{named}'
        f'<div class="size">{html.escape(size)}</div>')


def address(number: int, name: str, size: str, *, arrow: bool = False) -> str:
    return "data:text/html;charset=utf-8," + quote(page(number, name, size, arrow=arrow))


def _open(manager: ChromiumManager, screens: Sequence[Any], arrowed: int | None,
          seconds: float) -> None:
    config = paths.get_ini_config()
    settings = SettingsConfig.from_config(config)
    opened = 0
    failure: Exception | None = None
    for screen in screens:
        size = t("manager.screens.size", width=screen.width, height=screen.height)
        try:
            manager.launch_window(
                f"screen{screen.number}",
                address(screen.number, screen.name, size, arrow=screen.number == arrowed),
                screen, screen.number, mute_audio=True,
                additional_options=settings.chrome_options,
                include_default_options=settings.default_chrome_options,
                exclude_options=cfg_get(config, "Settings", "chromeoptionsexclude", ""))
            opened += 1
        except Exception as exc:  # noqa: BLE001 - one screen failing is one screen
            logger.warning("Could not open the number window on screen %s",
                           screen.number, exc_info=True)
            failure = exc
    if screens and not opened and failure is not None:
        raise failure
    time.sleep(seconds)


def show(screens: Sequence[Any], arrowed: int | None = None, seconds: float = SECONDS) -> None:
    """Open a window on each of `screens` and close them all after `seconds`. Blocking.

    A screen has `number`, `name`, `width`, `height`, `x` and `y`; `arrowed` is the number
    of the one that also shows an arrow. A second call while one is showing does nothing.
    """
    if not _showing.acquire(blocking=False):
        return
    try:
        manager = ChromiumManager()
        try:
            _open(manager, screens, arrowed, seconds)
        finally:
            manager.terminate_all()
    finally:
        _showing.release()
