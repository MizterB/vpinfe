"""What an import would do, before it does any of it.

Two questions this answers, and they are the same question asked twice: where does each
kind of thing come from, and what is already here.

**Every source is an option with a derived default.** A reader works out where the tables
and the artwork are; the user can say otherwise, and can leave one empty. Empty means that
kind is not imported - stated rather than implied, because "no ROMs came across" should be
something somebody chose and can see they chose.

**And an import can be run more than once.** A first pass fails partway, or somebody
imports the games now and the ROMs when the old machine is back on the network. So this
says what is new and what is already here before anything is written, and an existing game
is left alone unless the user says to fill in what it is missing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import mapping

# The kinds of thing an import can bring, in the order they are asked about. `key` is
# what the wizard calls the field; `label` is what a person reads.
SOURCES = (
    ("tables", "Game files", "The .vpx or .fpt files themselves."),
    ("media", "Artwork", "Playfield, backglass, wheel and the rest."),
)

# Derived, and deliberately not offered yet: for both of these the reading works and
# there is nowhere settled to put what it reads. Offering a field that carries nothing
# would be a promise the code cannot keep, which is worse than not asking, and the
# derivations stay because they are right and are what the options will use.
#
# ROMs need somewhere to place an asset, and the destinations live inside the upload
# planner rather than in anything an extension is handed. Registry settings need a
# decision that is not ours: VPinMAME's own program options folder is the Windows
# answer, and on standalone PinMAME is a plugin whose settings belong in the layered
# app/folder/table ini the launcher already reads. A per-game file of our own invention
# would be read by nothing.
NOT_YET = ("roms", "registry")

# What a second run does about a game it has already made. The default leaves it alone:
# an import that quietly rewrites what somebody has since curated is the worse mistake.
ON_EXISTING = (
    ("skip", "Leave them alone"),
    ("fill", "Add anything they are missing"),
)
DEFAULT_ON_EXISTING = "skip"


@dataclass
class Source:
    """Where one kind of thing comes from, and how we came to think so."""

    key: str
    label: str
    help: str
    path: str = ""
    derived: bool = False

    @property
    def active(self) -> bool:
        return bool(self.path)


@dataclass
class Match:
    """One game the source holds, against what the library already has."""

    key: str
    folder: str
    game_id: str = ""
    how: str = ""
    # Counted here because here is where the game is in hand. Looking them up later by
    # key cannot work: a real library held two entries with byte-identical keys, and a
    # dict keyed on them silently counts one.
    tables: int = 0
    media: int = 0
    companions: int = 0

    @property
    def existing(self) -> bool:
        return bool(self.game_id)


@dataclass
class Plan:
    sources: list[Source] = field(default_factory=list)
    matches: list[Match] = field(default_factory=list)
    on_existing: str = DEFAULT_ON_EXISTING

    @property
    def new(self) -> list[Match]:
        return [one for one in self.matches if not one.existing]

    @property
    def already(self) -> list[Match]:
        return [one for one in self.matches if one.existing]

    def source(self, key: str) -> Source | None:
        return next((one for one in self.sources if one.key == key), None)


# What the report counts, in the order it reads. The same keys come back from the run,
# so expected and actual are one shape and a difference is a subtraction rather than a
# comparison somebody has to make by eye.
COUNTS = (
    ("games", "Games"),
    ("tables", "Game files"),
    ("media", "Artwork files"),
    ("companions", "Backglasses and settings"),
)


def expected(plan: Plan) -> dict:
    """What this import should produce, counted before it runs.

    Counted the way the run counts, not the way the source reads, because those differ
    in two places and a report that ignores either reads as a shortfall for working
    correctly. Several builds of one machine become one game, and only the first of them
    brings artwork - the rest are the same table photographed twice.

    A source that is not set contributes nothing and says zero rather than being left
    out: "no artwork" is a number somebody chose, and an absent row reads as an oversight.
    """
    wanted = _wanted(plan)
    has = {source.key: bool(source.active) for source in plan.sources}

    folders, tables, media, companions = set(), 0, 0, 0
    for one in wanted:
        first = one.folder.lower() not in folders
        folders.add(one.folder.lower())
        if has.get("tables"):
            tables += one.tables
            # They ride with the table, so they arrive only where it does.
            companions += one.companions
        # Artwork rides with the game, and the game is made once.
        if has.get("media") and first:
            media += one.media

    return {"games": len(folders), "tables": tables, "media": media,
            "companions": companions, "roms": 0}


def _wanted(plan: Plan) -> list[Match]:
    """The games this run will act on, which is not every game the source holds."""
    return plan.matches if plan.on_existing == "fill" else plan.new


def against(expected_counts: dict, actual: dict) -> list[dict]:
    """Expected beside actual, with the difference, for the report.

    Both are shown even where they agree: a row that only appears when something went
    wrong makes a clean import look like a report with things missing from it.
    """
    rows = []
    for key, label in COUNTS:
        want = int(expected_counts.get(key, 0) or 0)
        got = int(actual.get(key, 0) or 0)
        rows.append({"key": key, "label": label, "expected": want, "actual": got,
                     "short": want - got})
    return rows


def derive_sources(library, chosen: dict | None = None) -> list[Source]:
    """Where each kind of thing appears to live, and whatever the user said instead.

    Derived first so the common case is one press. A value the user typed always wins,
    including an empty one - clearing a source is how somebody says "not that".
    """
    chosen = chosen or {}
    tables = next((one.tables_dir for one in library.systems if one.tables_dir), "")
    media = ""
    for system in library.systems:
        for game in system.games:
            if game.media:
                media = str(Path(game.media[0].path).parent.parent)
                break
        if media:
            break
    # Nothing derives a registry export: a share does not carry one unless somebody
    # exported it on purpose, so this stays empty until it is pointed at.
    guessed = {"tables": tables, "media": media,
               "roms": next((one.working_path for one in library.systems
                             if one.working_path), ""),
               "registry": ""}

    found = []
    for key, label, help_text in SOURCES:
        said = chosen.get(key)
        path = str(said if said is not None else guessed.get(key, "") or "").strip()
        found.append(Source(key=key, label=label, help=help_text, path=path,
                            derived=said is None and bool(path)))
    return found


def match_existing(library, existing: list[dict],
                   systems: list[str] | None = None,
                   folder_name_for=None, source_id: str = "",
                   kinds: tuple[str, ...] = (), companions_of=None) -> list[Match]:
    """Which of the source's games the library already holds.

    By the folder this import would create first, because that is what a previous run of
    this import made. Then by catalog id, which catches a game somebody has since renamed
    - a rename should not turn one game into two.
    """
    by_folder = {str(one.get("folder_name") or "").lower(): one for one in existing}
    by_vps = {str(one.get("vps_id") or "").lower(): one
              for one in existing if one.get("vps_id")}

    found = []
    for game in _games(library, systems):
        folder = mapping.folder_name(game)
        if folder_name_for:
            folder = folder_name_for(folder)
        held = by_folder.get(folder.lower())
        how = "folder" if held else ""
        if held is None and game.vps_id:
            held = by_vps.get(game.vps_id.lower())
            how = "catalog id" if held else ""
        found.append(Match(key=game.key, folder=folder,
                           game_id=str(held.get("game_id") or "") if held else "",
                           how=how,
                           tables=1 if game.table_file else 0,
                           media=len(mapping.media_for(source_id, game, kinds)),
                           companions=(len(companions_of(game.table_file))
                                       if companions_of and game.table_file else 0)))
    return found


def _games(library, systems: list[str] | None):
    """The games in the systems being brought across, which is not always all of them.

    A system somebody deselected has to drop out here rather than at the run, or what
    the summary counts and what the import does are two different libraries.
    """
    wanted = set(systems or [])
    return [game for system in library.systems
            if not wanted or system.name in wanted
            for game in system.games]


def build(library, existing: list[dict], chosen: dict | None = None,
          on_existing: str = DEFAULT_ON_EXISTING,
          systems: list[str] | None = None, folder_name_for=None,
          source_id: str = "", kinds: tuple[str, ...] = (),
          companions_of=None) -> Plan:
    return Plan(sources=derive_sources(library, chosen),
                matches=match_existing(library, existing, systems, folder_name_for,
                                       source_id, kinds, companions_of),
                on_existing=on_existing if on_existing in dict(ON_EXISTING)
                else DEFAULT_ON_EXISTING)
