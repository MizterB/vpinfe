"""A game's backglass file, drawn: which one a table reads, and its picture."""

from __future__ import annotations

from pathlib import Path

from common import service_errors, sized_media
from common.games import asset_lens, asset_resolver, directb2s_parser, game_lens, media_ops
from common.i18n import t

KIND = "backglass"


def _file(game_id: str, table_id: str, path: str) -> Path:
    """The backglass file named by `path`, or else the one `table_id` reads (the folder's
    own where no table is named)."""
    game = game_lens.game_or_refuse(game_id)
    game_dir = Path(game.full_path_game or "")
    if path:
        found = asset_lens.inside(game_dir, path)
        if found.suffix.lower() != ".directb2s":
            raise service_errors.RefusedError(t("error.backglass.not_a_backglass"),
                                              details={"path": path})
    else:
        files, _ = asset_resolver.folder_listing(game_dir)
        stem = media_ops.stem_or_refuse(game, table_id) if table_id else game_dir.name
        held = asset_resolver.resolve_for_table(stem, game_dir.name, files)[KIND]
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


__all__ = ["KIND", "picture_file"]
