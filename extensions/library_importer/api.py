"""What the importer offers over the API.

Every route is gated on a scope this extension declared; core attaches the gate. Reading
a source is a read, and pointing at a different one is a write - saying where an install
will read from is the decision worth being a separate permission from looking at what is
there.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

from fastapi import APIRouter

from . import adopt, folders, pinballx, popper
from . import plan as plan_for
from .plan import Plan
from .source import SourceGame, SourceLibrary

# Asked in order, first to claim a folder wins. PinballX is looked for first
# because it is the source somebody converting a pinball library actually has. Folders
# is last: a frontend's own folder holds game folders too, and the reader that knows
# its database should be the one that claims it.
READERS = (pinballx, popper, folders)

# Where the source is, in this extension's own settings. Not a core setting: it is a
# fact about somebody's old machine, and it has no meaning to anything else here.
SOURCE_KEY = "source_root"

# The order the questions come in. Which of them get asked depends on what is found, but
# never on how somebody arrived: going Back and forward again asks the same things in
# the same order rather than jumping over what is already answered.
STEPS = ("source", "sources", "existing", "how", "summary")


def _after(step: str) -> tuple[str, ...]:
    """The steps still to come after the one being left."""
    at = STEPS.index(step) if step in STEPS else 0
    return STEPS[at + 1:] or (STEPS[-1],)


def reader_for(root: Path, survey: Callable[..., dict] | None = None) -> ModuleType | None:
    """The reader that claims a folder, or None. First to claim it wins, and readers are
    asked in the order they are declared. `survey` is what tells a game folder from
    any other, for the readers that have no database to ask."""
    return next((one for one in READERS if one.detect(root, survey)), None)


def _once(survey: Callable[..., dict]) -> Callable[..., dict]:
    """`survey`, asking core about a folder once however many times it is asked.

    Made for one request and dropped with it, so a folder changed since is looked at
    again by the next.
    """
    held: dict[str, dict] = {}

    def ask(path: str | Path) -> dict:
        key = str(path)
        if key not in held:
            held[key] = survey(path)
        return held[key]

    return ask


def _trouble_with(ctx: Any, path: Path) -> str:
    """Why a folder cannot be read from, or "" where it can. A folder that is there but
    not open to this install reads as empty to everything below, and "nothing this
    build can read" would be the wrong thing to tell somebody who simply lacks access."""
    if not path.is_dir():
        return ctx.t("reason.unreachable")
    if not os.access(path, os.R_OK | os.X_OK):
        return ctx.t("reason.cannot_read")
    return ""


def _name(ctx: Any, reader: ModuleType) -> str:
    """What a source is called on screen: the catalog's word where it has one, and its
    own name where it is a product's."""
    return ctx.t("source.folders") if reader.SOURCE_ID == folders.SOURCE_ID \
        else reader.SOURCE_NAME


def _systems(values: dict) -> list[str]:
    """Which of the source's systems, or all of them where it was never asked."""
    return [str(one) for one in (values.get("systems") or [])]


def _chosen(values: dict) -> dict | None:
    held = {key: values[key] for key in plan_for.SOURCES if key in values}
    return held or None


def _mode(library: SourceLibrary, values: dict, games: list[SourceGame]) -> str:
    """What happens to the game files, given what is going.

    `copy` or `move` where there is something to carry and nobody has already decided:
    a source that holds game folders is a library folder as it stands, so its loose
    tables get folders where they lie (`in_place`) and a folder with none of those has
    nothing to do but be used (`as_is`). `plain` is a source that names no game file
    at all, which is entries with artwork and nothing to copy or move.
    """
    if library.in_place:
        return "in_place" if games else "as_is"
    if not any(game.table_file for game in games):
        return "plain"
    return "move" if values.get("how") == "move" else "copy"


def _state(ctx: Any, survey: Callable[..., dict] | None = None) -> dict:
    configured = ctx.config.get(SOURCE_KEY, "")
    if not configured:
        return {"path": "", "reachable": False, "source_id": "", "source_name": "",
                "reason": ctx.t("reason.no_source")}
    path = Path(configured)
    trouble = _trouble_with(ctx, path)
    if trouble:
        return {"path": configured, "reachable": False, "source_id": "",
                "source_name": "", "reason": trouble}
    reader = reader_for(path, survey or _once(ctx.games.survey))
    if reader is None:
        return {"path": configured, "reachable": True, "source_id": "",
                "source_name": "", "reason": ctx.t("reason.nothing_readable")}
    return {"path": configured, "reachable": True, "source_id": reader.SOURCE_ID,
            "source_name": _name(ctx, reader), "reason": ""}


