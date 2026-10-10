"""What needs you on Overview, as rows ordered by what each one costs.

Pure: this decides which rows there are, what each counts and where a click on it lands.
`sections.overview` draws them. A row draws only while its count is above zero, and keeps
its own unit - games, tables, recordings - so that nothing is added together and a click
can open the grid on exactly what the row counted.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from common import feature_checks
from common.i18n import t
from console import jobs_list, verbs

# The tone a row is drawn in, which says how much it costs to leave alone.
DANGER, WARM, ACCENT, MUTED = "danger", "warm", "accent", "muted"

# What a click does that is not opening a grid on a filter.
METADATA, REVIEW, RETRY = "metadata", "review", "retry"

# A fix VPinFE can do itself, drawn as the icon at the row's end.
GET_MEDIA, UPDATE = "get_media", "update"

_UNIT_GAMES = "console.games.games"
_UNIT_TABLES = "console.games.tables"
_UNIT_FOLDERS = "console.needs.folders"
_UNIT_RECORDINGS = "console.needs.recordings_count"


@dataclass(frozen=True)
class Opens:
    """Where a click lands: a rail view, the filter its grid arrives on, the state keys
    that view reads on arrival, and what to do instead where it is not a view."""

    view: str = ""
    arriving: dict[str, Any] | None = None
    keys: Mapping[str, Any] = field(default_factory=dict)
    then: str = ""


@dataclass(frozen=True)
class Fix:
    key: str
    label: str
    tip: str
    icon: str
    # What the fix is for: a media kind for Get Media.
    kind: str = ""


@dataclass(frozen=True)
class Need:
    key: str
    label: str
    tip: str
    tone: str
    icon: str
    opens: Opens
    # Games, tables or recordings the row counts, by id. Empty for a row with no count.
    ids: tuple[str, ...] = ()
    unit: str = ""
    fix: Fix | None = None

    @property
    def count(self) -> int:
        return len(self.ids)

    def counted(self) -> str:
        """The count in its own unit, or "" for a row that has none."""
        return t(self.unit, count=self.count) if self.unit and self.ids else ""


def _games_without(key: str, found: Mapping[str, list[dict[str, Any]]],
                   *, label: str, tip: str, tone: str, icon: str, opens: Opens,
                   fix: Fix | None = None) -> Need | None:
    ids = tuple(sorted(str(game["id"]) for game in found.get(key) or ()))
    if not ids:
        return None
    return Need(key, label, tip, tone, icon, opens, ids, _UNIT_GAMES, fix)


def _blank(name: str) -> dict[str, Any]:
    return {name: {"values": [""]}}


def _unread(failed: Any) -> str:
    """The reads that failed, in the words a person would use for what they were after."""
    said = (("update", t("console.needs.unread_update")),
            ("recordings", t("console.needs.unread_recordings")),
            ("fill", t("console.needs.unread_fill")))
    return ", ".join(words for key, words in said if key in failed)


def collect(library: Any, state: Mapping[str, Any]) -> list[Need]:
    """Every row that has something to say, in cost order: cannot be played, then
    missing, then ready for you, then tidy-up. A check the library has turned off does
    not draw."""
    # Not at import: `sections` draws these rows, and the grid module draws the metadata
    # line from `sections`.
    from console import games, sections

    hidden = library.hidden_checks()
    found = sections.findings(library)
    names = {key: (name, why) for key, name, why, _ in sections.CHECKS}
    watched = library.watched()
    collected = library.kept_kinds()["media"]
    rows: list[Need | None] = []

    broken = tuple(sorted(str(row.get("id") or "") for row in library.table_rows()
                          if row.get("rom") and row.get("rom_installed") is False))
    if broken:
        rows.append(Need("rom_missing", *names["rom_missing"], DANGER, verbs.CANNOT_PLAY,
                         Opens("tables", games.ROM_MISSING),
                         broken, _UNIT_TABLES))

    if any(one.where == feature_checks.WHERE_LAUNCHERS for one in state.get("trouble") or ()):
        rows.append(Need("launchers", t("console.needs.launchers"),
                         t("console.needs.launchers.tip"), DANGER, verbs.CANNOT_PLAY,
                         Opens("launchers")))

    unreadable = tuple(sorted(str(row.get("folder") or "")
                              for row in library.metadata_state().get("unreadable") or ()))
    if unreadable:
        rows.append(Need("unreadable", t("console.needs.unreadable"),
                         t("console.needs.unreadable.tip"), DANGER, verbs.CANNOT_PLAY,
                         Opens(then=METADATA), unreadable, _UNIT_FOLDERS))

    rows.append(_games_without("unmatched", found, label=names["unmatched"][0],
                               tip=names["unmatched"][1], tone=WARM, icon=verbs.NO_MATCH,
                               opens=Opens("games", games.UNMATCHED)))
    for key, kind in sections.FILLS.items():
        if kind in collected:
            rows.append(_games_without(
                key, found, label=names[key][0], tip=names[key][1], tone=WARM,
                icon=verbs.NO_ART,
                opens=Opens("games", _blank(f"media_{kind}")),
                fix=Fix(GET_MEDIA, t("console.media_fill.get_media"),
                        t("console.media_fill.get_media.help"), verbs.FETCH, kind)))
    if collected:
        everything: dict[str, Any] = {}
        for kind in sorted(collected):
            everything.update(_blank(f"media_{kind}"))
        rows.append(_games_without("no_media", found, label=names["no_media"][0],
                                   tip=names["no_media"][1], tone=WARM,
                                   icon=verbs.NO_MEDIA, opens=Opens("games", everything)))

    fill = watched.get("fill")
    if fill and jobs_list.outcome_of(fill) in jobs_list.TO_LOOK_AT:
        rows.append(Need("fill_errors", t("console.needs.fill_errors"),
                         t("console.needs.fill_errors.tip"), WARM, verbs.HAD_ERRORS,
                         Opens("jobs", keys={"jobs_outcome": jobs_list.outcome_of(fill),
                                             "jobs_find": jobs_list.named(fill)})))

    update = watched.get("update") or {}
    if update.get("update_available") and not update.get("error"):
        latest = str(update.get("latest_version") or "")
        fix = Fix(UPDATE, t("console.devices.update_3",
                            latest=latest or t("console.devices.newer_build")),
                  t("console.devices.update_3.help"), verbs.UPDATE) \
            if update.get("update_supported") else None
        rows.append(Need(UPDATE, t("console.needs.update", version=latest) if latest
                         else t("console.needs.update_unnamed"),
                         t("console.needs.update.tip"), ACCENT, verbs.UPDATE,
                         Opens("about"), fix=fix))

    newer = tuple(sorted(str(row.get("id") or "") for row in library.table_rows()
                         if row.get("update_available")))
    if newer:
        rows.append(Need("newer", t("console.games.filter_newer"),
                         t("console.needs.newer.tip"), ACCENT, verbs.NEWER_RELEASE,
                         Opens("tables", games.NEWER_ON_VPS),
                         newer, _UNIT_TABLES))

    waiting = tuple(sorted(one for one in watched.get("recordings") or () if one))
    if waiting:
        rows.append(Need("recordings", t("console.needs.recordings"),
                         t("console.needs.recordings.tip"), ACCENT, verbs.REVIEW,
                         Opens(then=REVIEW), waiting, _UNIT_RECORDINGS))

    rows.append(_games_without("no_year", found, label=names["no_year"][0],
                               tip=names["no_year"][1], tone=MUTED, icon=verbs.NO_YEAR,
                               opens=Opens("games", {"year": {"filterType": "text",
                                                             "type": "blank"}})))
    if unread := _unread(watched.get("unread") or ()):
        rows.append(Need("unread", t("console.needs.unread"),
                         t("console.needs.unread.tip", what=unread), MUTED, verbs.HAD_ERRORS,
                         Opens(then=RETRY)))
    return [one for one in rows if one is not None and one.key not in hidden]
