# Extensions: reference

An extension adds a feature to an install without being part of VPinFE. It ships as a
directory, declares what it needs in a manifest, and is handed one object, `ctx`, that it
reaches everything through. It never receives the application.

The word is **extension** throughout. *Plugin* means a Visual Pinball standalone plugin,
which is a different thing with its own page.

**Core writes and mounts every route.** An extension hands core data and Python
functions: settings, rows, a dialog object, an account's functions. Core serves them
under `/api/v1/ext/<name>`, draws them in the Console and gates them. An extension adds
routes of its own with `ctx.add_router` only for an API that is its own.

This page is for looking things up. Each `ctx` call has a heading, each declaration has a
section, and each section opens with the shape and then shows it.

## A whole extension

An extension with a setting, a secret, and a list of scores read from a server.

```
example_scores/
    extension.json
    __init__.py
    i18n/
        en.json
```

`extension.json`:

```json
{
  "name": "example_scores",
  "display_name": "Example Scores",
  "version": "0.1.0",
  "description": "Lists the top scores from an example scores server.",
  "requires_platform": 1,
  "capabilities": ["ui:mount", "config:own", "net:outbound"]
}
```

`__init__.py`:

```python
import json
import urllib.error
import urllib.request

from common.extensions.contract import Unavailable


def register(ctx):
    ctx.ui.settings([
        {"key": "server", "type": "string", "default": "https://scores.example.com"},
        {"key": "api_key", "type": "secret"},
    ])

    def top():
        address = ctx.config.get("server")
        key = ctx.config.get("api_key")
        request = urllib.request.Request(
            f"{address}/top", headers={"Authorization": f"Bearer {key}"} if key else {})
        try:
            with urllib.request.urlopen(request, timeout=10) as answer:
                return json.load(answer)
        except (urllib.error.URLError, TimeoutError) as exc:
            raise Unavailable(ctx.why(exc, at=address)) from exc

    def send_now():
        return ctx.t("sent", count=3)

    ctx.ui.list(
        "top", top, title="Example Scores",
        columns=[{"field": "name", "under": ["manufacturer"]},
                 {"field": "manufacturer"},
                 {"field": "score", "kind": "number"},
                 {"field": "played", "kind": "date"}],
        views=[{"key": "best", "columns": ["name", "score"],
                "sort": [{"field": "score", "desc": True}]}],
        acts={"send_now": send_now, "site": "https://scores.example.com"},
    )
```

`i18n/en.json`:

```json
{
  "description": "Lists the top scores from an example scores server.",
  "settings.server.label": "Server",
  "settings.server.help": "Where scores are read from. Blank uses {default}.",
  "settings.api_key.label": "API key",
  "list.top.column.name.header": "Table",
  "list.top.column.manufacturer.header": "Maker",
  "list.top.column.score.header": "Score",
  "list.top.column.played.header": "Played",
  "list.top.view.best.name": "Best Scores",
  "list.top.act.send_now.label": "Send Now",
  "list.top.act.site.label": "Open the Site",
  "sent": {"one": "{count} score sent", "other": "{count} scores sent"}
}
```

Put the folder in `extensions/` under the config directory, or run
`python main.py --check-extension ./example_scores` first (see "Checking one"). The
extension then has a page under Settings > Extensions with its two settings, and a list
called Example Scores under Community.

### Where an extension lives

The directory name is the extension's name, and the manifest has to agree. The name
addresses it in a URL, a scope, a log namespace, a config file and the Python package core
imports, so two answers to what it is called would each be right somewhere.

`__init__.py` defines `register(ctx)`. Core calls it once at startup and never again.
The package is imported under its name, so the name has to be a legal module name.

Two places are searched, in this order: `extensions/` under the config directory, then the
`extensions/` the build ships. An installed extension with the same name as a bundled one
answers, and the bundled one is left alone.

Registration is a moment. After `register` returns, `ctx.open` is False and anything that
needs to be declared (a router, for one) is refused.

## The manifest

`extension.json`, snake_case like every other JSON VPinFE writes. A key not in the table
is ignored.

| key | Required | Default | what it is |
|---|---|---|---|
| `name` | yes | none | 2 to 40 characters: `a-z`, `0-9` and `_`, starting with a letter. Matches the directory |
| `requires_platform` | yes | none | The platform ABI it was built against. This build offers `1`. Any other number is refused |
| `display_name` | no | empty | A product name, shown as written in every language. Left out, it is `name` in its own `i18n/`, and then the extension's `name` |
| `version` | no | empty | The extension's own version. Shown, never interpreted |
| `description` | no | empty | One line, shown beside it. Left out, it is `description` in its own `i18n/` |
| `scopes` | no | none | Core scopes it asks to use, such as `games:read`. See "Scopes and the gate" |
| `capabilities` | no | none | What it asks of the machine. See "Scopes and the gate" |
| `requires_features` | no | none | Install features it needs: `library`, `frontend`, `devices`, `overview` |
| `platforms` | no | every one | `linux`, `windows`, `macos`. Empty means every one |
| `events` | no | none | Event names it publishes, without its namespace |

Everything in it is a declaration a person can be shown before installing, which is why an
unknown capability, feature or platform is refused rather than ignored: a name nobody has
heard of is not something anybody could have agreed to.

An extension whose manifest names a platform this machine is not, or a feature this
install does not have, is not started. It is still listed, with the reason.

There is no `provides`: core mints `ext:<name>:read` and `ext:<name>:write` for every
extension. Whether an extension has settings is not declared either; core remembers what
a running extension registered, so its page can say its settings show while it runs.

## The context

`ctx` is the whole of an extension's reach. There is no way to get from it to the
application, and that is the guarantee the model rests on.

| on `ctx` | what it is |
|---|---|
| `ctx.name`, `ctx.manifest`, `ctx.host_version`, `ctx.logger`, `ctx.open`, `ctx.routers` | What this extension is, which VPinFE runs it, its log, and its own routes |
| `ctx.t`, `ctx.why`, `ctx.scope`, `ctx.add_router` | Words, a failure in words, a scope name, and an API of its own |
| `ctx.config` | `get`, `all`, `set` over its own settings |
| `ctx.events` | `subscribe` to a core event, `publish` one of its own |
| `ctx.files` | The folders it works from |
| `ctx.jobs` | Slow work, run the way core runs it |
| `ctx.ui` | What it offers a person: settings, lists, actions, an account, what it holds |
| `ctx.players` | Who plays here, and the accounts it holds for them |
| `ctx.entries` | Something added to every entry a theme is handed |
| `ctx.catalogs` | Where a game, a table or a file is somewhere else |
| `ctx.tokens` | A name a user may write into a command |
| `ctx.games` | The library, and everything core offers by name |
| `ctx.apps` | A way to play a table |

Every call that needs a capability or a scope its manifest did not declare raises
`ContractError`, from `common.extensions.contract`. During `register` that fails the
extension (see "When one breaks").

An extension imports `common.extensions.contract` and nothing else of VPinFE's. It holds
`Unavailable`, `ContractError`, `words(name)` and `why(exc, at="")`; the last two are
`ctx.t` and `ctx.why` for a module that is not handed `ctx`.

### The extension itself

#### `ctx.name`

The manifest's `name`: a string. It is also the Python package name and the URL segment.

```python
ctx.logger.info("%s is registering", ctx.name)
```

#### `ctx.manifest`

The parsed manifest, frozen: `name`, `display_name`, `version`, `description`,
`requires_platform`, `scopes`, `capabilities`, `requires_features`, `platforms`, `events`.
The lists are tuples.

```python
if "net:outbound" in ctx.manifest.capabilities:
    ctx.logger.debug("version %s may reach the network", ctx.manifest.version)
```

#### `ctx.host_version`

The version of the VPinFE running the extension, as a string.

```python
headers = {"User-Agent": f"{ctx.name}/{ctx.manifest.version} VPinFE/{ctx.host_version}"}
```

#### `ctx.logger`

A `logging.Logger` named `vpinfe.ext.<name>`. See "Logs".

```python
ctx.logger.warning("score server answered slowly: %s seconds", 4)
```

#### `ctx.open`

True while `register` runs and False after. Not something to branch on in normal code;
it is why a router added later is refused.

```python
assert ctx.open
```

#### `ctx.routers`

The routers added so far, as `(router, scope)` pairs. Read by core after `register`.
An extension has no reason to touch it; use `ctx.add_router`.

```python
ctx.add_router(router, scope=ctx.scope("read"))
assert (router, "ext:example_scores:read") in ctx.routers
```

#### `ctx.t`

`ctx.t(key, /, **params) -> str`. Required: `key`.

What the extension's own `i18n/<language>.json` says for `key`, in the language now set.
Slots in braces are filled from `params`. A plural entry is chosen by `count`.

```python
line = ctx.t("sent", count=3)    # "3 scores sent"
```

The user sees the sentence in their language. A key the catalog lacks answers the full key,
`ext.<name>.<key>`, so the gap is visible and `--check-extension` reports it. See "Words".

#### `ctx.why`

`ctx.why(exc, /, at="") -> str`. Required: `exc`.

Why something failed, in the words core uses under its own failures: a missing file, a
refused permission, a host that did not answer. For an exception core has no words for it
is the exception's own text, so the extension words that one itself. `at` is the URL or
path being reached, for an exception that does not carry it, such as the standard
library's `URLError`.

```python
try:
    urllib.request.urlopen(address, timeout=10)
except (urllib.error.URLError, TimeoutError) as exc:
    raise Unavailable(ctx.why(exc, at=address)) from exc
```

The user sees a line like `scores.example.com did not answer in time`. It does not raise.

#### `ctx.scope`

`ctx.scope(action) -> str`. Required: `action`.

The scope name for one of this extension's actions: `ext:<name>:<action>`. Only `read` and
`write` are real.

```python
router_scope = ctx.scope("write")    # "ext:example_scores:write"
```

Nothing is drawn. It raises nothing; a name other than `read` or `write` is refused later,
by `ctx.add_router`.

#### `ctx.add_router`

`ctx.add_router(router, *, scope)`. Required: `router`, `scope`.

Serve routes of the extension's own under `/api/v1/ext/<name>/`. Core attaches the gate;
the extension cannot choose to have none. `scope` is `ctx.scope("read")` or
`ctx.scope("write")`, and a request needs it. Use it for an API that is the extension's
own, such as a route a theme calls or a picture the service serves. Everything declared
through `ctx.ui` is served by core and needs no router.

```python
from fastapi import APIRouter

router = APIRouter()


@router.get("/hello")
def hello() -> dict:
    return {"name": ctx.name}


ctx.add_router(router, scope=ctx.scope("read"))
```

Nothing is drawn; a theme or another program calls `GET /api/v1/ext/<name>/hello`. It
raises `ContractError` if called after `register` returned, or if `scope` is not this
extension's `read` or `write`.

Routers mount once, at startup. An extension that adds routers and is switched on after
the run began shows "Starts at the next restart" rather than starting. See "Switching one
on or off".

### `ctx.config`

An extension's settings, under its own name. See "Config" for where they are kept.

#### `ctx.config.get`

`ctx.config.get(key, default="") -> str`. Required: `key`.

What is stored under `key`; where that is empty, the default the setting declares; where
there is neither, `default`. Always a string. A switch is `"true"` or `"false"`.

