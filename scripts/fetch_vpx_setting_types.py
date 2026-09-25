#!/usr/bin/env python3
"""Regenerate `apps/vpx/setting_types.py` from Visual Pinball's own declarations.

Visual Pinball writes a comment above every setting in its ini giving the label, the
description, the default and any enumerated answers - so all of that is read from the
user's own file at runtime and nothing needs to be kept here. What the comment cannot
say is the *type*: `Enable Log` and `ImageMngPosX` both default to a bare 0 or 1, and
only the source separates them. Without it every switch renders as a number field.

So this takes what the ini cannot give and nothing else: a map of `Section.Key` to a
type name, and the label of each plugin setting. A plugin's settings are written without
the comment, so the ini has no label for them either.

    ./scripts/fetch_vpx_setting_types.py [--from PATH [--from PATH]...]

Run it when Visual Pinball ships settings we do not know the type of. A key the map does
not carry falls back to what the ini implies, so a stale map degrades rather than breaks.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
import urllib.request
from collections.abc import Iterable

SOURCE = ("https://raw.githubusercontent.com/vpinball/vpinball/master/"
          "src/core/Settings_properties.inl")
OUT = pathlib.Path(__file__).resolve().parent.parent / "apps" / "vpx" / "setting_types.py"

# The macro's name says the type.
KINDS = {
    "Bool": "bool", "BoolDyn": "bool", "BoolBase": "bool",
    "Int": "int", "IntUnbounded": "int", "IntDyn": "int", "IntBase": "int",
    "Float": "number", "FloatUnbounded": "number", "FloatDyn": "number",
    "FloatStepped": "number", "FloatSteppedDyn": "number", "FloatBase": "number",
    "String": "string", "StringDyn": "string", "StringBase": "string",
    "Enum": "choice", "EnumDyn": "choice", "EnumWithMin": "choice", "Enum1": "choice",
    "EnumBase": "choice",
}
# It gathers other properties under one name.
NOT_A_SETTING = frozenset({"Array"})

DECL = re.compile(r"Prop(\w+)\(\s*(\w+)\s*,\s*(\w+)\s*,")
# Past the key of a `...Base` form: the label and the comment, each one or more string
# literals, then whether it is contextual.
_LITERALS = r'(?:"(?:[^"\\]|\\.)*"s?\s*)+'
BASE_CONTEXTUAL = re.compile(rf"\s*{_LITERALS},\s*{_LITERALS},\s*(true|false)\b")

# A plugin declares its own, and they are never in the core file: it registers them with
# the host when it loads. `MSGPI_BOOL_VAL_SETTING(var, "ShowGrill", "Show Grill", ...)`:
# the key, then its label. A label that is not a literal still leaves the type.
PLUGIN_DECL = re.compile(
    r'MSGPI_([A-Z]+)_(?:VAL_)?SETTING\(\s*\w+\s*,\s*"([^"]+)"'
    r'(?:\s*,\s*"((?:[^"\\]|\\.)*)")?')
PLUGIN_KINDS = {"BOOL": "bool", "INT": "int", "FLOAT": "number",
                "STRING": "string", "ENUM": "choice"}
# `id = "B2SLegacy"` in the manifest is the section suffix: `[Plugin.B2SLegacy]`.
PLUGIN_ID = re.compile(r'^\s*id\s*=\s*"([^"]+)"', re.M)

# The source names a section with a C++ identifier; the file it writes uses a separator.
# `PluginPinMAME` is `[Plugin.PinMAME]` on disk and `DefaultPropsBall` is
# `[DefaultProps\Ball]`. Two rules rather than a list of forty, so a plugin added later
# lands without this script changing.
SEPARATORS = (("DefaultProps", "\\"), ("Plugin", "."))


def section_on_disk(declared: str) -> str:
    for prefix, joiner in SEPARATORS:
        if declared.startswith(prefix) and len(declared) > len(prefix):
            return f"{prefix}{joiner}{declared[len(prefix):]}"
    return declared


def parsed(text: str) -> tuple[dict[str, str], set[str]]:
    """Every setting's type, and which of them are contextual.

    Contextual is the `...Dyn` half of each macro pair, or a `...Base` form that says so,
    and it decides whether a table override survives being saved:
    `LayeredINIPropertyStore::Save` drops a table value that equals the application's
    *unless* the property is contextual, in which case it is kept. Without this, a
    setting that can be held at the inherited value and one that cannot are
    indistinguishable here.

    Raises ValueError on a macro `KINDS` does not name.
    """
    flat = re.sub(r"\s+", " ", text)
    found: dict[str, str] = {}
    contextual: set[str] = set()
    unknown: set[str] = set()
    for declared in DECL.finditer(flat):
        macro, section, key = declared.groups()
        if macro in NOT_A_SETTING:
            continue
        kind = KINDS.get(macro)
        if kind is None:
            unknown.add(f"Prop{macro}")
            continue
        qualified = f"{section_on_disk(section)}.{key}"
        found[qualified] = kind
        if _contextual(macro, qualified, flat, declared.end()):
            contextual.add(qualified)
    if unknown:
        raise ValueError(f"No type for {', '.join(sorted(unknown))}; add it to KINDS.")
    return found, contextual


def _contextual(macro: str, qualified: str, text: str, after_key: int) -> bool:
    if not macro.endswith("Base"):
        return macro.endswith("Dyn")
    said = BASE_CONTEXTUAL.match(text, after_key)
    if said is None:
        raise ValueError(f"Cannot read whether {qualified} is contextual.")
    return said.group(1) == "true"


Build = tuple[dict[str, str], set[str], dict[str, str]]


def combined(builds: Iterable[Build]) -> Build:
    """Several builds as one map, oldest first. A setting more than one declares takes
    the last one's type, whether it is contextual, and its label."""
    types: dict[str, str] = {}
    contextual: set[str] = set()
    labels: dict[str, str] = {}
    for found, held, said in builds:
        types.update(found)
        contextual = (contextual - found.keys()) | held
        labels = {key: label for key, label in labels.items() if key not in found} | said
    return types, contextual, labels


