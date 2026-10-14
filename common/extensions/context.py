"""The curated facade an extension is handed, and nothing else.

`register(ctx)` never receives the application. Everything below is a narrow view over
one core facility, named for the extension that holds it, so that "which extension did
this?" is answerable from a log line, a config file or a scope.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from common import events as core_events

from . import accounts
from . import cards as cards_module
from .contract import ContractError, Manifest, words
from .contract import why as worded
from .fields import FieldError, settings_fields, ticked
from .games import ExtensionGames
from .store import ExtensionStore

if TYPE_CHECKING:
    from common import jobs

LOG_ROOT = "vpinfe.ext"


def logger_for(name: str) -> logging.Logger:
    return logging.getLogger(f"{LOG_ROOT}.{name}")


class ExtensionConfig:
    """An extension's settings, under its own name."""

    def __init__(self, name: str, store: ExtensionStore,
                 declared: Callable[[], dict[str, str]] = dict) -> None:
        self._name = name
        self._store = store
        self._declared = declared

    def get(self, key: str, default: str = "") -> str:
        """What is stored under `key`; where that is empty, the default its field
        declares; where there is neither, `default`."""
        wanted = str(key or "").strip()
        stored = self.all()
        if stored.get(wanted):
            return stored[wanted]
        return self._declared().get(wanted) or stored.get(wanted, default)

    def get_list(self, key: str) -> list[str]:
        """The choices ticked in a `multi` setting; the declared default where none has
        been saved."""
        return ticked(self.get(key))

    def all(self) -> dict[str, str]:
        return self._store.settings(self._name)

    def set(self, key: str, value: str) -> None:
        self._store.set_setting(self._name, key, value)


class ExtensionEvents:
    """The bus, seen from one extension: it is told what core did, and publishes under
    its own namespace so nothing it emits can be mistaken for a core event."""

    def __init__(self, name: str, declared: tuple[str, ...],
                 on_failure: Callable[..., None]) -> None:
        self._name = name
        self._declared = frozenset(declared)
        self._on_failure = on_failure
        self._logger = logger_for(name)
        self.registered: list[tuple[str, Callable]] = []

    def subscribe(self, event: str, handler: Callable) -> None:
        def contained(**payload: Any) -> None:
            try:
                handler(**payload)
            except Exception:
                self._logger.exception("Handling %s failed", event)
                self._on_failure("extension.reason.failed_handling", event=event)

        core_events.subscribe(event, contained)
        self.registered.append((event, contained))

    def publish(self, event: str, **payload: Any) -> None:
        wanted = str(event or "").strip()
        if wanted not in self._declared:
            raise ContractError(f"{self._name} publishes {wanted!r}, which its manifest "
                                "does not declare")
        core_events.emit(f"{self._name}.{wanted}", **payload)


class ExtensionFiles:
    """The folders an extension works from, so core will accept a path inside one.

    Nothing here stops an extension reading a file - in-process Python cannot be
    prevented from opening one, and pretending otherwise would be theater. What it does
    is let core's own routes take a path the extension is working with: an importer
    converting somebody's old library has to hand core files that are nowhere near ours,
    and without this every one of them is refused.

    Declared rather than assumed, and only by an extension whose manifest asks for it, so
    what an install will read is something a person agreed to and can be shown.
    """

    def __init__(self, name: str, allowed: bool, writes: bool = False) -> None:
        self._name = name
        self._allowed = allowed
        self._writes = writes
        self._roots: tuple[str, ...] = ()

    def roots(self) -> tuple[str, ...]:
        return self._roots

    def may_write(self) -> bool:
        """Whether the manifest declared `fs:write`, which is what lets core take a
        file out of one of these folders instead of copying it."""
        return self._writes

    def set_roots(self, paths: Iterable[str]) -> None:
        """Replace the set. The user moves a share or points somewhere else, and what
        core will accept has to follow rather than accumulate."""
        if not self._allowed:
            raise ContractError(f"{self._name} sets folders to read from, which needs "
                                "the fs:read capability its manifest does not declare")
        wanted = [str(one or "").strip() for one in paths]
        self._roots = tuple(str(Path(one).expanduser().resolve())
                            for one in wanted if one)


