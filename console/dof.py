"""Settings > Hardware > Output: what the DOF section cannot say from the schema alone.

The DOF Config Tool is asked on a schedule, and the foot says when it last was and offers
the act of asking now. Only this install's own client is asked, as the other pages' feet are.
"""

from __future__ import annotations

from typing import Any

from nicegui import ui

from common.failures import why
from common.i18n import t
from console import offload, panel
from console.on_page import on_page

SECTION = "dof"


async def foot(library: Any, rerender: Any, **_: Any) -> list[tuple[Any, Any]]:
    """When the config was last asked for, and the way to ask now. Dimmed, with the reason,
    while there is no API key to ask with."""
    from console.settings import last_checked

    try:
        state = await offload.io(library.dof_config_state)
    except Exception as exc:  # noqa: BLE001 - a settings page says why, never 500s
        return [panel.intro(t("console.dof.state_failed"), hint=why(exc))]

    @on_page
    async def now() -> None:
        from console import record

        # Held: an ongoing notification never times out on its own.
        downloading = ui.notification(t("said.dof_config.download"), spinner=True,
                                      timeout=None)
        try:
            job = await offload.io(library.download_dof_config)
            ended = await record.ended_job(library, str(job.get("id") or ""))
        except Exception as exc:  # noqa: BLE001 - the reason belongs on screen
            ui.notify(t("console.settings.check_failed"), caption=why(exc), type="negative")
            return
        finally:
            downloading.dismiss()
        if not ended or ended.get("error"):
            ui.notify(t("console.settings.check_failed"),
                      caption=str(ended.get("error") or ""), type="negative")
        else:
            # "Already up to date" is the ordinary outcome and says itself.
            changed = bool(ended.get("changed"))
            ui.notify(t("said.dof_config.updated") if changed
                      else t("console.settings.already_date"),
                      type="positive" if changed else "info")
        rerender()

    return [last_checked(str(state.get("checked") or ""), now,
                         blocked="" if state.get("has_key") else t("error.dof_config.no_key"))]
