"""Getting a game the art it has no file for, and keeping the art we fetched current.

A slot is filled only when nothing serves it. What counts as wanted is Kinds and the
online sources that are on; the size is the one the display settings name. A backglass
picture is also drawn from the game's own backglass file, which needs no match and no
network, and is tried before anything is downloaded.
"""

from __future__ import annotations

import logging
import tempfile
import threading
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from common.config.config_access import MediaConfig, cfg_bool
from common.config.config_store import ConfigStore
from common.config.paths import get_ini_config
from common.games.game_metadata import effective_vps_id, normalize_meta
from common.i18n import t
from common.media.media_specs import MEDIA_SPECS
from common.runtime import jobs, shutdown
from common.runtime.jobs import JobReporter

logger = logging.getLogger("vpinfe.common.games.media_fill")

_SPECS = {spec.kind: spec for spec in MEDIA_SPECS}

_lock = threading.Lock()
_pending: list[str] = []
_running = False


def enabled() -> bool:
    return cfg_bool(get_ini_config(), "updates", "get_media_for_new_games", True)


def _hidden_kinds() -> set[str]:
    from common.games.library_policy import get_library_policy

    return set(get_library_policy().get("hidden_media_kinds"))


def kept_kinds() -> set[str]:
    """The kinds this library collects that some enabled source publishes."""
    from common.online import sources

    hidden = _hidden_kinds()
    offered: set[str] = set()
    for source in sources.catalogs(sources.enabled_ids()):
        offered |= source.kinds
    return {kind for kind in _SPECS if kind not in hidden and kind in offered}


def fillable_kinds() -> set[str]:
    """The kinds a fill may put in an empty slot: the kept kinds, and the kinds a game's
    own files can supply where no online source is on."""
    return kept_kinds() | (set(_LOCAL) - _hidden_kinds())


def _file_offers(game_id: str) -> bool:
    """Whether the game has a backglass file that can be drawn."""
    from common.games import backglass_ops

    return backglass_ops.offer(game_id) is not None


def _file_draws(game_id: str) -> None:
    from common.games import backglass_ops

    backglass_ops.place_picture(game_id)


# A kind a game's own file can supply: whether it has one, and putting its picture in the
# slot. A game with no VPS match has these as much as any other.
_LOCAL: dict[str, tuple[Callable[[str], bool], Callable[[str], None]]] = {
    "backglass": (_file_offers, _file_draws),
}


def _from_file(kind: str, game_id: str, name: str) -> bool:
    """Whether the game's own file filled the slot. A file that offered a picture and
    then failed to draw it leaves the slot to the online sources."""
    offers, draws = _LOCAL.get(kind, (None, None))
    if offers is None or draws is None or not offers(game_id):
        return False
    try:
        draws(game_id)
    except Exception as exc:  # noqa: BLE001 - the online sources are still asked
        logger.warning("Getting art: could not draw %s for %s from its file: %s",
                       kind, name, exc)
        return False
    return True


def _reachable() -> tuple[str, ...]:
    """The enabled sources that answer now, asking each once and naming each that does
    not. Never empty for "all": an empty answer means nothing can be asked."""
    from common.online import sources

    live = []
    for source in sources.catalogs(sources.enabled_ids()):
        if source.reachable():
            live.append(source.id)
        else:
            logger.warning("%s could not be reached, so nothing is fetched from it "
                           "this time", source.name)
    return tuple(live)


def _unanswered(live: tuple[str, ...]) -> list[str]:
    from common.online import sources

    return [source.name for source in sources.catalogs(sources.enabled_ids())
            if source.id not in live]


def _asked_as(kind: str, variant: str) -> str | None:
    """The kind to ask a source for to fill `kind`'s slot, or None to leave it.

    Under the FSS variant the playfield window shows the FSS render, and nothing
    publishes an FSS video, so a table video there would play over the wrong picture.
    """
    if variant == "fss":
        if kind == "playfield":
            return "playfield_fss"
        if kind == "playfield_video":
            return None
    return kind


def _size(kind: str, media: MediaConfig) -> str:
    group = _SPECS[kind].asset_group or ""
    return {"table_resolution": media.playfield_resolution,
            "table_video_resolution": media.playfield_video_resolution}.get(group, group)