class ExtensionApps:
    """The programs this install can play a table with, as an extension may add to them.

    VPinFE plays Visual Pinball and, through the generic app, anything a person can point
    at a binary. An extension is how a format becomes first-class instead: something that
    claims its own suffixes, so a library of them can be imported and offered rather than
    read and dropped.
    """

    def __init__(self, name: str, scopes: Iterable[str],
                 directory: Path | None = None) -> None:
        self._name = name
        self._scopes = frozenset(scopes)
        self._directory = directory
        self._mine: list[str] = []

    def provide(self, **described: Any) -> str:
        """Add an app, described in plain data. Answers with the id it took.

        `id`, `suffixes`, and optionally `name`, `accepts_keys`, `companions`,
        `fields`, `kinds` and `command`. `command(entry, settings)` answers with a list
        of arguments, or with nothing to run the launcher's binary and arguments the way
        the generic app does.

        Its words are the extension's `i18n/<language>.json` under `app.<id>.`, keyed as
        an app's own file is. A `name` or a field's `label` given here is shown as written.
        """
        from . import provided_apps

        if provided_apps.APPS_PROVIDE not in self._scopes:
            raise ContractError(
                f"{self._name} provides an app, which needs "
                f"{provided_apps.APPS_PROVIDE}, and its manifest does not declare it")
        from common import apps, i18n

        built = provided_apps.build(self._name, described)
        apps.contribute(built)
        self._mine.append(built.id)
        if self._directory is not None:
            i18n.own(f"app.{built.id}", self._directory / "i18n", section=f"app.{built.id}")
        logger_for(self._name).info(
            "provides the %s app for %s", built.id,
            ", ".join(built.claim.suffixes) or "keyed entries")
        return built.id

    def suffixes(self) -> tuple[str, ...]:
        """Every file extension this install can play, its own and any provided.

        Ungated, unlike the library: this says what the build can do, not what the user
        has. An extension deciding whether a foreign library is worth importing needs it
        before it has been granted anything.
        """
        from common import apps

        found: list[str] = []
        for app in apps.all_apps():
            found.extend(app.claim.suffixes)
        return tuple(dict.fromkeys(found))

    def names(self) -> tuple[str, ...]:
        """The product names of the apps here. For a source that says which program a
        system used but not which files it holds - a database found in a folder named
        after the program is often all there is."""
        from common import apps

        return tuple(one.name for one in apps.all_apps() if one.name)

    def plays(self, name: str) -> bool:
        """Whether anything here plays a file of this name, or this bare suffix."""
        wanted = str(name or "").strip().lower()
        if not wanted:
            return False
        return any(wanted == one or wanted.endswith(one) for one in self.suffixes())

    def provided(self) -> tuple[str, ...]:
        """What this extension has added, which is what gets taken back with it."""
        return tuple(self._mine)

    def withdraw(self) -> None:
        """Take them all back. Called when the extension is unloaded, so a disabled
        extension does not leave a suffix claimed by something that is no longer here."""
        from common import apps, i18n

        for app_id in self._mine:
            apps.withdraw(app_id)
            i18n.disown(f"app.{app_id}")
        self._mine.clear()


COLUMN_KINDS = frozenset({"text", "number", "date"})
RANKING_KINDS = frozenset({"number", "date"})
RELATION_KEYS = frozenset({"vps_entry", "vps_release"})
VERB_KEYS = frozenset({"key", "run", "link", "danger", "needs", "one", "label"})

# The groups in the rail a list can be put in, each one core already draws.
AREAS = ("library", "frontend", "community", "system")
DEFAULT_AREA = "community"


@dataclass
class ListFunctions:
    """What a list's extension answers with."""

    rows: Callable[[], Any]
    status: Callable[[], Any] | None = None
    acts: Any = None
    verbs: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class AccountFunctions:
    """What a player's account is answered with, one function for each thing core asks."""

    read: Callable[[str], dict]
    write: Callable[[str, dict], Any] | None = None
    acts: dict[str, Callable[[str], Any]] = field(default_factory=dict)
    card: Callable[[str], dict | None] | None = None
    read_card: Callable[[Any], dict] | None = None
    available: Callable[[str], Any] | None = None


