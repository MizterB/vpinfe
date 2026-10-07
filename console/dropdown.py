"""The one dropdown. Every select in the Console is this class or a subclass of it.

`FIELD` is the value in a row of a panel or dialog: a bordered box one row tall, the
text centered in it. `OUTLINED` is a control standing on its own - a toolbar's picker, a
box that fills a panel - at Quasar's outlined height.

`ui.select` is not called anywhere else in `console/`; a call site names a look and never
writes the props. Both looks are checked by `tests/console/test_every_dropdown_is_one.py`.
"""

from __future__ import annotations

from typing import Any

from nicegui import ui

FIELD = "field"
OUTLINED = "outlined"

MARK = "console-select"
_PROPS = {FIELD: "dense borderless options-dense", OUTLINED: "dense outlined options-dense"}
_CLASSES = {FIELD: "console-edit-field console-edit-select", OUTLINED: ""}
_MANY = "console-edit-many"


class Select(ui.select):
    """A `ui.select` in one of the two looks.

    `multiple` draws what is chosen as chips, and a chosen option leaves the open list:
    the x on its chip is the only way out.
    """

    def __init__(self, *args: Any, look: str = FIELD, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.classes(f"{MARK} {_CLASSES[look]}").props(_PROPS[look])
        if kwargs.get("multiple"):
            self.props("use-chips")
            if look == FIELD:
                self.classes(_MANY)

    def _update_options(self) -> None:
        super()._update_options()
        if self.multiple:
            chosen = self.value or []
            self._props["options"] = [one for one in self._props["options"]
                                      if self._values[one["value"]] not in chosen]
