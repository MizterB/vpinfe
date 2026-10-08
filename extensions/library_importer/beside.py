"""What a table needs to start that a source keeps beside its tables, not in them.

A ROM name map, scripts the program does not ship, folders of DMD content and the
backglass server's per-table settings. The scripts and folders are matched to a table by
what its script mentions, which core reads when the table lands, and the line and the
settings by the ROM the table asks for, so a table gets what is its own and nothing
another table asked for.
"""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import finding

ALIAS_FILE = "VPMAlias.txt"
SCRIPTS_FOLDER = "Scripts"
SETTINGS_FILE = "B2STableSettings.xml"
DMD_SUFFIXES = (".ultradmd", ".flexdmd")

# The scripts VPinball ships in its `scripts` folder, taken from this release. A copy in a
# table's own folder wins over the program's, so a script on this list is never carried.
SHIPPED_RELEASE = "10.8.1"
SHIPPED = frozenset((
    '6803.vbs', 'ali.vbs', 'atari.vbs', 'atari1.vbs', 'atari1b.vbs', 'atari2.vbs',
    'b2b.vbs', 'b2bcollision.vbs', 'bally.vbs', 'ballyg.vbs', 'class1812.vbs',
    'fpvpx.vbs', 'gameplan.vbs', 'hankin.vbs', 'ltd.vbs', 'ltd3.vbs', 'ltd4a.vbs',
    'ltdpecmen.vbs', 'pdb.vbs', 'play1.vbs', 'play2.vbs', 'play4.vbs',
    'ultradmd_options.vbs', 'vpmkeys.vbs', 'wpc.vbs', 'alving.vbs', 'antar.vbs',
    'b2s.vbs', 'capcom.vbs', 'controller.vbs', 'core.vbs', 'de.vbs', 'de2.vbs',
    'gts1.vbs', 'gts3.vbs', 'idsa.vbs', 'inder.vbs', 'inder_atleta.vbs',
    'inder_centaur.vbs', 'inder_skateboard.vbs', 'ironballs.vbs', 'joctronic.vbs',
    'juegos.vbs', 'juegos2.vbs', 'jvh.vbs', 'lancelot.vbs', 'mac.vbs', 'mrgame.vbs',
    'nuova.vbs', 'p2k.vbs', 'peyper.vbs', 'playbar.vbs', 's11.vbs', 's4.vbs', 's6.vbs',
    's7.vbs', 's8_stillcrazy.vbs', 'sam.vbs', 'sega.vbs', 'sega2.vbs', 'sleic.vbs',
    'solarwars.vbs', 'spinball.vbs', 'stern.vbs', 'sys80.vbs', 'taito.vbs',
    'wpc_ph.vbs', 'zac.vbs', 'zac1.vbs', 'zac2.vbs', 'zacproto.vbs',
))

# The backglass server's entry, by its tag, and the VPX setting of the same meaning. A flag
# the server holds as 2, undecided, has no VPX value and is not written; the dual mode is
# a number in both and goes across as it is.
FLAGS = {"HideGrill": "Plugin.B2SLegacy.B2SHideGrill",
         "HideB2SDMD": "Plugin.B2SLegacy.B2SHideB2SDMD",
         "HideDMD": "Plugin.B2SLegacy.B2SHideDMD"}
MODES = {"DualMode": "Plugin.B2SLegacy.B2SDualMode"}


