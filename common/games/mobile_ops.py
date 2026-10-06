"""What a VPX Mobile device is carrying, and putting games on it or taking them off.

Asked of the device, never remembered. A phone is taken away, filled up and emptied by
hand, so anything this end recorded about it would be a claim rather than a fact.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from common import device_client, device_ops, service_errors
from common import jobs as job_registry
from common.games import game_identity, game_repository, mobile_transfer
from common.i18n import t


def carried_by(device_id: str) -> dict[str, Any]:
    """It is a short question and the answer is only true at the moment it is given."""
    device = device_ops.mobile_or_refuse(device_id)
    found = mobile_transfer.carried(device.address, device.port)
    games = game_repository.catalog()
    named = {id(game): game_id for game_id, game in games.items()}
    ids: dict[str, str] = {}
    for game in game_identity.in_priority(games.values()):
        ids.setdefault(str(game.game_dir_name or ""), named[id(game)])
    return {"device_id": device_id, "count": len(found),
            "games": [{"folder": name, "game_id": ids.get(name)} for name in found]}


def send(device_id: str, game_ids: Iterable[str],
         everything: bool = False) -> job_registry.Job:
    """A job, not an action.

    The lifecycle vocabulary is for things that happen at once - stop the table, reboot.
    A multi-file transfer with per-file progress over a phone's wifi is slow work, and
    slow work has a shape here already.
    """
    device = device_ops.mobile_or_refuse(device_id)
    folders = [_folder_or_refuse(game_id) for game_id in game_ids]
    if not folders:
        raise service_errors.RefusedError(t("error.devices.games_needed"))
    heard = device_ops.probe_one(device)
    if heard["state"] != device_client.ANSWERING:
        raise mobile_transfer.DeviceUnreachableError(heard["reason"])

    def work(job: job_registry.Job) -> None:
        reporter = job.reporter()

        # The whole transfer's progress, not one game's: what a person watching wants is
        # how far through the twelve they are. `at` comes in by call so it is this
        # folder's position and not wherever the loop has reached.
        def reporting(at: int) -> mobile_transfer.Progress:
            def sent(done: int, total: int, said: str) -> None:
                reporter.progress(at * 100 + int(100 * done / max(total, 1)),
                                  len(folders) * 100, said)
            return sent

        for index, folder in enumerate(folders):
            reporter.progress(index, len(folders), t("said.sending_game", game=folder.name))
            mobile_transfer.send(folder, device.address, device.port,
                                 everything=everything, on_progress=reporting(index))
        sent = t("said.send_result", count=len(folders),
                 device=device.display_name or device_id)
        reporter.progress(len(folders), len(folders), sent)
        job.detail = sent

    return job_registry.submit(job_registry.KIND_DEVICE_SEND, work)


def remove(device_id: str, name: str) -> None:
    device = device_ops.mobile_or_refuse(device_id)
    mobile_transfer.remove(name, device.address, device.port)


def _folder_or_refuse(game_id: str) -> Path:
    folder = game_repository.game_folder(game_id)
    if folder is None:
        raise service_errors.NotFoundError(
            t("error.games.unknown_game", game_id=(game_id)))
    return folder