class ExtensionUI:
    """What an extension offers a person: its settings, lists, actions and accounts.

    Declared rather than drawn, and served by core rather than by the extension: it hands
    over fields, a `rows()` and a dialog object, and core mounts the routes the Console
    reads. An extension that painted its own page would tie the Console's look to whoever
    wrote it, and would stop working the moment it moved out of this process - where a
    task described as data still does.

    A word left out is looked up in the extension's own `i18n/<language>.json`:
    `settings.<key>.label`, `list.<key>.title`, `action.<key>.label` and so on, as
    `docs/extensions/reference/words.md` lists them. One given is shown as written.
    """

    def __init__(self, name: str, allowed: bool) -> None:
        self._name = name
        self._allowed = allowed
        self.actions: list[dict] = []
        self.action_objects: dict[str, Any] = {}
        self.declared_lists: list[dict] = []
        self.list_functions: dict[str, ListFunctions] = {}
        self.settings_declared: list[dict] = []
        self.settings_check: Callable[[dict], Any] | None = None
        self.state_label = ""
        self.state_base = ""
        self.account_offered: dict = {}
        self.account_functions: AccountFunctions | None = None

    def settings(self, fields: Iterable[dict], *,
                 check: Callable[[dict], Any] | None = None) -> None:
        """This extension's settings. A field is `{"key", "type", "default", "choices"}`,
        `type` one of `common.extensions.fields.SETTINGS_TYPES`. A `number` may carry
        `min`, `max` and `unit`; a `path` says what it `wants`: `dir`, `file` or `exe`.

        `check(values)` gets every setting as it would be after the change and raises to
        refuse it: the refusal is shown under the field that was changed.
        """
        self._needs_ui("settings")
        if self.settings_declared:
            raise ContractError(f"{self._name} declares its settings twice")
        if check is not None and not callable(check):
            raise ContractError(f"{self._name} gives its settings a check that is not "
                                "a function")
        try:
            self.settings_declared = settings_fields(self._name, fields)
        except FieldError as exc:
            raise ContractError(str(exc)) from exc
        self.settings_check = check

    def settings_defaults(self) -> dict[str, str]:
        return {one["key"]: one["default"] for one in self.settings_declared}

    def action(self, key: str, dialog: Any, *, label: str = "",
               description: str = "") -> None:
        """A verb somebody can press, in the vocabulary the rest of the app uses.

        `dialog` has `ask(step)`, answering the dialog for that step, and any of
        `check(values)`, `act(key, values)` and `run(values, progress)`. A method that
        names `step` or `progress` among its arguments is handed it.
        """
        self._needs_ui("an action")
        wanted = str(key or "").strip()
        if not wanted:
            raise ContractError(f"{self._name} offers an action with no key")
        if wanted in self.action_objects:
            raise ContractError(f"{self._name} offers the action {wanted!r} twice")
        if not callable(getattr(dialog, "ask", None)):
            raise ContractError(f"{self._name} offers the action {wanted!r} with an "
                                "object that has no ask(step)")
        self.action_objects[wanted] = dialog
        self.actions.append({
            "key": wanted,
            "label": str(label or "").strip(),
            "description": str(description or "").strip(),
            "base": f"/actions/{wanted}",
        })

    def state(self, base: str, label: str = "") -> None:
        """Where core reads a list of rows: a label, a line under it, at most two acts."""
        self._needs_ui("state")
        self.state_base = str(base or "").strip()
        self.state_label = str(label or "").strip()

    def account(self, *, read: Callable[[str], dict],
                write: Callable[[str, dict], Any] | None = None,
                acts: dict[str, Callable[[str], Any]] | None = None,
                card: Callable[[str], dict | None] | None = None,
                read_card: Callable[[Any], dict] | None = None,
                available: Callable[[str], Any] | None = None,
                label: str = "", cards: Iterable[str] = (), marker: str = "",
                consent: Iterable[str] = (), sends_picture: bool = False) -> None:
        """Say that a player can hold an account with this extension.

        `read(player_id)` answers what the player's panel draws: whether it is claimed, a
        page, a status line and the acts. `write(player_id, values)` saves what was
        chosen. `acts` maps an act's key to a function of the player's id, each answering
        the account again or a `message`. `cards` are the `type`s of card it reads,
        `read_card(card)` checks one and answers `{"name", "initials", "values"}`, and
        `card(player_id)` makes the player's own as `{"card", "filename"}`, or None.
        `available(candidate)` answers whether an id is free, while it is being chosen.
        `marker` names where a card it makes hides its text, and is the extension's name
        unless given. `consent` is what Share tells the player becomes public, each line
        already in its own words from `ctx.t`. `sends_picture` declares that this
        extension sends a player's picture to its service: `ctx.players.picture` answers
        only where it is set, and core adds its own line to the consent.
        """
        self._needs_ui("an account")
        if self.account_offered:
            raise ContractError(f"{self._name} offers a second account; a player holds "
                                "one account with an extension")
        hidden = str(marker or self._name).strip()
        reads = tuple(dict.fromkeys(str(one or "").strip() for one in cards))
        if not callable(read) or not all(reads) or not cards_module.MARKER.match(hidden):
            raise ContractError(f"{self._name} offers an account with no read function, a "
                                "card with no type, or a marker that is not a plain name")
        if reads and not callable(read_card):
            raise ContractError(f"{self._name} reads cards without a read_card function")
        offered = dict(acts or {})
        if not all(str(key).strip() and callable(one) for key, one in offered.items()):
            raise ContractError(f"{self._name} gives an account an act that is not a "
                                "function")
        self.account_functions = AccountFunctions(
            read=read, write=write, acts=offered, card=card, read_card=read_card,
            available=available)
        self.account_offered = {"base": "/accounts", "label": str(label or "").strip(),
                                "cards": list(reads), "marker": hidden,
                                "check": "/available" if available else "",
                                "consent": [str(one) for one in consent if str(one).strip()],
                                "sends_picture": bool(sends_picture)}

    def kept(self, key: str) -> dict | None:
        """The last good read core keeps of one of this extension's lists:
        `{"rows", "read_at"}`, or None where there has been none."""
        from common.games import community_lists

        self._needs_ui("a kept list")
        said = community_lists.kept(self._name, str(key or "").strip())
        if said["rows"] is None:
            return None
        return {"rows": said["rows"], "read_at": said["read_at"]}

    def _needs_ui(self, what: str) -> None:
        if not self._allowed:
            raise ContractError(f"{self._name} offers {what}, which needs the ui:mount "
                                "capability its manifest does not declare")

    def list(self, key: str, rows: Callable[[], Any], *, columns: Sequence[dict],
             area: str = DEFAULT_AREA, title: str = "", views: Sequence[dict] = (),
             status: Callable[[], Any] | None = None, acts: Any = None,
             relation: dict | None = None, tag: str = "",
             verbs: Sequence[dict] = ()) -> None:
        """A list this extension holds, shown in the rail under `area`.

        `rows()` answers the rows, each a dict. `status()` answers the line the list's
        page says, text or `{"text", "detail", "to"}`. `acts` is what the title menu
        offers, a dict of `{key: function or address}` or a function answering one: a
        function runs when pressed and answers what to say, an address is opened.

        A column is `{"field", "header", "kind"}` with `kind` one of `text`, `number`,
        `date`, and the first may name `under`: row fields drawn on the line beneath its
        value. A view is `{"key", "name", "columns", "sort": [{"field", "desc"}], "help",
        "ranks"}`, and one that `ranks` is offered as an order for a collection, so it
        needs a `relation` and a sort on number or date columns only. `relation` is
        `{"field", "keys"}`, `keys` being `vps_entry` or `vps_release`. `tag` is put on
        every game (`vps_entry`) or table (`vps_release`) of this library the list
        relates to, so it needs a `relation`.

        `verbs` are what can be done to the rows, in the row's menu and the selection's.
        A verb is `{"key", "run" or "link", "label", "danger", "needs", "one"}`:
        `run(rows)` is called with the rows chosen and answers a `message` or
        `{"message", "url"}`, `link` names a row field holding a web address to open,
        `danger` asks first, `needs` names a boolean row field that must be true for the
        verb to act on a row, and `one` refuses several rows at once. A row needs an `id`,
        a string unique in the list, to be ticked or to have a menu.
        """
        self._needs_ui("a list")
        wanted = str(key or "").strip()
        where = str(area or DEFAULT_AREA).strip()
        if where not in AREAS:
            raise ContractError(f"{self._name} puts a list in {where!r}, which is not one "
                                f"of {', '.join(AREAS)}")
        names = [str((one or {}).get("field") or "").strip() for one in columns]
        if not wanted or not columns or not all(names):
            raise ContractError(f"{self._name} declares a list with no key or "
                                "a column with no field")
        if wanted in self.list_functions:
            raise ContractError(f"{self._name} declares the list {wanted!r} twice")
        if not callable(rows) or (status is not None and not callable(status)):
            raise ContractError(f"{self._name} gives the list {wanted!r} rows or a "
                                "status that is not a function")
        if acts is not None and not callable(acts) and not isinstance(acts, dict):
            raise ContractError(f"{self._name} gives the list {wanted!r} acts that are "
                                "neither a dict nor a function")
        if any((one or {}).get("under") for one in columns[1:]):
            raise ContractError(f"{self._name} puts a line under a column other than the "
                                "first, which is the only one drawn with one")
        kinds = {str((one or {}).get("kind") or "text") for one in columns}
        if not kinds <= COLUMN_KINDS:
            raise ContractError(f"{self._name} declares a column kind core does not draw: "
                                f"{', '.join(sorted(kinds - COLUMN_KINDS))}")
        for view in views:
            named = set(view.get("columns") or []) | {str(one.get("field") or "")
                                                      for one in view.get("sort") or []}
            if not str(view.get("key") or "").strip() or not named <= set(names):
                raise ContractError(f"{self._name} declares a view with no key or on a "
                                    "column it does not have")
        if relation and (relation.get("field") not in names
                         or relation.get("keys") not in RELATION_KEYS):
            raise ContractError(f"{self._name} relates its list on a field it does not "
                                "have, or by something other than a VPS entry or release")
        derived = " ".join(str(tag or "").split())
        if derived and not relation:
            raise ContractError(f"{self._name} derives a tag from a list that relates to "
                                "nothing in the library")
        measured = {name for name, one in zip(names, columns, strict=True)
                    if str((one or {}).get("kind") or "text") in RANKING_KINDS}
        for view in views:
            if not view.get("ranks"):
                continue
            sorted_on = {str(one.get("field") or "") for one in view.get("sort") or []}
            if not sorted_on or not sorted_on <= measured:
                raise ContractError(f"{self._name} ranks by a view that sorts on nothing, "
                                    "or on a column that is not a number or a date")
            if not relation:
                raise ContractError(f"{self._name} ranks by a view of a list that relates "
                                    "to nothing in the library")
        offered = self._verbs(wanted, verbs)
        self.list_functions[wanted] = ListFunctions(rows=rows, status=status, acts=acts,
                                                    verbs=offered)
        self.declared_lists.append({
            "key": wanted, "area": where, "title": str(title or "").strip(),
            "base": f"/lists/{wanted}",
            "columns": [{"field": name, "header": str(one.get("header") or ""),
                         "kind": str(one.get("kind") or "text"),
                         "help": str(one.get("help") or ""),
                         "under": [str(under) for under in one.get("under") or []]}
                        for name, one in zip(names, columns, strict=True)],
            "views": [{"key": str(view["key"]).strip(),
                       "name": str(view.get("name") or "").strip(),
                       "columns": [*(view.get("columns") or names)],
                       "sort": [{"field": str(one["field"]), "desc": bool(one.get("desc"))}
                                for one in view.get("sort") or []],
                       "help": str(view.get("help") or ""),
                       "ranks": bool(view.get("ranks"))} for view in views],
            "relation": dict(relation) if relation else None,
            "tag": derived,
            "about": f"/lists/{wanted}/about",
            "verbs": [{"key": verb, "label": one["label"], "link": one["link"],
                       "danger": one["danger"], "needs": one["needs"], "one": one["one"]}
                      for verb, one in offered.items()],
        })

    def _verbs(self, list_key: str, verbs: Sequence[dict]) -> dict[str, dict[str, Any]]:
        """The verbs of one list, checked, by key. Each holds its `run`, which is not
        declared to the Console."""
        found: dict[str, dict[str, Any]] = {}
        for raw in verbs:
            where = f"{self._name} gives the list {list_key!r}"
            if not isinstance(raw, dict):
                raise ContractError(f"{where} a verb that is not a dict")
            key = str(raw.get("key") or "").strip()
            if not key or key in found:
                raise ContractError(f"{where} a verb with no key, or two with the same one")
            unknown = sorted(set(raw) - VERB_KEYS)
            if unknown:
                raise ContractError(f"{where} the verb {key!r} with keys core does not "
                                    f"read: {', '.join(unknown)}. It reads "
                                    f"{', '.join(sorted(VERB_KEYS))}")
            run, link = raw.get("run"), str(raw.get("link") or "").strip()
            if (run is None) == (not link) or (run is not None and not callable(run)):
                raise ContractError(f"{where} the verb {key!r} with both a run function "
                                    "and a link, or with neither, or a run that is not "
                                    "a function")
            if link and (raw.get("danger") or raw.get("needs")):
                raise ContractError(f"{where} the link verb {key!r} danger or needs, "
                                    "which a link has no use for")
            found[key] = {"run": run, "link": link, "danger": bool(raw.get("danger")),
                          "needs": str(raw.get("needs") or "").strip(),
                          "one": bool(raw.get("one")) or bool(link),
                          "label": str(raw.get("label") or "").strip()}
        return found


