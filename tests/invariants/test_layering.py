"""Which package may import which, asserted rather than remembered.

`docs/common.md` says nothing in `common/` may import a domain package above it, and
that the Manager is one consumer of the shared services rather than their owner.
A rule that lives only in prose gets broken without anyone choosing to. This file is
the check, so the next break fails here instead of being found by reading.
"""

from __future__ import annotations

import ast
import inspect
import pathlib
import unittest

from tests.support import trees

REPO = pathlib.Path(__file__).resolve().parent.parent.parent

# `common/host/` is the device's own package, so a frontend import inside it is a
# device-to-device edge rather than a layering break. It predates this rule and is
# listed so that a *new* one still fails.
ALLOWED = {
    ("common/host/display_service.py", "frontend"),
    # The local resolution of the device client: deferred inside functions so that
    # importing it does not pull the frontend into an install that has no frontend.
    ("common/device_client.py", "frontend"),
}

# A unit of `common/` is a package, or a flat module standing for the package it will move
# to. A unit may import its own rank or any below it; the tiers say what is allowed to know
# about what. Every domain is rank 5 and may import another domain.
RANK = {
    "core": 0, "i18n": 0, "apps": 0,
    "config": 1,
    "security": 2, "media": 2, "runtime": 2,
    "devices": 3,
    "players": 4, "release": 4, "settings": 4,
    "games": 5, "online": 5, "host": 5, "uploads": 5, "capture": 5, "backups": 5,
    "extensions": 5,
}

# The packages that do not exist yet: a flat module is filed under the one it moves to.
# A module that is in none of these is core, and a move deletes its line.
FUTURE_HOME = {
    **dict.fromkeys(("config_access", "config_schema", "config_store", "setting_groups",
                     "labels", "input_registry", "paths", "path_state",
                     "ui_preferences"), "config"),
    **dict.fromkeys(("access_keys", "api_tokens", "approvals", "authenticator",
                     "machine_secrets", "sign_in", "encrypted_connections",
                     "pinned_certificates", "http_client", "accepted"),
                    "security"),
    **dict.fromkeys(("media_specs", "manufacturer_logos", "sized_media", "folder_browse"),
                    "media"),
    **dict.fromkeys(("jobs", "job_details", "lifecycle", "shutdown", "log_setup"),
                    "runtime"),
    **dict.fromkeys(("device_client", "device_registry", "device_ops", "device_migration",
                     "discovery", "install_setup", "launcher_wire", "install_identity",
                     "install_presence", "serving"), "devices"),
    **dict.fromkeys(("players", "player_pictures"), "players"),
    **dict.fromkeys(("release_notes", "whats_new", "upgrade_needs", "migration_ledger"),
                    "release"),
    **dict.fromkeys(("config_service", "settings_waiting", "feature_checks", "port_checks",
                     "theme_options"), "settings"),
}

# The imports that run against the ranks, each with the file that makes it. This list only
# shrinks: a new entry means a module reaching for something above it, and the fix is to
# hand the thing down, not to add a line here.
UPWARD: dict[tuple[str, str], str] = {
    ("common/apps/__init__.py", "config"): "reads a label from the config tier",
    ("common/config_schema.py", "devices"): "looks up the install id, lazily",
    ("common/config_store.py", "devices"): "looks up the install id, lazily",
    ("common/config_store.py", "games"): "the .info backups helper",
    ("common/config_service.py", "backups"): "the settings service names the backups folder",
    ("common/settings_waiting.py", "extensions"): "asks the extension host what is waiting",
}


def _imports(path: pathlib.Path) -> set[str]:
    """Every top-level package this module imports, however it spells it."""
    found = set()
    for node in ast.walk(trees.tree_for(path)):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            found |= {alias.name.split(".")[0] for alias in node.names}
    return found


# The extension store's calls about one extension, which take its name first, and the
# ones about the store as a whole. Every public method is in one or the other - a test
# below holds that - so a new one has to be placed before this check can pass.
STORE_CALLS_NAMING_AN_EXTENSION = {"enabled", "set_enabled", "settings", "set_setting",
                                   "forget", "accounts", "set_account", "declared",
                                   "set_declared"}
STORE_CALLS_ABOUT_THE_STORE = {"forget_holder"}


def _names_handed_to_the_store(tree: ast.Module) -> list[tuple[int, str]]:
    """(line, name) for each store call given an extension's name as a string, written
    at the call or held in a module-level constant. A name passed through a variable is
    the host's business: it is handed the names of whatever is installed."""
    methods = STORE_CALLS_NAMING_AN_EXTENSION
    constants = {target.id: node.value.value for node in tree.body
                 if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                 and isinstance(node.value.value, str)
                 for target in node.targets if isinstance(target, ast.Name)}
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in methods):
            continue
        given = node.args[:1] + [kw.value for kw in node.keywords if kw.arg == "name"]
        for argument in given:
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                found.append((node.lineno, argument.value))
            elif isinstance(argument, ast.Name) and argument.id in constants:
                found.append((node.lineno, constants[argument.id]))
    return found


