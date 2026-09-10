"""The one place that knows both vocabularies.

A reader reports what a source calls things; core stores what we call them. Everything
that turns one into the other is here, once, because a mapping decided in four places is
four things to keep in step.

The kind names are asked of core rather than written down, so a build that gains a media
kind does not leave a stale list behind here.
"""

from __future__ import annotations

from .source import SourceGame

# A PinballX media folder is one of our kinds. The pairs are unambiguous in this
# direction: the source files a still and a moving version of one subject in two folders,
# and we hold those as two kinds, so each folder has exactly one answer.
PINBALLX_KINDS = {
    "Table Images": "playfield",
    "Table Videos": "playfield_video",
    "Backglass Images": "backglass",
    "Backglass Videos": "backglass_video",
    "DMD Images": "scoreview",
    "DMD Videos": "scoreview_video",
    "Topper Images": "topper",
    "Topper Videos": "topper_video",
    "Wheel Images": "wheel",
    "Table Audio": "audio",
    "Launch Audio": "audio_launch",
    "Logos": "logo",
}

KINDS_BY_SOURCE = {"pinballx": PINBALLX_KINDS}


def media_for(source_id: str, game: SourceGame, known: tuple[str, ...]) -> list[tuple[str, str]]:
    """(kind, path) for every file we have a slot for.

    `known` is what core says it stores. A folder this build has no kind for is left
    behind rather than guessed at - PinballX's full-DMD menu video is a real example, and
    putting it somewhere approximate would be worse than not carrying it.
    """
    table = KINDS_BY_SOURCE.get(source_id, {})
    found = []
    for item in game.media:
        kind = table.get(item.source_kind, "")
        if kind and kind in known:
            found.append((kind, item.path))
    return found


def unmapped_kinds(source_id: str, game: SourceGame, known: tuple[str, ...]) -> list[str]:
    """What the source held that we have nowhere to put, so it can be said out loud."""
    table = KINDS_BY_SOURCE.get(source_id, {})
    return sorted({item.source_kind for item in game.media
                   if table.get(item.source_kind, "") not in known})


def folder_name(game: SourceGame) -> str:
    """What to call the game folder.

    The source's description, which in both frontends that share this format is already
    "Title (Manufacturer Year)" - our own convention, arrived at independently. Its name
    is the fallback, and it is the filename stem rather than anything anybody wrote.
    """
    return (game.description or game.key).strip()


def _title_from(game: SourceGame) -> str:
    """The machine's name, out of a description that carries more than it.

    PinballX has no title of its own - it holds "Attack from Mars (Bally 1995)" and
    nothing else - so an import that carried it straight across would put the
    manufacturer and the year in the name column beside the columns that already hold
    them, on every imported game and on none of the matched ones.

    Only where the trailing bracket is exactly the manufacturer and year the source also
    gave, so this is a removal of something known rather than a guess at what a name
    ends with. Anything else is left whole.
    """
    described = (game.description or "").strip()
    maker, year = game.manufacturer.strip(), game.year.strip()
    if not described or not maker or not year:
        return ""
    suffix = f"({maker} {year})"
    if described.endswith(suffix):
        return described[:-len(suffix)].strip()
    return ""


def details_for(game: SourceGame) -> dict:
    """What the source knew about the machine, in our field names.

    Only what it actually said. Sending a field the source left blank would write an
    empty value over nothing, which reads the same on disk but says we examined it and
    found none - and for an unmatched import nobody examined anything.
    """
    found = {
        "title": game.title or _title_from(game),
        "manufacturer": game.manufacturer,
        "year": game.year,
        "type": game.game_type,
        "ipdb_id": game.ipdb_id,
    }
    said = {name: value for name, value in found.items() if str(value or "").strip()}
    if game.themes:
        said["themes"] = list(game.themes)
    return said
