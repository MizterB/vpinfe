"""What a source's `User` folder holds for the tables whose scripts saved it.

Text files a script wrote, and `VPReg.stg`, where every table that saved a value shares
one file. Both are matched to a table by what its script mentions, which core reads when
the table lands.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import finding

SETS_FILE = "VPReg.stg"
INI_FILE = "VPReg.ini"


@dataclass(frozen=True)
class Saved:
    """The text files by the name a script would give them, and the sets of the `.stg`."""

    files: dict[str, tuple[Path, ...]] = field(default_factory=dict)
    stg: str = ""
    sets: frozenset[str] = frozenset()

    @property
    def names(self) -> tuple[str, ...]:
        """What to look for in a script: each file's name without its extension, and each
        set."""
        stems = {one.stem for found in self.files.values() for one in found}
        return tuple(sorted({*stems, *self.sets}, key=str.casefold))

    def files_for(self, named: tuple[str, ...]) -> list[Path]:
        return list(dict.fromkeys(
            one for name in named for one in self.files.get(name.casefold(), ())))

    def sets_for(self, named: tuple[str, ...]) -> list[str]:
        return [name for name in named if name in self.sets]


def read(ctx: Any, folder: str) -> Saved:
    """The saved files in `folder`. Nothing for a folder that is not given or not there."""
    if not folder:
        return Saved()
    files: dict[str, list[Path]] = {}
    try:
        listed = finding.files(folder)
    except OSError as exc:
        ctx.logger.warning("The saved files in %s could not be listed: %s", folder, exc)
        listed = []
    for one in listed:
        if one.name.startswith(".") or one.stem.casefold() == "vpreg":
            continue
        files.setdefault(one.stem.casefold(), []).append(one)
    stg = finding.child(folder, SETS_FILE)
    sets: frozenset[str] = frozenset()
    if stg is not None and stg.is_file():
        try:
            sets = frozenset(ctx.games.saved_sets(stg))
        except Exception as exc:
            ctx.logger.warning("The saved values in %s could not be read: %s", stg, exc)
    return Saved({key: tuple(found) for key, found in files.items()},
                 str(stg) if sets else "", sets)