def is_gap(row: dict[str, Any]) -> bool:
    """A media row the fill would fetch for: no file serves the game's tables, and no
    set someone chose answers the slot."""
    return (not row.get("table") and not row.get("present")
            and not str(row.get("standing_in") or "").startswith("set:"))


def _gaps(game_id: str) -> list[str]:
    from common.games import media_lens

    return [row["kind"] for row in media_lens.listing(game=game_id)["media"]
            if is_gap(row)]


def _fetch(game_id: str, kind: str, asked: str, vps_id: str, size: str,
           live: tuple[str, ...]) -> bool:
    """Put the source's file in the slot. False when no source has one."""
    from common.games import media_ops
    from common.online import sources
    from common.security.http_client import download_file

    offers = sources.offers(asked, vps_id, live)
    if not offers:
        return False
    offer = next((one for one in offers if one.size == size), offers[0])
    with tempfile.TemporaryDirectory() as staging:
        staged = Path(staging) / Path(offer.url).name
        download_file(offer.url, staged)
        media_ops.place_file(game_id, kind, "", staged, offer.source, offer.md5)
    return True


def _folders_to_games() -> dict[str, tuple[str, Any]]:
    from common.games import game_repository

    return {str(Path(str(game.full_path_game)).resolve()): (game_id, game)
            for game_id, game in game_repository.catalog().items()}


# A game, and the kinds to fill for it.
Target = tuple[str, Any, set[str]]


def _locked(games: list[Any]) -> set[int]:
    """The games whose folders cannot be written to, each named once in the log. Asked of
    every folder at once, so one that does not answer costs one wait and not one per file."""
    from common.games import library_folders

    held = set()
    for game, said in library_folders.blocked_games(games):
        logger.warning("Art: left %s alone: %s", game.game_dir_name, said)
        held.add(id(game))
    return held


def _fill_games(targets: list[Target], live: tuple[str, ...],
                reporter: JobReporter | None,
                proceed: Callable[[], bool]) -> dict[str, int]:
    """Fetch each target's gaps. `filled` and `failed` count files; `unmatched` counts
    games with no VPS id, which nothing can be looked up for; `skipped` counts games whose
    folder cannot be written to. With no source reachable only the kinds a game's own
    file can supply are filled."""
    counts = {"games": len(targets), "filled": 0, "unmatched": 0, "failed": 0, "skipped": 0}
    if not targets:
        return counts
    media = MediaConfig.from_config(get_ini_config())
    locked = _locked([game for _, game, _ in targets])
    for index, (game_id, game, wanted) in enumerate(targets):
        if not proceed():
            break
        if id(game) in locked:
            counts["skipped"] += 1
            continue
        name = str(game.game_dir_name or "")
        if reporter:
            reporter.progress(index, len(targets), t("said.media_fetch", game=name))
        vps_id = effective_vps_id(normalize_meta(game.meta_config or {}))
        counts["unmatched"] += bool(live and not vps_id)
        reach = wanted if live and vps_id else wanted & set(_LOCAL)
        placed = 0
        try:
            gaps = _gaps(game_id) if reach else []
        except Exception:
            logger.exception("Getting art: could not read what %s has", name)
            continue
        for kind in gaps:
            if kind not in reach:
                continue
            try:
                if _from_file(kind, game_id, name):
                    placed += 1
                    continue
                asked = _asked_as(kind, media.playfield_variant)
                if asked is None or not (live and vps_id):
                    continue
                if _fetch(game_id, kind, asked, vps_id, _size(asked, media), live):
                    placed += 1
            except Exception as exc:
                counts["failed"] += 1
                logger.warning("Getting art: could not get %s for %s: %s", kind, name, exc)
        counts["filled"] += placed
    return counts


def _fill(folders: list[str], wanted: set[str], live: tuple[str, ...],
          reporter: JobReporter | None, proceed: Callable[[], bool]) -> dict[str, int]:
    games = _folders_to_games()
    found = [games.get(str(Path(folder).resolve())) for folder in folders]
    return _fill_games([(game_id, game, wanted) for game_id, game in filter(None, found)],
                       live, reporter, proceed)


def fill(folders: Iterable[str | Path], kinds: Iterable[str] | None = None,
         reporter: JobReporter | None = None) -> dict[str, int]:
    """Fetch what each game in `folders` is missing, of `kinds` or else the fillable kinds.
    Never replaces a file, and never fetches a kind the library does not keep."""
    wanted = fillable_kinds() if kinds is None else fillable_kinds() & set(kinds)
    return _fill([str(folder) for folder in folders], wanted, _reachable(), reporter,
                 lambda: True)


