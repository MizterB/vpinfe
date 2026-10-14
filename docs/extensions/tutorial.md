# Build an app

The [cookbook](cookbook.md) gives you one small extension per task. This page builds one bigger
extension from an empty folder, a piece at a time, so you can see how the pieces fit together
and where each one turns up in the Console.

The extension is Scoreboard. It talks to the practice site, the stand-in for a score-sharing
service, and it ends up with:

- a page of its own in Settings, holding the site's address and your key,
- a list of the site's scores in the Community part of the rail,
- a menu of things to do with a score: open it, flag it, remove it,
- a dialog that posts a new score,
- a line in the log whenever a game ends.

Every stage below has the same four parts: what you add, what you see, what triggers it, and
what core did for you. The finished folder is [examples/scoreboard](examples/scoreboard), and
each block that names a file below is that file, or a piece of it.

## Before you start

- Read [Writing an extension](README.md) for where the extensions folder is and how to restart VPinFE.
- Start the practice site and leave it running:

  ```bash
  python docs/extensions/examples/practice_site.py
  ```

  It answers on `http://127.0.0.1:8790` and accepts the key `practice-key`.
- Make a folder called `scoreboard` in your extensions folder. Each stage adds to it, and
  you restart VPinFE after each one, because extensions load at startup.

## Stage 1: it loads

**What you have after it:** an extension VPinFE knows about, and nothing else.

The manifest is the first thing core reads. It names the extension and says what it asks to
do.

`scoreboard/extension.json`

```json
{
  "name": "scoreboard",
  "version": "1.0.0",
  "requires_platform": 1,
  "capabilities": ["config:own", "net:outbound", "ui:mount"]
}
```

- `name` is also the folder's name and the start of every word the extension shows.
- `capabilities` is the list the person installing it can read. `ui:mount` lets it add pages,
  `config:own` lets it keep settings, and `net:outbound` says it reaches the network.

Next to it goes an `__init__.py` with the one function core calls at startup:

```python
def register(ctx):
    pass
```

and an `i18n/en.json` holding the extension's name and a sentence about it:

```json
{
  "name": "Scoreboard",
  "description": "Lists, flags, removes and posts the scores on Example Scores."
}
```

**What you see:** open Settings, find Extensions in the list on the left, and Scoreboard is
there with an Enabled switch, the version, and chips saying what it can reach.

**What triggers it:** VPinFE starting. `register` runs once, and nothing in it runs again.

**What core did:** read the manifest, made the extension a `ctx` of its own, and drew the
page. You wrote no route and no page.

Before restarting, you can ask what core would make of the folder without running it:

```bash
./vpinfe --check-extension path/to/scoreboard
```

## Stage 2: settings

**What you have after it:** a place for the site's address and the key.

Two settings go in `register`, and their labels go in the words file.

`scoreboard/__init__.py` (excerpt)

```python
    ctx.ui.settings([
        {"key": "site", "type": "string", "default": "http://127.0.0.1:8790"},
        {"key": "key", "type": "secret"},
    ])
```

`scoreboard/i18n/en.json` (excerpt)

```json
  "settings.site.label": "Site",
  "settings.key.label": "Key",
  "settings.key.help": "The practice site's key is practice-key",
```

**What you see:** the Scoreboard page in Settings now has a Site field that hints at the
address and a Key field that says Not set. Type `practice-key` and press Enter. The Key box
then says Set, with a Clear button beside it, and it never shows the key again.

**What triggers it:** the person opening the page. Core reads the settings through what you
declared, and writes what they type to the extension's own file.

**What core did:** drew the fields, kept the key out of anything it sends to the page, and
made the values reachable as `ctx.config.get("site")` and `ctx.config.get("key")`.

See [Settings and lists](reference/settings-and-lists.md) for every field type a setting takes.

## Stage 3: a list

**What you have after it:** the site's scores, drawn by core.

First a function that asks the site for something. Every call in this extension goes through
it, so the key, the timeout and the failure handling are written once.

`scoreboard/__init__.py` (excerpt)

```python
    def call(path, method="GET", body=None):
        request = urllib.request.Request(
            ctx.config.get("site").rstrip("/") + path, method=method,
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
```

A failure is raised as `Unavailable`. The page header then reads "Could not read Scoreboard",
with your words in the hint beside it, instead of an empty list that looks like there are no
scores. `ctx.why` turns a network error into a sentence a person can use.

Then the rows and the list itself. At this stage the rows are the site's answer as it comes,
and the list call has no verbs yet. It names `columns`, which the next snippet defines above
the call in the file:

```python
    def rows():
        return call("/top")

    ctx.ui.list("scores", rows, area="community", columns=columns)
```

The columns say which field each one shows:

`scoreboard/__init__.py` (excerpt)

```python
    columns = [
        {"field": "player"},
        {"field": "table"},
        {"field": "score", "kind": "number"},
    ]
```

and the words give the page and its headers their names:

`scoreboard/i18n/en.json` (excerpt)

```json
  "error.refused": "The site did not accept the key",
  "list.scores.title": "Scoreboard",
  "list.scores.column.player.header": "Player",
  "list.scores.column.table.header": "Table",
  "list.scores.column.score.header": "Score",
```

The top of `__init__.py` gets the imports these use:

`scoreboard/__init__.py` (excerpt)

```python
import json
import urllib.error
import urllib.request

from common.extensions.contract import Unavailable
```

**What you see:** Scoreboard under Community in the rail. Open it and the three sample scores
are listed, AAA, BEE and CJ, with a search box above them and sortable columns. If the key is
not set yet, the header reads "Could not read Scoreboard" instead, and the hint says the site
did not accept the key.

**What triggers it:** the person opening the page, and the refresh button on it. Core calls
`rows` each time, and what they see is what the site said then.

**What core did:** drew the page, the header, the search, the sorting and the "Read just now"
line. It also put the page in the rail, because you named an `area`.

## Stage 4: things to do with a row

**What you have after it:** open, flag and remove, for one row or several.

A verb is something that can be done to the rows a person picks. Each row carries what its
verbs need, so the rows now add two keys of their own: where the score's page is, and whether
it can still be flagged.

`scoreboard/__init__.py` (excerpt)

```python
    def rows():
        return [{**one, "page": f"{ctx.config.get('site').rstrip('/')}/scores/{one['id']}",
                 "can_flag": not one["flagged"]} for one in call("/top")]
```

Then what each verb does:

`scoreboard/__init__.py` (excerpt)

```python
    def flag(picked):
        for one in picked:
            call(f"/scores/{one['id']}/flag", "POST")
        return ctx.t("message.flagged", count=len(picked))

    def remove(picked):
        for one in picked:
            call(f"/scores/{one['id']}", "DELETE")

    verbs = [
        {"key": "open", "link": "page"},
        {"key": "flag", "run": flag, "needs": "can_flag"},
        {"key": "remove", "run": remove, "danger": True},
    ]
```

And the list call gets the verbs. It also gets `acts`, a menu for the page as a whole, here
a link to the site itself:

`scoreboard/__init__.py` (excerpt)

```python
    ctx.ui.list("scores", rows, area="community", columns=columns, verbs=verbs,
                acts=lambda: {"site": ctx.config.get("site")})
```

The words for all of it:

`scoreboard/i18n/en.json` (excerpt)

```json
  "message.flagged": {"one": "Flagged the score", "other": "Flagged {count} scores"},
  "list.scores.act.site.label": "Open the Site",
  "list.scores.verb.open.label": "Open on the site",
  "list.scores.verb.flag.label": "Flag",
  "list.scores.verb.flag.needs": "Already flagged",
  "list.scores.verb.remove.label": "Remove",
  "list.scores.verb.remove.confirm": {
    "one": "Remove this score from the site?",
    "other": "Remove these {count} scores from the site?"
  },
```

**What you see:** tick a row and the line above the list reads "1 of 3 selected", with a
menu beside it holding Open on the site, Flag, Remove and Clear Selection. Right-click a row
for the same menu. Flag AAA and a message says "Flagged the score". Open the menu again and
Flag is dimmed, with "Already flagged" under it. Remove asks "Remove this score from the
site?" with Cancel and Remove, and does nothing until you press Remove. The menu in the
page's top right has Open the Site and Settings.

**What triggers it:** the person picking rows and pressing a verb. Your function is handed the
rows they picked, whole, with the keys you added. It runs once for however many were picked.

**What core did:** drew the menus, asked before the dangerous verb, dimmed Flag where
`can_flag` is false, said the message your function returned, and read the list again
afterwards, so the flag shows without a refresh.

See [Settings and lists](reference/settings-and-lists.md) for what a verb takes.

## Stage 5: a dialog

**What you have after it:** a way to post a score.

A dialog is an object core asks questions. `ask` gives the fields, `check` is handed what
was typed and either finds fault or says what comes next, and `run` does the work.

`scoreboard/__init__.py` (excerpt)