```python
address = ctx.config.get("server")
retries = int(ctx.config.get("retries", "3"))
```

The user sees the value they typed in the extension's settings. Does not raise.

#### `ctx.config.all`

`ctx.config.all() -> dict[str, str]`.

Everything stored, as strings. Settings never written are absent; defaults are not mixed
in. Includes secrets.

```python
held = ctx.config.all()
ctx.logger.debug("keys set: %s", sorted(held))
```

Does not raise.

#### `ctx.config.set`

`ctx.config.set(key, value)`. Required: `key`, `value`.

Store `value` under `key`. It need not be a declared setting; a key that is not declared
is kept but never drawn, and `accounts` and `declared` are reserved names. Values are text.

```python
ctx.config.set("last_week", "42")
```

The user sees the new value if the key is a declared setting. The file is written at once.

### `ctx.events`

The bus, seen from one extension. It is told what core did, and publishes under its own
namespace so nothing it emits can be mistaken for a core event.

#### `ctx.events.subscribe`

`ctx.events.subscribe(event, handler)`. Required: `event`, `handler`.

Call `handler(**payload)` whenever core emits `event`. See "What a game tells you" for the
events and what each carries. A handler takes keyword arguments and ignores what it does
not use. It runs on the thread that emitted the event, so it must return quickly.

```python
def on_played(**payload):
    if not payload["private"]:
        ctx.logger.info("played for %s seconds", payload["seconds"])


ctx.events.subscribe("table.play_recorded", on_played)
```

A handler that raises is contained and logged, and takes the extension out for this run
with the reason "Failed while handling table.play_recorded". Its subscriptions are
dropped and its routes answer 501.

#### `ctx.events.publish`

`ctx.events.publish(event, **payload)`. Required: `event`.

Emit `<name>.<event>` with `payload`. `event` has to be named in the manifest's `events`.

```python
ctx.events.publish("scored", game_id="g1", score=10)    # emits "example_scores.scored"
```

Other extensions and core subscribers hear it. It raises `ContractError` for an event the
manifest does not declare.

### `ctx.files`

The folders an extension works from, so core accepts a path inside one. Nothing here stops
an extension reading a file, because in-process Python cannot be prevented from opening
one. What it does is let core's own routes take a path the extension is working with: an
importer converting an old library has to hand core files nowhere near VPinFE's, and
without this every one is refused. Declared rather than assumed, so what an install will
read is something a person agreed to and can be shown.

#### `ctx.files.set_roots`

`ctx.files.set_roots(paths)`. Required: `paths`.

Replace the set of folders. Paths are expanded and resolved. Call it again when the user
points somewhere else; the set follows rather than accumulates. Needs the `fs:read`
capability.

```python
ctx.files.set_roots([ctx.config.get("source")])
```

The user sees, on the extension's page, that it reads files. Raises `ContractError`
without `fs:read`.

#### `ctx.files.roots`

`ctx.files.roots() -> tuple[str, ...]`.

The folders now declared, resolved.

```python
inside = any(path.startswith(root) for root in ctx.files.roots())
```

Does not raise.

#### `ctx.files.may_write`

`ctx.files.may_write() -> bool`.

Whether the manifest declared `fs:write`, which is what lets `ctx.games.add_table(...,
move=True)` take a file out of one of these folders instead of copying it.

```python
if not ctx.files.may_write():
    ctx.logger.info("copying, not moving")
```

Does not raise.

### `ctx.jobs`

Slow work, run the way core runs it. The job id is `<name>.<kind>`, so a job somebody is
watching says which extension is doing it. One at a time per kind: two imports of one
library at once would race each other into the same folders.

#### `ctx.jobs.submit`

`ctx.jobs.submit(kind, work, *, stoppable=False, keep_result=False) -> Job`.
Required: `kind`, `work`.

Run `work(job)` on its own thread. The job appears in the Jobs view and on
`/api/v1/jobs`. `work` receives the job:

| on the job | what it does |
|---|---|
| `job.progress(done, total, message)` | Says how far it is |
| `job.log(message)` | Adds a line to what the job reports |
| `job.detail` | A line beside the progress |
| `job.halt` | A `threading.Event`, set when somebody asks the job to stop. Look at it between units |
| `job.stopped` | Set it to True when the work ended early because `halt` was set |
| `job.problems` | How many parts did not come across |
| `job.id` | The id a run answers with as `job_id` |

With `stoppable=True` the job offers a **Stop** link, which calls
`POST /api/v1/ext/<name>/jobs/<kind>/stop` on the write scope. With `keep_result=True`
what `work` returns is written to disk, the latest 20 (the oldest go first), so the Jobs
view can open it after the page that started the job has gone, after a restart too. A
result may list `rows`, and every row with an `error` is shown under what did not come
across, by its `name`; `error` takes a string or `{text, detail}`.

```python
def work(job):
    for index, game in enumerate(games, start=1):
        if job.halt.is_set():
            job.stopped = True
            break
        job.progress(index, len(games), game["name"])
    return {"rows": []}


job = ctx.jobs.submit("import", work, stoppable=True, keep_result=True)
```

The user sees the job in the Jobs view with its progress, and a Stop link when
`stoppable`. An exception out of `work` ends the job as failed with that message; it does
not take the extension out.

#### `ctx.jobs.stop`

`ctx.jobs.stop(kind) -> bool`. Required: `kind`.

Ask this extension's running job of that kind to end early, by setting `job.halt`. False
where there is none, or where it was not started `stoppable`. It does not wait.

```python
if not ctx.jobs.stop("import"):
    ctx.logger.info("nothing to stop")
```

Does not raise.

#### `ctx.jobs.active`

`ctx.jobs.active() -> tuple[str, ...]`.

The ids of this extension's running jobs.

```python
busy = bool(ctx.jobs.active())
```

Does not raise.

### `ctx.ui`

What an extension offers a person. It is declared rather than drawn, and served by core:
the extension hands over fields, a `rows()` function and a dialog object, and core mounts
the routes the Console reads. All of it needs the `ui:mount` capability, and every call
here raises `ContractError` without it. The sections after this one describe each
declaration in full.

#### `ctx.ui.settings`

`ctx.ui.settings(fields, *, check=None)`. Required: `fields`.

Declare the extension's settings: a list of `{"key", "type", "default", "choices"}`. Once
only. See "Settings".

```python
ctx.ui.settings(
    [{"key": "server", "type": "string", "default": "https://scores.example.com"},
     {"key": "region", "type": "select", "default": "eu",
      "choices": [["eu", "Europe"], ["us", "United States"]]}],
    check=lambda values: None)
```

The user sees the fields on the extension's page. Raises `ContractError` if called twice,
if a key repeats, if a type is not one a settings page draws, if a secret has a default, if
a select has no choices or a default that is not one of them, or if `check` is not
callable.

#### `ctx.ui.settings_defaults`

`ctx.ui.settings_defaults() -> dict[str, str]`.

The declared default of each setting, by key. `ctx.config.get` already falls back to these;
this is for code that wants the whole set.

```python
defaults = ctx.ui.settings_defaults()
```

Does not raise. Empty before `settings` was called.

#### `ctx.ui.list`

`ctx.ui.list(key, rows, *, columns, area="community", title="", views=(), status=None,
acts=None, relation=None, tag="", verbs=())`. Required: `key`, `rows`, `columns`.

Declare a list. `rows()` returns the rows, each a dict. See "Lists" for columns, views,
acts, relation, tag and verbs.

```python
ctx.ui.list("top", read_top, title="Example Scores",
            columns=[{"field": "name"}, {"field": "score", "kind": "number"}])
```

The user sees the list in the rail under `area`. Raises `ContractError` for an unknown
area, no key or columns, a repeated key, rows or status that are not functions, `under` on
any column but the first, an unknown column kind, a view on a column the list lacks, a
relation on a missing field or with `keys` other than `vps_entry` or `vps_release`, a `tag`
without a relation, or a ranked view that sorts on anything but number or date columns or
has no relation, or a verb that is not a dict, has no key or a key already used, carries a key
core does not read, has both a `run` and a `link` or neither, or puts `danger` or `needs` on a
`link`. After `register` also raises when the title equals a core page's title
or another running extension's list in the same area.

#### `ctx.ui.kept`

`ctx.ui.kept(key) -> dict | None`. Required: `key`.

The last good read core keeps of one of this extension's lists: `{"rows": [...],
"read_at": "<UTC time>"}`, or None before the first good read. It is how an extension has
its list at start, before core's first read and whether or not the service answers.

```python
kept = ctx.ui.kept("top")
if kept is not None:
    cache.load(kept["rows"], kept["read_at"])
```

Does not raise beyond the `ui:mount` check.

#### `ctx.ui.action`

`ctx.ui.action(key, dialog, *, label="", description="")`. Required: `key`, `dialog`.

Offer a verb for the Console to draw. `dialog` is an object with `ask(step)` and, as far as
the action needs them, `check`, `act`, `run` and `progress`. See "Actions and dialogs".

```python
class Reset:
    def ask(self, step):
        return {"confirm": ctx.t("action.reset.confirm")}

    def run(self, values):
        return ctx.t("action.reset.done")


ctx.ui.action("reset", Reset())
```

The user sees a button under Actions on the extension's page, which opens a dialog.
Raises `ContractError` for a key that is empty or already used, or a `dialog` without a
callable `ask`.

#### `ctx.ui.state`

`ctx.ui.state(base, label="")`. Required: `base`.

Say where core reads what the extension is holding: rows with at most two buttons each,
drawn on its page. `base` is a route the extension serves itself with `ctx.add_router`,
under `GET /api/v1/ext/<name><base>`.

```python
@router.get("/held")
def held() -> dict:
    return {"rows": [{"id": "a", "label": "Taxi", "mark": "Pending",
                      "detail": "Waiting to send",
                      "actions": [{"key": "drop", "label": "Drop"}]}],
            "empty": ctx.t("held.empty")}


ctx.ui.state("/held", label=ctx.t("state.label"))
```

The user sees a section on the extension's page headed by `label`, then `state.label` in
its catalog, then the Console's own "Held". See "What it holds". Raises `ContractError`
without `ui:mount`.

#### `ctx.ui.account`

`ctx.ui.account(*, read, write=None, acts=None, card=None, read_card=None, available=None,
label="", cards=(), marker="", consent=(), sends_picture=False)`. Required: `read`.

Say that a player can hold an account with this extension. Once only. See "Accounts".

```python
ctx.ui.account(
    read=lambda player_id: {"user_id": "", "claimed": False, "acts": []},
    write=lambda player_id, values: ctx.players.set_account(player_id, values),
    consent=(ctx.t("account.consent.id"),))
