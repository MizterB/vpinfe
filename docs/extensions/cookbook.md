# Cookbook

Small, complete extensions, one task each. Every recipe is the smallest extension that does
one thing, so you can copy its folder whole into your extensions folder and change it. The
folders are under [examples/recipes](examples/recipes), and each block of code below is the
file of the same name there.

New to this? Read [Start here](README.md) first. Want to see how the pieces fit into one
extension? [Build an app](tutorial.md) grows one from an empty folder. Once you know the call
you want, the [Reference](reference.md) lists every one.

Recipes that talk to a service use the practice site, a few lines of standard-library Python
that plays a score-sharing service called Example Scores. Start it in a terminal and leave it
running:

```bash
python docs/extensions/examples/practice_site.py
```

It answers on `http://127.0.0.1:8790` and accepts the key `practice-key`. Stopping it forgets
what was posted.

Each recipe has the same parts: when to use it, the code, where it appears and what triggers
it, what you will see, a few variations and the mistake people make with it.

- [1. The smallest extension](#1-the-smallest-extension)
- [2. A key kept secret](#2-a-key-kept-secret)
- [3. The smallest dialog](#3-the-smallest-dialog)
- [4. A dialog with steps and a check](#4-a-dialog-with-steps-and-a-check)
- [5. A long job with progress](#5-a-long-job-with-progress)
- [6. Listening to events](#6-listening-to-events)
- [7. A list](#7-a-list)
- [8. A list you can add to](#8-a-list-you-can-add-to)
- [9. Acting on rows](#9-acting-on-rows)
- [10. States, chips, links and pictures in a column](#10-states-chips-links-and-pictures-in-a-column)
- [13. An account per player](#13-an-account-per-player)
- [16. A page of your own](#16-a-page-of-your-own)
- [18. An extension for one Linux distribution](#18-an-extension-for-one-linux-distribution)

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

**Where it appears:** on the extension's own page, Settings, then Extensions, then Smallest, and
in the log. **What triggers it:** VPinFE starting. `register` runs once, declares the setting
and writes the greeting to the log. After that, nothing runs until somebody opens the page.

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

### 2. A key kept secret

**Use it when:** the extension needs a password, a token or a key, and it must never be shown again once it is entered.

A `secret` is a field like any other, in a setting and in a dialog, with two differences. The box is masked and drawn empty, with *Set* or *Not set* in it, because core never sends the value back to the page. And leaving it empty keeps the one held, so the person does not have to type it again to change something else. Here one key is entered either way: in Settings, or from a dialog that asks for it.

`recipes/secret_key/extension.json`

```json
{
  "name": "secret_key",
  "version": "1.0.0",
  "requires_platform": 1,
  "capabilities": ["config:own", "ui:mount"]
}
```

`recipes/secret_key/__init__.py`

```python
class Connect:
    def __init__(self, ctx):
        self.ctx = ctx

    def ask(self, step):
        return {"fields": [{"key": "key", "label": self.ctx.t("dialog.key"),
                            "type": "secret",
                            "set": bool(self.ctx.config.get("key"))}]}

    def run(self, values):
        typed = values.get("key")
        if typed:
            self.ctx.config.set("key", typed)
            return self.ctx.t("dialog.saved")
        return self.ctx.t("dialog.kept")


def register(ctx):
    ctx.ui.settings([{"key": "key", "type": "secret"}])
    ctx.ui.action("connect", Connect(ctx))
```

`recipes/secret_key/i18n/en.json`

```json
{
  "name": "Secret Key",
  "description": "Keeps a key out of sight, set from a setting or from a dialog.",
  "settings.key.label": "Key",
  "action.connect.label": "Enter the Key",
  "dialog.key": "Key",
  "dialog.saved": "Saved the key",
  "dialog.kept": "Kept the key as it was"
}
```

**Where it appears:** on the extension's page in Settings, as a field and as a button.
**What triggers it:** the person typing in the field, or pressing the Enter the Key button. Nothing
runs in between.

**What you'll see:** Settings, then Extensions, then Secret Key: a masked Key field saying Not set. Type a key and leave the field, and it says Set, with Clear beside it. Clear asks first, then empties it. The Enter the Key button opens a dialog with the same field, and pressing the Enter the Key button with it empty leaves the key as it was.

**Variations:**

- Read it anywhere in the extension with `ctx.config.get("key")`. It is the one place the value is available, and it is empty where none is held.
- Put a secret in a dialog's first step and use it in `check` to see whether the service accepts it, as the dialog in recipe 4 does.
- Give a secret a `check` on the settings, `ctx.ui.settings(fields, check=function)`, to refuse a key the service does not know. The refusal shows under the field.

**Watch out:** a secret has no default, and `values.get("key")` in a dialog is `None` where the person left it empty. Treat that as keep, and never write an empty value over a key.

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

**Where it appears:** as a button on the extension's page in Settings. **What triggers it:**
the person pressing Say Hello. Nothing in VPinFE changes, so the only effect is the line
`run` returns.

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
                            "type": "secret"}]}

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

**Where it appears:** as a button on the extension's page in Settings. **What triggers it:**
the person pressing Post a Score. Each press of Next calls `check`. Only the Post button on the
summary calls `run`, and that is the one step that changes anything, by posting to the site.

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

**Where it appears:** as a button on the extension's page in Settings, and then in Jobs.
**What triggers it:** the person pressing Start on the summary. The work then runs on its own
thread until it finishes or the person presses Stop.

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
    def played(game_id="", seconds=0, private=False, **_rest):
        if private:
            return
        ctx.logger.info("%s", ctx.t("log.played", game=game_id, count=round(seconds / 60)))

    ctx.events.subscribe("table.play_recorded", played)
```

`recipes/play_log/i18n/en.json`

```json
{
  "name": "Play Log",
  "description": "Writes a line to the log each time a game ends.",
  "log.played": {"one": "{game} was played for a minute", "other": "{game} was played for {count} minutes"}
}
```

**Where it appears:** in the extension's log and nowhere else. It adds no page and no button.
**What triggers it:** a game ending on the cabinet, once VPinFE has written the play.

**What you'll see:** a line in the extension's log each time a game ends, such as
`medieval-madness was played for 14 minutes`. The log is under Logs in the Console.

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

**Where it appears:** as its own page in the rail, under Community. **What triggers it:** the
person opening the page or pressing refresh. Core calls `rows` each time.

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

### 8. A list you can add to

**Use it when:** the person should be able to put something new into a list, such as a score
on a site, and see it appear.

A list's `add` names a dialog you declared. Core puts a button for it above the list, opens
the dialog when it is pressed, and reads the list again once the dialog has run. The dialog is
the one you already know from recipe 3, so the list only points at it.

`recipes/add_score/extension.json`

```json
{
  "name": "add_score",
  "version": "1.0.0",
  "requires_platform": 1,
  "capabilities": ["config:own", "net:outbound", "ui:mount"]
}
```

`recipes/add_score/__init__.py`

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

    def call(path, body=None):
        request = urllib.request.Request(
            ctx.config.get("site") + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"X-API-Key": ctx.config.get("key"), "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=10) as answer:
                return json.loads(answer.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise Unavailable(ctx.t("error.refused")) from exc
            raise Unavailable(ctx.why(exc, at=request.full_url)) from exc
        except OSError as exc:
            raise Unavailable(ctx.why(exc, at=request.full_url)) from exc

    class Post:
        def ask(self, step):
            return {"step": "score", "title": ctx.t("dialog.post.title"), "fields": [
                {"key": "player", "label": ctx.t("dialog.player"), "type": "string"},
                {"key": "table", "label": ctx.t("dialog.table"), "type": "string"},
                {"key": "score", "label": ctx.t("dialog.points"), "type": "number"}]}

        def run(self, values):
            call("/scores", {"player": values["player"], "table": values["table"],
                             "score": int(values["score"])})
            return ctx.t("dialog.posted", table=values["table"])

    ctx.ui.action("post", Post())
    ctx.ui.list("scores", lambda: call("/top"), area="community", columns=[
        {"field": "player"},
        {"field": "table"},
        {"field": "score", "kind": "number"},
    ], add="post")
```

`recipes/add_score/i18n/en.json`

```json
{
  "name": "Add Score",
  "description": "Lists the scores on Example Scores and adds one from a button above the list.",
  "settings.site.label": "Site",
  "settings.key.label": "Key",
  "error.refused": "The site did not accept the key",
  "action.post.label": "Add a score",
  "dialog.post.title": "The score",
  "dialog.player": "Player",
  "dialog.table": "Table",
  "dialog.points": "Score",
  "dialog.posted": "Posted a score for {table}",
  "list.scores.title": "Add Score",
  "list.scores.column.player.header": "Player",
  "list.scores.column.table.header": "Table",
  "list.scores.column.score.header": "Score"
}
```

**Where it appears:** on the list's page under Community in the rail, in the bar above the
list. **What triggers it:** the person pressing the button. The dialog's `run` is called with
what they typed, and core reads the list again afterwards.

**What you'll see:** Add Score under Community in the rail, with an **Add a score** button
beside the search box. While the list is empty the button is there in full words, so a new
list never looks broken. Press it, type a player, a table and a score, and the dialog closes
with "Posted a score for Attack from Mars". The new score is in the list.

**Variations:**

- Name more than one dialog, `add=["post", "import"]`, and the button becomes a **+** with a
  menu of your dialogs' labels.
- A verb can open a dialog too, over the rows the person picked: give it `"action": "post"`
  in place of `run`. Your dialog's `ask(step, rows)` is handed the picked ids on its first
  call and gets them back as `values["rows"]` from then on.
- Add `"each": True` to that verb and the dialog opens once for each picked row, with **Skip**
  and **Stop** where Cancel would be.
- An act in the list's title menu can do the same: `{"key": "sign_in", "action": "connect"}`.

**Watch out:** the dialog named by `add`, a verb or an act has to be declared with
`ctx.ui.action`, in the same extension. An unknown one is refused at load, with its name in the
reason.

### 9. Acting on rows

**Use it when:** the person should be able to do something to the rows they pick, such as
flag a score, open its page or remove it.

`verbs` on a list are the things that can be done to a row. Core draws them in the row's
menu and, when the person ticks several rows, in the menu under the list. You say what each
one does, and core asks first when it is dangerous, dims it where it does not fit, and reads
the list again afterwards.

This one builds on the practice site's scores, which now have an `id`, a `flagged` flag and a
page of their own. A list's rows need an `id` for the person to be able to pick them.

`recipes/score_rows/extension.json`

```json
{
  "name": "score_rows",
  "version": "1.0.0",
  "requires_platform": 1,
  "capabilities": ["config:own", "net:outbound", "ui:mount"]
}
```

`recipes/score_rows/__init__.py`

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

    def call(path, method="GET", body=None):
        request = urllib.request.Request(
            ctx.config.get("site") + path, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"X-API-Key": ctx.config.get("key"), "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=10) as answer:
                return json.loads(answer.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise Unavailable(ctx.t("error.refused")) from exc
            raise Unavailable(ctx.why(exc, at=request.full_url)) from exc
        except OSError as exc:
            raise Unavailable(ctx.why(exc, at=request.full_url)) from exc

    def rows():
        return [{**one, "page": f"{ctx.config.get('site')}/scores/{one['id']}",
                 "can_flag": not one["flagged"]} for one in call("/top")]

    def flag(picked):
        for one in picked:
            call(f"/scores/{one['id']}/flag", "POST")
        return ctx.t("message.flagged", count=len(picked))

    def remove(picked):
        for one in picked:
            call(f"/scores/{one['id']}", "DELETE")

    ctx.ui.list("scores", rows, area="community", columns=[
        {"field": "player"},
        {"field": "table"},
        {"field": "score", "kind": "number"},
    ], verbs=[
        {"key": "open", "link": "page"},
        {"key": "flag", "run": flag, "needs": "can_flag"},
        {"key": "remove", "run": remove, "danger": True},
    ])
```

`recipes/score_rows/i18n/en.json`

```json
{
  "name": "Score Rows",
  "description": "Lists the scores on Example Scores and acts on the ones you pick.",
  "settings.site.label": "Site",
  "settings.key.label": "Key",
  "error.refused": "The site did not accept the key",
  "message.flagged": {"one": "Flagged the score", "other": "Flagged {count} scores"},
  "list.scores.title": "Score Rows",
  "list.scores.column.player.header": "Player",
  "list.scores.column.table.header": "Table",
  "list.scores.column.score.header": "Score",
  "list.scores.verb.open.label": "Open on the site",
  "list.scores.verb.flag.label": "Flag",
  "list.scores.verb.flag.needs": "Already flagged",
  "list.scores.verb.remove.label": "Remove",
  "list.scores.verb.remove.confirm": {
    "one": "Remove this score from the site?",
    "other": "Remove these {count} scores from the site?"
  }
}
```

**Where it appears:** on the list's page under Community in the rail, in the menu on each row
and in the menu above the list when rows are ticked. **What triggers it:** the person picking rows and pressing a verb. Your
function is handed the rows they picked, and core reads the list again afterwards.

**What you'll see:** Score Rows under Community in the rail, with the three sample scores
once the key is set. Right-click a row for Open on the site, Flag and, below a rule, Remove.
Tick two rows and the same menu is under the list, with Open on the site dimmed as One at a
time. Flag a score and its Flag is dimmed with Already flagged. Remove asks "Remove this score
from the site?" first, or "Remove these 2 scores from the site?" for two.

**Variations:**

- A verb that answers `{"message": ..., "url": ...}` shows the message and offers the address.
- Add `"one": True` to a run verb that only makes sense for a single row.
- A verb with no `needs` acts on every row picked. With `needs`, it acts only on the rows where
  that field is true. It is dimmed, with the `.needs` words, when the field is true on none.

**Watch out:** the `id` of a row is a string and must be different for every row of the list.
Two rows with the same id make the list fail with the reason, and a row with none can be read
but not picked.

### 10. States, chips, links and pictures in a column

**Use it when:** a column holds something the person should take in at a glance: whether a
challenge is open, which tags a table carries, where its rules are, what it looks like.

A column is text unless you give it a `kind`. Four kinds draw a value as more than text:
`state` for one of a few fixed values, `chips` for a list, `link` for a web address and
`picture` for a small image. You hand core the values and say which kind a column is, and core
draws it the same way on every page. A state names its own words and what it looks like.

This one needs no service. It lists five weekly challenges that are written into the file, so
you can see all four kinds at once. The state column has five states, one of each look:

- `open` is `{"tier": "on"}`, `closing` is `warn` and `closed` is `off`. A tier is a colored
  chip. The tiers are `on`, `off`, `unknown`, `warn` and `bad`.
- `cancelled` is `{"icon": "block"}`, a Material icon drawn before the word.
- `planned` is `{}`, a quiet word with nothing around it. Most states should look like this one.

`recipes/weekly_board/extension.json`

```json
{
  "name": "weekly_board",
  "version": "1.0.0",
  "requires_platform": 1,
  "capabilities": ["ui:mount"]
}
```

`recipes/weekly_board/__init__.py`

```python
CHALLENGES = [
    {"name": "Medieval Madness", "status": "open", "tags": ["Williams", "Classic"],
     "page": "https://scores.example.com/weeks/41", "art": "art/flipper.png"},
    {"name": "Attack from Mars", "status": "closing", "tags": ["Bally"],
     "page": "https://scores.example.com/weeks/40", "art": "art/flipper.png"},
    {"name": "The Addams Family", "status": "closed", "tags": [],
     "page": "https://scores.example.com/weeks/39", "art": ""},
    {"name": "Twilight Zone", "status": "cancelled", "tags": ["Bally"],
     "page": "", "art": ""},
    {"name": "Theatre of Magic", "status": "planned", "tags": [],
     "page": "", "art": ""},
]


def register(ctx):
    ctx.ui.list("board", lambda: CHALLENGES, area="community", columns=[
        {"field": "name"},
        {"field": "status", "kind": "state", "states": {
            "open": {"tier": "on"},
            "closing": {"tier": "warn"},
            "closed": {"tier": "off"},
            "cancelled": {"icon": "block"},
            "planned": {},
        }},
        {"field": "tags", "kind": "chips"},
        {"field": "page", "kind": "link"},
        {"field": "art", "kind": "picture"},
    ])
```

`recipes/weekly_board/i18n/en.json`

```json
{
  "name": "Weekly Board",
  "description": "Lists the weekly challenges, with a state, tags, a link and a picture for each.",
  "list.board.title": "Weekly Board",
  "list.board.column.name.header": "Challenge",
  "list.board.column.status.header": "Status",
  "list.board.column.status.state.open": "Open",
  "list.board.column.status.state.open.why": "Scores are being taken",
  "list.board.column.status.state.closing": "Closing",
  "list.board.column.status.state.closing.why": "Ends within a day",
  "list.board.column.status.state.closed": "Closed",
  "list.board.column.status.state.cancelled": "Cancelled",
  "list.board.column.status.state.planned": "Planned",
  "list.board.column.tags.header": "Tags",
  "list.board.column.page.header": "Rules",
  "list.board.column.art.header": "Picture"
}
```

The first row's picture is a real file, `recipes/weekly_board/art/flipper.png`, in the
extension's folder. Copy the folder whole and it comes with it.

**Where it appears:** on the list's page under Community in the rail, as the Status, Tags,
Rules and Picture columns. **What triggers it:** the person opening the page. Core reads the
rows, draws each column by its kind and serves the picture from VPinFE's own address.

**What you'll see:** Weekly Board under Community in the rail with five rows. Status shows
Open in green, Closing in amber, Closed in grey, Cancelled with a stop sign before it and
Planned as plain text. Hover Open and it says "Scores are being taken". The Status filter
offers all five words. Tags shows Williams and Classic as two chips on the first row, and
nothing on the rows with none. Rules is a link marked as leaving the Console, with the
column's header as its text. Picture shows the first two rows' picture at a small size, and
nothing on the others.

**Variations:**

- `{"field": "page", "kind": "link", "says": "title"}` reads the link as the row's `title`
  instead of the header, so each row's link says what it opens.
- A picture can be a web address: `"art": "https://example.com/a.png"`. Add `net:outbound` to
  `capabilities`, because core fetches it for you. Without it the list does not read, and says
  why.
- Leave `states` out of a state column and the extension does not start. The words for each
  state are `list.<key>.column.<field>.state.<value>`, and `--check-extension` tells you which
  you have not written.

**Watch out:** chips are for exceptions. A tag on every row says nothing, and a column of
chips where each row has one is a text column wearing a costume. Use `chips` for what some rows
have and most do not. The same goes for a tier: when most rows are `on`, give that state `{}`
and let only the ones worth noticing be colored.

## Players and games

### 13. An account per player

**Use it when:** each player has something of their own with the extension, such as a handle or a key for a service, and it should sit on that player's panel.

An account whose `read` answers `fields` and no `user_id` is drawn by core as a settings page is, one control for each field, on the player's panel under the extension's name. Each is saved as it is left with `write(player_id, values)`, which is handed just the field that changed. A secret is never answered: `read` says `set` and core draws it empty. Core adds the Share switch under the fields.

`recipes/player_handle/extension.json`

```json
{
  "name": "player_handle",
  "version": "1.0.0",
  "requires_platform": 1,
  "capabilities": ["ui:mount"]
}
```

`recipes/player_handle/__init__.py`

```python
def register(ctx):
    def read(player_id):
        held = ctx.players.account(player_id)
        return {"fields": [
            {"key": "handle", "type": "string", "label": ctx.t("account.handle"),
             "value": held.get("handle", "")},
            {"key": "api_key", "type": "secret", "label": ctx.t("account.key"),
             "set": bool(held.get("api_key"))}]}

    def write(player_id, values):
        held = dict(ctx.players.account(player_id))
        for key, value in values.items():
            if value is None:
                held.pop(key, None)
            else:
                held[key] = value
        ctx.players.set_account(player_id, held)

    ctx.ui.account(read=read, write=write)
```

`recipes/player_handle/i18n/en.json`

```json
{
  "name": "Player Handle",
  "description": "Keeps a handle and a key for each player.",
  "account.handle": "Handle",
  "account.key": "Key"
}
```

**Where it appears:** on a player's panel, under the extension's name. **What triggers it:**
the panel opening, which reads the fields, and the person leaving a field, which writes that
one for that player.

**What you'll see:** Frontend, then Players, then a player, then Player Handle: a Handle field, a masked Key field and a Share switch. Type a handle and leave the field, and it is kept for that player and no other. A key says Set once entered, with Clear beside it.

**Variations:**

- Make a field a `select` or a `switch` with `choices`, as in a settings page. The Fields table in the reference lists what an account draws.
- Raise an error from `write` to refuse a value. The refusal shows under the field, and the value is not kept.
- Answer `user_id` as well to have core draw the id, the claim and the card instead, which is the shape an account with a service of its own takes.

**Watch out:** `write` is handed `None` under a key when a secret is cleared, so remove the key and do not store the word None. A guest's account is held in memory and never written to disk, so a handle set on a guest is gone when they sign out.

## Beyond the Console

### 16. A page of your own

**Use it when:** the thing you are adding already has a web page of its own, such as a hardware tool's console, a manual or a dashboard on another port, and a person should reach it from the Console in one click.

`ctx.ui.link` declares an address and core draws it as a link.  The address is a string, or a function that returns one, so a link can follow a setting.  `{host}` is filled in with the host the Console was opened at, so a tool that runs beside VPinFE is reached by the name the person already used, from a laptop or from the cabinet.  The label and the tip are words in the extension's catalog, named for the link.

`recipes/tool_link/extension.json`

```json
{
  "name": "tool_link",
  "version": "1.0.0",
  "requires_platform": 1,
  "capabilities": ["config:own", "ui:mount"]
}
```

`recipes/tool_link/__init__.py`

```python
def register(ctx):
    ctx.ui.settings([{"key": "port", "type": "number", "default": 9090, "min": 1, "max": 65535}])

    def console():
        return f"http://{{host}}:{ctx.config.get('port')}/"

    ctx.ui.link("console", console, area="system")
    ctx.ui.link("manual", "https://tool.example.com/manual")
```

`recipes/tool_link/i18n/en.json`

```json
{
  "name": "Tool Link",
  "description": "Links to a hardware tool's own web page, and to its manual.",
  "settings.port.label": "Port",
  "settings.port.help": "The port the tool's page answers on",
  "link.console.label": "Tool console",
  "link.console.tip": "The tool's own page, in a new tab",
  "link.manual.label": "Manual"
}
```

**Where it appears:** a link with an `area` is drawn on the Console's rail in that area, and every link is in a menu at the end of the extension's page title.  The manual has no `area`, so it is in that menu only.  **What triggers it:** the person clicking it.  Nothing is fetched until they do, and nothing is drawn while the extension is switched off.

**What you'll see:** System on the rail shows Tool console with a small arrow-out mark, and the extension's page has a menu holding both links.  Both open in a new tab.  Change the Port setting and the next click goes to the new port.

**Variations:**

- Leave the `area` out of a link that belongs only on the extension's page.
- Return a different address from the function for each situation.  An answer that is not an `http://` or `https://` address leaves out that link, and `--check-extension` fails the extension.
- Link to a page you serve from VPinFE with `ctx.add_router` only if it can run with no sign-in: core answers every page under `/api/v1/ext/` sandboxed, as no origin of its own.  See [`ctx.ui.link`](reference/ui.md#ctxuilink).

**Watch out:** write `{host}` with doubled braces inside an f-string, as above, or Python fills it in and the host is lost.  A link is never drawn with another scheme: `file:`, `javascript:` and the rest are refused when it is declared, or dropped when a function answers one.

### 18. An extension for one Linux distribution

**Use it when:** the extension manages something only one kind of machine has, such as a cabinet's boot mode on VPinOS, and it should not be offered anywhere else.

`platforms` in the manifest names where it runs.  Beside `linux`, `windows` and `macos` it takes a Linux distribution's `ID`, the `ID=` line of `/etc/os-release`: `vpinos`, `ubuntu`, `debian`, `fedora`.  `linux` matches every Linux, and an `ID` matches that distribution only.  An extension runs where any name in the list matches.  Core does not keep a list of distributions, so any `ID` is accepted as long as it is written the way os-release writes it: lowercase letters, digits, `.`, `_` and `-`.

`recipes/vpinos_only/extension.json`

```json
{
  "name": "vpinos_only",
  "version": "1.0.0",
  "requires_platform": 1,
  "platforms": ["vpinos"],
  "capabilities": ["config:own", "ui:mount"]
}
```

`recipes/vpinos_only/__init__.py`

```python
def register(ctx):
    ctx.ui.settings([{"key": "boot", "type": "select", "default": "play",
                      "choices": [["play", "Play"], ["desktop", "Desktop"]]}])
```

`recipes/vpinos_only/i18n/en.json`

```json
{
  "name": "VPinOS Only",
  "description": "Settings for something only a VPinOS cabinet has.",
  "settings.boot.label": "Start in",
  "settings.boot.help": "What the cabinet comes up in after it is switched on"
}
```

**Where it appears:** on a VPinOS cabinet it is a page like any other, with the Start in setting.  Anywhere else it is listed under Extensions marked Off, and its page says "Cannot run on this device" with the reason and shows no settings.  **What triggers it:** core reads the machine's os-release the first time it loads an extension, and compares its `ID` to the list.  Nothing in the extension runs on a machine it is not for, not even `register`.

**What you'll see:** on a Mac the page says "It does not run on macOS", and on Ubuntu "It does not run on Ubuntu".  On a Linux with no `/etc/os-release` it says "It does not run on Linux".  On VPinOS it runs, and the page shows Start in.

**Variations:**

- Name several, `["vpinos", "ubuntu"]`, for an extension that runs on either.
- Name the family, `["linux"]`, to run on every distribution and keep Windows and macOS out.  A distribution built on another is its own `ID`: `ubuntu` does not match Linux Mint, so name both.
- Run `--check-extension` on your own computer.  It loads the extension whatever its `platforms` say, so you can try the code anywhere, and a `platforms` line tells you whether this machine would run it: `platforms  vpinos - not this machine: It does not run on macOS`.

**Watch out:** the `ID` is lowercase in `/etc/os-release` and here: `VPinOS` is refused, `vpinos` is not.  The name in the reason, "Ubuntu", is the distribution's `NAME`, which is for people to read, and it is not what `platforms` matches.
