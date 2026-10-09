"""What a source keeps for its games beyond the tables and their pictures, counted.

The ROMs and more page offers one switch for each of these that the source has any of, and
the count says what it would bring. Counted the way the run brings them, game by game.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from . import adopt, finding
from . import plan as plan_for
from .saved import Saved
from .source import SourceLibrary

# In the order the page lists them. Each is switched by `use_<key>`.
THINGS = ("roms", "scores", "altdata", "music", "pups")

# The source folder each one is read from; high scores have none of their own.
FOLDER = {"roms": "roms", "altdata": "altdata", "music": "music", "pups": "pups"}

_ALT = ("altsound", "altcolor", "serum")


def switch(key: str) -> str:
    return f"use_{key}"


def counted(library: SourceLibrary, made: plan_for.Plan, systems: Sequence[str],
            roms: dict[str, str], named: dict[str, tuple[str, ...]], kept: Saved,
            real: Callable[[str], str], with_roms: bool = True) -> dict[str, int]:
    """How many of the games this run acts on each thing comes with. A key is there only
    where the source has the folder, or for high scores where it has either of theirs.

    `made` is planned with every folder switched on, so a thing the person switched off
    is still counted and can be switched back. `with_roms` is whether the ROMs themselves
    are coming: the high scores and game settings read off a ROM's files go with them.
    """
    folder = {key: (there.path if (there := made.source(one)) else "")
              for key, one in FOLDER.items()}
    score_dirs = plan_for.score_folders(folder["roms"]) if folder["roms"] else {}
    found = dict.fromkeys(THINGS, 0)
    for game, match in plan_for.pairs(library, made, list(systems)):
        asked = roms.get(game.table_file, "") if game.table_file else ""
        rom = (real(asked) if asked else "") or asked
        file = finding.rom_file(folder["roms"], rom) if rom and folder["roms"] else None
        found["roms"] += int(file is not None)
        names = (named or {}).get(game.table_file, ()) if game.table_file else ()
        on_the_rom = (with_roms and file is not None
                      and any(finding.rom_file(here, rom) for here in score_dirs.values()))
        found["scores"] += int(on_the_rom or bool(kept.files_for(names))
                               or bool(kept.sets_for(names)))
        if rom and folder["altdata"]:
            found["altdata"] += int(any(
                (under := finding.child(folder["altdata"], one)) is not None
                and finding.child(under, rom) is not None for one in _ALT))
        called = adopt.names_of(game, match.folder, rom, asked)
        for key in ("music", "pups"):
            if folder[key]:
                found[key] += int(any(finding.child(folder[key], one) is not None
                                      for one in called))
    return found