PLAYERS_READ = "players:read"


class ExtensionPlayers:
    """Who plays here, and the accounts this extension holds for them.

    The roster is read as plain data, the rows `players.changed` carries. Reading it needs
    `players:read` in the manifest: names and initials are about people. An account's
    values are this extension's own and need nothing declared.
    """

    def __init__(self, name: str, scopes: Iterable[str], store: ExtensionStore,
                 ui: ExtensionUI | None = None) -> None:
        self._name = name
        self._reads = PLAYERS_READ in frozenset(scopes)
        self._store = store
        self._ui = ui

    def roster(self) -> list[dict]:
        """Every player: the owner, the kept players, then the guests as they joined."""
        self._needs_read()
        from common import players

        return players.get_roster().state()["players"]

    def get(self, player_id: str) -> dict | None:
        wanted = str(player_id or "").strip()
        return next((one for one in self.roster() if one["id"] == wanted), None)

    def up(self) -> list[dict]:
        """Who the next game counts for."""
        return [one for one in self.roster() if one["up"]]

    def record(self, player_id: str, game_id: str) -> dict | None:
        """A player's record of one game, as `GET /api/v1/players/{id}/record` lists it.
        None for the owner and for a player nobody has."""
        self._needs_read()
        from common import players
        from common.games import player_records

        player = players.get_roster().get(player_id)
        if player is None or player.owner:
            return None
        return player_records.get_records().shown(player, str(game_id or "").strip())

    def sharing(self, player_id: str) -> bool:
        """Whether this player's account here is sharing. Off until someone turns it on."""
        from common import players

        return players.get_roster().sharing(player_id, self._name)

    def picture(self, player_id: str) -> Path | None:
        """The path of a kept player's picture, for an extension that declared
        `sends_picture` and only while that player's Share here is on. None otherwise,
        including when the player has no picture."""
        from common import player_pictures, players

        offered = self._ui.account_offered if self._ui is not None else {}
        roster = players.get_roster()
        if not offered.get("sends_picture") or not roster.sharing(player_id, self._name):
            return None
        kept = roster.get(player_id)
        if kept is None or kept.guest:
            return None
        return player_pictures.find(roster.pictures_dir, kept.player_id)

    def account(self, player_id: str) -> dict[str, str]:
        """This player's account here, secrets included. Empty when they hold none."""
        return accounts.values(self._name, player_id, self._store)

    def set_account(self, player_id: str, values: dict[str, Any]) -> None:
        """Replace this player's account here. Empty values remove it. A guest's is held
        in memory and never written."""
        accounts.keep(self._name, player_id, values, self._store)

    def holders(self) -> list[str]:
        """The ids of every player holding an account here, in roster order."""
        return accounts.holders(self._name, self._store)

    def _needs_read(self) -> None:
        if not self._reads:
            raise ContractError(f"{self._name} reads the players, which needs "
                                f"{PLAYERS_READ}, and its manifest does not declare it")