```python
class PostScore:
    def __init__(self, ctx, call):
        self.ctx = ctx
        self.call = call

    def ask(self, step):
        return {"title": self.ctx.t("dialog.title"),
                "fields": [
                    {"key": "player", "label": self.ctx.t("dialog.player"), "type": "string"},
                    {"key": "table", "label": self.ctx.t("dialog.table"), "type": "string"},
                    {"key": "score", "label": self.ctx.t("dialog.points"), "type": "number"}]}

    def check(self, values, step):
        needed = self.ctx.t("dialog.needed")
        errors = {key: needed for key in ("player", "table")
                  if not str(values.get(key) or "").strip()}
        if int(values.get("score") or 0) <= 0:
            errors["score"] = needed
        if errors:
            return {**self.ask(step), "errors": errors}
        return {"title": self.ctx.t("dialog.sure.title"),
                "confirm": self.ctx.t("dialog.confirm"),
                "summary": [[self.ctx.t("dialog.player"), values["player"]],
                            [self.ctx.t("dialog.table"), values["table"]],
                            [self.ctx.t("dialog.points"), f"{int(values['score']):,}"]]}

    def run(self, values):
        self.call("/scores", "POST", {"player": values["player"], "table": values["table"],
                                      "score": int(values["score"])})
        return self.ctx.t("dialog.posted", table=values["table"])
```

The class is handed `call`, the function from stage 3, so the dialog and the list talk to the
site the same way. One line in `register` gives it a name:

`scoreboard/__init__.py` (excerpt)

```python
    ctx.ui.action("post", PostScore(ctx, call))
```

The words:

`scoreboard/i18n/en.json` (excerpt)

```json
  "action.post.label": "Post a Score",
  "dialog.title": "The score",
  "dialog.player": "Player",
  "dialog.table": "Table",
  "dialog.points": "Score",
  "dialog.needed": "This is needed",
  "dialog.sure.title": "Post this score?",
  "dialog.confirm": "Post",
  "dialog.posted": "Posted a score for {table}",
```

**What you see:** the Scoreboard page in Settings has an Actions section with a **Post a
Score** button. Press it and a dialog called "The score" asks for Player, Table and Score.
Press Next with them empty and each says "This is needed" under it. Fill them in, press Next,
and the dialog changes to "Post this score?" and lists what you typed, with the score as
1,500,000 where you typed 1500000. Press Post and it says "Posted a score for" and the table.
Open the list and the score is there.

**What triggers it:** the person pressing the button. Nothing runs until then.

**What core did:** drew the dialog and its buttons, called `check` each time Next was pressed,
showed the errors under the fields they name, kept the person on the same step until there
were none, and showed the message `run` returned. The step is read off what you return: a
`summary` and a `confirm` make a "Post this score?" step.

See [Actions](reference/actions.md) for the steps a dialog can have and every type of field.

## Stage 6: reacting to the game

**What you have after it:** the extension hears when a game ends.

`scoreboard/__init__.py` (excerpt)

```python
    def played(game_id="", seconds=0, private=False, **_rest):
        if private:
            return
        ctx.logger.info("%s", ctx.t("log.played", game=game_id, count=round(seconds / 60)))

    ctx.events.subscribe("table.play_recorded", played)
```

and one word:

`scoreboard/i18n/en.json` (excerpt)

```json
  "log.played": {"one": "{game} was played for a minute", "other": "{game} was played for {count} minutes"}
```

**What you see:** a line in the log, such as `medieval-madness was played for 14 minutes`,
each time a game ends. Open Logs in the Console and look for lines from `vpinfe.ext.scoreboard`.

**What triggers it:** a game ending on the cabinet, after VPinFE has written the play. Play a
table and quit it. VPinFE emits the event and your function is called with what happened.

**What core did:** kept a list of who is listening, and called yours with the event's fields
as keyword arguments. Take what you use and `**_rest` for the rest, so a field added later
does not break you. The event carries `private`, true for a game somebody marked Private.
Return early on it: nothing about a Private game goes anywhere, a log line included once
you copy this shape into something that sends.

A handler that raises takes the extension out for the rest of the run, so keep it short. To
post the score of the game that just ended you would start a job, not wait for the site here.
See [Running one](reference/running.md) for what happens when an extension fails.

## The whole of it

That is all of Scoreboard, as it sits in the folder.

`scoreboard/extension.json`

```json
{
  "name": "scoreboard",
  "version": "1.0.0",
  "requires_platform": 1,
  "capabilities": ["config:own", "net:outbound", "ui:mount"]
}
```

`scoreboard/__init__.py`