def _scope(game_ids: Iterable[str] | None) -> dict[str, Any]:
    """The library's games named by `game_ids`, or all of them. Ids it does not hold
    are left out."""
    from common.games import game_repository

    held = game_repository.catalog()
    if game_ids is None:
        return dict(held)
    return {one: held[one] for one in dict.fromkeys(game_ids) if one in held}


def plan(game_ids: Iterable[str] | None = None) -> dict[str, Any]:
    """What getting missing art for these games would do, fetching nothing.

    Per kind the library keeps: how many games have no file for it, how many of those
    an enabled source or the game's own file has one for, and how many of that is the
    game's own file. Reads the catalog index, and the backglass file of a game that has
    a backglass gap.
    """
    from common.games import media_lens
    from common.online import sources

    scope = _scope(game_ids)
    kept = fillable_kinds()
    kinds = [kind for kind in _SPECS if kind in kept]
    variant = MediaConfig.from_config(get_ini_config()).playfield_variant
    enabled = sources.catalogs(sources.enabled_ids())
    live = tuple(source.id for source in enabled if source.reachable())
    only = next(iter(scope)) if len(scope) == 1 else ""
    gaps: dict[str, list[str]] = {}
    for row in media_lens.listing(game=only)["media"] if scope else []:
        if row["game_id"] in scope and is_gap(row):
            gaps.setdefault(row["game_id"], []).append(row["kind"])
    missing = dict.fromkeys(kinds, 0)
    available = dict.fromkeys(kinds, 0)
    local = dict.fromkeys(kinds, 0)
    unmatched = 0
    for game_id, game in scope.items():
        vps_id = effective_vps_id(normalize_meta(game.meta_config or {}))
        unmatched += not vps_id
        for kind in gaps.get(game_id, []):
            if kind not in missing:
                continue
            missing[kind] += 1
            if kind in _LOCAL and _LOCAL[kind][0](game_id):
                available[kind] += 1
                local[kind] += 1
                continue
            asked = _asked_as(kind, variant)
            if vps_id and asked and live and sources.offers(asked, vps_id, live):
                available[kind] += 1
    return {"games": len(scope), "unmatched": unmatched,
            "sources": [source.name for source in enabled],
            "unreachable": _unanswered(live),
            "kinds": [{"kind": kind, "missing": missing[kind],
                       "available": available[kind], "local": local[kind]}
                      for kind in kinds]}


def _offered() -> dict[str, dict[str, tuple[str, int, str]]]:
    """Per kind the library keeps, the games with no file for it that an enabled source has
    one for: game id to its VPS id, how many files the sources offer and its name.

    Makes no request: a source answers from the index it already holds, and one that holds
    none yet offers nothing, so every gap reads as one no source fills. A backglass the
    game's own file could draw is not offered by a source, and a game with no VPS match has
    nothing a source can be asked for. With no source reachable the answer is empty.
    """
    from common.games import media_lens
    from common.online import sources

    scope = _scope(None)
    kept = fillable_kinds()
    variant = MediaConfig.from_config(get_ini_config()).playfield_variant
    out: dict[str, dict[str, tuple[str, int, str]]] = {}
    with sources.cached_only():
        live = tuple(source.id for source in sources.catalogs(sources.enabled_ids())
                     if source.reachable())
        if not live or not scope:
            return {}
        matched: dict[str, str] = {}
        for row in media_lens.library_rows():
            game = scope.get(row["game_id"])
            if game is None or row["kind"] not in kept or not is_gap(row):
                continue
            if row["game_id"] not in matched:
                matched[row["game_id"]] = effective_vps_id(normalize_meta(game.meta_config or {}))
            vps_id = matched[row["game_id"]]
            asked = _asked_as(row["kind"], variant)
            if not vps_id or not asked:
                continue
            if offers := sources.offers(asked, vps_id, live):
                out.setdefault(row["kind"], {})[row["game_id"]] = (
                    vps_id, len(offers), str(row.get("game") or ""))
    return out


def offered_listing() -> dict[str, list[dict[str, Any]]]:
    """`_offered` for a page that names the games: per kind, one record for each game a
    source can fill the slot of, with its id, its VPS entry, its name and how many files
    the sources offer. The records Needs You leaves out of its counts are exactly these."""
    return {kind: [{"game_id": game_id, "vps_id": vps_id, "name": name, "available": count}
                   for game_id, (vps_id, count, name) in games.items()]
            for kind, games in _offered().items()}