class ExtensionEntries:
    """What this extension adds to every entry a theme is handed.

    One key, filled in by core when the player moves to a game. A theme reads
    `entry.ext.<key>` and never learns which extension answered - which is the point: the
    surface a theme sees does not grow a method per connector.
    """

    def __init__(self, name: str) -> None:
        self._name = name

    def contribute(self, key: str, fetch: Callable[[dict], object]) -> None:
        """Answer about one game at a time.

        `fetch` is given a plain description of the game - its ids and what is known
        about the machine - and returns whatever a theme should read, or None where there
        is nothing to say. It is called on core's thread when the wheel stops, so it may
        block; it must not raise for a game it simply has no answer about.
        """
        from . import contributions

        wanted = str(key or "").strip()
        if not wanted:
            raise ContractError(f"{self._name} contributes under no key")
        contributions.register(self._name, wanted, fetch)

    def stale(self, key: str) -> None:
        """What this extension answered under `key` is out of date: core drops what it
        holds, and asks again the next time each game is reached."""
        from . import contributions

        contributions.forget_answers(self._name, str(key or "").strip())

class ExtensionCatalogs:
    """Outside places a game, a table or a file can be reached, which core draws."""

    def __init__(self, name: str) -> None:
        self._name = name

    def contribute(self, key: str, name: str, subject: str,
                   link: Callable[[dict], str]) -> None:
        """`subject` is `game`, `table` or `file`. `link` is given a plain description
        of one and answers its address there, or "" where it has none."""
        from . import catalogs

        wanted = str(key or "").strip()
        if not wanted or not str(name or "").strip():
            raise ContractError(f"{self._name} contributes a link with no key or name")
        try:
            catalogs.register(self._name, wanted, str(name).strip(), str(subject or ""),
                              link)
        except ValueError as exc:
            raise ContractError(str(exc)) from exc


