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
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from common import failures, i18n, sized_media
from common.service_errors import NotFoundError, RefusedError, ServiceError

from . import contract, pane, pictures
from .fields import FieldError, dialog_fields, dialog_step, listed, number_text, ticked

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
    elif kind in ("select", "multi"):
        out["value"] = (stored or default) if kind == "select" else ticked(stored or default)
        out["choices"] = [[value, said(record, f"settings.{key}.choice.{value}", label)]
                          for value, label in one["choices"]]
    elif kind == "number":
        out["value"] = stored or default
        out.update({bound: one[bound] for bound in ("min", "max", "unit") if bound in one})
    else:
        out["value"] = stored
        out["placeholder"] = default
        if kind == "path":
            out["wants"] = one["wants"]
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
        kind = one["type"]
        text = "" if value is None else str(value)
        if kind == "secret" and value is not None and not text.strip():
            continue
        if kind == "switch":
            text = "true" if value in (True, "true") else "false"
        offered = {choice[0] for choice in one["choices"]}
        if kind == "select" and text not in offered:
            raise RefusedError(i18n.t("error.extensions.bad_choice", key=key, value=text))
        if kind == "multi":
            chosen = ticked(value)
            if value not in ("", None) and listed(value) is None:
                raise RefusedError(i18n.t("error.extensions.bad_choice", key=key,
                                          value=text))
            for each in chosen:
                if each not in offered:
                    raise RefusedError(i18n.t("error.extensions.bad_choice", key=key,
                                              value=each))
            text = json.dumps(chosen)
        if kind == "number" and text.strip():
            counted = number_text(text, one)
            if counted is None:
                raise RefusedError(i18n.t("error.extensions.bad_number", key=key, value=text))
            text = counted
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


def list_rows(record: Record, key: str, *, addressed: bool = True) -> dict:
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
    if addressed:
        _addressed(record, key, rows)
    return {"rows": rows}


def _addressed_facts(record: Record, facts: list[dict]) -> None:
    """Turn each picture a fact names into the address core serves it from. Raises
    `OutboundNotDeclaredError` for a web address the extension did not declare."""
    for fact in facts:
        if fact["kind"] == "picture":
            fact["value"] = pictures.address(record, fact["value"])
        elif fact["picture"]:
            fact["picture"] = pictures.address(record, fact["picture"])


def _addressed(record: Record, key: str, rows: list[dict]) -> None:
    declared = next((one for one in record.declared_lists if one["key"] == key), {})
    fields = list(dict.fromkeys(
        column["field"] if column["kind"] == "picture" else column.get("picture")
        for column in declared.get("columns", [])
        if column["kind"] == "picture" or column.get("picture")))
    for field in fields:
        for row in rows:
            try:
                row[field] = pictures.address(record, row.get(field))
            except pictures.OutboundNotDeclaredError as exc:
                raise ExtensionError(i18n.t(
                    "error.extensions.picture_outbound",
                    display=record.display_name, key=f"list {key}")) from exc


def picture(record: Record, picture_id: str) -> sized_media.Served:
    return pictures.served(record, picture_id)


def _acts(record: Record, kind: str, key: str, functions: Any) -> dict[str, Any]:
    acts = functions.acts
    if callable(acts):
        acts = called(record, f"{kind} {key} acts", acts)
    return dict(acts or {})


def _menu(record: Record, kind: str, key: str, functions: Any) -> list[dict]:
    """The title menu of a list or a page: each act with its label and, where it opens
    something, what."""
    offered = []
    for act, what in _acts(record, kind, key, functions).items():
        label = said(record, f"{kind}.{key}.act.{act}.label", act)
        opens = what.get("action") if isinstance(what, dict) else None
        if opens is not None and opens not in _context(record).ui.action_objects:
            raise ExtensionError(i18n.t("error.extensions.no_action",
                                         display=record.display_name, key=opens))
        offered.append({"key": act, "label": label,
                        **({"url": str(what)} if isinstance(what, str) else {}),
                        **({"action": str(opens)} if opens is not None else {})})
    return offered


