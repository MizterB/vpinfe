"""What a frontend browser plays, where it is worth noticing - one drawing for the Devices
page and Settings > Frontend > Browser."""

from __future__ import annotations

from typing import Any

from common.i18n import t

from . import panel

# `plays` is not here: the normal case draws nothing.
STATES = {
    "no_h264": {"label": t("console.devices.browser_no_h264"), "tier": "warn",
                "why": t("frontend_browser.finding.no_h264")},
    "no_video": {"label": t("console.devices.browser_no_video"), "tier": "bad",
                 "why": t("frontend_browser.finding.no_video")},
    "no_browser": {"label": t("console.devices.browser_no_browser"), "tier": "bad",
                   "why": t("frontend_browser.finding.no_browser")},
    "unknown": {"label": t("console.devices.browser_not_checked"), "tier": "unknown",
                "why": t("console.devices.browser_checked_when")},
}


def value(name: str, state: str, unnamed: str) -> Any:
    """The browser's name as text, with a chip beside it only for a state worth noticing.
    `unnamed` stands in where no name was reported and there is no chip."""
    limited = STATES.get(state)
    if limited is None:
        return name or unnamed
    return panel.state(limited["label"], limited["tier"], beside=name, hint=limited["why"])