```

The user sees the account in each player's panel under Frontend > Players. Raises
`ContractError` for a second account, a `read` that is not a function, a card type that is
empty, a marker that is not a plain name, `cards` without `read_card`, or an act that is
not a function.

### `ctx.players`

Who plays is core's; what a service calls them is the extension's. Core keeps the roster
(the owner, the other players, the guests, who is up) and an extension holds an account for
any of them it can. A row is plain data: `id`, `name`, `initials`, `owner`, `guest`, `up`,
`shares_initials_with`, `picture_version`.

#### `ctx.players.roster`

`ctx.players.roster() -> list[dict]`.

Every player: the owner, the kept players, then the guests as they joined. Needs
`players:read` in `scopes`, because names and initials are about people.

```python
names = [one["name"] for one in ctx.players.roster()]
```

Raises `ContractError` without `players:read`.

#### `ctx.players.get`

`ctx.players.get(player_id) -> dict | None`. Required: `player_id`.

One row, or None. Needs `players:read`.

```python
owner = next((one for one in ctx.players.roster() if one["owner"]), None)
initials = (ctx.players.get(owner["id"]) or {}).get("initials", "")
```

Raises `ContractError` without `players:read`.

#### `ctx.players.up`

`ctx.players.up() -> list[dict]`.

The rows of who the next game counts for. Needs `players:read`.

```python
if len(ctx.players.up()) > 1:
    ctx.logger.info("several players are up")
```

Raises `ContractError` without `players:read`.

#### `ctx.players.record`

`ctx.players.record(player_id, game_id) -> dict | None`. Required: both.

What a player other than the owner has done with one game, as
`GET /api/v1/players/{id}/record` lists it: `play_count`, `play_time_seconds`,
`last_played`, `best_score`, `rating`. None for the owner, whose record is the library's and
is read through `ctx.games`, and for a player nobody has. Read only. Needs `players:read`.

```python
record = ctx.players.record(player_id, game_id) or {}
plays = record.get("play_count", 0)
```

Raises `ContractError` without `players:read`.

#### `ctx.players.sharing`

`ctx.players.sharing(player_id) -> bool`. Required: `player_id`.

Whether this player's account with this extension is sharing. Share is core's switch, the
same on every account; it is off until somebody turns it on, except for a guest who joined
with a card, whose account shares. An extension sends nothing on its own while it is off.
Something the person asks for by hand, an act, is theirs to have asked. Needs nothing
declared.

```python
if ctx.players.sharing(player_id):
    send(player_id)
```

Does not raise.

#### `ctx.players.picture`

`ctx.players.picture(player_id) -> Path | None`. Required: `player_id`.

The path of the player's picture file. Only for an extension that declared
`sends_picture=True` on its account, and only while that player's Share here is on. None
otherwise: Share off, a guest, no picture, or `sends_picture` not declared. There is no
second switch.

```python
path = ctx.players.picture(player_id)
if path is not None:
    upload(path.read_bytes())
```

Does not raise.

#### `ctx.players.account`

`ctx.players.account(player_id) -> dict[str, str]`. Required: `player_id`.

The values this extension holds for the player, secrets included. Empty when they hold none.
Values are strings.

```python
held = ctx.players.account(player_id)
user_id = held.get("user_id", "")
```

Does not raise.

#### `ctx.players.set_account`

`ctx.players.set_account(player_id, values)`. Required: both.

Replace the account's values. An empty `values` removes the account. They are kept in the
extension's settings file under `accounts`, keyed by player id. **A guest's are held in
memory and never written**, so a visitor leaves nothing on the disk, and they go when the
guest does. Removing a player forgets their account with every extension.

```python
ctx.players.set_account(player_id, {"user_id": "ace", "key": secret})
ctx.players.set_account(player_id, {})    # disconnect
```

Does not raise.

#### `ctx.players.holders`

`ctx.players.holders() -> list[str]`.

The ids of every player holding an account here, in roster order.

```python
for player_id in ctx.players.holders():
    refresh(player_id)
```

Does not raise.

### `ctx.entries`

Something added to every entry a theme is handed. See "Something to an entry".

#### `ctx.entries.contribute`

`ctx.entries.contribute(key, fetch)`. Required: both.

Answer about one game at a time. `fetch(game)` receives `{game_id, vps_id, name,
manufacturer, year, ipdb_id}`, each the effective value, and returns whatever a theme
should read, or None where there is nothing to say. It is called on core's thread when the
wheel stops, so it may block, and it must not raise for a game it simply has no answer
about.

```python
ctx.entries.contribute("rating", lambda game: {"stars": 4} if game["vps_id"] else None)
```

A theme reads `entry.ext.rating`. Raises `ContractError` for an empty key.

#### `ctx.entries.stale`

`ctx.entries.stale(key)`. Required: `key`.

What this extension answered under `key` is out of date: core drops what it holds, and each
game is asked again the next time it is reached. Only the extension that contributes a key
can drop it.

```python
ctx.entries.stale("rating")
```

Does not raise.

### `ctx.catalogs`

Where a game, a table or a file is somewhere else. See "An outside link".

#### `ctx.catalogs.contribute`

`ctx.catalogs.contribute(key, name, subject, link)`. Required: all four.

`subject` is `game`, `table` or `file`. `link(item)` receives a plain description of one
and returns its address there, or `""`.

```python
ctx.catalogs.contribute("scores", "Example Scores", "game",
                        lambda game: f"https://scores.example.com/t/{game['vps_id']}")
```

The user sees a row named `name` with an open-in-new icon. A `link` that raises, or
answers anything but an http or https address, is left out. Raises `ContractError` for any
other `subject`.

### `ctx.tokens`

A name a user may write into a command. See "A name a command can use".

#### `ctx.tokens.VPINFE`

The string `"vpinfe"`: the context of the pair of commands around VPinFE itself.

```python
ctx.tokens.offer("season", (ctx.tokens.VPINFE, ctx.tokens.TABLE), lambda values: "spring")
```

#### `ctx.tokens.TABLE`

The string `"table"`: the context of the pair of commands around every table.

```python
ctx.tokens.offer("season", (ctx.tokens.TABLE,), lambda values: "spring")
```

#### `ctx.tokens.offer`

`ctx.tokens.offer(name, contexts, value, *, says="", after_only=False) -> str`.
Required: `name`, `contexts`, `value`.

Offer `{<extension>.<name>}`. Answers the full name, which is what a user types. `value(values)`
receives what the command context has resolved so far and answers a string; empty is an
answer.

```python
full = ctx.tokens.offer("season", (ctx.tokens.TABLE,), lambda values: "spring")
# full == "example_scores.season"
```

The user sees it in the list of names a command may use, with what it stands for. Raises
`ContractError` for a name with nothing saying what it stands for (`says`, or
`token.<name>.says` in the catalog), an unknown context, or a name already taken.

### `ctx.games`

The library, as an extension is allowed to see it. It is not a second implementation of the
HTTP API; it calls the API's own route functions, so the two cannot answer differently.
An extension in this process cannot use the API over HTTP, because a synchronous call into
the server it is running inside deadlocks, and it may not import the library, so this is
the door.

It is bounded twice. The manifest's `scopes` decide which calls an extension may make, and
a path it hands over has to be inside a folder it declared through `ctx.files.set_roots`.
A call that needs a scope the manifest lacks raises `ContractError`; so does a path outside
the declared folders.

| call | scope it needs |
|---|---|
| `kinds`, `existing`, `folder_name_for`, `folder`, `survey`, `companions_of`, `companions_for`, `roms_of`, `reads_of`, `saved_sets`, `asset_kinds` | `games:read` |
| `create`, `add_table`, `put_saved_sets`, `put_asset`, `put_rom_alias`, `put_media` | `games:write` |
| `put_manufacturer_logos` | `config:write` |
| `reaches` | none |

The rest of the library is offered by name, listed under "Offered by name" below.

#### `ctx.games.kinds`

`ctx.games.kinds() -> tuple[str, ...]`.

Every media kind this build stores: the vocabulary an importer maps onto, so it need not
hard-code a list that would go stale.

```python
wanted = [kind for kind in ("wheel", "backglass", "flyer") if kind in ctx.games.kinds()]
```

#### `ctx.games.existing`

`ctx.games.existing() -> list[dict]`.

Every game already here, in the little an importer needs to recognize one: `game_id`,
`folder_name`, `name`, `vps_id`, `ipdb_id`, and `table_files`, the lowercase names of the
game files it holds. Not the whole library; a second run asks "have I made this one
before", and folder name, catalog id and title answer it.

```python
made = {one["folder_name"] for one in ctx.games.existing()}
```

#### `ctx.games.folder_name_for`

`ctx.games.folder_name_for(name) -> str`. Required: `name`.

The folder a game of this name would get. Asked rather than guessed: `Star Trek: The Next
Generation` and `Star Trek The Next Generation` are one folder here, and an importer that
reads them as two fails on a name already taken.

```python
folder = ctx.games.folder_name_for("Star Trek: The Next Generation")
```

#### `ctx.games.folder`

`ctx.games.folder(game_id) -> str`. Required: `game_id`.

The game's folder on disk. Raises `LookupError` for an unknown game.

```python
where = ctx.games.folder(game_id)
```

#### `ctx.games.survey`

`ctx.games.survey(path) -> dict`. Required: `path`.

What a folder holds: `game_folders` the library would read as games, and the `loose` table
files lying in it. A name that starts with a dot is left out. Only a folder this extension
works from.

```python
found = ctx.games.survey(ctx.config.get("source"))
count = len(found["game_folders"]) + len(found["loose"])
```

Raises `ContractError` for a folder outside `ctx.files.roots()`.

#### `ctx.games.create`

`ctx.games.create(name, location="") -> str`. Required: `name`.

Make an entry and answer with its id. `location` names a library folder, or is empty for
the default.

```python
game_id = ctx.games.create("Taxi")
```

The user sees a new game in the library. Raises `LookupError` if the entry is not among
the games this device reads.

#### `ctx.games.add_table`

`ctx.games.add_table(game_id, path, move=False, names=()) -> dict`.
Required: `game_id`, `path`.

Copy a game file into an entry, with whatever belongs to it. Answers `table_id`,
`companions`, `rom` (the ROM the table turns out to need) and `named`, those of `names`
that the table's script mentions as a string, whole word and any case. `move=True` takes
the files out of where they were, which needs the `fs:write` capability.

```python
added = ctx.games.add_table(game_id, "/data/old/Taxi.vpx", names=("Taxi",))
table_id = added["table_id"]
```

Raises `ContractError` for a path outside the declared folders or `move` without
`fs:write`, and `FileNotFoundError` for a file that is not there.

#### `ctx.games.companions_of`

`ctx.games.companions_of(path) -> tuple[str, ...]`. Required: `path`.

The file names that would come with this table if it were added. For counting beforehand,
so a plan and the run that follows it agree.

```python
beside = ctx.games.companions_of("/data/old/Taxi.vpx")
```

Raises `FileNotFoundError` for a table that is gone, and `ContractError` outside the
declared folders.

#### `ctx.games.companions_for`

`ctx.games.companions_for(paths) -> dict[str, tuple[str, ...]]`. Required: `paths`.

`companions_of` for many tables, each folder listed once. On a network share a listing is
the cost, so ask for a library together. Keyed by the path as given; a table that is gone is
left out where `companions_of` raises, so a table with nothing beside it can be told from
one that is gone.

```python
beside = ctx.games.companions_for(["/data/old/Taxi.vpx", "/data/old/Eight Ball.vpx"])
```

Raises `ContractError` outside the declared folders.

#### `ctx.games.roms_of`

`ctx.games.roms_of(paths) -> dict[str, str]`. Required: `paths`.

`{path: rom}` for the tables whose script names a ROM. Each table's script is read; a table
that is gone, cannot be read or names none is left out.

```python
roms = ctx.games.roms_of(["/data/old/Taxi.vpx"])
```

Raises `ContractError` outside the declared folders. Opening a table costs a read of the
file, so ask for a library in batches and keep what you are told.

#### `ctx.games.reads_of`

`ctx.games.reads_of(paths, names=()) -> dict[str, tuple[str, tuple[str, ...]]]`.
Required: `paths`.

`roms_of` and, from the same read, which of `names` each script mentions. Answers
`{path: (rom, named)}` and keeps a table that names no ROM, with `""`.

```python
read = ctx.games.reads_of(["/data/old/Taxi.vpx"], names=("Taxi", "DOF"))
rom, named = read["/data/old/Taxi.vpx"]
```

Raises `ContractError` outside the declared folders.

#### `ctx.games.saved_sets`

`ctx.games.saved_sets(path) -> tuple[str, ...]`. Required: `path`.

The names of the sets a `VPReg.stg` holds, for matching to the tables that save under them.
Empty where the file is not one.

```python
sets = ctx.games.saved_sets("/data/old/VPReg.stg")
```

#### `ctx.games.put_saved_sets`

`ctx.games.put_saved_sets(game_id, path, sets) -> int`. Required: all three.

Write the named sets of a `VPReg.stg` as the game's own `user/VPReg.ini`, rather than
copying the file (a copy would hand every table the values every other table saved).
Answers how many sets were written. A set the game's ini already holds is left as it is.

```python
written = ctx.games.put_saved_sets(game_id, "/data/old/VPReg.stg", ["Taxi"])
```

#### `ctx.games.asset_kinds`

`ctx.games.asset_kinds() -> tuple[str, ...]`.

The kinds that live in a folder of their own, and so can be placed whole: `nvram`, `cfg`,
`scripts` and the like.

```python
placeable = ctx.games.asset_kinds()
```

#### `ctx.games.put_asset`

`ctx.games.put_asset(game_id, kind, path, rom="") -> str`. Required: `game_id`, `kind`,
`path`.

Put a file or a whole folder where this kind of asset belongs: a ROM set, an alternative
sound bank, a color set. `rom` is for kinds that live under a ROM name. `nvram` and `cfg`
go under `pinmame/`, `scripts` in the game's `scripts/`, and `dmd_content` as a file or a
folder beside the table. Answers the path it took, relative to the game, with forward
slashes. Never replaces.

```python
landed = ctx.games.put_asset(game_id, "nvram", "/data/old/taxi.nv", rom="taxi")
```

Raises `FileExistsError` where something is already there, `FileNotFoundError` for a
missing source, `ValueError` for a kind with no folder or one that needs a ROM, and
`ContractError` outside the declared folders.

#### `ctx.games.put_rom_alias`

`ctx.games.put_rom_alias(game_id, alias, rom) -> str`. Required: all three.

Write the one `alias,rom` line a table needs as the game's `pinmame/alias.txt`: the name
the table's script asks for and the ROM set that answers it. Answers the path, relative to
the game.

```python
ctx.games.put_rom_alias(game_id, "taxi_l4", "taxi")
```

Raises `FileExistsError` where the game holds a name map, and `ValueError` for an empty
name or one with a comma or a newline.

#### `ctx.games.put_manufacturer_logos`

`ctx.games.put_manufacturer_logos(makers, candidates) -> dict`. Required: both.

Copy each `(maker name, image)` of `candidates` that serves one of `makers` into the
manufacturer logos folder, which every theme shares. Replaces none. Answers
`{"placed": [...], "held": [...]}` by file name. Needs `config:write`.

```python
done = ctx.games.put_manufacturer_logos(["Bally"], [("Bally", "/data/old/bally.png")])
```

Raises `ContractError` outside the declared folders.

#### `ctx.games.put_media`

`ctx.games.put_media(game_id, kind, path, table_stem="", replace=True, page=1) -> str`.
Required: `game_id`, `kind`, `path`.

Put a file in one of an entry's media slots. Answers what it landed as. `replace=False`
fills an empty slot and raises `FileExistsError` where one is held. `page=n` adds page n of
a flyer or instruction card beside the page 1 the slot shows, up to one past the last.

```python
ctx.games.put_media(game_id, "wheel", "/data/old/Taxi.png", replace=False)
```

Raises `ValueError` for a kind that is not in `ctx.games.kinds()`, `FileExistsError` as above,
and `ContractError` outside the declared folders.

#### `ctx.games.reaches`

`ctx.games.reaches() -> tuple[str, ...]`.

The names core offers that this extension may actually call: what is offered, narrowed to
the scopes its manifest declared. Includes the names in "Offered by name".

```python
if "rate_table" in ctx.games.reaches():
    ctx.games.rate_table(game_id, table_id, 8)