def _act(record: Record, kind: str, key: str, functions: Any, act: str) -> dict:
    what = _acts(record, kind, key, functions).get(act)
    if what is None or isinstance(what, (str, dict)):
        raise NotFoundError(i18n.t("error.extensions.no_act", display=record.display_name,
                                   key=act))
    return _message(record, f"{kind} {key} act {act}",
                    called(record, f"{kind} {key} act {act}", what))


def list_about(record: Record, key: str) -> dict:
    functions = _list(record, key)
    status = ""
    if functions.status is not None:
        status = plain(record, f"list {key} status",
                       called(record, f"list {key} status", functions.status)) or ""
    return {"status": status, "acts": _menu(record, "list", key, functions)}


def list_act(record: Record, key: str, act: str) -> dict:
    return _act(record, "list", key, _list(record, key), act)


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
    held = {row["id"]: row for row in list_rows(record, key, addressed=False)["rows"]
            if "id" in row}
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


def _detail(record: Record, key: str) -> Any:
    found = _list(record, key).detail
    if found is None:
        raise NotFoundError(i18n.t("error.extensions.no_detail", display=record.display_name,
                                   key=key))
    return found


def list_detail(record: Record, key: str, row_id: str) -> dict:
    """What the pane shows for a row: the extension's `detail(row_id)`, checked, with each
    picture turned into core's own address and each secret held back."""
    at = f"list {key} detail"
    answer = plain(record, at, called(record, at, _detail(record, key), row_id))
    if answer is None:
        raise NotFoundError(i18n.t("error.extensions.no_row", display=record.display_name,
                                   id=row_id))
    try:
        shown = pane.shaped(answer, row_id)
    except pane.PaneError as exc:
        raise ExtensionError(i18n.t(exc.line, display=record.display_name, id=row_id,
                                    **exc.params)) from exc
    try:
        if shown["picture"]:
            shown["picture"] = pictures.address(record, shown["picture"])
        for section in shown["sections"]:
            _addressed_facts(record, section["facts"])
    except pictures.OutboundNotDeclaredError as exc:
        raise ExtensionError(i18n.t("error.extensions.picture_outbound",
                                    display=record.display_name, key=f"list {key}")) from exc
    return shown


def list_save(record: Record, key: str, row_id: str, values: dict) -> dict:
    """Write the fields a pane offers for a row, then answer the pane as it stands. The
    keys must be fields the extension's own answer offers now."""
    functions = _list(record, key)
    if functions.save is None:
        raise NotFoundError(i18n.t("error.extensions.no_save", display=record.display_name,
                                   key=key))
    offered = [one for section in list_detail(record, key, row_id)["sections"]
               for one in section["fields"]]
    changes = pane.accepted(
        offered, values or {},
        lambda line, **params: RefusedError(i18n.t(line, display=record.display_name,
                                                   **params)))
    if changes:
        try:
            called(record, f"list {key} save", functions.save, row_id, changes)
        except ExtensionError as exc:
            exc.field = next(iter(changes))
            raise
    return list_detail(record, key, row_id)


# -- pages -----------------------------------------------------------------------------


def _page(record: Record, key: str) -> Any:
    found = _context(record).ui.page_functions.get(key)
    if found is None:
        raise NotFoundError(i18n.t("error.extensions.no_page", display=record.display_name,
                                   key=key))
    return found


def page_read(record: Record, key: str) -> dict:
    """A page as the Console draws it: the extension's `read()`, checked, with each picture
    turned into core's own address and each secret held back."""
    at = f"page {key}"
    answer = plain(record, at, called(record, at, _page(record, key).read))
    try:
        shown = pane.shaped(answer, key)
    except pane.PaneError as exc:
        raise ExtensionError(i18n.t(exc.line, display=record.display_name, id=f"its page {key}",
                                    **exc.params)) from exc
    try:
        if shown["picture"]:
            shown["picture"] = pictures.address(record, shown["picture"])
        for section in shown["sections"]:
            _addressed_facts(record, section["facts"])
    except pictures.OutboundNotDeclaredError as exc:
        raise ExtensionError(i18n.t("error.extensions.picture_outbound",
                                    display=record.display_name, key=at)) from exc
    return shown