def rendered(types: dict[str, str], contextual: set[str] | None = None,
             labels: dict[str, str] | None = None) -> str:
    # Escaped: a `DefaultProps\\Ball` section carries a backslash, and written raw it
    # is an invalid escape in the file this generates.
    rows = "".join(f'    {key!r}: "{kind}",\n' for key, kind in sorted(types.items()))
    marks = "".join(f"    {key!r},\n" for key in sorted(contextual or ()))
    names = "".join(f"    {key!r}: {label!r},\n"
                    for key, label in sorted((labels or {}).items()))
    return (
        '"""What type each Visual Pinball setting is, and what a plugin calls its own.\n'
        "\n"
        "Generated by `scripts/fetch_vpx_setting_types.py` from Visual Pinball's own\n"
        "property declarations. The label, the description, the default and any\n"
        "enumerated answers of the rest are written into the ini by Visual Pinball\n"
        "itself and are read from the user's own file at runtime.\n"
        "\n"
        "It is here because the ini cannot say what a type is. `Enable Log` and\n"
        "`ImageMngPosX` both default to a bare 0 or 1, and without this every switch in\n"
        "the program renders as a number field.\n"
        "\n"
        "A key this does not carry falls back to what the ini implies, so a version of\n"
        "Visual Pinball newer than this file degrades rather than breaks.\n"
        '"""\n'
        "\n"
        "from __future__ import annotations\n"
        "\n"
        f"# {len(types)} declarations.\n"
        "TYPES: dict[str, str] = {\n"
        f"{rows}"
        "}\n"
        "\n"
        "# The ones a table can hold at the application's own value.\n"
        "#\n"
        "# Saving a table's settings drops any value equal to the application's, so a\n"
        "# table cannot be pinned to what it already inherits - except for these, which\n"
        "# are kept. Declared by the `...Dyn` half of each macro pair.\n"
        f"# {len(contextual or ())} of them.\n"
        "CONTEXTUAL: frozenset[str] = frozenset({\n"
        f"{marks}"
        "})\n"
        "\n"
        "# A plugin setting's label, where it is not the key. The ini writes every plugin\n"
        "# setting but `Enable` bare, so it has none to give.\n"
        f"# {len(labels or {})} of them.\n"
        "LABELS: dict[str, str] = {\n"
        f"{names}"
        "}\n"
    )


def from_plugins(root: pathlib.Path) -> tuple[dict[str, str], dict[str, str]]:
    """Every setting the shipped plugins register, by the section they land in, and the
    label of each one whose label is not its key.

    A plugin names itself in its manifest and its settings in its sources, so the two
    are read together. Without this the switches somebody actually reaches for - turn
    the backglass DMD overlay off, turn a plugin on - are typeless and draw as text.
    """
    found: dict[str, str] = {}
    labels: dict[str, str] = {}
    for manifest in sorted(root.rglob("plugin.cfg")):
        named = PLUGIN_ID.search(manifest.read_text(encoding="utf-8", errors="replace"))
        if named is None:
            continue
        section = f"Plugin.{named.group(1)}"
        # Every plugin has one and no plugin declares it: the host creates it so that a
        # plugin can be switched off, and it is the switch somebody actually reaches for.
        found[f"{section}.Enable"] = "bool"
        for source in sorted(manifest.parent.rglob("*")):
            if source.suffix not in (".cpp", ".h"):
                continue
            text = source.read_text(encoding="utf-8", errors="replace")
            for macro, key, label in PLUGIN_DECL.findall(text):
                kind = PLUGIN_KINDS.get(macro)
                if kind is None:
                    continue
                found[f"{section}.{key}"] = kind
                if label and label != key:
                    labels[f"{section}.{key}"] = label
    return found, labels


def from_checkout(root: pathlib.Path) -> Build:
    types, contextual = parsed((root / "src" / "core" / "Settings_properties.inl")
                               .read_text(encoding="utf-8"))
    # The plugins come second, so a plugin that redeclares a core setting is the one
    # that answers for its own section.
    plugin_types, labels = from_plugins(root / "plugins")
    types.update(plugin_types)
    return types, contextual, labels


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from", dest="sources", action="append", default=[],
                    metavar="PATH",
                    help="a checkout of vpinball, instead of fetching the sources; once "
                         "per build, oldest first")
    args = ap.parse_args()

    try:
        labels: dict[str, str] = {}
        if args.sources:
            types, contextual, labels = combined(
                from_checkout(pathlib.Path(source)) for source in args.sources)
        else:
            with urllib.request.urlopen(SOURCE, timeout=30) as answer:
                types, contextual = parsed(answer.read().decode("utf-8"))
            print("Only the core settings were read. Point --from at a checkout to "
                  "take the plugins' as well.", file=sys.stderr)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    if not types:
        print("No declarations found; the source's shape has changed.", file=sys.stderr)
        return 1
    OUT.write_text(rendered(types, contextual, labels), encoding="utf-8")
    counts: dict[str, int] = {}
    for kind in types.values():
        counts[kind] = counts.get(kind, 0) + 1
    print(f"wrote {OUT.relative_to(OUT.parent.parent.parent)}: {len(types)} settings")
    for kind, n in sorted(counts.items()):
        print(f"    {kind:8} {n}")
    print(f"    {'contextual':8} {len(contextual)}")
    print(f"    {'labels':8} {len(labels)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
