"""The one dropdown. Every select in the Manager is this class or a subclass of it.

`FIELD` is the value in a row of a panel or dialog: a bordered box one row tall, the
text centered in it. `OUTLINED` is a control standing on its own - a toolbar's picker, a
box that fills a panel - at Quasar's outlined height.

`ui.select` is not called anywhere else in `manager/`; a call site names a look and never
writes the props. Both looks are checked by `tests/manager/test_every_dropdown_is_one.py`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from nicegui import ui

FIELD = "field"
OUTLINED = "outlined"

MARK = "manager-select"
_PROPS = {FIELD: "dense borderless options-dense", OUTLINED: "dense outlined options-dense"}
_CLASSES = {FIELD: "manager-edit-field manager-edit-select", OUTLINED: ""}
_MANY = "manager-edit-many"


class Select(ui.select):
    """A `ui.select` in one of the two looks.

    `multiple` draws what is chosen as chips, and a chosen option leaves the open list:
    the x on its chip is the only way out.

    `sections` maps an option's value to the heading it sits under in the open list. The
    options must already be in the order the headings run; a heading is drawn before the
    first option of each run and cannot be chosen. Not for `multiple`, and not with typed
    search, which filters the headings as if they were options.
    """

    SECTIONED = """
        <q-item-label v-if="props.opt.section" header class="manager-group">
          {{ props.opt.label }}
        </q-item-label>
        <q-item v-else v-bind="props.itemProps">
          <q-item-section><q-item-label>{{ props.opt.label }}</q-item-label></q-item-section>
        </q-item>
    """

    def __init__(self, *args: Any, look: str = FIELD,
                 sections: Mapping[Any, str] | None = None, **kwargs: Any) -> None:
        # Before `super().__init__`, which builds the payload for the first time.
        self._sections = dict(sections or {})
        super().__init__(*args, **kwargs)
        self.classes(f"{MARK} {_CLASSES[look]}").props(_PROPS[look])
        if kwargs.get("multiple"):
            self.props("use-chips")
            if look == FIELD:
                self.classes(_MANY)
        if self._sections:
            self.add_slot("option", self.SECTIONED)

    def _update_options(self) -> None:
        super()._update_options()
        if self.multiple:
            chosen = self.value or []
            self._props["options"] = [one for one in self._props["options"]
                                      if self._values[one["value"]] not in chosen]
        if self._sections:
            options: list[dict[str, Any]] = []
            heading = None
            # A change of value inside `super()._update_options` can draw the list once already.
            for one in (one for one in self._props["options"] if not one.get("section")):
                under = self._sections.get(self._values[one["value"]])
                if under is not None and under != heading:
                    options.append({"label": under, "value": f"section:{under}",
                                    "disable": True, "section": True})
                    heading = under
                options.append(one)
            self._props["options"] = options
