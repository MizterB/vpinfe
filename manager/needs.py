"""What needs you on Overview, as rows ordered by what each one costs.

Pure: this decides which rows there are, what each counts and where a click on it lands.
`sections.overview` draws them. A row draws only while its count is above zero, and keeps
its own unit - games, tables, recordings - so that nothing is added together and a click
can open the grid on exactly what the row counted.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from common import approvals, feature_checks
from common.i18n import t
from manager import jobs_list, verbs

# The tone a row is drawn in, which says how much it costs to leave alone.
DANGER, WARM, ACCENT, MUTED = "danger", "warm", "accent", "muted"

# What a click does that is not opening a grid on a filter.
REVIEW, RETRY = "review", "retry"

# The Settings page saying whether the library's metadata files read and are current.
METADATA_PAGE = "library.metadata"

# The rows an extension raises are keyed `ext:<extension>:<kind>`; `away:<extension>` in the
# reads that failed says that extension's needs could not be read, `away:*` that none could.
EXTENSION, AWAY = "ext:", "away:"

# The rows for a theme or an extension waiting to be accepted, keyed `unaccepted:theme:<key>`
# and `unaccepted:ext:<name>`. They are about this install and cannot be set aside:
# whatever is stopped stays so until the Owner accepts it or removes it.
UNACCEPTED = "unaccepted:"
AWAY_ALL = AWAY + "*"

# A program's ask to make one change, keyed `asked:<id>`. It lapses on its own and is
# answered, never set aside.
ASKED = "asked:"

# A fix VPinFE can do itself, the first entry of the row's menu.
GET_MEDIA, UPDATE, FETCH_FIXES = "get_media", "update", "fetch_fixes"

_UNIT_GAMES = "manager.games.games"
_UNIT_TABLES = "manager.games.tables"
_UNIT_FOLDERS = "manager.needs.folders"
_UNIT_RECORDINGS = "manager.needs.recordings_count"


@dataclass(frozen=True)
class Opens:
    """Where a click lands: a rail view, the filter its grid arrives on, the state keys
    that view reads on arrival, and what to do instead where it is not a view."""

    view: str = ""
    arriving: dict[str, Any] | None = None
    keys: Mapping[str, Any] = field(default_factory=dict)
    then: str = ""
    # One of an extension's dialogs, opened over nothing.
    extension: str = ""
    action: str = ""


@dataclass(frozen=True)
class Fix:
    key: str
    label: str
    tip: str
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
    # What a dismissal of a row with no ids of its own is recorded against: the version
    # that is out, the job that had errors.
    token: tuple[str, ...] = ()
    # The ids that joined since the row was dismissed. Only set by `arrange`.
    new: tuple[str, ...] = ()
    # An extension's row: its name, drawn where a count would be, and the count it gave,
    # which is in its label and has no ids of its own to open a grid on.
    source: str = ""
    total: int = 0
    # An ask's id, and the exact request it would let through, in one line.
    answer: str = ""
    detail: str = ""

    @property
    def count(self) -> int:
        return len(self.ids) or self.total

    @property
    def covered(self) -> tuple[str, ...]:
        """What a dismissal of this row is recorded against."""
        return self.ids or self.token

    @property
    def by_kind(self) -> bool:
        """An extension's row that named no ids and no token, so a dismissal is kept against
        its kind and the count changing does not bring it back."""
        return is_extension(self.key) and self.token == (self.key.rpartition(":")[2],)

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


def script_fixes_opens(ids: tuple[str, ...]) -> Opens:
    """The Tables grid on the tables a script fix is published for."""
    from manager import games

    return Opens("tables", keys={games.FIXES_KEY: ids})


def no_tables_opens() -> Opens:
    """Games on the No Tables view."""
    from manager import games

    return Opens("games", keys={games.ARRIVE_VIEW: games.NO_TABLES_VIEW})


def blank(name: str) -> dict[str, Any]:
    return {name: {"values": [""]}}


def _unread(failed: Any) -> str:
    """The reads that failed, in the words a person would use for what they were after."""
    said = (("update", t("manager.needs.unread_update")),
            ("recordings", t("manager.needs.unread_recordings")),
            ("fill", t("manager.needs.unread_fill")),
            ("extensions", t("manager.needs.unread_extensions")),
            ("unaccepted", t("manager.needs.unread_unaccepted")))
    return ", ".join(words for key, words in said if key in failed)


def extension_rows(raised: Any) -> list[Need]:
    """The rows running extensions raise, after core's own, in the order they answered."""
    from manager import community

    out = []
    for one in raised:
        if str(one.get("opens") or "") == "action":
            opens = Opens(extension=str(one["extension"]), action=str(one["to"]))
        else:
            make = community.page_view_key if one.get("opens") == "page" \
                else community.view_key
            opens = Opens(make(str(one["extension"]), str(one["to"])))
        out.append(Need(str(one["key"]), str(one["label"]), str(one.get("says") or ""),
                        str(one.get("tone") or WARM), community.ICON, opens,
                        token=tuple(str(each) for each in one.get("covered") or ()),
                        source=str(one.get("display_name") or ""),
                        total=int(one.get("count") or 0)))
    return out