```python
import json
import urllib.error
import urllib.request

from common.extensions.contract import Unavailable


class PostScore:
    def __init__(self, ctx, call):
        self.ctx = ctx
        self.call = call

    def ask(self, step):
        return {"title": self.ctx.t("dialog.title"),
                "fields": [
                    {"key": "player", "label": self.ctx.t("dialog.player"), "type": "string"},
                    {"key": "table", "label": self.ctx.t("dialog.table"), "type": "string"},
                    {"key": "score", "label": self.ctx.t("dialog.points"), "type": "number"}]}

    def check(self, values, step):
        needed = self.ctx.t("dialog.needed")
        errors = {key: needed for key in ("player", "table")
                  if not str(values.get(key) or "").strip()}
        if int(values.get("score") or 0) <= 0:
            errors["score"] = needed
        if errors:
            return {**self.ask(step), "errors": errors}
        return {"title": self.ctx.t("dialog.sure.title"),
                "confirm": self.ctx.t("dialog.confirm"),
                "summary": [[self.ctx.t("dialog.player"), values["player"]],
                            [self.ctx.t("dialog.table"), values["table"]],
                            [self.ctx.t("dialog.points"), f"{int(values['score']):,}"]]}

    def run(self, values):
        self.call("/scores", "POST", {"player": values["player"], "table": values["table"],
                                      "score": int(values["score"])})
        return self.ctx.t("dialog.posted", table=values["table"])


def register(ctx):
    ctx.ui.settings([
        {"key": "site", "type": "string", "default": "http://127.0.0.1:8790"},
        {"key": "key", "type": "secret"},
    ])

    def call(path, method="GET", body=None):
        request = urllib.request.Request(
            ctx.config.get("site").rstrip("/") + path, method=method,
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
        return [{**one, "page": f"{ctx.config.get('site').rstrip('/')}/scores/{one['id']}",
                 "can_flag": not one["flagged"]} for one in call("/top")]

    columns = [
        {"field": "player"},
        {"field": "table"},
        {"field": "score", "kind": "number"},
    ]

    def flag(picked):
        for one in picked:
            call(f"/scores/{one['id']}/flag", "POST")
        return ctx.t("message.flagged", count=len(picked))

    def remove(picked):
        for one in picked:
            call(f"/scores/{one['id']}", "DELETE")

    verbs = [
        {"key": "open", "link": "page"},
        {"key": "flag", "run": flag, "needs": "can_flag"},
        {"key": "remove", "run": remove, "danger": True},
    ]

    ctx.ui.list("scores", rows, area="community", columns=columns, verbs=verbs,
                acts=lambda: {"site": ctx.config.get("site")})

    ctx.ui.action("post", PostScore(ctx, call))

    def played(game_id="", seconds=0, private=False, **_rest):
        if private:
            return
        ctx.logger.info("%s", ctx.t("log.played", game=game_id, count=round(seconds / 60)))

    ctx.events.subscribe("table.play_recorded", played)
```

`scoreboard/i18n/en.json`

```json
{
  "name": "Scoreboard",
  "description": "Lists, flags, removes and posts the scores on Example Scores.",
  "settings.site.label": "Site",
  "settings.key.label": "Key",
  "settings.key.help": "The practice site's key is practice-key",
  "error.refused": "The site did not accept the key",
  "message.flagged": {"one": "Flagged the score", "other": "Flagged {count} scores"},
  "list.scores.title": "Scoreboard",
  "list.scores.column.player.header": "Player",
  "list.scores.column.table.header": "Table",
  "list.scores.column.score.header": "Score",
  "list.scores.act.site.label": "Open the Site",
  "list.scores.verb.open.label": "Open on the site",
  "list.scores.verb.flag.label": "Flag",
  "list.scores.verb.flag.needs": "Already flagged",
  "list.scores.verb.remove.label": "Remove",
  "list.scores.verb.remove.confirm": {
    "one": "Remove this score from the site?",
    "other": "Remove these {count} scores from the site?"
  },
  "action.post.label": "Post a Score",
  "dialog.title": "The score",
  "dialog.player": "Player",
  "dialog.table": "Table",
  "dialog.points": "Score",
  "dialog.needed": "This is needed",
  "dialog.sure.title": "Post this score?",
  "dialog.confirm": "Post",
  "dialog.posted": "Posted a score for {table}",
  "log.played": {"one": "{game} was played for a minute", "other": "{game} was played for {count} minutes"}
}
```

## Where next

- **Another way to hold a person's data.** Scoreboard has one key for the whole cabinet. If
  each player has their own, see [an account per player](cookbook.md#13-an-account-per-player).
- **Something that takes a while.** Posting is quick. A sync of every score is not, and wants
  [a long job with progress](cookbook.md#5-a-long-job-with-progress).
- **Every call.** The [reference](reference.md) has a page for each part of `ctx`.