def holders() -> dict[str, list[str]]:
    """The library's games by the VPS entry each is matched to: entry id to game ids. Makes
    no request. A game with no match is not in it."""
    out: dict[str, list[str]] = {}
    for game_id, game in sorted(_scope(None).items()):
        if vps_id := effective_vps_id(normalize_meta(game.meta_config or {})):
            out.setdefault(vps_id, []).append(game_id)
    return out


def offered_games() -> dict[str, list[str]]:
    """`_offered` by game: per kind, the ids of the games a source can fill the slot of."""
    return {kind: sorted(games) for kind, games in _offered().items()}


def start(game_ids: Iterable[str] | None = None, kinds: Iterable[str] | None = None,
          slots: Iterable[tuple[str, str]] = ()) -> jobs.Job:
    """Get missing art as a job: these games' gaps of `kinds`, or exactly `slots`.

    `game_ids` None is the whole library and `kinds` None every kept kind. A kind the
    library does not keep is never fetched. Raises BlockedError while a fill runs.
    """
    kept = fillable_kinds()
    picked: dict[str, set[str]] = {}
    for game_id, kind in slots:
        picked.setdefault(game_id, set()).add(kind)
    if picked:
        targets = [(game_id, game, picked[game_id] & kept)
                   for game_id, game in _scope(picked).items()]
    else:
        chosen = kept if kinds is None else kept & set(kinds)
        targets = [(game_id, game, chosen) for game_id, game in _scope(game_ids).items()]

    def work(job: jobs.Job) -> dict[str, Any]:
        live = _reachable()
        return {**_fill_games(targets, live, job.reporter(), lambda: not shutdown.requested()),
                "unreachable": _unanswered(live)}

    return jobs.submit(jobs.KIND_MEDIA_FILL, work)


def request(folders: Iterable[str | Path]) -> None:
    """Queue these game folders for a fill, starting the job if none is running.

    A request while one runs joins that run. Does nothing when the switch is off.
    """
    global _running
    if not enabled():
        return
    wanted = [str(folder) for folder in folders if folder]
    if not wanted:
        return
    with _lock:
        _pending.extend(folder for folder in wanted if folder not in _pending)
        if _running:
            return
        _running = True
    _start()


def _start() -> None:
    try:
        jobs.submit(jobs.KIND_MEDIA_FILL, _work)
    except jobs.JobBusyError:
        # The run that just emptied the queue is still finishing, and holds the kind
        # until it does.
        retry = threading.Timer(1.0, _start)
        retry.daemon = True
        retry.start()


def _proceed() -> bool:
    return enabled() and not shutdown.requested()


def _work(job: jobs.Job) -> dict[str, int]:
    """Drain the queue. Kinds and the sources are read once for the whole run."""
    global _running
    reporter = job.reporter()
    wanted = fillable_kinds()
    live = _reachable()
    totals = {"games": 0, "filled": 0, "unmatched": 0, "failed": 0, "skipped": 0}
    while True:
        with _lock:
            batch = list(_pending)
            _pending.clear()
            if not batch or not _proceed():
                _running = False
                logger.info("Art for new games: %s file(s) for %s game(s), %s not "
                            "matched, %s failed, %s left alone", totals["filled"],
                            totals["games"], totals["unmatched"], totals["failed"],
                            totals["skipped"])
                return totals
        for key, value in _fill(batch, wanted, live, reporter, _proceed).items():
            totals[key] += value


def update_enabled() -> bool:
    return cfg_bool(get_ini_config(), "updates", "update_downloaded_media", True)