def page_save(record: Record, key: str, values: dict) -> dict:
    """Write the fields a page offers, then answer the page as it stands. The keys must be
    fields the extension's own answer offers now."""
    functions = _page(record, key)
    if functions.save is None:
        raise NotFoundError(i18n.t("error.extensions.no_page_save",
                                   display=record.display_name, key=key))
    offered = [one for section in page_read(record, key)["sections"]
               for one in section["fields"]]
    changes = pane.accepted(
        offered, values or {},
        lambda line, **params: RefusedError(i18n.t(line, display=record.display_name,
                                                   **params)))
    if changes:
        try:
            called(record, f"page {key} save", functions.save, changes)
        except ExtensionError as exc:
            exc.field = next(iter(changes))
            raise
    return page_read(record, key)


def page_about(record: Record, key: str) -> dict:
    return {"acts": _menu(record, "page", key, _page(record, key))}


def page_act(record: Record, key: str, act: str) -> dict:
    return _act(record, "page", key, _page(record, key), act)


# -- panel groups ----------------------------------------------------------------------

def _group(record: Record, subject: str) -> Any:
    found = _context(record).ui.group_functions.get(subject)
    if found is None:
        raise NotFoundError(i18n.t("error.extensions.no_group", display=record.display_name,
                                   subject=subject))
    return found


def group_read(record: Record, subject: str, who: dict) -> dict:
    """The group on a game's or table's panel: its heading, and the one section the
    extension answered with, or None where it has nothing to say. `who` is the subject core
    chose to ask about."""
    functions = _group(record, subject)
    at = f"{subject} group"
    answer = plain(record, at, called(record, at, functions.read, dict(who)))
    try:
        section = pane.grouped(answer)
    except pane.PaneError as exc:
        raise ExtensionError(i18n.t(exc.line, display=record.display_name,
                                    id=f"its {subject} group", **exc.params)) from exc
    try:
        _addressed_facts(record, (section or {}).get("facts", []))
    except pictures.OutboundNotDeclaredError as exc:
        raise ExtensionError(i18n.t("error.extensions.picture_outbound",
                                    display=record.display_name, key=at)) from exc
    title = next((one["title"] for one in record.groups() if one["subject"] == subject), "")
    return {"title": title, "section": section}


def group_save(record: Record, subject: str, who: dict, values: dict) -> dict:
    """Write the fields a group offers for a subject, then answer the group as it stands.
    The keys must be fields the extension's own answer offers now."""
    functions = _group(record, subject)
    if functions.save is None:
        raise NotFoundError(i18n.t("error.extensions.no_group_save",
                                   display=record.display_name, subject=subject))
    offered = (group_read(record, subject, who)["section"] or {}).get("fields", [])
    changes = pane.accepted(
        offered, values or {},
        lambda line, **params: RefusedError(i18n.t(line, display=record.display_name,
                                                   **params)))
    if changes:
        try:
            called(record, f"{subject} group save", functions.save, dict(who), changes)
        except ExtensionError as exc:
            exc.field = next(iter(changes))
            raise
    return group_read(record, subject, who)


