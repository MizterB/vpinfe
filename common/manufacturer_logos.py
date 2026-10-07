"""Manufacturer logos: media keyed by a game's manufacturer, not by the game or a theme.

A logo belongs to hundreds of tables and outlives any one theme, so it lives in a folder
of its own - `media.manufacturer_logos_dir`, defaulting to manufacturer_logos/ under the
config dir - served at /manufacturers/<slug>/logo. The folder is flat: image files named
for the manufacturer. Nothing ships in the tree.

A file and a manufacturer meet at a slug of the name with case, punctuation and corporate
suffixes dropped, so "Williams Electronics.PNG", "williams.png" and a table whose
manufacturer is "Williams" all find each other. The exceptions no rule can cover
("D. Gottlieb & Co.") belong in an alias map beside the images: manufacturers.json,
{"name or slug": "canonical-slug"}.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path

from common.media_specs import IMAGE_FAMILY

_ALIAS_FILE = "manufacturers.json"
_REFERENCE_FILE = "manufacturers-reference.json"
DEFAULT_FOLDER = "manufacturer_logos"

# Corporate boilerplate that varies between VPSdb entries for one brand.
_SUFFIX_TOKENS = {
    "mfg", "manufacturing", "corp", "corporation", "co", "company",
    "inc", "incorporated", "ltd", "limited", "electronics", "industries",
}

_folder: Path | None = None


def configure_manufacturer_logos(folder: str | Path | None) -> None:
    global _folder
    _folder = Path(folder) if folder else None


def resolve_logos_dir(configured: str, config_dir: str | Path) -> Path:
    return Path(configured) if configured.strip() else Path(config_dir) / DEFAULT_FOLDER


def manufacturer_slug(name: str) -> str:
    words = re.split(r"[^a-z0-9]+", str(name or "").lower())
    kept = [w for w in words if w and w not in _SUFFIX_TOKENS]
    return "-".join(kept or [w for w in words if w])


def _alias_map(folder: Path) -> dict[str, str]:
    try:
        data = json.loads((folder / _ALIAS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    # Empty values are placeholders, not aliases - honoring one would erase a working slug.
    return {manufacturer_slug(k): str(v) for k, v in data.items()
            if isinstance(v, str) and v.strip()}


def _logos_by_slug(folder: Path) -> dict[str, Path]:
    """The folder's images by slug, read on every call so a file dropped in shows without
    a restart."""
    rank = {ext: place for place, ext in enumerate(IMAGE_FAMILY)}
    try:
        files = sorted((one for one in folder.iterdir()
                        if one.suffix.lower() in rank and one.is_file()),
                       key=lambda one: (rank[one.suffix.lower()], one.name))
    except OSError:
        return {}
    found: dict[str, Path] = {}
    for one in files:
        found.setdefault(manufacturer_slug(one.stem), one)
    return found


def manufacturer_logo_file(slug: str) -> Path | None:
    """The image a slug's logo is, or None. A slug is what `manufacturer_slug` returns."""
    if _folder is None or not slug or slug != manufacturer_slug(slug):
        return None
    return _logos_by_slug(_folder).get(slug)


def _entry(name: str, aliases: dict[str, str]) -> dict:
    slug = manufacturer_slug(name)
    target = manufacturer_slug(aliases.get(slug, "")) or None
    effective = target or slug
    found = manufacturer_logo_file(effective) if effective else None
    return {"name": name, "slug": slug, "aliased_to": target,
            "logo": f"/manufacturers/{effective}/logo" if found else None}


def manufacturer_logo_url(name: str) -> str | None:
    """The URL a manufacturer's logo is served at, or None when there is no logo."""
    if _folder is None or not str(name or "").strip():
        return None
    return _entry(name, _alias_map(_folder))["logo"]


def manufacturer_report(names: Iterable[object]) -> list[dict]:
    """One row per distinct name: slug, effective alias, resolved logo.

    This is the lookup made visible - the answer to "what filename would this
    manufacturer find" without running the algorithm in your head, and the only
    way to see that an alias is redirecting past a file you named for the manufacturer.
    """
    aliases = _alias_map(_folder) if _folder is not None else {}
    distinct = sorted({str(n).strip() for n in names if str(n or "").strip()},
                      key=str.lower)
    return [_entry(name, aliases) for name in distinct]


def vps_manufacturer_names(vpsdb_path: str | Path) -> list[str]:
    """Every distinct manufacturer string in a cached vpsdb.json."""
    try:
        data = json.loads(Path(vpsdb_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return sorted({str(t.get("manufacturer", "")).strip() for t in data
                   if isinstance(t, dict) and str(t.get("manufacturer", "")).strip()},
                  key=str.lower)


def write_manufacturer_reference(names: Iterable[object]) -> Path | None:
    """Generate manufacturers-reference.json in the logos folder.

    The reference is for people: open it to learn what slug a name computes,
    what an alias currently redirects, and which names have no logo yet. The
    lookup never reads it, so it can never break anything.
    """
    if _folder is None:
        return None
    report = manufacturer_report(names)
    if not report:
        return None
    path = _folder / _REFERENCE_FILE
    payload = {
        "about": ("Generated by VPinFE from VPSdb. Do not edit - regenerated on "
                  "sync, and never read by the logo lookup. To alias a name, "
                  "copy it into manufacturers.json in this folder."),
        "manufacturers": report,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        return None
    return path