```

Does not raise.

#### Offered by name

Anything else core offers is reached as `ctx.games.<name>(...)`, with the signature the
API's own function has. Not every name is on every build; `ctx.games.reaches()` lists what
is. A name that is not offered raises `AttributeError`, and one that needs a scope the
manifest lacks raises `ContractError` when it is looked up.

| scope | names |
|---|---|
| `games:read` | `list_games(q="", limit=0, offset=0)`, `get_game(game_id)`, `game_tables`, `game_media(game_id, codecs=False)`, `table_media(game_id, table_id, codecs=False)`, `media_detail(game_id, kind, table_id="", page=1)`, `vps_state`, `vps_details`, `vps_catalog(downloading=None)`, `vps_settle(rows)` |
| `games:write` | `set_details(game_id, **fields)`, `rate_game(game_id, rating)`, `rate_table(game_id, table_id, rating)`, `set_tags(game_id, tags)`, `set_favorite(game_id, favorite)`, `set_default_table(game_id, table_id)`, `set_play_record(game_id, play_count=None, play_time_seconds=None, last_played=None)`, `reset_play_record(game_id)`, `take_vps_details(game_id, fields=None)`, `match_game(game_id, vps_id, guess=False)`, `remove_media(game_id, kind, table_id="", page=None)`, `get_missing_media(game_ids)`, `forget_table(game_id, table_id)`, `add_keyed_table(game_id, app_id, key)` |
| `config:read` | `new_game_destination()` |
| `config:write` | `use_library_folder(path)`, `write_table_settings(table_id, values)`, `use_logos_for_wheels()` |
| `launch:invoke` | `launch_game(game_id, table="")` |

Notes on the less obvious ones:

- `vps_catalog(downloading=None)` answers `{enabled, ready}`. `enabled` is the *Match new
  games* switch; where it is on and there is no catalog on disk one is fetched first,
  calling `downloading` just before it starts.
- `vps_settle(rows)` takes rows of what a source knows (`vps_id`, `ipdb_id`, `title`,
  `manufacturer`, `year`, `folder`) and answers each in order with the entry it is:
  `vps_id`, `how` (`vps_id`, `ipdb` or `name`) and `entry` (`id`, `name`, `manufacturer`,
  `year`, `type`, `ipdb_id` and `folder_name`, the folder VPinFE would name the game); or
  `vps_id` empty with a `reason` (`not_found`, `two_entries` or `ipdb_differs`) and up to
  five `candidates`. It reads the catalog on disk and writes nothing.
- `match_game` matches a game to an entry as *Matched on import*, or as a plain guess a
  rematch may replace where `guess` is true.
- `write_table_settings` writes values as one table's own settings, never the launcher's,
  and leaves out a value the launcher already has, so a table whose values all match gets no
  file. `use_logos_for_wheels()` sets `[Media] wheelset` to the reserved `logo` set so every
  game's wheel shows its logo, and answers `{"wheelset": "logo"}`.
- `get_missing_media(game_ids)` starts the media fill for those games whatever the *Get Media
  for New Games* switch says, answering `{"started": true}`, or `{"started": false}` while
  another fill runs. The fill does not queue.
- Launching is gated apart from the rest. It takes over the cabinet rather than editing a
  record, so `games:write` does not grant it: an extension that starts a game asks for
  `launch:invoke` by name, and whoever installs it reads it by name.
- There is no `set_private`. A Private game's flag can be read, never set, by an extension.

```python
found = ctx.games.list_games(q="taxi", limit=10, offset=0)
ctx.games.rate_table(game_id, table_id, 8)
```

### `ctx.apps`

A way to play a table. See "A way to play a table".

#### `ctx.apps.provide`

`ctx.apps.provide(**described) -> str`. Required: `id` and `suffixes`.

Add an app, described in plain data. Answers the id it took. Keys: `id`, `suffixes`, and
optionally `name`, `accepts_keys`, `companions`, `fields`, `kinds` and `command`.
`command(entry, settings)` receives `entry` as `{entry_id, game_dir, table, key}` and
`settings` as the launcher's values, and answers a **list** of arguments, never a string. It
answers nothing to run the launcher's configured binary and arguments instead. Needs the
`apps:provide` scope.

```python
ctx.apps.provide(
    id="fp",
    name="Future Pinball",
    suffixes=(".fpt",),
    fields=({"key": "bam_path", "path": "dir"},),
    command=lambda entry, settings: ["/opt/fp", "--play", entry["table"]],
)
```

The user sees a launcher type of that name, and tables of those suffixes are importable.
Raises `ContractError` without `apps:provide` in `scopes`, and a refusal for an id already in
use or a suffix an app this build ships already claims.

#### `ctx.apps.suffixes`

`ctx.apps.suffixes() -> tuple[str, ...]`.

Every file extension this install can play, its own and any provided. Not gated: this says
what the build can do, not what the user has. An importer deciding whether a foreign library
is worth importing needs it before it has been granted anything.

```python
playable = ".fpt" in ctx.apps.suffixes()
```

#### `ctx.apps.names`

`ctx.apps.names() -> tuple[str, ...]`.

The product names of the apps here. For a source that says which program a system used but
not which files it holds; a database found in a folder named after the program is often all
there is.

```python
if "Future Pinball" in ctx.apps.names():
    ctx.logger.info("Future Pinball can be played here")
```

#### `ctx.apps.plays`

`ctx.apps.plays(name) -> bool`. Required: `name`.

Whether anything here plays a file of this name, or this bare suffix.

```python
if ctx.apps.plays("Taxi.fpt"):
    queue("Taxi.fpt")
```

#### `ctx.apps.provided`

`ctx.apps.provided() -> tuple[str, ...]`.

The ids this extension has added, which is what gets taken back with it.

```python
ctx.logger.info("providing %s", ", ".join(ctx.apps.provided()))
```

#### `ctx.apps.withdraw`

`ctx.apps.withdraw()`.

Take every provided app back, and their words. Core calls this when the extension is
unloaded; an extension has no reason to. A disabled extension therefore leaves no suffix
claimed by something that is no longer there.

```python
ctx.apps.withdraw()    # the host does this on unload
```

## Settings

Declared with `ctx.ui.settings`. Core draws them on the extension's page and stores them
in the extension's own file.

A field is `{"key", "type", "default", "choices"}`:

| key | meaning |
|---|---|
| `key` | Required. The name `ctx.config.get` reads it by. Unique |
| `type` | One of the settings types below. Left out, `string` |
| `default` | Text. A switch defaults to `"false"` unless true. A secret may not have one. A select's default must be one of its choices, and is the first when left out |
| `choices` | A select's `[[value, label], ...]` |

The types a settings page draws are exactly `SETTINGS_TYPES`:

| type | draws |
|---|---|
| `string` | A line of text, with the default as its placeholder |
| `secret` | A masked line. The value is never answered; the page is told `set: true` or `false` |
| `switch` | On or off. Stored as `"true"` or `"false"` |
| `select` | One of `choices` |

Everything is stored as a string. A secret takes `type: "secret"`, never `string`: core
removes secrets from every answer it gives for the extension, by that type. A `secret`
write that is empty is skipped, so leaving the field blank keeps what was there.

**`check`.** `check(values)` receives every setting as it would be after the change, with
the unset ones at their defaults. It raises to refuse the change, and the refusal is shown
under the first field that changed. It returns nothing.

```python
def check(values):
    if not values["server"].startswith("https://"):
        raise ValueError(ctx.t("error.https"))