def unaccepted_rows(waiting: Mapping[str, Any]) -> list[Need]:
    """A row for each theme and extension that is stopped for want of being accepted."""
    from manager import ext_page

    out = []
    for theme in waiting.get("themes") or ():
        out.append(Need(f"{UNACCEPTED}theme:{theme['key']}",
                        t("manager.needs.unaccepted", name=theme.get("name") or theme["key"]),
                        t("manager.needs.unaccepted.tip"), WARM, verbs.LOCKED,
                        Opens("themes")))
    for extension in waiting.get("extensions") or ():
        name = str(extension["name"])
        out.append(Need(f"{UNACCEPTED}ext:{name}",
                        t("manager.needs.unaccepted",
                          name=extension.get("display_name") or name),
                        t("manager.needs.unaccepted.tip"), WARM, verbs.LOCKED,
                        Opens("settings", keys={"settings_page": ext_page.key(name)})))
    return out


def asked_rows(waiting: Any) -> list[Need]:
    """A row for each change a program has asked to make, waiting on the Owner."""
    out = []
    for one in waiting:
        body = one.get("body")
        change = " ".join(part for part in (one["method"], one["path"],
                                            "" if body is None else approvals.canonical(body))
                          if part)
        minutes = max(1, -(-int(one.get("expires_in") or 0) // 60))
        out.append(Need(f"{ASKED}{one['id']}", t("manager.needs.asked", program=one["token"]),
                        t("manager.needs.asked.tip", change=change, count=minutes),
                        WARM, verbs.LOCKED, Opens(), answer=str(one["id"]), detail=change))
    return out


def collect(library: Any, state: Mapping[str, Any]) -> list[Need]:
    """Every row that has something to say, in cost order: cannot be played, then
    missing, then ready for you, then tidy-up. A check the library has turned off does
    not draw."""
    # Not at import: `sections` draws these rows, and the grid module draws the metadata
    # line from `sections`.
    from manager import games, sections

    hidden = library.stopped()
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
        rows.append(Need("launchers", t("manager.needs.launchers"),
                         t("manager.needs.launchers.tip"), DANGER, verbs.CANNOT_PLAY,
                         Opens("launchers"), token=("launchers",)))

    unreadable = tuple(sorted(str(row.get("folder") or "")
                              for row in library.metadata_state().get("unreadable") or ()))
    if unreadable:
        rows.append(Need("unreadable", t("manager.needs.unreadable"),
                         t("manager.needs.unreadable.tip"), DANGER, verbs.CANNOT_PLAY,
                         Opens("settings", keys={"settings_page": METADATA_PAGE}),
                         unreadable, _UNIT_FOLDERS))

    rows.append(_games_without("unmatched", found, label=names["unmatched"][0],
                               tip=names["unmatched"][1], tone=WARM, icon=verbs.NO_MATCH,
                               opens=Opens("games", games.UNMATCHED)))
    rows.append(_games_without("no_tables", found, label=names["no_tables"][0],
                               tip=names["no_tables"][1], tone=WARM, icon=verbs.NO_TABLE,
                               opens=no_tables_opens()))
    for key, kind in sections.FILLS.items():
        if kind in collected:
            rows.append(_games_without(
                key, found, label=names[key][0], tip=names[key][1], tone=WARM,
                icon=verbs.NO_ART,
                opens=Opens("games", blank(f"media_{kind}")),
                fix=Fix(GET_MEDIA, t("manager.media_fill.get_media"),
                        t("manager.media_fill.get_media.help"), kind)))
    if collected:
        everything: dict[str, Any] = {}
        for kind in sorted(collected):
            everything.update(blank(f"media_{kind}"))
        rows.append(_games_without("no_media", found, label=names["no_media"][0],
                                   tip=names["no_media"][1], tone=WARM,
                                   icon=verbs.NO_MEDIA, opens=Opens("games", everything)))

    fill = watched.get("fill")
    if fill and jobs_list.outcome_of(fill) in jobs_list.TO_LOOK_AT:
        rows.append(Need("fill_errors", t("manager.needs.fill_errors"),
                         t("manager.needs.fill_errors.tip"), WARM, verbs.HAD_ERRORS,
                         Opens("jobs", keys={"jobs_outcome": jobs_list.outcome_of(fill),
                                             "jobs_find": jobs_list.named(fill)}),
                         token=(str(fill.get("id") or "fill"),)))

    update = watched.get("update") or {}
    if update.get("update_available") and not update.get("error"):
        latest = str(update.get("latest_version") or "")
        fix = Fix(UPDATE, t("manager.devices.update_3",
                            latest=latest or t("manager.devices.newer_build")),
                  t("manager.devices.update_3.help")) \
            if update.get("update_supported") else None
        rows.append(Need(UPDATE, t("manager.needs.update", version=latest) if latest
                         else t("manager.needs.update_unnamed"),
                         t("manager.needs.update.tip"), ACCENT, verbs.UPDATE,
                         Opens("about"), fix=fix, token=(latest or UPDATE,)))

    newer = tuple(sorted(str(row.get("id") or "") for row in library.table_rows()
                         if row.get("update_available")))
    if newer:
        rows.append(Need("newer", t("manager.games.filter_newer"),
                         t("manager.needs.newer.tip"), ACCENT, verbs.NEWER_RELEASE,
                         Opens("tables", games.NEWER_ON_VPS),
                         newer, _UNIT_TABLES))

    if mended := library.script_fix_tables():
        rows.append(Need("script_fixes", t("manager.sections.script_fixes"),
                         t("manager.needs.script_fixes.tip"), ACCENT, verbs.FETCH,
                         script_fixes_opens(mended),
                         mended, _UNIT_TABLES,
                         Fix(FETCH_FIXES, t("word.fetch"),
                             t("manager.needs.script_fixes.fetch.help"))))

    waiting = tuple(sorted(one for one in watched.get("recordings") or () if one))
    if waiting:
        rows.append(Need("recordings", t("manager.needs.recordings"),
                         t("manager.needs.recordings.tip"), ACCENT, verbs.REVIEW,
                         Opens(then=REVIEW), waiting, _UNIT_RECORDINGS))

    rows.append(_games_without("no_year", found, label=names["no_year"][0],
                               tip=names["no_year"][1], tone=MUTED, icon=verbs.NO_YEAR,
                               opens=Opens("games", {"year": {"filterType": "number",
                                                             "type": "blank"}})))
    rows += asked_rows(watched.get("asked") or ())
    rows += unaccepted_rows(watched.get("unaccepted") or {})
    rows += extension_rows(watched.get("extension_needs") or ())
    if unread := _unread(watched.get("unread") or ()):
        rows.append(Need("unread", t("manager.needs.unread"),
                         t("manager.needs.unread.tip", what=unread), MUTED, verbs.HAD_ERRORS,
                         Opens(then=RETRY)))
    return [one for one in rows
            if one is not None and (one.key not in hidden or is_extension(one.key))]


# Every row that can be set aside, in cost order. `unread` is not one: it is the page saying
# it could not look, and setting that aside would hide the one thing it must say.
ORDER = ("rom_missing", "launchers", "unreadable", "unmatched", "no_tables", "no_playfield",
         "no_backglass", "no_media", "fill_errors", "update", "newer", "script_fixes", "recordings",
         "no_year")

# The rows about this install rather than the library. Their stop is this install's alone;
# a library row's is the library's, as the Audit page already keeps it.
DEVICE_ROWS = ("launchers", "fill_errors", "update", "recordings")

# What a row's read cannot say while that read failed, by row.
_READ_BY = {"update": "update", "recordings": "recordings", "fill_errors": "fill"}

_ICONS = {"rom_missing": verbs.CANNOT_PLAY, "launchers": verbs.CANNOT_PLAY,
          "unreadable": verbs.CANNOT_PLAY, "unmatched": verbs.NO_MATCH,
          "no_tables": verbs.NO_TABLE,
          "no_playfield": verbs.NO_ART, "no_backglass": verbs.NO_ART,
          "no_media": verbs.NO_MEDIA, "fill_errors": verbs.HAD_ERRORS,
          "update": verbs.UPDATE, "newer": verbs.NEWER_RELEASE,
          "script_fixes": verbs.FETCH, "recordings": verbs.REVIEW,
          "no_year": verbs.NO_YEAR}


def is_device(key: str) -> bool:
    """An extension is installed on this install, so a stop of its row is this install's."""
    return key in DEVICE_ROWS or is_extension(key)


def is_extension(key: str) -> bool:
    return key.startswith(EXTENSION)


def can_set_aside(key: str) -> bool:
    return key in ORDER or is_extension(key)


def blind(library: Any) -> set[str]:
    """The rows that are absent because nothing could be counted, not because nothing is
    wrong: no VPX to audit roms against, no catalog to compare versions with, a kind of
    media the library does not collect."""
    from manager import sections

    rows = library.table_rows()
    out: set[str] = set()
    if all(row.get("rom_installed") is None for row in rows):
        out.add("rom_missing")
    if all(row.get("update_available") is None for row in rows):
        out.add("newer")
    patches = library.script_patches()
    if not patches or patches.get("reachable") is False:
        out.add("script_fixes")
    collected = library.kept_kinds()["media"]
    out |= {key for key, kind in sections.FILLS.items() if kind not in collected}
    if not collected:
        out.add("no_media")
    return out


def name_of(key: str) -> str:
    """What a row is called while it is not drawn as one: in Set Aside, on the Audit page
    and beside its switch. The row itself may carry more, like the version."""
    from manager import sections

    checks = {one[0]: one[1] for one in sections.CHECKS}
    if key in checks:
        return checks[key]
    return {"launchers": t("manager.needs.launchers"),
            "unreadable": t("manager.needs.unreadable"),
            "fill_errors": t("manager.needs.fill_errors"),
            "update": t("manager.needs.update_unnamed"),
            "newer": t("manager.games.filter_newer"),
            "script_fixes": t("manager.sections.script_fixes"),
            "recordings": t("manager.needs.recordings")}[key]


def comes_back(key: str, need: Need | None = None) -> str:
    """When a dismissed row is drawn again, in the words the menu and the chip both use.
    An extension's row that gave no ids or token is only drawn again once the extension has
    stopped asking, so it is the `need` that says which wording is true."""
    if is_extension(key):
        if need is not None and need.by_kind:
            return t("manager.needs.back.extension_kind")
        return t("manager.needs.back.extension")
    return {"rom_missing": t("manager.needs.back.rom_missing"),
            "launchers": t("manager.needs.back.launchers"),
            "unreadable": t("manager.needs.back.unreadable"),
            "unmatched": t("manager.needs.back.unmatched"),
            "no_tables": t("manager.needs.back.no_tables"),
            "no_playfield": t("manager.needs.back.no_playfield"),
            "no_backglass": t("manager.needs.back.no_backglass"),
            "no_media": t("manager.needs.back.no_media"),
            "fill_errors": t("manager.needs.back.fill_errors"),
            "update": t("manager.needs.back.update"),
            "newer": t("manager.needs.back.newer"),
            "script_fixes": t("manager.needs.back.script_fixes"),
            "recordings": t("manager.needs.back.recordings"),
            "no_year": t("manager.needs.back.no_year")}[key]


@dataclass(frozen=True)
class Aside:
    """A row that is not drawn among the rest: dismissed over what it counted, or not
    being checked at all."""

    key: str
    label: str
    icon: str
    chip: str
    tip: str
    # False where it was dismissed, which Show Again undoes; True where its check is off,
    # which Check Again turns back on.
    stopped: bool = False


@dataclass(frozen=True)
class Arranged:
    rows: list[Need]
    aside: list[Aside]
    # The dismissals as they stand once what no row counts any more has left them.
    record: dict[str, list[str]]


def _dismissed_aside(need: Need) -> Aside:
    skipped = need.key == UPDATE
    return Aside(need.key, need.label, need.icon,
                 t("manager.needs.chip_skipped") if skipped else t("manager.needs.chip_dismissed"),
                 comes_back(need.key, need))


def _stopped_aside(key: str) -> Aside:
    return Aside(key, name_of(key), _ICONS[key], t("manager.needs.chip_stopped"),
                 t("manager.needs.chip_stopped.tip"), stopped=True)


def _extension_unread(key: str, unread: Any) -> bool:
    """Whether the extension a row belongs to could not say what it needs."""
    if not is_extension(key):
        return False
    name = key[len(EXTENSION):].partition(":")[0]
    return AWAY + name in unread or AWAY_ALL in unread


def arrange(rows: list[Need], record: Mapping[str, list[str]], stopped: set[str],
            unread: Any = (), blind: Collection[str] = ()) -> Arranged:
    """Which rows draw, which are set aside, and what is left of the dismissals.

    A row stays away while every id it counts is in its record. When one joins, the row
    returns with its true total and the new ones marked - unless none of the old ones is
    left, in which case it is a different finding and carries no mark. An id the row no
    longer counts leaves the record, except where the row is absent because its check is
    off, its read failed or it was `blind`: there nothing says the id is gone.
    """
    shown: list[Need] = []
    aside: list[Aside] = []
    kept: dict[str, list[str]] = {}
    for need in rows:
        covered = need.covered
        held = set(record.get(need.key, ()))
        if is_extension(need.key) and need.key in stopped:
            # Its dismissal is kept: Check Again brings the row back as it was left.
            if held:
                kept[need.key] = list(record[need.key])
            aside.append(Aside(need.key, need.label, need.icon, t("manager.needs.chip_stopped"),
                               t("manager.needs.chip_stopped.tip"), stopped=True))
            continue
        still = [one for one in covered if one in held]
        if still:
            kept[need.key] = still
        new = tuple(one for one in covered if one not in held)
        if not held or not covered:
            shown.append(need)
        elif not new:
            aside.append(_dismissed_aside(need))
        else:
            shown.append(replace(need, new=new) if still else need)
    present = {one.key for one in rows}
    for key, ids in record.items():
        if key not in present and (key in stopped or key in blind
                                     or _READ_BY.get(key) in unread
                                     or _extension_unread(key, unread)):
            kept[key] = list(ids)
    aside += [_stopped_aside(key) for key in ORDER if key in stopped]
    return Arranged(shown, aside, kept)


LIBRARY, DEVICE = "library", "device"

_COST = {DANGER: 0, WARM: 1, ACCENT: 2, MUTED: 3}


@dataclass(frozen=True)
class Group:
    """The rows one owner raised. `owner` is "" for the row that says the page could not
    look, which belongs to none of them and has no heading."""

    owner: str
    label: str
    rows: list[Need]


def owner_of(need: Need) -> str:
    """Who raised a row: the library, this device, or one extension."""
    if is_extension(need.key):
        return EXTENSION + need.key[len(EXTENSION):].partition(":")[0]
    if need.key == "unread":
        return ""
    return DEVICE if need.key in DEVICE_ROWS or need.key.startswith((UNACCEPTED, ASKED)) \
        else LIBRARY


def _group_label(owner: str, rows: list[Need]) -> str:
    if owner == LIBRARY:
        return t("manager.needs.group.library")
    if owner == DEVICE:
        return t("manager.needs.group.device")
    if not owner:
        return ""
    return next((one.source for one in rows if one.source), owner[len(EXTENSION):])


def grouped(rows: list[Need]) -> list[Group]:
    """Rows by owner, costliest first inside a group and, on a tie, in the order given. A
    group goes by its costliest row, so one holding a row that cannot play comes before
    one holding only tidy-up; groups that tie keep the library, then this device, then the
    extensions by name. The row that says the page could not look is always last."""
    by_owner: dict[str, list[Need]] = {}
    for need in rows:
        by_owner.setdefault(owner_of(need), []).append(need)
    groups = [Group(owner, _group_label(owner, members),
                    sorted(members, key=lambda one: _COST[one.tone]))
              for owner, members in by_owner.items()]

    def order(group: Group) -> tuple[bool, int, int, str]:
        place = 0 if group.owner == LIBRARY else 1 if group.owner == DEVICE else 2
        return (not group.owner, min(_COST[one.tone] for one in group.rows), place,
                group.label.casefold())

    return sorted(groups, key=order)
