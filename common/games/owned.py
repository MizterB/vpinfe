from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from common.games import game_identity, game_repository
from common.games.game_metadata import default_table, game_title, game_vps_id, normalize_meta
from common.games.tables import entry_for_filename, table_entries


def owned(vps_ids: Iterable[Any]) -> dict[str, Any]:
    wanted = {str(one or "").strip() for one in vps_ids} - {""}
    found: dict[str, dict[str, str]] = {}
    if not wanted:
        return {"owned": found, "other_versions": {}}
    games = list(game_repository.all_games())
    for game in games:
        game_id = game_identity.game_id(game)
        name = game_title(game)
        entry = game_vps_id(game)
        if entry in wanted and entry not in found:
            found[entry] = {"game_id": game_id, "table_id": "", "name": name}
        for key, table in table_entries(normalize_meta(game.meta_config)).items():
            source = table.get("source") if isinstance(table, dict) else None
            release = str((source or {}).get("vps_file_id") or "").strip()
            if release in wanted and release not in found:
                found[release] = {"game_id": game_id, "table_id": str(key), "name": name}
    return {"owned": found, "other_versions": _other_versions(wanted - set(found), games)}


def _other_versions(missing: set[str], games: list[Any]) -> dict[str, dict[str, str]]:
    if not missing:
        return {}
    from common.games.game_service import load_vpsdb
    from common.online.vps_lens import entry_address

    machines: dict[str, tuple[str, str]] = {}
    for entry in load_vpsdb():
        for release in entry.get("tableFiles") or []:
            said = str(release.get("id") or "")
            if said in missing:
                urls = [str(one.get("url") or "") for one in release.get("urls") or []]
                machines[said] = (str(entry.get("id") or ""),
                                  next((one for one in urls if one),
                                       entry_address(str(entry.get("id") or ""))))
    by_entry = {game_vps_id(game): game for game in games if game_vps_id(game)}
    other: dict[str, dict[str, str]] = {}
    for release, (machine, address) in machines.items():
        game = by_entry.get(machine)
        if game is None:
            continue
        meta = normalize_meta(game.meta_config)
        filename, table = default_table(meta, folder_name=game.game_dir_name or "")
        other[release] = {"game_id": game_identity.game_id(game),
                          "table_id": entry_for_filename(table_entries(meta), filename)[0],
                          "name": game_title(game),
                          "version": str(table.get("version") or ""), "url": address}
    return other
