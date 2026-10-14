"""What core answers when the Console asks for something an extension declared.

An extension hands core fields, rows and functions; the routes are core's. Each handler
here reads the declaration of one running extension, calls the function it named, and
answers in the shape the Console already reads. Nothing in this module imports a web
framework: the router that carries these over HTTP is `httpapi/extensions_served.py`.

A function the extension supplied that raises is the extension's refusal or its failure,
never core's fault: it becomes an `ExtensionError` carrying the line `ctx.why` words, and
the API answers with that line without disabling the extension. A request core can tell
is wrong before it calls anything raises `NotFoundError` or `RefusedError` instead.
"""

from __future__ import annotations

import inspect
import json
import logging
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from common import failures, i18n
from common.service_errors import NotFoundError, RefusedError, ServiceError

from . import contract
from .fields import FieldError, dialog_fields, dialog_step

if TYPE_CHECKING:
    from .host import Record


class ExtensionError(ServiceError):
    """A function an extension supplied raised. `unreachable` says the service it was
    reaching did not answer, and `field` names the setting a refusal belongs under."""

    def __init__(self, message: str, *, unreachable: bool = False, field: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.unreachable = unreachable
        self.field = field


def said(record: Record, suffix: str, fallback: str = "", **params: Any) -> str:
    """What the extension says for `suffix` in its own catalog, else `fallback`."""
    found = i18n.first_key(f"ext.{record.name}.{suffix}")
    return i18n.t(found, **params) if found else fallback


def called(record: Record, at: str, function: Callable[..., Any], *args: Any,
           **kwargs: Any) -> Any:
    """Call something the extension supplied, turning whatever it raises into the line a
    person reads. An error raised `from` a failure to reach a service counts as one."""
    try:
        return function(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - an extension's raise is its answer
        line = contract.why(exc, at)
        logging.getLogger(f"vpinfe.ext.{record.name}").warning(
            "%s failed: %s", at, line, exc_info=True)
        raise ExtensionError(line, unreachable=_unreachable(exc)) from exc


def _unreachable(exc: BaseException | None) -> bool:
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        if isinstance(exc, contract.Unavailable) or failures.upstream(exc):
            return True
        seen.add(id(exc))
        exc = exc.__cause__
    return False


def plain(record: Record, at: str, value: Any) -> Any:
    """`value` as JSON would carry it, so a row core cannot encode is the extension's
    failure to answer and not a server error that gets the extension disabled."""
    try:
        return json.loads(json.dumps(value))
    except (TypeError, ValueError, RecursionError) as exc:
        raise ExtensionError(i18n.t("error.extensions.not_data", display=record.display_name,
                                     at=at)) from exc


def _extras(function: Callable[..., Any], **offered: Any) -> dict[str, Any]:
    """The keyword arguments `function` names among those on offer."""
    try:
        named = inspect.signature(function).parameters
    except (TypeError, ValueError):
        return {}
    return {key: value for key, value in offered.items() if key in named}


def _context(record: Record) -> Any:
    if record.context is None:
        raise NotFoundError(i18n.t("error.extensions.not_running",
                                   display=record.display_name, value=record.reason))
    return record.context


# -- settings --------------------------------------------------------------------------


def _held(record: Record) -> dict[str, str]:
    return _context(record).config.all()


def _setting(record: Record, one: dict, held: dict[str, str]) -> dict:
    key, kind, default = one["key"], one["type"], one["default"]
    stored = held.get(key) or ""
    out: dict[str, Any] = {
        "key": key, "type": kind, "label": said(record, f"settings.{key}.label", key),
        "help": said(record, f"settings.{key}.help", default=default)}
    if kind == "secret":
        out["set"] = bool(stored)
    elif kind == "switch":
        out["value"] = (stored or default) == "true"
    elif kind == "select":
        out["value"] = stored or default
        out["choices"] = [[value, said(record, f"settings.{key}.choice.{value}", label)]
                          for value, label in one["choices"]]
    else:
        out["value"] = stored
        out["placeholder"] = default
    return out


def settings_read(record: Record) -> dict:
    held = _held(record)
    return {"fields": [_setting(record, one, held)
                       for one in _context(record).ui.settings_declared]}


def settings_write(record: Record, values: dict) -> dict:
    context = _context(record)
    declared = {one["key"]: one for one in context.ui.settings_declared}
    changes: dict[str, str] = {}
    for key, value in (values or {}).items():
        one = declared.get(key)
        if one is None:
            raise RefusedError(i18n.t("error.extensions.no_setting", key=key))
        text = "" if value is None else str(value)
        if one["type"] == "secret" and not text:
            continue
        if one["type"] == "switch":
            text = "true" if value in (True, "true") else "false"
        if one["type"] == "select" and text not in {choice[0] for choice in one["choices"]}:
            raise RefusedError(i18n.t("error.extensions.bad_choice", key=key, value=text))
        changes[key] = text
    check = context.ui.settings_check
    if check is not None and changes:
        held = _held(record)
        after = {key: changes.get(key, held.get(key, "")) or one["default"]
                 for key, one in declared.items()}
        try:
            called(record, "settings", check, after)
        except ExtensionError as exc:
            exc.field = next(iter(changes))
            raise
    for key, text in changes.items():
        context.config.set(key, text)
    return settings_read(record)


# -- lists -----------------------------------------------------------------------------


def _list(record: Record, key: str) -> Any:
    found = _context(record).ui.list_functions.get(key)
    if found is None:
        raise NotFoundError(i18n.t("error.extensions.no_list", display=record.display_name,
                                   key=key))
    return found


def list_rows(record: Record, key: str) -> dict:
    functions = _list(record, key)
    rows = plain(record, f"list {key}", called(record, f"list {key}", functions.rows))
    if not isinstance(rows, list) or not all(isinstance(one, dict) for one in rows):
        raise ExtensionError(i18n.t("error.extensions.not_rows",
                                     display=record.display_name, key=key))
    seen: set[str] = set()
    for row in rows:
        if row.get("id") in (None, ""):
            row.pop("id", None)
            continue
        row["id"] = str(row["id"])
        if row["id"] in seen:
            raise ExtensionError(i18n.t("error.extensions.duplicate_row_id",
                                         display=record.display_name, key=key, id=row["id"]))
        seen.add(row["id"])
    return {"rows": rows}


def _acts(record: Record, key: str, functions: Any) -> dict[str, Any]:
    acts = functions.acts
    if callable(acts):
        acts = called(record, f"list {key} acts", acts)
    return dict(acts or {})


def list_about(record: Record, key: str) -> dict:
    functions = _list(record, key)
    status = ""
    if functions.status is not None:
        status = plain(record, f"list {key} status",
                       called(record, f"list {key} status", functions.status)) or ""
    offered = []
    for act, what in _acts(record, key, functions).items():
        label = said(record, f"list.{key}.act.{act}.label", act)
        offered.append({"key": act, "label": label,
                        **({"url": str(what)} if isinstance(what, str) else {})})
    return {"status": status, "acts": offered}


def list_act(record: Record, key: str, act: str) -> dict:
    functions = _list(record, key)
    what = _acts(record, key, functions).get(act)
    if what is None or isinstance(what, str):
        raise NotFoundError(i18n.t("error.extensions.no_act", display=record.display_name,
                                   key=act))
    return _message(record, f"list {key} act {act}", called(record, f"list {key} act {act}",
                                                             what))


def list_verb(record: Record, key: str, verb: str, ids: list[str]) -> dict:
    """Run one of a list's verbs on the rows with these ids, as the list holds them now.
    The rows a verb's `needs` field is false on are left out, and a verb with none left
    refuses."""
    functions = _list(record, key)
    chosen = functions.verbs.get(verb)
    if chosen is None or chosen["run"] is None:
        raise NotFoundError(i18n.t("error.extensions.no_verb", display=record.display_name,
                                   key=verb))
    wanted = list(dict.fromkeys(ids))
    if not wanted or (chosen["one"] and len(wanted) != 1):
        raise RefusedError(i18n.t("error.extensions.verb_rows", display=record.display_name,
                                  key=verb))
    held = {row["id"]: row for row in list_rows(record, key)["rows"] if "id" in row}
    gone = [one for one in wanted if one not in held]
    if gone:
        raise NotFoundError(i18n.t("error.extensions.no_row", display=record.display_name,
                                   id=gone[0]))
    rows = [held[one] for one in wanted if not chosen["needs"] or held[one].get(chosen["needs"])]
    if not rows:
        raise RefusedError(said(record, f"list.{key}.verb.{verb}.needs",
                                i18n.t("error.extensions.verb_needs",
                                       display=record.display_name, key=verb)))
    at = f"list {key} verb {verb}"
    return _message(record, at, called(record, at, chosen["run"], rows))


def _message(record: Record, at: str, result: Any) -> dict:
    if result is None:
        return {}
    if isinstance(result, str):
        return {"message": result}
    return plain(record, at, result)


# -- dialogs ---------------------------------------------------------------------------


class Progress:
    """How far a dialog's `run` has got, for the page that waits on it."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stage = ""
        self._message = ""
        self._done = 0
        self._total = 0

    def stage(self, name: str, message: str = "", total: int = 0) -> None:
        with self._lock:
            self._stage, self._message, self._done, self._total = name, message, 0, total

    def advance(self, done: int | None = None, message: str | None = None) -> None:
        with self._lock:
            self._done = self._done + 1 if done is None else done
            if message is not None:
                self._message = message

    def clear(self) -> None:
        self.stage("")

    def snapshot(self) -> dict:
        with self._lock:
            return {"stage": self._stage, "message": self._message, "done": self._done,
                    "total": self._total}


_progress: dict[tuple[str, str], Progress] = {}
_progress_lock = threading.Lock()


def _tracker(record: Record, key: str) -> Progress:
    with _progress_lock:
        return _progress.setdefault((record.name, key), Progress())


def _dialog(record: Record, key: str) -> Any:
    found = _context(record).ui.action_objects.get(key)
    if found is None:
        raise NotFoundError(i18n.t("error.extensions.no_action", display=record.display_name,
                                   key=key))
    return found


def _titled(record: Record, key: str, answer: Any) -> dict:
    """A step answer with its fields checked, and the action's own label as the title it
    did not give."""
    if not isinstance(answer, dict):
        raise ExtensionError(i18n.t("error.extensions.bad_answer",
                                     display=record.display_name, key=key))
    try:
        dialog_step(record.name, answer)
        dialog_fields(record.name, answer.get("fields") or [])
    except FieldError as exc:
        raise ExtensionError(str(exc)) from exc
    if not answer.get("title"):
        declared: dict = next((one for one in _context(record).ui.actions
                               if one["key"] == key), {})
        answer = {**answer, "title": said(record, f"action.{key}.label",
                                          declared.get("label") or key)}
    return answer


def dialog_ask(record: Record, key: str, step: str = "") -> dict:
    """The step to draw. A dialog with no `check` has no step after this one, so the step is
    the last and its button is the title."""
    dialog = _dialog(record, key)
    answer = _titled(record, key, plain(record, f"action {key}",
                                        called(record, f"action {key}", dialog.ask, step)))
    if not hasattr(dialog, "check") and not (answer.get("summary") or answer.get("confirm")):
        answer = {**answer, "confirm": answer["title"]}
    return answer


def dialog_check(record: Record, key: str, values: dict, step: str = "") -> dict:
    check = getattr(_dialog(record, key), "check", None)
    if check is None:
        return dialog_ask(record, key, step)
    answer = called(record, f"action {key} check", check, values or {},
                    **_extras(check, step=step))
    if answer is None:
        return dialog_ask(record, key, step)
    return _titled(record, key, plain(record, f"action {key} check", answer))


def dialog_act(record: Record, key: str, act: str, values: dict, step: str = "") -> dict:
    do = getattr(_dialog(record, key), "act", None)
    if do is None:
        raise NotFoundError(i18n.t("error.extensions.no_act", display=record.display_name,
                                   key=act))
    answer = called(record, f"action {key} act {act}", do, act, values or {},
                    **_extras(do, step=step))
    if answer is None:
        return dialog_ask(record, key, step)
    return _titled(record, key, plain(record, f"action {key} act {act}", answer))


def dialog_run(record: Record, key: str, values: dict, step: str = "") -> dict:
    run = getattr(_dialog(record, key), "run", None)
    if run is None:
        raise NotFoundError(i18n.t("error.extensions.no_run", display=record.display_name,
                                   key=key))
    tracker = _tracker(record, key)
    try:
        answer = called(record, f"action {key} run", run, values or {},
                        **_extras(run, step=step, progress=tracker))
    finally:
        tracker.clear()
    return _message(record, f"action {key} run", answer)


def dialog_progress(record: Record, key: str) -> dict:
    own = getattr(_dialog(record, key), "progress", None)
    if own is None:
        return _tracker(record, key).snapshot()
    return plain(record, f"action {key} progress",
                 called(record, f"action {key} progress", own) or {})


def job_stop(record: Record, kind: str) -> dict:
    """Ask the extension's running job of that kind to end after the unit in hand."""
    return {"stopped": _context(record).jobs.stop(kind)}


# -- accounts --------------------------------------------------------------------------


def _account(record: Record) -> Any:
    found = _context(record).ui.account_functions
    if found is None:
        raise NotFoundError(i18n.t("error.extensions.no_account", display=record.display_name))
    return found


def account_read(record: Record, player_id: str) -> dict:
    return plain(record, "account", called(record, "account", _account(record).read,
                                           player_id))


def account_write(record: Record, player_id: str, values: dict) -> dict:
    write = _account(record).write
    if write is None:
        raise RefusedError(i18n.t("error.extensions.account_read_only",
                                  display=record.display_name))
    answer = called(record, "account write", write, player_id, values or {})
    if isinstance(answer, dict):
        return plain(record, "account write", answer)
    return account_read(record, player_id)


def account_act(record: Record, player_id: str, act: str) -> dict:
    do = _account(record).acts.get(act)
    if do is None:
        raise NotFoundError(i18n.t("error.extensions.no_act", display=record.display_name,
                                   key=act))
    answer = called(record, f"account act {act}", do, player_id)
    if answer is None:
        return account_read(record, player_id)
    return _message(record, f"account act {act}", answer)


def account_card(record: Record, player_id: str) -> dict:
    make = _account(record).card
    answer = called(record, "account card", make, player_id) if make else None
    if answer is None:
        raise NotFoundError(i18n.t("error.extensions.no_card", display=record.display_name))
    return plain(record, "account card", answer)


def account_read_card(record: Record, card: Any) -> dict:
    read = _account(record).read_card
    if read is None:
        raise NotFoundError(i18n.t("error.extensions.no_read_card", display=record.display_name))
    return plain(record, "account card", called(record, "account card", read, card))


def account_available(record: Record, candidate: str) -> dict:
    check = _account(record).available
    if check is None:
        raise NotFoundError(i18n.t("error.extensions.no_available", display=record.display_name))
    return {"available": bool(called(record, "account available", check, candidate))}


__all__ = [
    "ExtensionError", "Progress", "account_act", "account_available",
    "account_card", "account_read", "account_read_card", "account_write", "called",
    "dialog_act", "dialog_ask", "dialog_check", "dialog_progress", "dialog_run",
    "list_about", "list_act", "list_rows", "plain", "said", "settings_read",
    "settings_write",
]
