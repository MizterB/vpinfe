# Cookbook

Small, complete extensions, one task each. Every recipe is the smallest extension that does
one thing, so you can copy its folder whole into your extensions folder and change it. The
folders are under [examples/recipes](examples/recipes), and each block of code below is the
file of the same name there.

New to this? Read [Start here](README.md) first. Once you know the call you want, the
[Reference](reference.md) lists every one.

Recipes that talk to a service use the practice site, a few lines of standard-library Python
that plays a score-sharing service called Example Scores. Start it in a terminal and leave it
running:

```bash
python docs/extensions/examples/practice_site.py
```

It answers on `http://127.0.0.1:8790` and accepts the key `practice-key`. Stopping it forgets
what was posted.

Each recipe has the same parts: when to use it, the code, what you will see, a few variations
and the mistake people make with it.

- [1. The smallest extension](#1-the-smallest-extension)
- [3. The smallest dialog](#3-the-smallest-dialog)
- [4. A dialog with steps and a check](#4-a-dialog-with-steps-and-a-check)
- [5. A long job with progress](#5-a-long-job-with-progress)
- [6. Listening to events](#6-listening-to-events)
- [7. A list](#7-a-list)

## Basics

### 1. The smallest extension

**Use it when:** you want to see an extension load, or you need a place to start from.

The folder holds the manifest, the `register` function core calls once at startup, and the
words it shows.

`recipes/smallest/extension.json`

```json
{
  "name": "smallest",
  "version": "1.0.0",
  "requires_platform": 1,
  "capabilities": ["config:own", "ui:mount"]
}
```

`recipes/smallest/__init__.py`

```python
def register(ctx):
    ctx.ui.settings([{"key": "greeting", "type": "string", "default": "Hello"}])
    ctx.logger.info("%s", ctx.config.get("greeting"))
```

`recipes/smallest/i18n/en.json`

```json
{
  "name": "Smallest",
  "description": "The least an extension can be: one setting.",
  "settings.greeting.label": "Greeting"
}
```

**What you'll see:** Settings, then Extensions, then Smallest: a Greeting field with Hello
shown faintly in it. Until somebody types something, `ctx.config.get("greeting")` answers
Hello, the default. After they do, it answers what they typed.

**Variations:**

- Add `"type": "switch"` to make the setting a toggle. It is stored and read as the text
  `"true"` or `"false"`.
- Use `"type": "secret"` for a key. A secret has no default, and core never sends it back to
  the page.
- Give it a `check` function, `ctx.ui.settings(fields, check=function)`. It is handed every
  setting as it would be after the change and raises to refuse it. The refusal shows under
  the field.

**Watch out:** the folder name, the `name` in the manifest and the words' prefix are one
name. It is lowercase letters, digits and underscores, starting with a letter. The words file
has no `ext.smallest.` in front of its keys, core adds that.

### 3. The smallest dialog

**Use it when:** the person has to be asked something before anything happens.

An action is an object with an `ask` method. It answers the fields to draw, and `run` does the
work once the person presses the button. With no `check` method there is no step after this one,
so the button is the action's own name.

`recipes/hello_dialog/extension.json`

```json
{
  "name": "hello_dialog",
  "version": "1.0.0",
  "requires_platform": 1,
  "capabilities": ["ui:mount"]
}
```

`recipes/hello_dialog/__init__.py`

```python
class Hello:
    def __init__(self, ctx):
        self.ctx = ctx

    def ask(self, step):
        return {"fields": [{"key": "who", "label": self.ctx.t("dialog.who"),
                            "type": "string"}]}

    def run(self, values):
        return self.ctx.t("dialog.done", who=values.get("who") or "world")


def register(ctx):
    ctx.ui.action("hello", Hello(ctx))
```

`recipes/hello_dialog/i18n/en.json`

```json
{
  "name": "Hello Dialog",
  "description": "The smallest dialog: one question and a line to say when it is done.",
  "action.hello.label": "Say Hello",
  "dialog.who": "Who is it for?",
  "dialog.done": "Hello, {who}"
}
```

**What you'll see:** Settings, then Extensions, then Hello Dialog, with a Say Hello button. It
opens a dialog with one question, and the line `run` returns is shown when it is done.

**Variations:**

- Make `who` a `select` with `"choices": [["a", "Alice"], ["b", "Bob"]]` for a fixed list.
- Add `"help": "text"` to the step for a line under the title.
- Return `{"message": ..., "summary": [...]}` from `run` instead of text to show facts under
  the message.

**Watch out:** the label of every field is text you pass in, so it comes from `ctx.t` like
every other word. A field with no label shows its key.

### 4. A dialog with steps and a check

**Use it when:** what to ask next depends on the last answer, or an answer has to be checked
before going on.

`ask(step)` answers the question for a step. `check(values, step)` is called on Next with
everything answered so far, and answers the step to go to. Answering the step it was given,
with `errors`, a line for each field it refuses, keeps the person where they are and says
why, under the field. A step with a `summary` and a
`confirm` is the last one: its button runs the action.

`recipes/post_score/extension.json`

```json
{
  "name": "post_score",
  "version": "1.0.0",
  "requires_platform": 1,
  "capabilities": ["config:own", "net:outbound", "ui:mount"]
}
```

`recipes/post_score/__init__.py`

```python
import json
import urllib.error
import urllib.request

from common.extensions.contract import Unavailable


class PostScore:
    def __init__(self, ctx):
        self.ctx = ctx

    def _send(self, key, path, body=None):
        request = urllib.request.Request(
            self.ctx.config.get("site") + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"X-API-Key": key, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=10):
                return True
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                return False
            raise Unavailable(self.ctx.why(exc, at=request.full_url)) from exc
        except OSError as exc:
            raise Unavailable(self.ctx.why(exc, at=request.full_url)) from exc

    def ask(self, step):
        if step == "score":
            return {"step": "score", "title": self.ctx.t("dialog.score.title"),
                    "fields": [
                        {"key": "player", "label": self.ctx.t("dialog.player"),
                         "type": "string"},
                        {"key": "table", "label": self.ctx.t("dialog.table"),
                         "type": "string"},
                        {"key": "score", "label": self.ctx.t("dialog.points"),
                         "type": "number"}]}
        return {"step": "key", "title": self.ctx.t("dialog.key.title"),
                "help": self.ctx.t("dialog.key.help"),
                "fields": [{"key": "key", "label": self.ctx.t("dialog.key"),
                            "type": "string"}]}

    def check(self, values, step):
        if step == "key":
            if not self._send(values.get("key", ""), "/check"):
                return {**self.ask("key"),
                        "errors": {"key": self.ctx.t("dialog.key.refused")}}
            return self.ask("score")
        return {"step": "sure", "title": self.ctx.t("dialog.sure.title"),
                "confirm": self.ctx.t("dialog.sure.confirm"),
                "summary": [[self.ctx.t("dialog.player"), values["player"]],
                            [self.ctx.t("dialog.table"), values["table"]],
                            [self.ctx.t("dialog.points"), f"{int(values['score']):,}"]]}

    def run(self, values):
        self._send(values["key"], "/scores", {
            "player": values["player"], "table": values["table"],
            "score": int(values["score"])})
        return self.ctx.t("dialog.posted", table=values["table"])


def register(ctx):
    ctx.ui.settings([{"key": "site", "type": "string",
                      "default": "http://127.0.0.1:8790"}])
    ctx.ui.action("post", PostScore(ctx))
```

`recipes/post_score/i18n/en.json`

```json
{
  "name": "Post Score",
  "description": "Checks a key against Example Scores, then posts a score to it.",
  "settings.site.label": "Site",
  "action.post.label": "Post a Score",
  "dialog.key.title": "Sign in",
  "dialog.key.help": "The practice site's key is practice-key",
  "dialog.key": "Key",
  "dialog.key.refused": "The site did not accept that key",
  "dialog.score.title": "The score",
  "dialog.player": "Player",
  "dialog.table": "Table",
  "dialog.points": "Score",
  "dialog.sure.title": "Post this score?",
  "dialog.sure.confirm": "Post",
  "dialog.posted": "Posted a score for {table}"
}
```

**What you'll see:** Settings, then Extensions, then Post Score, with a Post a Score button.
It asks for a key and refuses a wrong one under the field. A right one leads to the score, and
then to a summary with a Post button. The practice site has the score afterward.

**Variations:**

- Return `"ready": False` from a step to keep Next disabled until `check` is happy.
- Add `"acts": [{"key": "test", "label": "Test"}]` to a step and handle `act(key, values)` to
  give it a button that does something without moving on.
- Answer a step with `"step": "other"` from `run` when the path turned out longer than the
  summary said.

**Watch out:** `check` is called again each time the person goes Back and forward, so keep it
free of side effects. Anything that changes something belongs in `run`.

### 5. A long job with progress

**Use it when:** the work takes longer than a person will wait with a dialog open.

`ctx.jobs.submit` runs a function on its own thread and returns the job. Handing back its `id`
closes the dialog, and the job is followed in Jobs. `job.progress(done, total, message)` moves
the bar. A job started `stoppable` offers a Stop, which sets `job.halt`: look at it between
units of work and end early.

`recipes/slow_sync/extension.json`

```json
{
  "name": "slow_sync",
  "version": "1.0.0",
  "requires_platform": 1,
  "capabilities": ["ui:mount"]
}
```

`recipes/slow_sync/__init__.py`

```python
import time

STEPS = 20


class Sync:
    def __init__(self, ctx):
        self.ctx = ctx

    def ask(self, step):
        return {"fields": [], "summary": [[self.ctx.t("dialog.steps"), str(STEPS)]],
                "confirm": self.ctx.t("dialog.start")}

    def run(self, values):
        def work(job):
            for done in range(1, STEPS + 1):
                if job.halt.is_set():
                    job.stopped = True
                    return {"done": done - 1}
                time.sleep(0.5)
                job.progress(done, STEPS, self.ctx.t("job.step", done=done, total=STEPS))
            return {"done": STEPS}

        job = self.ctx.jobs.submit("sync", work, stoppable=True)
        return {"job_id": job.id}


def register(ctx):
    ctx.ui.action("sync", Sync(ctx))
```

`recipes/slow_sync/i18n/en.json`

```json
{
  "name": "Slow Sync",
  "description": "A job that takes ten seconds, reports how far it has got and can be stopped.",
  "action.sync.label": "Start the Sync",
  "dialog.steps": "Steps",
  "dialog.start": "Start",
  "job.step": "Step {done} of {total}"
}
```

**What you'll see:** a Start the Sync button on the extension's page. It opens a summary with
a Start button, and the job appears in Jobs with its step count and a Stop button.

**Variations:**

- A dialog that finishes in the call itself can report with the `progress` it is handed:
  `def run(self, values, progress)`, then `progress.stage("Working", total=10)` and
  `progress.advance()`.
- Start the job with `keep_result=True` to keep what the function returned, so Jobs can open
  it after a restart.
- Set `job.problems = n` for the parts that did not come across. The job still finishes
  done.

**Watch out:** a job that never looks at `job.halt` cannot be stopped, whatever Stop says.
Check it once per unit, not once at the top.

### 6. Listening to events

**Use it when:** something should happen when VPinFE does something, such as a game ending.

`ctx.events.subscribe(name, handler)` calls the handler with the event's fields as keyword
arguments. Take what you need and `**_rest` for the others, so a field added later does not
break you.

`recipes/play_log/extension.json`

```json
{
  "name": "play_log",
  "version": "1.0.0",
  "requires_platform": 1,
  "scopes": ["games:read"],
  "capabilities": ["config:own"]
}
```

`recipes/play_log/__init__.py`

```python
def register(ctx):
    def played(game_id="", seconds=0, **_rest):
        ctx.logger.info("%s", ctx.t("log.played", game=game_id, minutes=round(seconds / 60)))

    ctx.events.subscribe("table.play_recorded", played)
```

`recipes/play_log/i18n/en.json`

```json
{
  "name": "Play Log",
  "description": "Writes a line to the log each time a game ends.",
  "log.played": "{game} was played for {minutes} minutes"
}
```

**What you'll see:** a line in the extension's log each time a game ends, such as `Medieval
Madness was played for 14 minutes`. The log is under Logs in the Console.

**Variations:**

- `game.selected` fires when the wheel stops on a game and nothing may wait on it, so keep
  its handler quick.
- `table.launched` and `table.exited` mark the start and end of a play.
- Publish your own with `ctx.events.publish("name", ...)` after naming it under `events` in
  the manifest. Others hear it as `<your name>.name`.

**Watch out:** a handler that raises is logged and the extension is marked as having failed,
but VPinFE carries on. A handler is not where to wait for a service: start a job instead.

## Lists

### 7. A list

**Use it when:** you have rows to show, such as the scores a service keeps.

`ctx.ui.list` hands core the rows and the columns, and core draws the page, the sorting and
the search. The list is shown in the rail under the area you name: `library`, `frontend`,
`community` or `system`.

`recipes/top_scores/extension.json`

```json
{
  "name": "top_scores",
  "version": "1.0.0",
  "requires_platform": 1,
  "capabilities": ["config:own", "net:outbound", "ui:mount"]
}
```

`recipes/top_scores/__init__.py`

```python
import json
import urllib.error
import urllib.request

from common.extensions.contract import Unavailable


def register(ctx):
    ctx.ui.settings([
        {"key": "site", "type": "string", "default": "http://127.0.0.1:8790"},
        {"key": "key", "type": "secret"},
    ])

    def rows():
        request = urllib.request.Request(ctx.config.get("site") + "/top",
                                         headers={"X-API-Key": ctx.config.get("key")})
        try:
            with urllib.request.urlopen(request, timeout=10) as answer:
                return json.loads(answer.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise Unavailable(ctx.t("error.refused")) from exc
            raise Unavailable(ctx.why(exc, at=request.full_url)) from exc
        except OSError as exc:
            raise Unavailable(ctx.why(exc, at=request.full_url)) from exc

    ctx.ui.list("top", rows, area="community", columns=[
        {"field": "player"},
        {"field": "table"},
        {"field": "score", "kind": "number"},
    ])
```

`recipes/top_scores/i18n/en.json`

```json
{
  "name": "Top Scores",
  "description": "Lists the best scores on Example Scores.",
  "settings.site.label": "Site",
  "settings.key.label": "Key",
  "error.refused": "The site did not accept the key",
  "list.top.title": "Top Scores",
  "list.top.column.player.header": "Player",
  "list.top.column.table.header": "Table",
  "list.top.column.score.header": "Score"
}
```

**What you'll see:** Top Scores under Community in the rail. Until the key is set under
Settings, then Extensions, the page says the site did not accept it. With `practice-key`
there, it lists the three sample scores, best first.

**Variations:**

- Add `status=function` to say a line above the list, such as when it was last read.
- Add `acts={"refresh": function, "docs": "https://..."}` for the title menu: a function runs
  when pressed, and an address is opened.
- Add `views=[{"key": "best", "name": ..., "columns": [...], "sort": [...]}]` for named
  orderings the person can pick.

**Watch out:** a list's title may not be the name of one of VPinFE's own pages, and two lists
in one area may not share a title. The extension is refused at load, and the reason is in its
page.