def _update_game(game_id: str, game: Any, vps_id: str, wanted: set[str],
                 live: tuple[str, ...], media: MediaConfig) -> tuple[int, int]:
    """Replace this game's stale art. Answers (updated, failed).

    Files are hashed only where the recorded hash is gone from the catalog.
    """
    from common.games import asset_origin, media_lens, media_placement
    from common.online import sources
    from common.online.vpsdb_media import file_md5, replace_file

    game_dir = Path(str(game.full_path_game))
    recorded = {path: source for path, source in asset_origin.sources(game_dir).items()
                if source.get("hash") and source.get("host") in live}
    # An empty id would list every game's rows against this folder's ledger.
    if not vps_id or not game_id or not recorded:
        return 0, 0
    hosts = tuple({str(source["host"]) for source in recorded.values()})
    published = {offer.md5 for kind in _SPECS
                 for offer in sources.offers(kind, vps_id, hosts)}
    gone = {path for path, source in recorded.items() if source["hash"] not in published}
    if not gone:
        return 0, 0
    updated = failed = 0
    for row in media_lens.listing(game=game_id)["media"]:
        path = row.get("path") or ""
        kind = row["kind"]
        asked = _asked_as(kind, media.playfield_variant) if kind in wanted else None
        if path not in gone or not row["present"] or asked is None:
            continue
        gone.discard(path)
        host, held = str(recorded[path]["host"]), str(recorded[path]["hash"])
        mine = sources.offers(asked, vps_id, (host,))
        if not mine or file_md5(game_dir / path) != held:
            continue
        size = _size(asked, media)
        offer = next((one for one in mine if one.size == size), mine[0])
        try:
            replace_file(offer.url, game_dir / path)
        except Exception as exc:
            failed += 1
            logger.warning("Updating art: could not replace %s for %s: %s", kind,
                           game.game_dir_name, exc)
            continue
        media_placement.record_origin(game_dir, game_dir / path, host, offer.md5)
        updated += 1
    return updated, failed


def art_updater(config: ConfigStore, catalog: dict | None = None,
                ) -> Callable[[str, Any, str], tuple[int, int]] | None:
    """`_update_game` for one game at a time, as (game_id, game, vps_id), with the catalog
    read again, or `catalog` where the caller holds a copy it has just read, and each
    source asked once. None when nothing can be asked."""
    from common.online import vpinmediadb

    vpinmediadb.refresh_manifest(catalog)
    live = _reachable()
    wanted = kept_kinds()
    if not live or not wanted:
        return None
    media = MediaConfig.from_config(config)

    def update(game_id: str, game: Any, vps_id: str) -> tuple[int, int]:
        return _update_game(game_id, game, vps_id, wanted, live, media)

    return update


def update_downloaded(reporter: JobReporter | None = None,
                      proceed: Callable[[], bool] = lambda: True) -> dict[str, int]:
    """Replace art we downloaded that the catalog has since replaced.

    Only a file whose recorded hash still matches it, of a kind the library keeps, from
    a source that is on. `updated` and `failed` count files; `skipped` counts games whose
    folder cannot be written to.
    """
    from common.games import game_repository, media_service

    counts = {"games": 0, "updated": 0, "failed": 0, "skipped": 0}
    update = art_updater(get_ini_config())
    if update is None:
        return counts
    games = list(game_repository.catalog().items())
    locked = _locked([game for _, game in games])
    for index, (game_id, game) in enumerate(games):
        if not proceed():
            break
        if id(game) in locked:
            counts["skipped"] += 1
            continue
        name = str(game.game_dir_name or "")
        if reporter:
            reporter.progress(index, len(games), t("said.media_update", game=name))
        try:
            updated, failed = update(game_id, game,
                                     effective_vps_id(normalize_meta(game.meta_config or {})))
        except Exception:
            logger.exception("Updating art: could not read what %s has", name)
            continue
        counts["games"] += 1
        counts["failed"] += failed
        if updated:
            counts["updated"] += updated
            media_service.invalidate_media_cache()
            game_repository.refresh_game(Path(str(game.full_path_game)))
    logger.info("Updating art: %s file(s) replaced across %s game(s), %s failed, "
                "%s left alone", counts["updated"], counts["games"], counts["failed"],
                counts["skipped"])
    return counts


def start_update() -> bool:
    """Run `update_downloaded` as a job. False when a fill holds the job kind."""
    def work(job: jobs.Job) -> dict[str, int]:
        from common.games import backglass_ops

        def proceed() -> bool:
            return update_enabled() and not shutdown.requested()

        redrawn = backglass_ops.redraw_all(proceed)
        if redrawn:
            logger.info("Updating art: %s backglass picture(s) drawn again", redrawn)
        return update_downloaded(job.reporter(), proceed)

    try:
        jobs.submit(jobs.KIND_MEDIA_FILL, work)
    except jobs.JobBusyError:
        return False
    return True


def reset_for_tests() -> None:
    global _running
    with _lock:
        _pending.clear()
        _running = False