def _preview(library: SourceLibrary) -> dict:
    """What was found, counted. The whole library would be megabytes and nobody reads a
    thousand rows to decide whether to go ahead."""
    systems = []
    for system in library.systems:
        with_media = sum(1 for game in system.games if game.media)
        with_table = sum(1 for game in system.games if game.table_file)
        matched = sum(1 for game in system.games if game.vps_id)
        systems.append({
            "name": system.name,
            "games": len(system.games),
            "with_artwork": with_media,
            "with_a_game_file": with_table,
            "already_matched": matched,
            "tables_dir": system.tables_dir,
            "enabled": system.enabled,
        })
    return {"source_id": library.source_id, "root": library.root,
            "systems": systems, "notes": list(library.notes)}


def build(ctx: Any) -> None:
    """Register the routes, and keep what core may read in step with the setting."""
    def follow_the_setting(*extra: str) -> None:
        """Tell core every folder this import will actually read from.

        The install folder is not enough, and assuming it is costs a whole run: a
        frontend keeps its database and artwork under its own roof, but the tables sit
        wherever the emulator was installed, which can be anywhere. Core refuses every
        one of them where the importer resolved the path and never declared it.

        So the roots follow what was resolved, not what was configured. Anything the
        plan points at is a folder this will open, and core cannot know that from the
        source root alone.
        """
        configured = ctx.config.get(SOURCE_KEY, "")
        wanted = [configured] if configured else []
        wanted += [one for one in extra if one]
        ctx.files.set_roots(wanted)

    def declare_roots(library: SourceLibrary, values: dict) -> None:
        """Tell core where this import will read, before anything tries to read there.

        Before the plan, not after it: the plan counts what travels with each table,
        which means opening the tables folder, which core refuses until it has been told
        about it. The source map is derived from the library alone, so it is available
        first and does not need the plan that needs it.
        """
        found = plan_for.derive_sources(library, _chosen(values))
        follow_the_setting(*[source.path for source in found if source.active])

    follow_the_setting()

    def point_at(wanted: str) -> None:
        """Make this the source and declare it, before core is asked anything about it.

        Asking core what a folder holds is refused for a folder not declared, and an
        uncaught refusal in a route disables the extension.
        """
        ctx.config.set(SOURCE_KEY, wanted)
        follow_the_setting()

    def read(reader: ModuleType, path: Path, values: dict,
             survey: Callable[..., dict]) -> SourceLibrary:
        return reader.read(path, ctx.apps.plays, ctx.apps.names(),
                           survey=survey, chosen=_chosen(values))

    def known(library: SourceLibrary) -> list[dict]:
        """Every game already here, and the game folders a source holds in place.

        Those are listed under their folder name, first so a real entry of the same name
        replaces them: a loose table beside a folder of its own name is recognized as
        having one before the folder is a library folder and can say so itself.
        """
        held = [{"game_id": f"in_place:{name}", "folder_name": name}
                for name in library.in_place]
        return held + ctx.games.existing()

    def plan(library: SourceLibrary, values: dict, existing: list[dict]) -> Plan:
        return plan_for.build(library, existing, _chosen(values),
                              str(values.get("on_existing")
                                  or plan_for.DEFAULT_ON_EXISTING),
                              _systems(values), ctx.games.folder_name_for,
                              library.source_id, ctx.games.kinds(),
                              ctx.games.companions_of)

    def path_of(location: str) -> str:
        """Where a location is, or "" where it is not somewhere games can be made.

        Core answers by where games can go: the place new ones go, and every other
        writable library folder.
        """
        found = ctx.games.new_game_destination()
        if not location:
            return "" if found.get("reason") else str(found.get("path") or "")
        return next((str(one.get("path") or "")
                     for one in [found, *(found.get("alternatives") or [])]
                     if one.get("location_id") == location), "")

    def into_of(values: dict, location: str = "") -> str:
        """Where copies go: what was typed, else the location a caller named, else the
        place new games already go."""
        if "into" in values:
            return str(values["into"] or "").strip()
        return path_of(location)

    def space(library: SourceLibrary, values: dict, mode: str,
              games: list[SourceGame]) -> tuple[int, int, str]:
        """Bytes this will write, the room there is for them, and where.

        Asked of the place the games will actually be made, which is the `into` in
        `values`, or the default where there is none. A caller that names a location
        instead has it put in `values` first. Room is -1 where it cannot be told. A move
        writes only the artwork, beside the files; a source with systems on different
        drives is asked at the first.
        """
        if mode not in ("copy", "move", "in_place"):
            return 0, -1, ""
        need = plan_for.bytes_to_copy(games, library.source_id, ctx.games.kinds(),
                                      ctx.games.companions_of, move=mode != "copy")
        target = (into_of(values) if mode == "copy" else
                  next((plan_for.tables_folder(one)
                        for one in plan_for.systems_going(library, games)
                        if plan_for.tables_folder(one)), library.root))
        free, where = plan_for.room_at(target) if target else (-1, "")
        return need, free, where

    def short_of_room(need: int, free: int, where: str) -> str:
        """Why this cannot start for want of room, or "". Said the same at the summary
        and at the run, so the one is not a promise the other breaks."""
        if need > free >= 0:
            return ctx.t("reason.no_room", size=plan_for.size_of(need),
                         free=plan_for.size_of(free), where=where)
        return ""

    reading = APIRouter()

    @reading.get("/source")
    def source() -> dict:
        """Where this install is set to import from, and what is there."""
        return _state(ctx)

    @reading.get("/preview")
    def preview() -> dict:
        """What a scan of the chosen source found. Reads it, writes nothing."""
        survey = _once(ctx.games.survey)
        state = _state(ctx, survey)
        if not state["source_id"]:
            return {"source_id": "", "root": state["path"], "systems": [],
                    "notes": [state["reason"]]}
        reader = next(one for one in READERS if one.SOURCE_ID == state["source_id"])
        return _preview(read(reader, Path(state["path"]), {}, survey))

    writing = APIRouter()

    @writing.put("/source")
    def set_source(body: dict) -> dict:
        """Point at a folder.

        Its own permission, and not because it writes a setting: core reads files under
        this folder while it is set, so choosing it is the moment somebody widens what
        this install will open. Looking at what is already there is not the same act.
        """
        wanted = str(body.get("path") or "").strip()
        ctx.config.set(SOURCE_KEY, wanted)
        follow_the_setting()
        return _state(ctx)

    @reading.get("/wizard")
    def wizard_form() -> dict:
        """Step one: what are you importing from, and where is it.

        The kind is asked rather than only sniffed. Somebody knows what they have, and a
        detector that is wrong leaves them arguing with a guess; offering "work it out"
        as the default means the common case is still one press.
        """
        state = _state(ctx)
        return {
            "step": "source",
            "title": ctx.t("wizard.source.title"),
            "help": ctx.t("wizard.source.help"),
            "fields": [
                {"key": "source_type", "type": "select",
                 "label": ctx.t("wizard.source.source_type.label"),
                 "value": "auto",
                 "choices": [["auto", ctx.t("wizard.source.auto")]]
                            + [[one.SOURCE_ID, _name(ctx, one)] for one in READERS],
                 "help": ctx.t("wizard.source.source_type.help")},
                {"key": "path", "type": "path", "wants": "dir",
                 "label": ctx.t("wizard.source.path.label"),
                 "value": state["path"],
                 "help": ctx.t("wizard.source.path.help")},
            ],
        }

    def _reader_for(values: dict, path: Path,
                    survey: Callable[..., dict]) -> ModuleType | None:
        """The reader this source is to be read with.

        What somebody chose, where they chose; otherwise the first that claims the
        folder. A chosen reader that does not claim it is still used - being told "that
        is not a Popper install" is more useful than quietly reading it as something
        else.
        """
        wanted = str(values.get("source_type") or "auto").strip()
        if wanted and wanted != "auto":
            return next((one for one in READERS if one.SOURCE_ID == wanted), None)
        return reader_for(path, survey)

    @writing.post("/wizard/check")
    def wizard_check(body: dict) -> dict:
        """Whatever comes next: another question, or what it all adds up to."""
        values = body.get("values") or {}
        leaving = str(body.get("step") or "source")
        wanted = str(values.get("path") or "").strip()
        if not wanted:
            return _again(ctx.t("reason.say_where"), values)

        point_at(wanted)
        path = Path(wanted)
        trouble = _trouble_with(ctx, path)
        if trouble:
            return _again(trouble, values)
        survey = _once(ctx.games.survey)
        reader = _reader_for(values, path, survey)
        if reader is None:
            return _again(ctx.t("reason.nothing_readable"), values)
        if not reader.detect(path, survey):
            return _again(ctx.t("reason.not_this_source", source=_name(ctx, reader)),
                          values)

        library = read(reader, path, values, survey)
        declare_roots(library, values)
        made = plan(library, values, known(library))
        games = plan_for.going(library, made, _systems(values))
        mode = _mode(library, values, games)

        if leaving == "how" and mode in ("copy", "move"):
            refused = _refuse_how(values)
            if refused:
                return _how_step(reader, library, values, games, refused)

        for step in _after(leaving):
            if step == "sources":
                return _sources_step(reader, library, made)
            # `skip_existing` is how a caller that knows nothing here can matter, a first
            # run, starts past this question instead of being asked it.
            if step == "existing" and made.already and not values.get("skip_existing"):
                return _existing_step(made)
            if step == "how" and mode in ("copy", "move"):
                return _how_step(reader, library, values, games)
            if step == "summary":
                break
        return _summary_step(reader, library, made, values, games)

    def _again(reason: str, values: dict) -> dict:
        """The source step again - every refusal here is about the folder, so it lands
        under that field rather than under the whole form."""
        found = wizard_form()
        found["errors"] = {"path": reason}
        for field in found["fields"]:
            if field["key"] in values:
                field["value"] = values[field["key"]]
        return found

    def _sources_step(reader: ModuleType, library: SourceLibrary, made: Plan) -> dict:
        fields: list[dict[str, Any]] = [{
            "key": source.key, "type": "path", "label": source.label,
            "value": source.path,
            "help": (ctx.t("wizard.sources.worked_out", help=source.help)
                     if source.derived else source.help),
        } for source in made.sources]

        # Only where there is a choice to make. One system is not a decision, and a
        # control with a single option in it is a question that answers itself.
        systems = [one.name for one in library.systems if one.games]
        if len(systems) > 1:
            fields.insert(0, {
                "key": "systems", "type": "multi",
                "label": ctx.t("wizard.sources.systems.label"),
                "value": systems,
                "choices": [[one, one] for one in systems],
                "help": ctx.t("wizard.sources.systems.help"),
            })

        return {
            "step": "sources",
            "title": ctx.t("wizard.sources.title", source=_name(ctx, reader)),
            "help": ctx.t("wizard.sources.help"),
            "fields": fields,
        }

    def _existing_step(made: Plan) -> dict:
        return {
            "step": "existing",
            "title": ctx.t("wizard.existing.title", count=len(made.already)),
            "help": ctx.t("wizard.existing.help"),
            "fields": [{
                "key": "on_existing", "type": "select",
                "label": ctx.t("wizard.existing.on_existing.label"),
                "value": made.on_existing,
                "choices": [[one, ctx.t(f"on_existing.{one}")]
                            for one in plan_for.ON_EXISTING],
            }],
            "notes": [one.folder for one in made.already[:8]]
                     + ([ctx.t("wizard.existing.more", count=len(made.already) - 8)]
                        if len(made.already) > 8 else []),
        }

    def _refuse_how(values: dict) -> dict[str, str]:
        """What is wrong with the answer to the how step, by field. Moving needs nothing
        more; copying needs a folder to copy into, and one that is there."""
        if values.get("how") == "move":
            return {}
        into = str(values.get("into") or "").strip()
        if not into:
            return {"into": ctx.t("reason.say_into")}
        if not Path(into).expanduser().is_dir():
            return {"into": ctx.t("reason.unreachable")}
        return {}

    def _how_step(reader: ModuleType, library: SourceLibrary, values: dict,
                  games: list[SourceGame], errors: dict[str, str] | None = None) -> dict:
        """Copy or move, and where the copies go.

        Copy is the default: moving leaves whatever else opens those files, a frontend's
        list among it, pointing at files that are gone, and the choice says so before it
        is made.
        """
        folder = Path(library.root).name or library.root
        moving_help = (ctx.t("wizard.how.move.folders_help")
                       if library.source_id == folders.SOURCE_ID
                       else ctx.t("wizard.how.move.frontend_help", source=_name(ctx, reader)))
        into = into_of(values)
        need, free, where = space(library, {**values, "into": into}, "copy", games)
        size = plan_for.size_of(need)
        step: dict[str, Any] = {
            "step": "how",
            "title": ctx.t("wizard.how.title"),
            "help": ctx.t("wizard.how.help", count=sum(1 for one in games if one.table_file),
                          folder=folder),
            "fields": [
                {"key": "how", "type": "choice",
                 "label": ctx.t("wizard.how.how.label"),
                 "value": str(values.get("how") or "copy"),
                 "choices": [
                     ["copy", ctx.t("wizard.how.copy"),
                      ctx.t("wizard.how.copy.help", folder=folder), "content_copy"],
                     ["move", ctx.t("wizard.how.move"),
                      moving_help, "drive_file_move"]]},
                {"key": "into", "type": "path", "wants": "dir",
                 "label": ctx.t("wizard.how.into.label"), "value": into,
                 "opens_at": str(Path(library.root).parent),
                 "help": (ctx.t("wizard.how.into.room", size=size,
                                free=plan_for.size_of(free), where=where)
                          if into and free >= 0
                          else ctx.t("wizard.how.into.needs", size=size))},
            ],
        }
        if errors:
            step["errors"] = errors
        return step

    def _summary_step(reader: ModuleType, library: SourceLibrary, made: Plan,
                      values: dict, games: list[SourceGame]) -> dict:
        """Everything the previous steps decided, and what it comes to."""
        found = _preview(library)
        counts = plan_for.expected(made)
        mode = _mode(library, values, games)
        tables = sum(1 for one in games if one.table_file)
        need, free, where = space(library, values, mode, games)
        short = short_of_room(need, free, where)

        rows = [[ctx.t("wizard.summary.reads_as"), _name(ctx, reader)],
                [ctx.t("wizard.summary.folder"), library.root]]
        rows += [[source.label if source.active else ctx.t(f"kind.{source.key}.none"),
                  source.path or ctx.t("wizard.summary.not_imported")]
                 for source in made.sources]
        if library.in_place:
            rows.append([ctx.t("wizard.summary.as_is"),
                         ctx.t("wizard.summary.game_folders", count=len(library.in_place))])
        if made.already:
            rows.append([ctx.t("wizard.summary.already_here"),
                         ctx.t(f"wizard.summary.already.{made.on_existing}",
                               count=len(made.already))])
        inside = ", ".join(dict.fromkeys(
            plan_for.tables_folder(one) for one in plan_for.systems_going(library, games)
            if plan_for.tables_folder(one))) or library.root
        how, going_into = ctx.t("wizard.summary.how"), ctx.t("wizard.summary.going_into")
        if mode == "copy":
            rows += [[how, ctx.t("wizard.summary.how.copy")], [going_into, into_of(values)]]
        elif mode == "move":
            rows += [[how, ctx.t("wizard.summary.how.move")],
                     [going_into, ctx.t("wizard.how.move.where", folder=inside)]]
        elif mode == "in_place":
            rows += [[how, ctx.t("wizard.summary.how.in_place")],
                     [going_into,
                      ctx.t("wizard.summary.library_folder", folder=library.root)]]
        elif mode == "as_is":
            rows.append([going_into,
                         ctx.t("wizard.summary.library_folder", folder=library.root)])
        else:
            rows.append([going_into, ctx.t("wizard.summary.default_location")])
        if need:
            rows.append([ctx.t("wizard.summary.space"),
                         ctx.t("wizard.summary.space_free", size=plan_for.size_of(need),
                               free=plan_for.size_of(free), where=where)
                         if free >= 0 else plan_for.size_of(need)])
        rows.append([ctx.t("wizard.summary.comes_across")])
        rows += [[ctx.t(f"count.{key}"), str(counts[key])] for key in plan_for.COUNTS]

        ready = bool(games) or mode == "as_is"
        reason = short or ("" if ready else ctx.t("reason.nothing_left"))
        confirm = {
            "copy": lambda: ctx.t("wizard.summary.confirm_copy", count=tables),
            "move": lambda: ctx.t("wizard.summary.confirm_move", count=tables),
            "in_place": lambda: ctx.t("wizard.summary.confirm_in_place", count=tables),
            "as_is": lambda: ctx.t("wizard.summary.confirm_as_is"),
        }.get(mode, lambda: ctx.t("wizard.summary.confirm", count=len(games)))()

        return {
            "step": "summary",
            "title": ctx.t("wizard.summary.title"),
            "ready": ready and not short,
            "reason": reason,
            "summary": rows,
            "notes": [*found["notes"], *made.notes],
            "confirm": confirm,
        }

    @writing.post("/wizard/run", status_code=202)
    def start_import(body: dict) -> dict:
        """Convert the chosen source into game folders. Answers with a job.

        A job because it is slow and because it is the shape everything slow here takes:
        an import of six hundred games is minutes of copying, and a request that waited
        for it would time out somewhere in the middle with no way to ask what happened.
        Progress and the outcome are on /api/v1/jobs, the same as a library scan.
        """
        values = body.get("values") or {}
        wanted = str(values.get("path") or "").strip()
        path = Path(wanted)
        location = str(body.get("location") or "")
        systems = _systems(values)

        def refused(reason: str) -> dict:
            """The shape the Console reads a refusal by: not started, and why."""
            return {"started": False, "ok": False, "reason": reason}

        if not wanted or not path.is_dir():
            return refused(ctx.t("reason.nothing_readable"))
        survey = _once(ctx.games.survey)
        point_at(wanted)
        reader = _reader_for(values, path, survey)
        if reader is None:
            return refused(ctx.t("reason.nothing_readable"))

        library = read(reader, path, values, survey)
        declare_roots(library, values)
        checked = plan_for.going(library, plan(library, values, known(library)), systems)
        mode = _mode(library, values, checked)
        typed_into = "into" in values
        if mode == "copy":
            values = {**values, "into": into_of(values, location)}
            wrong = _refuse_how(values)
            if wrong:
                return refused(wrong["into"])
        short = short_of_room(*space(library, values, mode, checked))
        if short:
            return refused(short)

        def work(job: Any) -> dict:
            job.log(f"Read {len(library.games)} games from {library.root}")
            # First, so the plan below sees the games that are already in it.
            rooted = (ctx.games.use_library_folder(library.root)["location_id"]
                      if library.in_place else "")
            made = plan(library, values, ctx.games.existing())
            games = plan_for.going(library, made, systems)
            mode = _mode(library, values, games)
            where, places = location, {}
            if mode == "copy" and typed_into:
                where = ctx.games.use_library_folder(values["into"])["location_id"]
            elif mode in ("move", "in_place"):
                # Only the systems this run acts on: a deselected one is not a place
                # anyone asked to have registered.
                places = {one.name: rooted or ctx.games.use_library_folder(
                    plan_for.tables_folder(one))["location_id"]
                    for one in plan_for.systems_going(library, games)
                    if plan_for.tables_folder(one)}
            want = plan_for.expected(made)
            report = adopt.run(ctx, library, systems, where, made,
                               move=mode in ("move", "in_place"), places=places)
            # Counted again from the plan the run was handed, so the report says what
            # was asked for beside what happened rather than what was hoped for.
            report["against"] = plan_for.against(want, report)
            report["expected"] = want
            job.log(f"Created {report['games']}, failed {report['failed']}")
            return report

        job = ctx.jobs.submit("import", work)
        return {"started": True, "job_id": job.id,
                "links": {"job": f"/api/v1/jobs/{job.id}"}}

    ctx.ui.action("import", "/wizard")
    ctx.add_router(reading, scope=ctx.scope("read"))
    ctx.add_router(writing, scope=ctx.scope("write"))
