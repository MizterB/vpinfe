# Actions and dialogs

`ctx.ui.action(key, dialog, *, label, description)`. An extension does not draw. It declares
an **action**, a verb, and core renders it, so every action looks like the Console and
keeps working if that extension later runs out of process.

The dialog is any object. It must have `ask`; the rest are used if present:

| method | called when | returns |
|---|---|---|
| `ask(step)` | The dialog opens (`step` is `""`), or a done step is reopened | The step: what to ask, if anything |
| `check(values[, step])` | Next is pressed, or a value changes | The step again, with `ready`, `summary`, `notes`, `errors`. None means ask again |
| `act(key, values[, step])` | A step's own quiet button is pressed | The step redrawn. None means ask again |
| `run(values[, step][, progress])` | The last step's button is pressed | A message string, a dict, or `{"job_id": ...}` |
| `progress()` | Core polls it while a step is slow | `{stage, message, done, total}` |

`step` and `progress` are handed only to a method that names them. The default tracker given
as `progress` has `stage(name, message="", total=0)`, `advance(done=None, message=None)` and
`clear()`, and answers the same shape for `GET .../progress` when the dialog defines no
`progress` of its own. An action that is one call and a sentence does not need it.

```python
class Import:
    def ask(self, step):
        return {"help": ctx.t("action.import.help"),
                "fields": [{"key": "folder", "type": "path", "wants": "dir",
                            "label": ctx.t("action.import.folder")}],
                "confirm": ctx.t("action.import.confirm")}

    def check(self, values):
        if not values.get("folder"):
            return {"ready": False, "reason": ctx.t("action.import.no_folder")}
        return {"ready": True, "summary": [["Folder", values["folder"]]]}

    def run(self, values, progress):
        progress.stage("reading", total=2)
        progress.advance()
        return {"message": ctx.t("action.import.done")}


ctx.ui.action("import", Import())
```

**How many steps an action has is read off what it answers, never declared.** No `fields`
means press it and it happens. `fields` means fill them in first. A `confirm` means a step
showing what would happen before it runs. A declared mode would be a second statement of what
the answers already say, and the two come apart.

A `confirm` with no `summary` is the last step with nothing to show first: its forward button
reads the `confirm` and pressing it runs. A run may answer with a `step` instead of an
outcome, drawn the way a `check` answer is, so an answer that changes the path can move on to
a question that was not there when the last step was drawn. Each step is given up to 15
minutes to answer, so one that reads a slow source is waited for rather than reported as
failed.

**A step answer** is a dict. Keys:

| key | meaning |
|---|---|
| `title` | The step's heading. Left out, the action's label (`action.<key>.label`) |
| `help` | A line, or `{follows, says, else}` to say what `says` holds for the value the field named `follows` has now, and `else` for any other |
| `fields` | The fields to ask for. See [Fields](#fields) |
| `confirm` | The verb at the point of no return, the action's own: a generic "Confirm" makes every action look like every other one |
| `steps` | `[{key, label, done}]`, the path as it stands. A `done` step reopens with `GET .../actions/<key>?step=<key>`. An action that cannot say how many steps it has sends none and loses nothing |
| `welcome` | True centers the step, for a flow's first: the `title` at display size, the `help` as the lead, and the label of its `choice` as the question over it. Every `check` and `act` answer replaces the step, so one still a welcome repeats `welcome: true` |
| `ready`, `reason` | `ready: false` holds Next or the last step's `confirm` until true again, with `reason` said beside the held button. Any step may send it |
| `summary` | `[[label, value], ...]`: what the steps add up to. A row of one is a heading, not a fact |
| `notes` | Lines that travel with the summary, because a count that stays quiet about what the job cannot do describes something that will not happen. A string, or `{text, detail}` where `detail` shows on hover |
| `errors` | `{field_key: text}`: refuse one field by name, drawn under it. Each value takes the same two forms a note does |
| `acts` | `[{key, label}]`: quiet buttons inside the step's body. Pressing one calls `act` and gets the same step back, redrawn; an act never moves the step on |

Fields in an answer are checked against the table in [Fields](#fields) when the answer is made. One
of any other type fails that call with a line naming the field and the types that are
drawn.

**The run.** `run` returns a message string (said, then the dialog closes), or a dict with an
optional `message` and `summary`, or a **job**. For slow work, start one and answer
`{"job_id": job.id}`: core serves that as `202`, hands the id to the Jobs view and closes
the dialog, where `job.progress` and the stop are drawn.

```python
def run(self, values):
    job = ctx.jobs.submit("import", lambda job: self.convert(job, values),
                          stoppable=True, keep_result=True)
    return {"job_id": job.id}
```

**stoppable.** `ctx.jobs.submit(..., stoppable=True)` offers a stop link
(`POST /api/v1/ext/<name>/jobs/<kind>/stop`) and the work reads `job.halt` between units. See
`ctx.jobs.submit`.

**keep_result.** `keep_result=True` writes what the work returns to disk for the Jobs view,
the latest 20.

**Action words**, in the catalog: `action.<key>.label`, `action.<key>.description`, and
`action.<key>.result.<field>` for a count a run reports, beside the number. A label or
description passed in code is shown as written.

## Fields

One vocabulary: a dialog's steps, the settings page and an account's panel draw the same
types in the same controls. A field is `{key, type, label, value, help}` plus what the type
takes. `help` takes the forms described above. A settings field's `label`, `help` and
choices come from the catalog (`settings.<key>.label`), so a settings field is declared with
`{key, type, default, choices}` and nothing to say.

| type | asks for | dialog | settings | account |
|---|---|---|---|---|
| `string` | a line of text | yes | yes | yes |
| `secret` | a masked line. Drawn empty, with *Set* or *Not set* in it; what is typed is kept across a dialog's steps and never filled back from an answer. An extension answers `set` (true or false) and never the value; leaving it empty keeps the one held. A settings page and an account also draw *Clear* beside a held one, which asks first | yes | yes | yes |
| `path` | a file or folder on the machine core runs on, with `wants`: `dir`, `file` or `exe`. A dialog's may add `opens_at`, the folder its picker starts in while the field is empty | yes | yes | yes |
| `select` | one of `choices`, each `[key, label]` and optionally `[key, label, help]`, the help shown beside the option in the list, and under the field once it is chosen. Labels within one field are different, since the help is found by label | yes | yes | yes |
| `multi` | several of `choices`. A setting is stored as a JSON list of the keys ticked, and `ctx.config.get_list(key)` reads it | yes | yes | yes |
| `switch` | on or off | yes | yes | yes |
| `number` | a number, with `unit`, `min` and `max`. A setting is stored as its digits and left empty it falls back to its default | yes | yes | yes |
| `choice` | one of `choices`, two to four, each `[key, label, help]` with its own line of help, and optionally a fourth element: the name of a picture, or a list of paths to a few of the person's own images, inside the folders the extension declared in `ctx.files.set_roots` | yes | no | no |
| `checklist` | any of `rows` ticked, for a list too long for `multi`: each row `{key, name, note, groups}`, with `chips` as `[group, label]` pairs, a chip shown only when a row is in its group; the answer is the keys ticked | yes | no | no |
| `settle` | a VPS entry for each of `rows`, `{key, name, entry, vps_id, reason, settled}`, `entry` being the `{name, manufacturer, year}` it would offer: the row says it or Not found, with the reason, and Change... opens the VPS picker; settled rows are behind Show all. The answer maps a row's key to the id picked, with `""` for a row said to be in no catalog; a key left out is a row untouched | yes | no | no |

A `choice` option's picture is a name, and `null` is none. Core draws `desktop` and
`cabinet` itself and reads any other name as a Material icon, so a flow never supplies a
drawing. Options with pictures are tiles on a `welcome` step and rows on any other. Beside
other fields the `choice`'s label heads its rows; alone on a step, its `title` is the
question.

**A secret.** Whatever surface asks for one, the value goes to the extension and never comes
back: core takes it out of every answer and puts `set` in its place. Declare a setting as
`{"key": "api_key", "type": "secret"}`; a secret has no default. A dialog's `check` and `run`
get the typed value under the key, and get no key at all where the person left it empty, so
`values.get("api_key")` being `None` means keep the one held. *Clear* sends `null` for a
setting, and an account's `write` is handed `None` under the key.

A type that a surface does not draw is refused when it is declared, not when somebody opens
the page.
