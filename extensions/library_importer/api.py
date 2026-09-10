"""What the importer offers over the API.

Every route is gated on a scope this extension declared; core attaches the gate. Reading
a source is a read, and pointing at a different one is a write - saying where an install
will read from is the decision worth being a separate permission from looking at what is
there.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from . import adopt, emulationstation, pinballx

# Asked in order, first to claim a folder wins. PinballX is looked for first
# because it is the source somebody converting a pinball library actually has.
READERS = (pinballx, emulationstation)

# Where the source is, in this extension's own settings. Not a core setting: it is a
# fact about somebody's old machine, and it has no meaning to anything else here.
SOURCE_KEY = "source_root"


def reader_for(root: Path):
    """The reader that claims a folder, or None. First to claim it wins, and readers are
    asked in the order they are declared."""
    return next((one for one in READERS if one.detect(root)), None)


def _state(ctx) -> dict:
    configured = ctx.config.get(SOURCE_KEY, "")
    if not configured:
        return {"path": "", "reachable": False, "source_id": "", "source_name": "",
                "reason": "No source has been chosen"}
    path = Path(configured)
    if not path.is_dir():
        return {"path": configured, "reachable": False, "source_id": "",
                "source_name": "", "reason": "That folder is not reachable from here"}
    reader = reader_for(path)
    if reader is None:
        return {"path": configured, "reachable": True, "source_id": "",
                "source_name": "",
                "reason": "Nothing this build can read is in that folder"}
    return {"path": configured, "reachable": True, "source_id": reader.SOURCE_ID,
            "source_name": reader.SOURCE_NAME, "reason": ""}


def _preview(library) -> dict:
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


def build(ctx) -> None:
    """Register the routes, and keep what core may read in step with the setting."""
    def follow_the_setting() -> None:
        configured = ctx.config.get(SOURCE_KEY, "")
        ctx.files.set_roots([configured] if configured else [])

    follow_the_setting()

    reading = APIRouter()

    @reading.get("/source")
    def source() -> dict:
        """Where this install is set to import from, and what is there."""
        return _state(ctx)

    @reading.get("/preview")
    def preview() -> dict:
        """What a scan of the chosen source found. Reads it, writes nothing."""
        state = _state(ctx)
        if not state["source_id"]:
            return {"source_id": "", "root": state["path"], "systems": [],
                    "notes": [state["reason"]]}
        reader = next(one for one in READERS if one.SOURCE_ID == state["source_id"])
        return _preview(reader.read(Path(state["path"])))

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
        """What to ask first: where the library is."""
        state = _state(ctx)
        return {
            "title": "Bring in a library from another frontend",
            "help": "Point at the folder the other frontend keeps its library in. "
                    "Nothing there is written to or moved.",
            "fields": [{
                "key": "path", "type": "path", "label": "Folder",
                "value": state["path"],
                "help": "Its database and its artwork are read from here.",
            }],
            "facts": ([["Reads as", state["source_name"]]] if state["source_id"] else []),
            "notes": ([state["reason"]] if state["reason"] and state["path"] else []),
        }

    @writing.post("/wizard/check")
    def wizard_check(body: dict) -> dict:
        """What would happen, and what is left to choose.

        Pointing at the folder is done here rather than at the end, because it is what
        makes the source readable at all - there is nothing to summarize until it is set.
        """
        wanted = str((body.get("values") or {}).get("path") or "").strip()
        ctx.config.set(SOURCE_KEY, wanted)
        follow_the_setting()

        state = _state(ctx)
        if not state["source_id"]:
            return {"ready": False, "reason": state["reason"]}

        reader = next(one for one in READERS if one.SOURCE_ID == state["source_id"])
        found = _preview(reader.read(Path(state["path"])))
        systems = found["systems"]
        games = sum(one["games"] for one in systems)
        return {
            "ready": bool(games),
            "reason": "" if games else "Nothing in there to bring in",
            "summary": [
                ["Reads as", state["source_name"]],
                ["Games", str(games)],
                ["With artwork", str(sum(one["with_artwork"] for one in systems))],
                ["Already matched", str(sum(one["already_matched"] for one in systems))],
            ],
            "notes": found["notes"],
            # One system is not a choice, so it is not offered as one.
            "fields": ([{
                "key": "systems", "type": "multi", "label": "Bring in",
                "value": [one["name"] for one in systems],
                "choices": [[one["name"], f"{one['name']} ({one['games']})"]
                            for one in systems],
            }] if len(systems) > 1 else []),
            "confirm": f"Bring in {games} game{'' if games == 1 else 's'}",
        }

    @writing.post("/wizard/start")
    def wizard_start(body: dict) -> dict:
        values = body.get("values") or {}
        return start_import({"systems": values.get("systems") or [],
                             "location": values.get("location") or ""})

    @writing.post("/import", status_code=202)
    def start_import(body: dict) -> dict:
        """Convert the chosen source into game folders. Answers with a job.

        A job because it is slow and because it is the shape everything slow here takes:
        an import of six hundred games is minutes of copying, and a request that waited
        for it would time out somewhere in the middle with no way to ask what happened.
        Progress and the outcome are on /api/v1/jobs, the same as a library scan.
        """
        state = _state(ctx)
        if not state["source_id"]:
            return {"started": False, "reason": state["reason"]}
        reader = next(one for one in READERS if one.SOURCE_ID == state["source_id"])
        systems = [str(one) for one in (body.get("systems") or [])]
        location = str(body.get("location") or "")

        def work(job):
            library = reader.read(Path(state["path"]))
            job.log(f"Read {len(library.games)} games from {state['path']}")
            report = adopt.run(ctx, library, systems, location)
            job.log(f"Created {report['created']}, failed {report['failed']}")
            return report

        job = ctx.jobs.submit("import", work)
        return {"started": True, "job_id": job.id,
                "links": {"job": f"/api/v1/jobs/{job.id}"}}

    ctx.ui.task(key="import", label="Bring in a library",
                description="Convert a library from another frontend into game folders.",
                confirm="Import", base="/wizard")
    ctx.add_router(reading, scope=ctx.scope("read"))
    ctx.add_router(writing, scope=ctx.scope("write"))