def _unit_of(module: str) -> str | None:
    """The unit of `common/` a dotted module name belongs to, or None outside it."""
    parts = module.split(".")
    if parts[0] != "common":
        return None
    if len(parts) == 1:
        return "core"
    return parts[1] if parts[1] in RANK else FUTURE_HOME.get(parts[1], "core")


def _common_units(tree: ast.Module) -> set[str]:
    """Every unit of `common/` this module imports, whether it names the module
    (`from common.paths import X`) or imports it from the package (`from common import paths`)."""
    found = set()
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names = [node.module]
            if node.module == "common":
                names = [f"common.{alias.name}" for alias in node.names]
        elif isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        found |= {unit for unit in map(_unit_of, names) if unit}
    return found


def _upward_imports() -> list[tuple[str, str]]:
    """(file, unit) for each import of a unit ranked above the file's own."""
    found = []
    for path in sorted((REPO / "common").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        relative = path.relative_to(REPO).as_posix()
        own = _unit_of(".".join(path.relative_to(REPO).with_suffix("").parts)) or "core"
        for unit in sorted(_common_units(trees.tree_for(path))):
            if RANK[unit] > RANK[own]:
                found.append((relative, unit))
    return found


def _offenders(package: str, forbidden: set[str]) -> list[str]:
    out = []
    for path in sorted((REPO / package).rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        relative = path.relative_to(REPO).as_posix()
        for imported in sorted(_imports(path) & forbidden):
            if (relative, imported) not in ALLOWED:
                out.append(f"{relative} imports {imported}")
    return out


class LayeringTests(unittest.TestCase):
    def test_common_does_not_import_the_packages_above_it(self) -> None:
        """Anything may depend on `common/`, so it may depend on nothing that depends
        on it - otherwise a library install has to ship a frontend to import a game."""
        self.assertEqual(_offenders("common", {"httpapi", "frontend", "manager"}), [])

    def test_a_unit_imports_only_its_own_rank_or_below(self) -> None:
        """`docs/common.md`, Layers: the shared services are ranked, and a service that
        reaches for one above it is a helper filed in the wrong place."""
        self.assertEqual(sorted(set(_upward_imports()) - set(UPWARD)), [])

    def test_every_upward_import_listed_still_happens(self) -> None:
        """A stale entry silently permits the import coming back."""
        self.assertEqual(sorted(set(UPWARD) - set(_upward_imports())), [])

    def test_every_module_of_common_has_a_rank(self) -> None:
        """A new package is ranked, and a placement for a module that moved is dropped.
        A flat module in neither table is core, so it fails only by importing upward."""
        flat = {path.stem for path in (REPO / "common").glob("*.py")
                if path.stem != "__init__"}
        packages = {path.name for path in (REPO / "common").iterdir()
                    if path.is_dir() and path.name != "__pycache__"}
        self.assertEqual(sorted(packages - set(RANK)), [])
        self.assertEqual(sorted(set(FUTURE_HOME) - flat), [])
        self.assertEqual(sorted(set(FUTURE_HOME.values()) - set(RANK)), [])

    def test_the_rank_check_sees_an_import_however_it_is_spelled(self) -> None:
        tree = trees.parse_snippet(
            "from common import paths, games\n"
            "from common.online import themes\n"
            "import common.host.dof_service\n"
            "from . import sibling\n")

        self.assertEqual(sorted(_common_units(tree)), ["config", "games", "host", "online"])

    def test_common_names_no_extension_to_the_extension_store(self) -> None:
        """An extension's settings are its own. Core reading one by name makes a core
        fact live in an extension, and it goes wrong the moment that extension is off."""
        found = []
        for path in sorted((REPO / "common").rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            relative = path.relative_to(REPO).as_posix()
            found += [f"{relative}:{line} names {name!r}"
                      for line, name in _names_handed_to_the_store(trees.tree_for(path))]
        self.assertEqual(found, [])

    def test_the_store_check_sees_a_name_written_either_way(self) -> None:
        tree = trees.parse_snippet(
            "OWNER = 'somebody'\n"
            "get_extension_store().settings('somebody')\n"
            "store.set_setting(OWNER, 'key', 'value')\n"
            "store.enabled(name='somebody')\n"
            "store.settings(extension)\n")

        self.assertEqual(_names_handed_to_the_store(tree),
                         [(2, "somebody"), (3, "somebody"), (4, "somebody")])

    def test_every_store_call_is_placed(self) -> None:
        from common.extensions.store import ExtensionStore

        public = {name for name, _ in inspect.getmembers(ExtensionStore, inspect.isfunction)
                  if not name.startswith("_")}
        self.assertEqual(public - STORE_CALLS_NAMING_AN_EXTENSION
                         - STORE_CALLS_ABOUT_THE_STORE, set())

    def test_the_api_does_not_reach_into_a_user_interface(self) -> None:
        """Business logic under a UI package makes that UI privileged: a replacement
        would import the incumbent, which is a skin rather than a replacement."""
        self.assertEqual(_offenders("httpapi", {"manager"}), [])

    def test_the_allowlist_only_names_files_that_exist(self) -> None:
        """A stale entry silently permits whatever moves into that path."""
        missing = sorted(name for name, _ in ALLOWED if not (REPO / name).exists())
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