ctx.ui.settings([{"key": "server", "type": "string", "default": "https://example.com"}],
                check=check)
```

Words, in the extension's `i18n`: `settings.<key>.label` (falls back to the key),
`settings.<key>.help` (the `{default}` slot is the default; falls back to empty) and
`settings.<key>.choice.<value>` for a select option. The heading over the section is
`settings.label`.

Core refuses a write for a key that is not declared (`error.extensions.no_setting`) and a
select value that is not a choice (`error.extensions.bad_choice`). Both reach the page as a
refusal under the field.

## Lists

`ctx.ui.list(key, rows, *, columns, area, title, views, status, acts, relation, tag, verbs)`.
A list an extension holds, shown in the rail.

```python
ctx.ui.list(
    "tables", read_tables, title="Example Scores", area="community",
    columns=[{"field": "name", "under": ["manufacturer", "year"]},
             {"field": "manufacturer"},
             {"field": "year", "kind": "number"},
             {"field": "plays", "kind": "number"},
             {"field": "vps_id"}],
    views=[{"key": "most_played", "columns": ["name", "plays"],
            "sort": [{"field": "plays", "desc": True}], "ranks": True}],
    relation={"field": "vps_id", "keys": "vps_entry"},
    status=lambda: {"text": ctx.t("status"), "to": "settings"},
    acts=lambda: {"send_now": send_now, "site": "https://scores.example.com"},
    verbs=[{"key": "open", "link": "page"},
           {"key": "hide", "run": hide, "danger": True}],
    tag="Weekly Challenge")
```

**Key and rows.** `key` is unique within the extension. `rows()` returns a list of dicts
that JSON can carry. A row that cannot be carried, or a result that is not a list of dicts,
is the extension's failure to answer: it is shown on the list, and the extension keeps
running (`error.extensions.not_data`, `error.extensions.not_rows`). A service that did not
answer raises `Unavailable`; see "Unavailable".

**Row ids.** A row's `id` is a string, unique in the list (a number is read as its text, and
two rows with one id are the extension's failure to answer,
`error.extensions.duplicate_row_id`, for any list, verbs or not). It is what a verb is told the row by. A row with no
`id` is drawn, but it cannot be ticked and has no menu.

**Area.** Which group of the rail the list is in.

| `area` | in the rail under | offered when the install has |
|---|---|---|
| `library` | Library | the `library` feature |
| `frontend` | Frontend | the `frontend` feature |
| `community` (default) | Community | always |
| `system` | System | always |

A list is in the rail only while its extension runs. A page still open when it stops says
Off, or Stopped with the reason, in place of Refresh, and the list is not asked.

**Title.** `title` is shown as written; left out, it is `list.<key>.title` in the catalog.
It may not equal a core page's title (Overview, Games, Tables, Media, Assets, Collections,
Tags, Discovery, Players, Launchers, Themes, Settings, Devices, Metrics, Logs, Jobs,
Backups, About, Library, Frontend, Community, System), nor another running extension's list
title in the same area, compared without regard to case. Either raises `ContractError`
from `register`, so the extension fails to start with the log naming the clash.

**Columns.** `{"field", "header", "kind", "help", "under"}`.

| key | meaning |
|---|---|
| `field` | Required. The row key it shows |
| `kind` | `text` (default), `number` or `date` |
| `header` | Shown as written; left out, `list.<key>.column.<field>.header`, then the field |
| `help` | The tooltip on the header. Left out, `...help` in the catalog, then the header |
| `under` | First column only. Row fields drawn on the line beneath its value, as a game's maker and year are |

**Views.** `{"key", "name", "columns", "sort", "help", "ranks"}`. A view names the columns it
shows (all when left out) and how it sorts: `[{"field", "desc"}]`, one field after another.
`name` and `help` fall back to `list.<key>.view.<viewkey>.name` and `...help`. A view may
only name columns the list has.

**Ranks.** `"ranks": True` offers the view as an order for a collection, named for the list's
title and the view's name (*Example Scores: Most Played*). It puts this library's games in the
view's sort, each field in its own direction, and there is no reversing it. A game the list
does not rank follows in title order, so the order never drops one. A ranked view sorts on
`number` or `date` columns only and its list needs a `relation`; anything else is refused. The
order is read with the tags, on the same schedule, and moves on its own from the last good
read. While the extension is stopped, a collection in its order keeps it and shows its games
in title order until it runs again.

**Relation.** `{"field", "keys"}`. Core asks which of the rows this library holds and makes
their name a link. `keys` is `vps_entry` for a link to the game, or `vps_release` for one to
the table; `field` is the row key that holds the id.

**Tag.** With `tag="Weekly Challenge"` and a relation, core puts that tag on what this
library holds from the list: the game for a `vps_entry` relation, the table for a
`vps_release` one, so a challenge naming one build of a machine tags that build and not the
others. The tag is the extension's: nobody can rename, merge, remove it or put it on by hand,
and it goes when the extension stops. It is written as given in every language, because it is
stored on games, which makes it data.

**Reading.** Core asks `rows()` on every visit and on Refresh, so it answers with the whole
list as it is now rather than holding a copy of its own. It keeps the last good read on
disk (`ctx.ui.kept`). The page draws it at once, with how old it is, and asks again behind it;
a read that fails leaves the last good list on screen, said to be stale. Tags and ranks are
read shortly after start and every 30 minutes after; a read that fails keeps the last good
one.

**Status.** `status()` returns text, or `{"text", "detail", "to"}`. It is one line drawn
quietly in the bar above the list, or under the reason when the list could not be read.
`detail` shows on hover. `to` makes the line a link: `players` opens Frontend > Players,
where each player's accounts and their Share are, and `settings` opens the extension's own
page. Any other `to` draws no link. An empty status draws nothing.

**Acts.** The menu at the end of the page's title, in order, with **Settings** added after
them wherever the extension has settings. `acts` is a dict `{key: function or address}`, or a
function returning one, called each time the page opens and after each act, so an act can be
offered only while it can work (a Send Now with nothing waiting is left out rather than
refused).

- A function runs when the act is pressed. It returns None, a message string that is said, or
  a dict `{"message", "url"}`: a `url` is opened in a new tab.
- A string is an address. The act is a link opening that address in a new tab, marked as
  leaving, and the extension is never called for it. It has to start with `http://` or
  `https://`, or it is not drawn.

An act's label is `list.<key>.act.<act>.label`, falling back to the act's key.

**Verbs.** What a person can do to rows: one, or several ticked. Each verb is in the row's
right-click menu and in the menu the bar shows while any row is ticked. `{"key", "run" or
"link", "danger", "needs", "one", "label"}`:

| key | meaning |
|---|---|
| `key` | Required, unique in the list. What the catalog finds its words by |
| `run` | A function, called with the rows as dicts. It returns None, a message string that is said, or `{"message", "url"}`: a `url` is opened in a new tab. Core reads the list again afterwards |
| `link` | In place of `run`: the row field that holds an address. The verb opens it in a new tab, marked as leaving, and the extension is never called. The field has to start with `http://` or `https://`, or the verb is dimmed, saying **No address**. A link is always `one`, and takes no `danger` or `needs` |
| `danger` | Draws it last, under a rule, in red, and asks first. The question is `list.<key>.verb.<verb>.confirm`, with `{count}` the number of rows ticked, which can be more than the rows the verb acts on when it also has `needs`. The asking is the Console's; the route itself runs the verb when it is called |
| `needs` | A row field that is true or false. The verb is dimmed on a row where it is not, saying `list.<key>.verb.<verb>.needs`, and acts on the rows where it is true when several are ticked. Core checks this again when the verb is pressed |
| `one` | Meaningless over several rows. With several ticked it stays in the menu, dimmed, saying **One at a time**. Core refuses it for any other number of rows |
| `label` | Shown as written; left out, `list.<key>.verb.<verb>.label`, then the verb's key |

The question a danger verb asks is plural, `{"one": "Remove this row?", "other": "Remove
{count} rows?"}`, and takes `{count}`. Left out, core asks "`<label>` this row?" or
"`<label>` `<count>` rows?". A verb is not offered while the extension is stopped. A verb
that raises is the extension's failure to act, said with its reason (`Unavailable` is a 502).

Words: `list.<key>.title`, `list.<key>.column.<field>.header|help`,
`list.<key>.view.<viewkey>.name|help`, `list.<key>.act.<act>.label`,
`list.<key>.verb.<verb>.label|tip|confirm|needs`. `tip` is what a hover adds to the label.

## Actions and dialogs

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
| `fields` | The fields to ask for. See "Fields" |
| `confirm` | The verb at the point of no return, the action's own: a generic "Confirm" makes every action look like every other one |
| `steps` | `[{key, label, done}]`, the path as it stands. A `done` step reopens with `GET .../actions/<key>?step=<key>`. An action that cannot say how many steps it has sends none and loses nothing |
| `welcome` | True centers the step, for a flow's first: the `title` at display size, the `help` as the lead, and the label of its `choice` as the question over it. Every `check` and `act` answer replaces the step, so one still a welcome repeats `welcome: true` |
| `ready`, `reason` | `ready: false` holds Next or the last step's `confirm` until true again, with `reason` said beside the held button. Any step may send it |
| `summary` | `[[label, value], ...]`: what the steps add up to. A row of one is a heading, not a fact |
| `notes` | Lines that travel with the summary, because a count that stays quiet about what the job cannot do describes something that will not happen. A string, or `{text, detail}` where `detail` shows on hover |
| `errors` | `{field_key: text}`: refuse one field by name, drawn under it. Each value takes the same two forms a note does |
| `acts` | `[{key, label}]`: quiet buttons inside the step's body. Pressing one calls `act` and gets the same step back, redrawn; an act never moves the step on |

Fields in an answer are checked against the table in "Fields" when the answer is made. One
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

### Fields

The fields a dialog may ask for are `{key, type, label, value, help}` plus what the type
takes. `help` takes the forms described above. A `path` field may add `opens_at`, the folder
its picker starts in while the field is empty. The types are exactly `DIALOG_TYPES`:

