"""A game's backglass file, drawn: which one a table reads, and its picture."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from common import service_errors, sized_media
from common.games import (
    asset_lens,
    asset_origin,
    asset_resolver,
    directb2s_parser,
    game_lens,
    media_lookup,
    media_ops,
    media_placement,
)
from common.games.game_repository import game_to_row
from common.i18n import t

logger = logging.getLogger("vpinfe.common.games.backglass_ops")

KIND = "backglass"


def _file(game_id: str, table_id: str, path: str) -> Path:
    """The backglass file named by `path`, or else the one `table_id` reads. Where no
    table is named it is the folder's own, and failing that the default table's."""
    game = game_lens.game_or_refuse(game_id)
    game_dir = Path(game.full_path_game or "")
    if path:
        found = asset_lens.inside(game_dir, path)
        if found.suffix.lower() != ".directb2s":
            raise service_errors.RefusedError(t("error.backglass.not_a_backglass"),
                                              details={"path": path})
    else:
        files, _ = asset_resolver.folder_listing(game_dir)
        if table_id:
            media_ops.stem_or_refuse(game, table_id)
            names = [media_lookup.table_filename(game, table_id)]
        else:
            ordered = sorted(_table_rows(game, ""), key=lambda row: not row.get("default"))
            names = [game_dir.name, *(str(row.get("filename") or "") for row in ordered)]
        held: dict = {}
        for name in names:
            held = asset_resolver.resolve_for_table(name, game_dir.name, files)[KIND]
            if held.get("file"):
                break
        if not held.get("file"):
            raise service_errors.NotFoundError(t("error.backglass.none"))
        found = game_dir / held["file"]
    if not found.is_file():
        raise service_errors.NotFoundError(t("error.backglass.none"))
    return found


def picture_file(game_id: str, table_id: str = "", look: str = "on",
                 version: str = "authentic", grill: bool = False, path: str = "",
                 size: int | None = None) -> sized_media.Served:
    """The backglass picture in the look asked for. `grill` is the picture as the
    renderer in effect cuts it. The version token is the file's, so a changed file is
    a new picture."""
    if look not in directb2s_parser.LOOKS:
        raise service_errors.RefusedError(t("error.backglass.unknown_look"),
                                          details={"look": look})
    if version not in directb2s_parser.VERSIONS:
        raise service_errors.RefusedError(t("error.backglass.unknown_version"),
                                          details={"version": version})
    size = sized_media.size_or_refuse(size, "image")
    source = _file(game_id, table_id, path)
    try:
        drawn = directb2s_parser.picture(
            source, look, version, grill)  # type: ignore[arg-type]
    except directb2s_parser.BackglassError:
        raise service_errors.NotFoundError(t("error.backglass.damaged")) from None
    served = sized_media.served(drawn, size)
    return sized_media.Served(served.path, sized_media.version(source) or "")


_ON = ("1", "true")


def _table_rows(game: Any, table_id: str) -> list[dict]:
    from common.games import table_lens

    rows = [row for row in table_lens.table_rows(game, game_to_row(game)) if row.get("id")]
    return [row for row in rows if row["id"] == table_id] if table_id else rows


def grill_cut(game_id: str, table_id: str = "") -> bool:
    """Whether the renderer in effect cuts the grill off the picture. B2S Legacy is on
    unless its setting says otherwise, and wins over B2S. The folder's first table answers
    for the shared slot. Cut where the settings cannot be read."""
    from common.games import launcher_ops

    game = game_lens.game_or_refuse(game_id)
    row = next((one for one in _table_rows(game, table_id)
                if one.get("launcher") and one.get("launcher_app_configurable")), None)
    if row is None:
        return True
    try:
        held = launcher_ops.effective_values(row["launcher"], row["id"])
    except Exception:  # noqa: BLE001 - the picture is drawn without its settings
        return True

    def on(key: str) -> bool:
        return held.get(key, "").lower() in _ON

    if (held.get("Plugin.B2SLegacy.Enable") or "1").lower() in _ON:
        return on("Plugin.B2SLegacy.B2SHideGrill")
    return not on("Plugin.B2S.ShowGrill")


def _drawn(game_id: str, table_id: str) -> tuple[Path, str]:
    """The picture to place and its hash: On, authentic, cut as the renderer cuts it."""
    from common.online.vpsdb_media import file_md5

    served = picture_file(game_id, table_id, grill=grill_cut(game_id, table_id))
    return served.path, file_md5(served.path)


def offer(game_id: str, table_id: str = "") -> dict | None:
    """The file whose picture could fill the backglass slot, as the slot's dialog needs
    it: where it is, the version token its picture is addressed by, and whether the grill
    is cut. None where the table reads no backglass file or the one it reads is damaged."""
    try:
        found = _file(game_id, table_id, "")
        facts = directb2s_parser.read(found)
        if facts is None or directb2s_parser.damaged(facts):
            return None
        game_dir = Path(game_lens.game_or_refuse(game_id).full_path_game or "")
        return {"path": found.relative_to(game_dir).as_posix(), "file": found.name,
                "grill": grill_cut(game_id, table_id),
                "version": sized_media.version(found) or ""}
    except service_errors.NotFoundError:
        return None
    except Exception:  # noqa: BLE001 - a slot is described without its extra tab
        logger.exception("Could not offer the backglass file of %s", game_id)
        return None


def place_picture(game_id: str, table_id: str = "") -> dict:
    """Write the file's picture as this slot's backglass picture, recorded as drawn from
    the file so a later redraw knows it is ours."""
    drawn, md5 = _drawn(game_id, table_id)
    return media_ops.place_file(game_id, "backglass", table_id, drawn,
                                asset_origin.BACKGLASS_FILE, md5)


def redraw(game_id: str) -> int:
    """Draw again every picture of this game's that the file made and nobody has since
    replaced. Answers how many were redrawn. A picture whose file no longer matches the
    hash recorded for it was changed by hand and is left, and so is one with another file
    of the same family at its tier: placing the redraw would delete it."""
    from common.online.vpsdb_media import file_md5

    game = game_lens.game_or_refuse(game_id)
    game_dir = Path(game.full_path_game or "")
    held = {path: source for path, source in asset_origin.sources(game_dir).items()
            if source.get("host") == asset_origin.BACKGLASS_FILE and source.get("hash")}
    if not held:
        return 0
    redrawn = 0
    for table in ({"id": "", "stem": game_dir.name},
                  *({"id": row["id"], "stem": Path(str(row.get("filename") or "")).stem}
                    for row in _table_rows(game, ""))):
        name = media_placement.target_name(KIND, table["stem"], ".png")
        path = f"medias/{name}"
        source = held.get(path)
        if source is None or file_md5(game_dir / path) != source["hash"]:
            continue
        if media_placement.displaced(game_dir, KIND, table["stem"], ".png") != [game_dir / path]:
            continue
        try:
            drawn, md5 = _drawn(game_id, table["id"])
        except service_errors.ServiceError:
            continue
        if md5 and md5 != source["hash"]:
            media_ops.place_file(game_id, KIND, table["id"], drawn,
                                 asset_origin.BACKGLASS_FILE, md5)
            redrawn += 1
    return redrawn


def redraw_all(proceed: Callable[[], bool] = lambda: True) -> int:
    """`redraw` for every game that has such a picture. Answers how many were redrawn."""
    from common.games import game_repository

    total = 0
    for game_id, game in list(game_repository.catalog().items()):
        if not proceed():
            break
        try:
            if any(source.get("host") == asset_origin.BACKGLASS_FILE
                   for source in asset_origin.sources(str(game.full_path_game)).values()):
                total += redraw(game_id)
        except Exception:  # noqa: BLE001 - one game's picture is not the sweep
            logger.exception("Could not redraw the backglass picture of %s",
                             game.game_dir_name)
    return total


__all__ = ["KIND", "grill_cut", "offer", "picture_file", "place_picture", "redraw",
           "redraw_all"]