@dataclass
class Beside:
    """The name map, the scripts and the backglass settings, read once per run."""

    aliases: dict[str, str] = field(default_factory=dict)
    scripts: dict[str, Path] = field(default_factory=dict)
    settings: dict[str, dict[str, str]] = field(default_factory=dict)
    _dmd: dict[str, dict[str, Path]] = field(default_factory=dict)

    @property
    def names(self) -> tuple[str, ...]:
        """What to look for in a script, apart from the DMD folders, which depend on the
        table's own folder."""
        return tuple(sorted((one.name for one in self.scripts.values()), key=str.casefold))

    def real_rom(self, rom: str) -> str:
        """The ROM set PinMAME loads for the name a table asks for."""
        return self.aliases.get(str(rom or "").strip().casefold(), "")

    def dmd_in(self, folder: Path) -> dict[str, Path]:
        """The DMD content folders in `folder`, by name in any case."""
        key = str(folder)
        if key not in self._dmd:
            try:
                self._dmd[key] = {one.name.casefold(): one for one in finding.folders(folder)
                                  if one.name.casefold().endswith(DMD_SUFFIXES)}
            except OSError:
                self._dmd[key] = {}
        return self._dmd[key]

    def asked_of(self, table_file: str) -> tuple[str, ...]:
        """The names to look for in one table's script: the scripts, the DMD folders that
        sit beside this table, and the suffix of each kind of them, which is all a script
        that builds the folder's name from the table's gives."""
        here = self.dmd_in(Path(table_file).parent) if table_file else {}
        suffixes = {suffix for name in here for suffix in DMD_SUFFIXES if name.endswith(suffix)}
        beside = [one.name for one in here.values()]
        return (*self.names, *sorted(beside, key=str.casefold), *sorted(suffixes))

    def scripts_for(self, named: tuple[str, ...]) -> list[Path]:
        return [self.scripts[name.casefold()] for name in named if name.casefold() in self.scripts]

    def dmd_for(self, table_file: str, named: tuple[str, ...]) -> list[Path]:
        """The DMD folders beside the table that its script names, in full or by suffix.

        A suffix alone picks a folder only where it is the one folder of that kind beside
        the table: two of them leave nothing to say which the script means.
        """
        if not table_file:
            return []
        here = self.dmd_in(Path(table_file).parent)
        found: dict[str, Path] = {}
        for name in named:
            key = name.casefold()
            if key in here:
                found[key] = here[key]
            elif key in DMD_SUFFIXES:
                same = [one for folder, one in here.items() if folder.endswith(key)]
                if len(same) == 1:
                    found[same[0].name.casefold()] = same[0]
        return list(found.values())

    def settings_for(self, *keys: str) -> dict[str, str]:
        """The VPX settings of the first of these keys the server has an entry for."""
        for key in keys:
            found = self.settings.get(str(key or "").strip().casefold())
            if found:
                return dict(found)
        return {}


def name_map(ctx: Any, roms: str) -> Beside:
    """Only the ROM name map, for a step that needs no more of what sits beside."""
    return Beside(
        aliases=_aliases(ctx, finding.child(Path(roms).parent, ALIAS_FILE) if roms else None))


def read(ctx: Any, places: dict[str, str]) -> Beside:
    """What sits beside the folders the run reads from. Nothing for a folder not given."""
    roms, user, tables = (places.get(one, "") for one in ("roms", "user", "tables"))
    return Beside(
        aliases=name_map(ctx, roms).aliases,
        scripts=_scripts(ctx, _scripts_folder(user, tables)),
        settings=_settings(ctx, finding.child(tables, SETTINGS_FILE) if tables else None))


def roots(places: dict[str, str]) -> list[str]:
    """The folders core must be told it may read from to place what this reads."""
    found = _scripts_folder(places.get("user", ""), places.get("tables", ""))
    return [str(found)] if found is not None else []


def _scripts_folder(user: str, tables: str) -> Path | None:
    for beside in (user, tables):
        found = finding.child(Path(beside).parent, SCRIPTS_FOLDER) if beside else None
        if found is not None and found.is_dir():
            return found
    return None


def _aliases(ctx: Any, path: Path | None) -> dict[str, str]:
    if path is None or not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        ctx.logger.warning("The ROM name map %s could not be read: %s", path, exc)
        return {}
    found: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.replace(",", " ").split()
        if len(parts) >= 2 and not parts[0].startswith("#"):
            found.setdefault(parts[0].casefold(), parts[1])
    return found


def _scripts(ctx: Any, folder: Path | None) -> dict[str, Path]:
    """The scripts in `folder` that the program does not ship, by name in any case."""
    if folder is None:
        return {}
    try:
        listed = finding.files(folder)
    except OSError as exc:
        ctx.logger.warning("The scripts in %s could not be listed: %s", folder, exc)
        return {}
    return {one.name.casefold(): one for one in listed
            if one.suffix.casefold() == ".vbs" and one.name.casefold() not in SHIPPED}


def _settings(ctx: Any, path: Path | None) -> dict[str, dict[str, str]]:
    """Each entry of the backglass server's file, as VPX settings, by the key the server
    filed it under."""
    if path is None or not path.is_file():
        return {}
    try:
        root = ElementTree.parse(path).getroot()
    except (OSError, ElementTree.ParseError) as exc:
        ctx.logger.warning("The backglass settings %s could not be read: %s", path, exc)
        return {}
    found: dict[str, dict[str, str]] = {}
    for entry in root:
        values = _values_of(entry)
        if values:
            found.setdefault(entry.tag.casefold(), values)
    return found


def _values_of(entry: ElementTree.Element) -> dict[str, str]:
    values: dict[str, str] = {}
    for tag, key in {**FLAGS, **MODES}.items():
        said = (entry.findtext(tag) or "").strip()
        if tag in MODES and said in ("1", "2"):
            values[key] = said
        elif tag in FLAGS and said in ("0", "1"):
            values[key] = said
    return values