| type | asks for |
|---|---|
| `string` | a line of text |
| `path` | a file or folder on the machine core runs on, with `wants`: `dir`, `file` or `exe` |
| `select` | one of `choices`, each `[key, label]` and optionally `[key, label, help]`, the help shown beside the option in the list, and under the field once it is chosen. Labels within one field are different, since the help is found by label |
| `multi` | several of `choices` |
| `switch` | on or off |
| `choice` | one of `choices`, two to four, each `[key, label, help]` with its own line of help, and optionally a fourth element: the name of a picture, or a list of paths to a few of the person's own images, inside the folders the extension declared in `ctx.files.set_roots` |
| `number` | a number, with `unit`, `min` and `max` |
| `checklist` | any of `rows` ticked, for a list too long for `multi`: each row `{key, name, note, groups}`, with `chips` as `[group, label]` pairs, a chip shown only when a row is in its group; the answer is the keys ticked |
| `settle` | a VPS entry for each of `rows`, `{key, name, entry, vps_id, reason, settled}`, `entry` being the `{name, manufacturer, year}` it would offer: the row says it or Not found, with the reason, and Change... opens the VPS picker; settled rows are behind Show all. The answer maps a row's key to the id picked, with `""` for a row said to be in no catalog; a key left out is a row untouched |

A `choice` option's picture is a name, and `null` is none. Core draws `desktop` and
`cabinet` itself and reads any other name as a Material icon, so a flow never supplies a
drawing. Options with pictures are tiles on a `welcome` step and rows on any other. Beside
other fields the `choice`'s label heads its rows; alone on a step, its `title` is the
question.

A settings page draws a smaller set, which is its own table:

| type | draws |
|---|---|
| `string` | A line of text |
| `secret` | A masked line, never answered |
| `switch` | On or off |
| `select` | One of `choices` |

A type that a surface does not draw is refused when it is declared, not when somebody opens
the page.

## Accounts

`ctx.ui.account(...)`. Who plays is core's; what a service calls them is the extension's. An
extension holds an account for any player it can: a user id and key at a scores site, a name
a leaderboard posts under. Like settings, an account is declared rather than drawn: core
asks the extension's functions with the player's id, and draws the same panel for every
extension that offers one. A user id is chosen free, claimed deliberately, then read-only.

Only one account per extension. The functions:

| argument | called as | returns |
|---|---|---|
| `read` (required) | `read(player_id)` | The account as the panel draws it, below |
| `write` | `write(player_id, values)` | Nothing, or the account. Saves what was chosen. Never mints a key: claiming is its own act. Left out, the account is read only |
| `acts` | `{key: fn(player_id)}` | None (the account again), a message string, or `{"message", "url"}` |
| `card` | `card(player_id)` | `{"card": {...}, "filename": "..."}`, or None while the player has none |
| `read_card` | `read_card(card)` | `{"name", "initials", "values"}` |
| `available` | `available(candidate)` | Truthy if the id is free. Asked live as one is typed. Raise to say it could not be reached |

```python
ctx.ui.account(
    read=read_account, write=write_account,
    acts={"send_now": send_now, "claim": claim, "consent": consent, "disconnect": disconnect},
    available=is_free, card=make_card, read_card=read_card,
    cards=("scores_card",), consent=(ctx.t("account.consent.id"),),
    sends_picture=True)
```

**The answer of `read`.** A dict:

| key | meaning |
|---|---|
| `user_id` | The id chosen, lower case as the service will keep it, or `""` before one is chosen |
| `claimed` | Whether it is registered with the service. Free to change or drop until then with a plain write; read only after. Where an extension cannot vouch for a key it holds, answering true is the safe side of that guess |
| `needs_consent` | Whether Share still owes the player a look at what it makes public before it next turns on. True until a `claim` or a `consent` act settles it, independently of `claimed` |
| `page` | The account's public page once claimed, `""` before |
| `status` | One line in words (*1 game waiting to send*), or `""` while unclaimed |
| `waiting`, `waiting_count` | The same fact as a boolean and a number |
| `acts` | `[{key, label, description}]`. `send_now` is the one drawn generically, only while claimed and something waits |
| `card` | Whether a card can be made for this player now |
| `picture` | True if the service holds a picture for this player |
| `fields` | Unused by this shape; `[]` |

**Claiming is deliberate, never a side effect.** The Console's own dialog checks `available`
live as an id is typed, saves it with a plain write (nothing sent, no key made), and only
makes the key and registers the pair when the player turns Share on. The acts it uses:

| act key | what it should do |
|---|---|
| `claim` | Check the id is still free, mint the key, register the pair, answer the account. Raise an ordinary error where the id was taken in the meantime, the player has no initials, or the account already holds a key; the Console shows what it says and leaves Share off |
| `consent` | Settle `needs_consent` with no send of any kind. Used instead of `claim` where `claimed` is already true |
| `disconnect` | Forget the id and key here, `ctx.players.set_account(player_id, {})`. The account stays with the service, whatever was already shared |
| `send_now` | Send what is waiting. Answers a message |

**Consent.** `consent` is what Share tells the player becomes public, asked once, the first
time it is turned on: each line already in its own words from `ctx.t`, drawn as what the
account shares. Core adds that the service can neither rename nor delete an account, since
this shape never offers either.

**Share.** Core's switch, the same on every account. `ctx.players.sharing(player_id)` reads
it. `account.share_changed` says when it moves; see "What a game tells you". **Turning Share
off drops whatever the account holds back to send**, games that failed to go or a queue of
scores, so nothing played while it was on goes later by hand or when it is turned on again.
Core's words under the switch are `account.share.help` in the catalog when the extension
has them, else the Console's own naming of a played game, a rating and a high score.

**A secret in an account** is accepted on a write and never answered. Core takes the value
out of every answer from an extension's routes, settings included, and puts `set`, true or
false, in its place. This shape's own `user_id` and key pair does not use `fields` at all: the
key never crosses the wire in either direction, only `claimed`.

**A picture.** An account that answers `picture: true` gets a *Use {Service}'s Picture* button in
the player's picture dialog, named for the extension's display name. Pressing it calls the
extension's own route `GET /api/v1/ext/<name>/accounts/{player_id}/picture`, which the
extension serves with `ctx.add_router`, returning image bytes with a content type of
`image/png`, `image/jpeg`, `image/webp`, `image/gif` or `image/bmp`, or a `404` while there
is none. The bytes are kept exactly as an upload is kept (centre square, at most 1024 pixels,
WebP, Undo). Core never follows an address an extension hands it. A guest has none to set.

An extension that sends a player's picture to its service declares `sends_picture=True`,
reads the file with `ctx.players.picture(player_id)` (which answers only while Share is on),
and core adds its own line to `consent`. **An extension that starts sending after a player has
already consented owes the dialog again:** its `needs_consent` answers true until a consent
that named the picture. That is the extension's to track; core cannot know which line a past
consent showed.

### Cards

A card is a player's account as a file they can carry to another install: a QR code of the
card's text, drawn by core as an SVG, with the text also hidden in the file in a comment, a
`<metadata>` and a `<desc>`, named for the extension: `<!--SCORES_SITE_PAYLOAD:...-->`,
`id="scores_site-payload"` and `id="scores_site-payload-desc"`. `marker=` names them
otherwise, and has to be a plain name. A card is read from that text and never from the
picture.

The card an extension answers is a JSON object with a `type`, written compact with its keys
sorted. `cards=` lists the `type`s it reads: a card arriving at
`POST /api/v1/players/guests/card` goes to the extension that declared its `type`, which
answers who it is for. The guest joins up alone with the card's initials (one to three
characters, as they are), and their account shares. The same card again puts that guest up
rather than adding a second. A card used for a player's existing account,
`POST /api/v1/players/{id}/accounts/{extension}/card`, is read the same way, and the `values`
it answers are written to that account with `write`.

VPinPlay's card is the one 2.x's *Download QR Code* saved, byte for byte: the same text, the
same QR settings, the same hiding places. Cards are on people's phones, so a card from either
version joins on the other, for good.

