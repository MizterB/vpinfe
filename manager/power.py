"""The power icon at the foot of the rail: this install's own device menu, from every page.

The verbs are the ones the Devices page draws for this device. Restart and the window
reopen go through the waiting line, so they follow the Manager to a new port, and lead the
menu with how much is waiting once the line has been dismissed.
"""

from __future__ import annotations

from typing import Any

from nicegui import ui

from common.i18n import t
from manager.devices import devices
from manager.kit import panel, verbs
from manager.kit.data import Library
from manager.settings import waiting


class Power:
    def __init__(self, library: Library, bar: waiting.Bar, state: dict[str, Any],
                 entries: list[dict[str, Any]], local_id: str) -> None:
        self.library = library
        self.bar = bar
        self.state = state
        self.local_id = local_id
        self.device = next((one for one in entries
                            if str(one.get("device_id") or "") == local_id),
                           {"device_id": local_id})
        self._menu: ui.menu | None = None
        self._button: ui.element | None = None
        self._dot: ui.element | None = None
        self._drawn: object = None
        bar.watchers.append(self.refill)

    def place(self) -> None:
        with ui.element("div").classes("manager-nav-mark"):
            button, self._menu = panel.menu_button(verbs.POWER, t("manager.page.power"))
            self._menu.props('anchor="bottom right" self="bottom left"')
            self._dot = ui.label("").classes("manager-nav-badge manager-nav-badge--dot")
        self._button = button
        button.set_visibility(False)
        self._dot.set_visibility(False)

    async def load(self) -> None:
        """What this install performs, unless the page has already read it."""
        cache = self.state.setdefault("device_actions", {})
        if self.local_id not in cache:
            cache[self.local_id] = await devices.load_actions(
                self.library, self.device, self.local_id, None)
        self.refill()

    def refill(self) -> None:
        """Draw the menu from what is cached and what the line says. Nothing is drawn
        again when it would be the same."""
        menu, button, dot = self._menu, self._button, self._dot
        if menu is None or button is None or dot is None or menu.is_deleted:
            return
        offered = (self.state.get("device_actions") or {}).get(self.local_id)
        lead = self.bar.lead()
        if lead is not None and not devices.offers(offered, lead[0]):
            lead = None
        acts = devices.acts(
            self.library, [devices.Target(self.device, self.library, offered, False)], None,
            routed=self.bar.routes(), led=lead)
        shape = (tuple((one.label, one.run is None, one.hint) for one in acts),
                 lead is not None)
        if shape == self._drawn:
            return
        self._drawn = shape
        panel.verb_menu(menu, devices.device_label(self.device), acts)
        button.set_visibility(bool(acts))
        dot.set_visibility(lead is not None)