class ExtensionTokens:
    """Names a user may write into a command, brought by this extension.

    Stored as `<extension>.<name>`.
    """

    # The two moments a command runs, so an extension names one without importing core.
    VPINFE = "vpinfe"
    TABLE = "table"

    def __init__(self, name: str) -> None:
        self._name = name

    def offer(self, name: str, contexts: Iterable[str], value: Callable[[dict], str], *,
              says: str = "", after_only: bool = False) -> str:
        """Answer with the full name, which is what a user types. What it stands for is
        `says`, or `token.<name>.says` in the extension's own catalog."""
        from common import tokens

        try:
            return tokens.register(self._name, name, frozenset(contexts), value,
                                   says=says, after_only=after_only)
        except ValueError as exc:
            raise ContractError(str(exc)) from exc


class ExtensionJobs:
    """Slow work, run the way core runs it.

    The kind carries the extension's name, so a job somebody is watching says which
    extension is doing it - the same reason the log namespace does. One at a time per
    kind, which is core's rule and is right here too: two imports of one library at once
    would race each other into the same folders.
    """

    def __init__(self, name: str) -> None:
        self._name = name

    def submit(self, kind: str, work: Callable[[jobs.Job], object], *,
               stoppable: bool = False, keep_result: bool = False) -> jobs.Job:
        """Run `work` on its own thread. With `stoppable`, the job offers to be stopped
        (core answers that on the extension's write scope): the work looks at
        `job.halt` between its units and ends early when it is set. With `keep_result`
        what `work` returns is written to disk, so the Jobs view can open it after the page
        that started the job has gone; `job.problems` says how many parts did not come
        across."""
        from common import jobs

        return jobs.submit(
            f"{self._name}.{str(kind or '').strip()}", work,
            stop_link=f"/api/v1/ext/{self._name}/jobs/{str(kind or '').strip()}/stop"
            if stoppable else "",
            keep_result=keep_result)

    def stop(self, kind: str) -> bool:
        """Ask this extension's running job of that kind to end early. False where there
        is none, or where it was not started `stoppable`."""
        from common import jobs

        running = [one for one in jobs.active(f"{self._name}.{str(kind or '').strip()}")
                   if one.stoppable]
        for job in running:
            job.halt.set()
        return bool(running)

    def active(self) -> tuple[str, ...]:
        from common import jobs

        return tuple(job.id for job in jobs.active()
                     if job.kind.startswith(f"{self._name}."))