Words: `account.label` (the heading over the account; left out, the extension's name) and
`account.share.help`.

### What it holds

`ctx.ui.state(base, label)` is not an account. It names a route of the extension's own that
answers what the extension is holding, drawn on its page:

```
GET /api/v1/ext/<name><base>
{"rows": [{"id", "label", "mark", "detail", "actions": [{"key", "label"}]}], "empty": "..."}
POST /api/v1/ext/<name><base>/<key>      {"id": "<row id>"}
```

`mark` is a chip on the row that is different, never on all of them. Two `actions` at most
are drawn. `empty` is the extension's own words for a list with no rows. Both routes are the
extension's, added with `ctx.add_router`; the read on the read scope and the posts on the
write scope. The heading is the `label`, else `state.label` in the catalog, else the
Console's own.

## A way to play a table

VPinFE plays Visual Pinball, and through the generic app anything a person can point at a
binary. An extension is how another format becomes first class: it claims its own suffixes,
so a library of them is worth importing rather than read and dropped. `ctx.apps.provide` needs
`apps:provide` in the manifest's `scopes`.

```python
ctx.apps.provide(
    id="fp",
    name="Future Pinball",
    suffixes=(".fpt",),
    fields=({"key": "bam_path", "path": "dir"},),
    command=lambda entry, settings: ["/opt/fp", "--play", entry["table"]],
)
```

```json
{
  "app.fp.field.bam_path.label": "BAM folder",
  "app.fp.field.bam_path.description": "Where BAM is installed, if it is"
}
```

The app's words are in the extension's `i18n/en.json` under `app.<id>.`, keyed the way an
app's own file is (see "An app's words" in `docs/conventions.md`). A field that file does not
name takes core's words, so Program reads the same on every launcher. `name` is given in
code here because Future Pinball is a product name, and is shown as written.

It is described in plain data because an extension cannot import the app contract; its one
door is `common.extensions.contract`, which is what makes the import boundary checkable.
`command` answers with a list of arguments, never a string: splitting one is how a path with
a space in it becomes a crash or an injection, and only the extension knows where its own
arguments end. A string raises. Answering with nothing runs the launcher's configured binary
and arguments instead.

Apps this build ships are offered first, so a provided one cannot take `.vpx` out from under
Visual Pinball by loading before somebody looks. An id already in use is refused: ids are
stored in a table's record and read back long afterwards. What an extension provides is taken
back when it unloads, so a disabled extension leaves no suffix claimed by something no
longer there.

A provided app does not get the rest of the app contract: parsing a table, resolving a ROM,
a settings surface, a launch of its own for a recording. Those are declared absent rather than
half answered, the same way the generic app declares them.

## Something to an entry

A theme reads `entry.ext.<key>`. It never learns which extension answered, and no extension
gets a method of its own on the theme surface; the alternative needs a new call for every
connector that follows.

```python
def rating_for(game):
    # game is {game_id, vps_id, name, manufacturer, year, ipdb_id}: a description,
    # never core's object.
    return {"stars": look_it_up(game["vps_id"])}


ctx.entries.contribute("rating", rating_for)
```

Each value in the description is the effective one: an extension sees the match a user
corrected, not the one the scan found.

**Core makes the call; the browser makes none.** `fetch` runs on core's thread when the
player moves to a game, so it may block, but it must not raise for a game it simply has no
answer about. One that raises costs its own key and nothing else.

Three things core does that no theme author sees. The answer is held per process, so one
fetch serves every window and survives a reload. The games either side are fetched on the
same signal, so what somebody sees is the answer fetched a step ago and the gap only shows on
the first game of a cold start. And the message that carries an answer names the game it is
about, so one arriving after the wheel has moved lands on the entry it belongs to.

The slot is always present and empty at library load: a list of four hundred games cannot
wait on four hundred calls to somebody else's server. A theme written as
`if (entry.ext.rating)` is correct throughout without knowing there is a waiting state.

An answer is held for the rest of the run. When what an extension knows changes, a fresh list
read say, `ctx.entries.stale("rating")` drops what core holds under that key, and each game is
asked again the next time it is reached.

An extension that answers from one of its own lists makes no call per game at all: it holds
the rows its list last answered, and reads them back at start with `ctx.ui.kept(key)`.
VPinPlay's rating works that way.

## An outside link

A game, a table or a file can have a page somewhere else, and an extension can say where.

```python
ctx.catalogs.contribute(
    "scores", "Example Scores", "game",
    lambda game: f"https://scores.example.com/tables?vpsid={game['vps_id']}")
```

`subject` is `game`, `table` or `file`; anything else is refused at registration. `link` is
handed a plain description of the subject and answers its address there, or `""`. Core draws
it as a row named for the place, with an open-in-new icon. A link that raises, or answers
anything but an http or https address, is left out.

## A name a command can use

A user writes commands that run when VPinFE starts and around every table. Core declares what
one of them may say (`{table}`, `{rom}`, `{program}`) and an extension adds to that list.

```python
def season(values):
    # values is what this context has resolved so far. Answer a string; empty is an
    # answer, and this must not raise on an install that has none.
    return ctx.config.get("season", "")


ctx.tokens.offer("season", (ctx.tokens.TABLE,), season)
```

What it stands for is `token.season.says` in the extension's `i18n/en.json`, or `says=`. A
name with nothing saying what it stands for is refused.

**The name carries the extension's id.** You declare `season`; a user writes
`{example_scores.season}`. The dotted half is built from the manifest rather than spelled
here, so two extensions may offer the same idea without reaching each other, and core's own
names, which never carry a dot, can grow without reaching either. Who is playing is one of
core's: `{player}` is the initials of the one player up, and blank with several.

`contexts` says where the command runs: `ctx.tokens.VPINFE` for the pair around VPinFE
itself, `ctx.tokens.TABLE` for the pair around every table. Declare only the ones the name
means anything in. A name that is always blank costs a reader more than one that was never
offered.

`value` runs while a command is being prepared, so it has to answer quickly. One that raises
stands for nothing and is logged, and the table still launches. Pass `after_only=True` for
something only the half that runs afterwards can know.

**A name goes when its extension does.** A command still holding one is refused by that name,
the same as any name nothing declares. The alternative is a `--flag` left with nothing after
it, reading whatever came next as its value.

## What a game tells you

Core events say who played and who rated what, as plain lists and dicts. `game` and
`ini_config` ride along on some for core's own subscribers and are not part of this contract.

| event | carries |
|---|---|
| `table.launching` | `table_id`, `source`. Every hook on it has finished before the table starts |
| `table.launched` | `game_id`, `table_id`, `source`; `up`, who the game counts for, taken once as it starts, each `{id, name, initials, owner, guest}`; and `private`, whether the game is Private |
| `table.exited` | `table_id`, `source`. Announced on every path out |
| `table.play_recorded` | the same as `table.launched`, once the game has ended and its play is written, with `private` read again then; `seconds` played; `reading`, the machine's high score table as read after the game, or None; `new_entries`, `[{player, entries}]` for each player with an entry new this game |
| `game.rated` | `game_id`; `player`, whose rating it is, `{id, name, initials, owner, guest}`, or None on an install with no owner yet; and `rating`, 0 to 5, 0 meaning unrated. The owner's rating is the library's, anyone else's is in their own record |
| `account.share_changed` | `player`, `{id, name, initials, owner, guest}`; `extension`, whose account it is; and `share`, what it is now. It carries every extension's, so one reads only its own |
| `players.changed` | `state`, the whole roster: `{"players": [...]}`, each row as `ctx.players.roster()` gives it |
| `game.selected` | The wheel stopped on a game. It carries core objects (`game`, `neighbors`) that are not part of this contract; subscribe to know that it happened |

**A Private game's data is never sent anywhere.** Not its plays, its time, its scores or its
rating, and not the fact that the library holds it: to no service, for no player, whoever was
up and whatever their Share says. A game is Private when somebody marks it so; the events
carry `private`, and a game's rows from `ctx.games` carry it too, for anything an extension
sends outside a session. An extension reads the flag and cannot set it.

A table's events carry `source`, who started it: `frontend`, `remote`, `api`, or `capture` for
a launch that records the table's media. A recording is not a play. Nobody is up for it, it
writes no play data, and there is no `table.play_recorded` after it, so an extension counting
plays counts on that event or leaves out a `capture` launch.

```python
def on_played(**payload):
    if payload["private"]:
        return
    for credited in payload["new_entries"]:
        post_score(credited["player"]["id"], credited["entries"])


ctx.events.subscribe("table.play_recorded", on_played)
```

**A game counts for who was up; a new score goes to the player whose initials it has**, up or
not. An entry with no initials, or `???`, goes to the one player up, and with several up to
nobody. Core matches them once, so no two extensions disagree about whose a score was. An
entry is new when the table after the game holds it more times than the table before,
whatever its rank; a machine that keeps one number has a new entry when it changed. A game
with no reading before it has nothing new. `reading` is `{rom, resolved_rom, score_kind}`
with either `entries`, each `{section, rank, initials, score, ...}`, or a single `value`.

A service that takes one player a game decides for itself what to do with several up, and its
account's status line says so rather than going quiet.

## Its words

An extension keeps what it says in `i18n/en.json` beside its code, and a translation is the
same file under the language's name, `i18n/de.json`. The file is served under
`ext.<name>.`, so an extension adds words and never changes one of core's. Keys are flat
strings with dots in them.

| key | names | falls back to |
|---|---|---|
| `name`, `description` | The extension, where the manifest leaves them out | The extension's `name`; nothing |
| `settings.label`, `state.label` | The heading over its settings and over what it holds | The Console's own |
| `settings.<key>.label` | A setting | The key |
| `settings.<key>.help` | A line under the setting; `{default}` is its default | Nothing |
| `settings.<key>.choice.<value>` | A select option | The label given in `choices` |
| `list.<key>.title` | A list's title | The key |
| `list.<key>.column.<field>.header` | A column's header | The field |
| `list.<key>.column.<field>.help` | A column's tooltip | Its header |
| `list.<key>.view.<viewkey>.name` | A view's name | The view's key |
| `list.<key>.view.<viewkey>.help` | A view's tooltip | Nothing |
| `list.<key>.act.<act>.label` | An act in a list's title menu | The act's key |
| `action.<key>.label`, `action.<key>.description` | An action | The key; nothing |
| `action.<key>.result.<field>` | A count a run reports, beside the number | The field |
| `account.label` | The heading over a player's account with it | The extension's name |
| `account.share.help` | What its account's Share makes of what is played, under the switch | The Console's own naming |
| `token.<name>.says` | What a name a command can use stands for | A name with none is refused |
| `app.<id>.name`, `app.<id>.field.<key>.label`, `app.<id>.field.<key>.description` | An app it provides | Core's words for a field it does not name |

Anything else is its own to ask for with `ctx.t("wizard.title")`, and `contract.words(name)`
is the same for a module that is not handed `ctx`. A key the file does not have answers the
full key, `ext.<name>.<key>`, so a gap is visible.

A column with no `help` gets its header as its tooltip, so declare one: it is what the person
hovering the header reads. A word handed over in code, `title="VPinPlay"`, is shown as
written in every language, which is for a product name.

**Slots.** `{name}` in a value is filled from the call's keyword arguments with
`format_map`. **Plurals.** A value that is an object `{"one": "...", "other": "..."}` is
chosen by the `count` argument: `ja`, `zh`, `ko`, `vi` and `th` always use `other`.

```json
{"sent": {"one": "{count} score sent", "other": "{count} scores sent"}}
```

`scripts/i18n.py` reads a bundled extension's file along with core's, and `--record` and
`--pseudo` write its hashes and pseudo-locale. The invariants hold a bundled one's file to
what its code asks for, both ways, and to the rules under "Type" in `docs/conventions.md`,
and fail on a sentence written anywhere in its code outside a docstring, a log line, a query
or a builtin exception. What a `ValueError` says reaches a log and nobody else; what a
setting's `check` or a function core calls raises is read by a person, so it comes from
`ctx.t`, or from `ctx.why` when it is the reason something failed.

**A failure with its reason.** A note or a row's error carries a reason the same way:
`{"text": ctx.t(...), "detail": ctx.why(exc)}`.

## Scopes and the gate

Core attaches the gate. An extension that adds its own routes names one of two scopes and
core puts it on every route in the router. An extension cannot ship a route without a gate,
because it never attaches one.

| scope | gates |
|---|---|
| `ext:<name>:read` | Every `GET` core serves for the extension, and a router added with `ctx.scope("read")` |
| `ext:<name>:write` | Every `POST` and `PUT` core serves for the extension, and a router added with `ctx.scope("write")` |

A scope belonging to an extension is granted only while that extension is running.

### What `scopes` in the manifest asks for

The manifest's `scopes` are the core scopes the extension asks to use. They are a consent
declaration (the extension's page lists them in plain words) and they decide which
`ctx.games` and `ctx.players` calls work. A scope that does not exist fails the extension
with "Asks for scopes that do not exist".

| scope | lets the extension |
|---|---|
| `games:read` | Read the library through `ctx.games` |
| `games:write` | Create games, add tables and media, change details, ratings and tags through `ctx.games` |
| `games:export_full` | Export the library in full |
| `collections:read`, `collections:write` | Read, change collections |
| `play:read`, `launch:invoke`, `play:stop` | See what is playing, start a game, stop one. Three separate permissions |
| `uploads:write` | Upload files |
| `vps:read` | Read the VPS catalog |
| `filesystem:read` | Browse folders |
| `capture:run` | Record media |
| `config:read`, `config:write` | Read, change VPinFE's configuration |
| `system:read`, `system:admin` | Read system state, administer it |
| `events:subscribe` | Subscribe to the event stream over the API |
| `jobs:read` | Read jobs |
| `input:act` | Send input |
| `devices:read`, `devices:write` | Read, change devices |
| `preferences:read`, `preferences:write` | Read, change preferences |
| `instance:read` | Read the install's identity and the list of extensions |
| `players:read`, `players:write` | Read, change players. `ctx.players.roster` and the calls beside it need `players:read` |
| `apps:provide` | Provide an app with `ctx.apps.provide` |

### Capabilities

A capability is what an extension asks of the machine, as opposed to of the domain. The list
is the consent surface: a capability nobody has heard of cannot be consented to.

| capability | reaches |
|---|---|
| `ui:mount` | Needed for every `ctx.ui` call: settings, lists, actions, an account, what it holds |
| `config:own` | Its own settings file |
| `net:outbound` | The network. A declaration for the person installing; see below |
| `proc:spawn` | Starting programs. A declaration for the person installing |
| `hardware:usb` | USB devices. A declaration for the person installing |
| `fs:read` | `ctx.files.set_roots`: the folders core will take a path from |
| `fs:write` | Moving a file out of those folders with `ctx.games.add_table(..., move=True)` |

**Capabilities are advisory.** An extension runs in VPinFE's process, and in-process Python
cannot be prevented from opening a file, opening a socket or starting a program. What the
declaration does is make the extension say what it intends, show that to whoever installs
it, and hold the calls that go through `ctx` to it. `ui:mount`, `fs:read`, `fs:write` and the
scopes are enforced where core is the one acting; `net:outbound`, `proc:spawn` and
`hardware:usb` are not enforced at all. The moment extensions run out of process the same
declarations become the boundary.

## Config

Two homes, because there are two owners.

| file | holds |
|---|---|
| `vpinfe.json`, `extensions.switched_off` | the names of the extensions switched off |
| `extension_settings/<name>.json` | that extension's own settings, its players' `accounts`, and what core remembers it `declared` |

Never the rest of `vpinfe.json`: that file holds what core is configured with, and it is where
a token would go. `accounts` and `declared` are reserved, so they cannot be setting names.

A setting a 2.x file held for an extension is copied across once, while that file is
converted, and removed from it. Core keeps the old names in its schema so the file still
converts, and nothing writes them again.

A file each rather than a namespace inside one, for the same reason: a namespace in somebody
else's file is a weaker form of "own" than a file. One extension's bad file costs that
extension and no other. Settings are not beside an extension's code: one the build ships has
no directory in the config dir, so they need a home that does not depend on where the code
came from.

### Switching one on or off

Whether an extension is switched off is core's setting, because core has to know before it
loads anything. A person switches one with the switch on its page under Settings >
Extensions, or with `PUT /api/v1/extensions/{name}/enabled` (needs `config:write`;
`GET /api/v1/extensions` lists them and needs `instance:read`). Either writes
`extensions.switched_off`.

- **Off is at once.** The extension goes the way a broken one does, below, and says it was
  switched off rather than that it broke.
- **On is at once for an extension that only declares through `ctx.ui`**: its lists, settings,
  actions and account come back with no restart, because core serves them.
- **On waits for a restart for an extension with routers of its own** (`ctx.add_router`),
  because routes mount once at startup and one that was off never registered any. It says
  "Starts at the next restart" until then.

## Logs

`vpinfe.ext.<name>`, issued as `ctx.logger`. An extension never logs into a core namespace,
because the namespace is how "which extension did this?" stays answerable. Everything below
that says "the log" means these lines in VPinFE's log.

## When one breaks

Reading the manifest, importing the package and calling `register` are each somebody else's
code, and any of them failing costs one extension and no other. Every failure below says why,
on the extension's page under Settings > Extensions and in `GET /api/v1/extensions`; the log
has the traceback.

| what failed | what happens | where it shows |
|---|---|---|
| The manifest is missing, unreadable, names a bad name or an unknown capability, feature or platform, or says no platform | Not loaded. State *failed* | The extension's page, with the reason in words (for instance "Its folder has no extension.json") |
| The manifest's `name` is not the folder's | Not loaded | "Its manifest calls it X, so its folder has to be called that too" |
| `requires_platform` is not offered | Not loaded | "Built for extension platform 2, and this build offers 1" |
| The manifest names a platform this machine is not, or a feature this install lacks | Not started, listed as *off* | "It does not run on Windows", or the missing features, with a button to open this device's settings |
| `scopes` names a scope that does not exist | Taken out at startup | "Asks for scopes that do not exist: ..." |
| The package will not import, `register` is missing, or `register` raises | *failed*. What it had offered by then is taken back | "The log says why it did not start". The exception is in the log |
| A `ctx` call raises `ContractError` during `register` (a setting without `ui:mount`, a list title that clashes) | The same: *failed* | The log has the `ContractError` line, which says what to change |
| A function core calls raises (a list's `rows`, a status, an act, a dialog step, a setting's `check`, an account function) | That request alone fails with the line `ctx.why` words. The extension keeps running | On the page that asked: the list says it could not be read, a setting shows the refusal under the field |
| A function raises `Unavailable`, or raises `from` a connection failure | The same, but served as `502` with the error code `upstream_unavailable` | The page says it "could not reach its service" with the line given |
| `rows()` returns something JSON cannot carry, or a result that is not a list of dicts | That request fails | The list says what it cannot show |
| An unhandled error out of one of its own routers (`ctx.add_router`) | Taken out for this run. State *disabled*. Its subscriptions and apps are withdrawn, its scopes go, and its routes answer `501` naming the extension and the reason | The page: "Unhandled error serving /api/v1/ext/..." |
| An event handler it subscribed raises | The same: taken out for this run | The page: "Failed while handling table.play_recorded" |
| Switched off | Withdrawn like the above, but says so | "Switched off" |
| Switched on, with routers of its own | *off* until the next start | "Starts at the next restart" |

A *disabled* extension is not written down: a fault that happened once must not take an
extension away until somebody notices a setting they never set. It starts again on the next
run.

What is withdrawn when one is taken out: its subscriptions are dropped, so it is told nothing
more; its scopes go with it, so nothing holds a grant into something that is not running; the
apps it provided, with their words, and the services it answered go too, so no suffix stays
claimed by it and core asks it nothing; its routes keep their paths and answer `501` rather
than `404`, because a `404` reads as a typo.

### Unavailable

`Unavailable` is for a service that did not answer, or answered with something unreadable.
Raise it from any function core calls, with the message a person reads.

```python
from common.extensions.contract import Unavailable

try:
    rows = fetch(address)
except (OSError, ValueError) as exc:
    raise Unavailable(ctx.why(exc, at=address)) from exc
```

Core serves it as `502` with `upstream_unavailable` rather than as a mistake in the request,
and the Console draws it as "could not reach its service" with that message under it. A
failure to connect raised without `Unavailable` counts too, as long as the error is in the
cause chain. The extension is not disabled; the next visit or Refresh asks again.

### Checking one

`python main.py --check-extension <folder>` loads one extension the way core does, in a
scratch store, and reports. Exit status 0 means it passed, 1 means it did not. Only read
functions are called (a list's `rows`, a status, a dialog's first step, the settings) and
nothing is sent or saved.

```
=== extensions/vpinplay
loads      vpinplay 1.0.0
settings   endpoint (string, default 'https://api.vpinplay.com:8888')
list       tables in community: 10 columns, 5 views
account    a player can hold one
reads      list tables: could not reach its service - Tunnel connection failed: 403 Forbidden
reads      settings: 1 fields
=== extensions/library_importer
loads      library_importer 0.1.0
dialog     import: ask check run progress
routes     its own, on ext:library_importer:read (2 routes)
routes     its own, on ext:library_importer:write (1 routes)
reads      dialog import: first step has 2 fields
```

| line | meaning |
|---|---|
| `loads` | It registered: name and version |
| `settings`, `list`, `dialog`, `account` | What it declared. A dialog lists the methods the object has |
| `routes` | Routers of its own, with the scope and route count |
| `reads` | What a read function answered. A service that is down gives `reads      <what>: could not reach its service - <message>` and is not a failure |
| `missing` | A word the extension shows as its own key. See below |
| `fails` | Why it did not load: the line that the page would show, then the exception |

A word the catalog lacks, for a name, a description, a setting's label, a select choice, a
list title, a column header, a view name or an action label:

```
missing    ext.bad_scores.settings.api_key.label - a setting's label
missing    ext.bad_scores.list.top.column.score.header - a column's header
missing    ext.bad_scores.list.top.view.best.name - a view's name
```

A failure:

```
fails      The log says why it did not start - ContractError: worse_scores offers settings, which needs the ui:mount capability its manifest does not declare
fails      Its manifest calls it example_scores, so its folder has to be called that too
```

### The command line

| flag | meaning |
|---|---|
| `--check-extension <folder>` | Load and report one extension, as above. Repeat for more |
| `--configdir <dir>` | Use this configuration directory, where installed extensions are searched. Also `VPINFE_CONFIG_DIR` |

## What core serves

Everything declared through `ctx.ui` is served by core under `/api/v1/ext/<name>`, each
route behind a check that the extension is running. `GET` needs `ext:<name>:read`, and `POST`
and `PUT` need `ext:<name>:write`. A request for something the extension did not declare is a
`404`; one for an extension that is not running is a `501` naming the extension and why.

| route | answers |
|---|---|
| `GET /settings` | `{"fields": [...]}`: each `{key, type, label, help, value}`; a secret has `set` instead of `value`; a select has `choices`; a string has `placeholder` |
| `PUT /settings` | Body `{"values": {...}}`. Saves, answers as `GET` does. A refusal is a `400` with the field |
| `GET /lists/{key}` | `{"rows": [...]}` |
| `GET /lists/{key}/about` | `{"status": ..., "acts": [{key, label[, url]}]}` |
| `POST /lists/{key}/about/acts/{act}` | `{"message"?, "url"?}` |
| `POST /lists/{key}/verbs/{verb}` | Body `{"ids": [...]}`. `{"message"?, "url"?}` |
| `GET /actions/{key}?step=` | A step answer |
| `POST /actions/{key}/check` | Body `{values, step}`. A step answer |
| `POST /actions/{key}/act` | Body `{act, values, step}`. A step answer |
| `POST /actions/{key}/run` | Body `{values, step}`. The outcome, or `202` with `{"job_id": ...}` |
| `GET /actions/{key}/progress` | `{stage, message, done, total}` |
| `POST /jobs/{kind}/stop` | `{"stopped": bool}` |
| `GET /accounts/{player_id}` | The account, as `read` answers |
| `PUT /accounts/{player_id}` | Body `{"values": {...}}`. As `GET` |
| `POST /accounts/{player_id}/acts/{act}` | `{"message"?, "url"?}`, or the account |
| `GET /accounts/{player_id}/card` | `{"card": {...}, "filename"}`, or `404` while there is none |
| `POST /accounts/cards` | Body `{"card": {...}}`. `{name, initials, values}` |
| `GET /available?candidate=` | `{"available": bool}` |

Outside `/ext/`, core serves the parts of a player's account that are core's:
`POST /api/v1/players/guests/card`, `POST /api/v1/players/{id}/accounts/{extension}/card` and
`POST /api/v1/players/{id}/accounts/{extension}/picture` (which asks the extension's own
`GET /accounts/{player_id}/picture` route).

A response from any route under `/ext/` has its secrets taken out on the way to the client,
whether core or the extension wrote it. An extension's own routes are mounted at `/api/v1/ext/<name>`
too, behind the same running check and the scope given to `ctx.add_router`.

## Where the code is

- `common/extensions/contract.py` - the manifest and the shape of the context. The only
  module of VPinFE's an extension imports.
- `common/extensions/context.py` - what `register(ctx)` is handed.
- `common/extensions/serving.py` - what core answers for what an extension declared.
- `common/extensions/fields.py` - the field types, as two lists.
- `common/extensions/host.py` - loading, the registry, and the kill switch.
- `common/extensions/store.py` - the switched-off list, and each extension's own file.
- `common/extensions/check.py` - `--check-extension`.
- `common/extensions/accounts.py` - where an account's values live, and the secret taken out
  of every answer.
- `common/extensions/cards.py` - drawing a card and reading one.
- `httpapi/extensions.py` - the gate, the mount, `GET /api/v1/extensions` and the switch.
- `httpapi/extensions_served.py` - the routes core serves for what an extension declared.
- `httpapi/player_accounts.py` - a player's accounts, Share and cards on the wire.

`tests/fixtures/extensions/sample/` is a worked example that uses the router API, and
`tests/fixtures/community/challenge/` one that uses `ctx.ui`.
