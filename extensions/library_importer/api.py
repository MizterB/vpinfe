"""What the importer offers over the API.

Every route is gated on a scope this extension declared; core attaches the gate. Reading
a source is a read, and pointing at a different one is a write - saying where an install
will read from is the decision worth being a separate permission from looking at what is
there.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from . import adopt, pinballx

READERS = (pinballx,)

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

    ctx.add_router(reading, scope=ctx.scope("read"))
    ctx.add_router(writing, scope=ctx.scope("write"))