class ExtensionContext:
    """What `register(ctx)` is given."""

    def __init__(self, manifest: Manifest, store: ExtensionStore,
                 on_failure: Callable[..., None], directory: Path | None = None) -> None:
        self.name = manifest.name
        self.manifest = manifest
        self.logger = logger_for(manifest.name)
        self.config = ExtensionConfig(manifest.name, store,
                                      lambda: self.ui.settings_defaults())
        self.events = ExtensionEvents(manifest.name, manifest.events, on_failure)
        self.files = ExtensionFiles(manifest.name, "fs:read" in manifest.capabilities,
                                    "fs:write" in manifest.capabilities)
        self.jobs = ExtensionJobs(manifest.name)
        self.ui = ExtensionUI(manifest.name, "ui:mount" in manifest.capabilities)
        self.players = ExtensionPlayers(manifest.name, manifest.scopes, store, self.ui)
        self.entries = ExtensionEntries(manifest.name)
        self.catalogs = ExtensionCatalogs(manifest.name)
        self.tokens = ExtensionTokens(manifest.name)
        self.games = ExtensionGames(manifest.name, manifest.scopes, self.files)
        self.apps = ExtensionApps(manifest.name, manifest.scopes, directory)
        # Which program this is, for an extension that has to say so to somebody else.
        # Through the context rather than an import: the one module an extension may
        # import is the contract, and that is what makes the boundary checkable.
        from common.vpinfe_version import get_version

        self.host_version = get_version()
        self.routers: list[tuple[Any, str]] = []
        # Registration is a moment, not a phase: routers are mounted once, so one added
        # after `register` returned would never be reachable and silently answer nothing.
        self.open = True

    def t(self, key: str, /, **params: Any) -> str:
        """What this extension's `i18n/<language>.json` says for `key`, in the language
        now set: a wizard's title, a field's label, a sentence a route answers with."""
        return words(self.name)(key, **params)

    def why(self, exc: BaseException, /, at: str | os.PathLike[str] = "") -> str:
        """What core says under a failure of its own: `contract.why`."""
        return worded(exc, at)

    def scope(self, action: str) -> str:
        """The scope for one of this extension's own actions."""
        return f"ext:{self.name}:{str(action or '').strip()}"

    def add_router(self, router: Any, *, scope: str) -> None:
        """Offer routes under `/api/v1/ext/<name>/`, gated on this extension's `read` or
        `write` scope. Core attaches the gate; the extension cannot choose to have none."""
        if not self.open:
            raise ContractError(f"{self.name} added a router after registering")
        allowed = (self.scope("read"), self.scope("write"))
        if scope not in allowed:
            raise ContractError(f"{self.name} gates a router on {scope!r}; its scopes "
                                f"are {' and '.join(allowed)}")
        self.routers.append((router, scope))