def needs_read(record: Record) -> list[dict]:
    """What this extension asks for on Overview now, one row for each declared kind that
    holds, worded in the language set. A kind holds when it names ids or a count above zero.
    `covered` is what a dismissal of the row is kept against: the ids, else the token the
    extension gave, else the kind."""
    functions = _context(record).ui
    if functions.needs_function is None:
        return []
    answer = plain(record, "needs", called(record, "needs", functions.needs_function))
    if not isinstance(answer, list):
        raise ExtensionError(i18n.t("error.extensions.needs_shape", display=record.display_name))
    declared = {one["kind"]: one for one in record.declared_needs}
    out: list[dict] = []
    for one in answer:
        kind = one.get("kind") if isinstance(one, dict) else None
        if not isinstance(kind, str) or kind not in declared:
            raise ExtensionError(i18n.t("error.extensions.need_unknown",
                                        display=record.display_name, kind=str(kind)))
        try:
            ids = [str(each) for each in one.get("ids") or [] if str(each)]
            count = len(ids) or int(one.get("count") or 0)
            given = one.get("token")
            token = [str(each) for each in (given if isinstance(given, list) else [given])
                     if each is not None and str(each)]
        except (TypeError, ValueError, OverflowError) as exc:
            raise ExtensionError(i18n.t("error.extensions.needs_shape",
                                        display=record.display_name)) from exc
        if any(row["kind"] == kind for row in out):
            raise ExtensionError(i18n.t("error.extensions.needs_shape",
                                        display=record.display_name))
        if count <= 0:
            continue
        found = declared[kind]
        out.append({
            "extension": record.name, "display_name": record.display_name, "kind": kind,
            "key": f"ext:{record.name}:{kind}",
            "label": said(record, f"need.{kind}.label", record.display_name, count=count),
            "says": said(record, f"need.{kind}.says", "", count=count),
            "tone": found["tone"], "opens": found["opens"], "to": found["to"],
            "count": count, "covered": ids or token or [str(kind)]})
    return out


def needs_all(records: Sequence[Record]) -> dict:
    """The needs of every running extension that declared some. `away` names the extensions
    that gave none this time - not running, or failing to answer - so the dismissals kept
    against them are left alone; `failed` is the ones that raised."""
    rows: list[dict] = []
    away: list[str] = []
    failed: list[str] = []
    for record in records:
        if not record.running:
            away.append(record.name)
            continue
        if not record.declared_needs:
            continue
        try:
            rows += needs_read(record)
        except ExtensionError:
            away.append(record.name)
            failed.append(record.name)
    return {"needs": rows, "away": away, "failed": failed}


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
    if any(isinstance(one, dict) and one.get("key") == "rows"
           for one in answer.get("fields") or []):
        raise ExtensionError(i18n.t("error.extensions.rows_field", display=record.display_name))
    if not answer.get("title"):
        declared: dict = next((one for one in _context(record).ui.actions
                               if one["key"] == key), {})
        answer = {**answer, "title": said(record, f"action.{key}.label",
                                          declared.get("label") or key)}
    return answer


def _chosen(values: dict | None) -> list[str]:
    """The ids of the rows a dialog was opened over, which travel in its values."""
    rows = (values or {}).get("rows")
    return [str(one) for one in rows] if isinstance(rows, list) else []


def dialog_ask(record: Record, key: str, step: str = "",
               rows: Sequence[str] = ()) -> dict:
    """The step to draw. A dialog with no `check` has no step after this one, so the step is
    the last and its button is the title. `rows` are the ids of the rows it was opened
    over, handed to an `ask` that names them."""
    dialog = _dialog(record, key)
    answer = _titled(record, key, plain(record, f"action {key}", called(
        record, f"action {key}", dialog.ask, step, **_extras(dialog.ask, rows=list(rows)))))
    if not hasattr(dialog, "check") and not (answer.get("summary") or answer.get("confirm")):
        answer = {**answer, "confirm": answer["title"]}
    return answer


def dialog_check(record: Record, key: str, values: dict, step: str = "") -> dict:
    check = getattr(_dialog(record, key), "check", None)
    if check is None:
        return dialog_ask(record, key, step, _chosen(values))
    answer = called(record, f"action {key} check", check, values or {},
                    **_extras(check, step=step))
    if answer is None:
        return dialog_ask(record, key, step, _chosen(values))
    return _titled(record, key, plain(record, f"action {key} check", answer))


def dialog_act(record: Record, key: str, act: str, values: dict, step: str = "") -> dict:
    do = getattr(_dialog(record, key), "act", None)
    if do is None:
        raise NotFoundError(i18n.t("error.extensions.no_act", display=record.display_name,
                                   key=act))
    answer = called(record, f"action {key} act {act}", do, act, values or {},
                    **_extras(do, step=step))
    if answer is None:
        return dialog_ask(record, key, step, _chosen(values))
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
