# `ctx.ui`

What an extension offers a person.  You declare it and core serves it: you hand over fields, a
`rows()` function and a dialog object, and core mounts the routes the Console reads.  All of it
needs the `ui:mount` capability, and every call here raises `ContractError` without it.  The
sections after this one describe each declaration in full.

A list, page, group, verb or action takes `tier=`, from `common.extensions.contract`: `PLAY`
for what a Remote pass may reach, `LIBRARY` when it says nothing, `PROTECTED` for what changes
the device and so needs a Confirm.  A single act or a `save` that differs from its surface
takes `@tier(...)` over the function.  The manifest's `tiers` must list `protected` where it is
used, and its `play` must name each surface put at `PLAY` (`list:scores`, `action:reset`).  See [Scopes and the gate](scopes.md#scopes-and-the-gate).

## `ctx.ui.settings`

`ctx.ui.settings(fields, *, check=None)`.  Required: `fields`.

Declare the extension's settings: a list of `{"key", "type", "default", "choices"}`, with
`min`, `max` and `unit` on a `number` and `wants` on a `path`.  The types are in the table
under [Fields](actions.md#fields).  Call it once.  See [Settings](settings-and-lists.md#settings).

```python
ctx.ui.settings(
    [{"key": "server", "type": "string", "default": "https://scores.example.com"},
     {"key": "region", "type": "select", "default": "eu",
      "choices": [["eu", "Europe"], ["us", "United States"]]}],
    check=lambda values: None)
```

A person sees the fields on the extension's page.  It raises `ContractError` if you call it
twice, repeat a key, use a type a settings page does not offer, give a secret a default, give a
select or a multi no choices or a default that is not one of them, give a number a default that
is not a number inside its limits, or pass a `check` that is not callable.

## `ctx.ui.settings_defaults`

`ctx.ui.settings_defaults() -> dict[str, str]`.

The declared default of each setting, by key.  `ctx.config.get` already falls back to these;
this is for code that wants the whole set.

```python
defaults = ctx.ui.settings_defaults()
```

It never raises, and is empty before `settings` is called.

## `ctx.ui.list`

`ctx.ui.list(key, rows, *, columns, area, title="", icon="", views=(), status=None,
acts=None, tag="", verbs=(), add=(), detail=None, save=None, tier=LIBRARY)`.  Required:
`key`, `rows`, `columns`, `area`.

Declare a list.  `rows()` returns the rows, each a dict.  See
[Lists](settings-and-lists.md#lists) for columns, views, acts, tag, verbs, add and
the pane (`detail` and `save`).

```python
ctx.ui.list("top", read_top, title="Example Scores", area="community",
            columns=[{"field": "name"}, {"field": "score", "kind": "number"}])
```

A person sees the list in the rail under `area`.  It raises `ContractError` for:

- a missing or unknown area, a missing key or columns, or a repeated key
- `rows` or `status` that is not a function
- `under` on any column but the identifier, or an unknown column kind
- a view on a column the list does not have
- `keys` on a column that is not a game or table, or `keys` other than `vps` or `vpinfe`
- `name_from` on a column that is not a link, game or table
- `picture` or `icon` on any column but the identifier, or `picture` on a picture column
- more than one `identifier` column, or an `identifier` on a `state`, `chips`, `link` or `picture` column, or a list with no column that can be the row's name
- a `tag` on a list whose identifier is not a game or table
- a ranked view that sorts on anything but number or date columns, or on a list whose
  identifier is not a game or table
- a verb that is not a dict, has no key or a key already used, or carries a key core does not
  read
- a verb with more than one of `run`, `link` and `action`, or none of them
- `danger` or `needs` on a `link`, `danger` on an `action`, or `each` without an `action`
- an `add` that is not a key, or names one twice
- a `detail` or `save` that is not a function, or a `save` with no `detail`

After `register` returns, it also raises when the title matches a core page's title or another
running extension's list in the same area, and when a verb, an act or `add` opens a dialog the
extension never declared.

### Rail icons

A list, a page or a link wears the icon its `icon` names in the rail, one of these Material icon
names, and the extension icon where it names none.  A name that is not here raises
`ContractError` from `register`, and the error lists the names.

`analytics`, `bar_chart`, `build`, `bolt`, `calendar_month`, `campaign`, `chat`, `cloud`,
`computer`, `dashboard`, `download`, `emoji_events`, `event`, `extension`, `favorite`, `folder`,
`groups`, `history`, `inventory_2`, `leaderboard`, `link`, `list_alt`, `lock`, `map`,
`monitoring`, `music_note`, `notifications`, `person`, `photo_library`, `public`,
`receipt_long`, `rocket_launch`, `schedule`, `sell`, `settings`, `share`, `shopping_cart`,
`speed`, `sports_esports`, `star`, `storage`, `sync`, `timeline`, `trending_up`, `tune`,
`upload`, `videogame_asset`, `visibility`, `wifi`.

The set is `RAIL_ICONS` in `common/extensions/context.py`.

## `ctx.ui.page`

`ctx.ui.page(key, read, *, area, title="", icon="", acts=None, save=None,
tier=LIBRARY)`.
Required: `key`, `read`, `area`.

Declare a page: an entry in the rail under `area` that opens one subject drawn as a panel, with
no grid.  `read()` answers what a [pane's](settings-and-lists.md#lists) `detail` does: a `title`
(required), a line `under` it, an optional `picture`, and `sections` of `facts`, `fields` and
`rows`.  Core draws them full width, as it draws every other panel.

```python
def read():
    return {"title": ctx.t("page.machine.heading"),
            "sections": [{"key": "boot", "label": ctx.t("page.machine.boot"), "fields": [
                {"key": "boot", "type": "select", "label": ctx.t("page.machine.boot.mode"),
                 "value": MACHINE["boot"], "choices": [["play", "Play"], ["desk", "Desktop"]]}]}]}


def save(values):
    MACHINE.update(values)


ctx.ui.page("machine", read, area="system", save=save, acts={"check": check})
```

With `save(values)` the fields can be changed: each is written as it is set, with the keys that
changed, and core reads the page again to draw what was kept.  It is handed only keys the page
offers now, and it refuses a value by raising, as a pane's `save` does.  `acts` is the page's
menu, written as a list's acts are: a function, an address, or a dialog to open.  Each is a
button in the menu at the end of the page title, with the extension's Settings after them.

A person sees the page in the rail under `area`, after core's own entries and the extension's
lists (and before About, in System).  The rail entry and the title are `title`, else `page.<key>.title` in the extension's catalog,
else the extension's name.  The answer's own `title` is the heading over the page.  The page is
served at `GET /api/v1/ext/<name>/pages/<key>`, changed with `PUT` at the same address and
`{"values": {...}}`, and its acts are at `.../pages/<key>/about`.  They are served at the page's
`tier=`.

It raises `ContractError` without `ui:mount`, for a missing or unknown area, a missing key, a key declared
twice, and a `read` or `save` that is not a function.  After `register` returns, it also raises
when the title matches a core page's title or another running extension's list or page in the
same area, and when an act opens a dialog the extension never declared.  `--check-extension`
says each page it finds and reads it once.

## `ctx.ui.panel_group`

`ctx.ui.panel_group(subject, read, *, title="", icon="", section="", save=None, acts=None,
private_ok=False, tier=LIBRARY)`.
Required: `subject`, `read`.

Put a group on a game's panel (`subject` `"game"`) or on one table's (`"table"`).  With no
`section` it is a section of its own, after core's, named `title` and drawn with `icon`, one of
`RAIL_ICONS`.  With a `section`, one of `details`, `play`, `collections` or `guides`, it is drawn
at the end of that section of core's, under a heading of `title`.  `read(who)` answers the group's one section, the same `{"facts", "fields",
"rows"}` a [pane's](settings-and-lists.md#lists) section holds, and core draws it as it draws
the rest of the panel.  Answer None, or a section with nothing in it, and the group is not
drawn.

`who` is `{"game_id", "vps_id", "name"}`, and for a table also `{"table_id", "vps_file_id",
"version"}`.  A game marked Private is never asked about: core does not call `read` or `save`
for it, so the extension is not told the library holds it.  Declare the group `private_ok=True`
and core asks about Private games too, with `private` true or false in `who`; do it for a group
that curates the library and sends nothing out.  A game's group is also drawn on each
of its tables' panels, and a table's group only on a table's.

```python
def notes(who):
    return {"fields": [{"key": "note", "type": "string", "label": ctx.t("group.note"),
                        "value": ctx.config.get(f"note.{who['game_id']}")}]}


def keep(who, values):
    ctx.config.set(f"note.{who['game_id']}", values["note"] or "")


ctx.ui.panel_group("game", notes, section="play", save=keep)
```

With `save(who, values)` the group's fields can be changed: each is written as it is set, with the
keys that changed, and core reads the group again to draw what was kept.  It is handed only keys
the group offers now, and it refuses a value by raising, as a pane's `save` does.  A group
that is read often should be quick: core reads it each time the panel opens, without holding
the panel back.  A group that answers nothing leaves nothing in the panel, and one that raises
or cannot be read draws a single quiet line saying so.

With `acts`, a strip of buttons closes the group: a dict of `{key: function or address}`, or a
function of `who` that answers one.  A function is called with `who` when its button is pressed
and answers what to say, as a list's act does; an address is opened.  Each button's words are
`group.<subject>.act.<act>.label`.  The strip is drawn only while the group is.

The name is `title`, else `group.<subject>.title` in the extension's catalog, else the
extension's name.  The group is served at `GET /api/v1/ext/<name>/groups/game/<game_id>` and
`GET /api/v1/ext/<name>/groups/table/<game_id>/<table_id>`, changed with `PUT` at the same
address and `{"values": {...}}`, and its acts at `POST .../groups/game/<game_id>/acts/<act>`
and `.../groups/table/<game_id>/<table_id>/acts/<act>`.  Reading, `PUT` and the acts need the
group's tier, except that a group at Protected is read with Library and changed only with the
Confirm.

It raises `ContractError` without `ui:mount` or without `games:read` in the manifest's `scopes`,
for a `subject` that is not `game` or `table`, for a `section` or `icon` that is not in the set,
for a `tier` the manifest does not list, for a subject declared twice, for a `read` or
a `save` that is not a function, and for `acts` that are neither a dict nor a function.  `--check-extension` says each group it finds.

## `ctx.ui.verb`

`ctx.ui.verb(subject, key, run, *, label="", one=False, danger=False, private_ok=False,
tier=LIBRARY)`.  Required: `subject`, `key`, `run`.

Add an entry to the menu of the Games grid (`subject` `"game"`) or the Tables grid
(`"table"`).  It is drawn on a row, on a selection and on the panel's header, each time in a
block of this extension's own after core's, under the extension's name.  Bundled extensions'
blocks come first, then the others, each by name.  `run(who)` is called with a list of what
was chosen, each `{"game_id", "vps_id", "name"}` and for a table also `{"table_id",
"vps_file_id", "version"}`, and answers what to say, as an act does: a message, or
`{"message", "url"}` to open an address as well.  A game marked Private is left out of `who`,
and an entry with none left refuses, unless the entry says `private_ok=True`: it is then
offered on Private games too, and each item of `who` carries `private`, true or false.  Say it
only for an entry that sends nothing out of VPinFE, such as one that tidies the library.

```python
def flag(who):
    ids = set((ctx.config.get("flagged") or "").split(",")) - {""}
    ctx.config.set("flagged", ",".join(sorted(ids | {one["game_id"] for one in who})))
    return ctx.t("message.flagged", count=len(who))


ctx.ui.verb("game", "flag", flag)
```

With `one`, the entry takes a single game or table: with several chosen it stays in the menu,
dimmed.  With `danger`, core asks first and draws the entry last in the block, under a rule.
The words are `verb.<subject>.<key>.label`, `.tip` and `.confirm` in the extension's catalog.
A `label` you give is used as written, and the catalog is read for it only when you give
none.  The entry is served at `POST /api/v1/ext/<name>/verbs/game/<verb>` and `.../verbs/table/<verb>` with `{"targets":
[{"game_id", "table_id"}]}`, and needs the verb's `tier=`.

It raises `ContractError` without `ui:mount` or without `games:read` in the manifest's
`scopes`, for a `subject` that is not `game` or `table`, for a key that is not lower-case
words joined by underscores or is declared twice for the subject, and for a `run` that is not
a function.  `--check-extension` says each entry it finds.

## `ctx.ui.needs`

`ctx.ui.needs(kinds, read)`.  Required: `kinds`, `read`.

Ask for a person's attention on Overview, under Needs You, with the rows core's own checks
raise.  `kinds` names each thing you may ask for, and what a click on its row opens: exactly
one of `"list"`, `"page"` or `"action"`, naming something this extension declares, and an
optional `"tone"` of `danger`, `warm` (the default), `accent` or `muted`.  `read` is a function
core calls each time Overview is drawn.  It answers a list of `{"kind", "ids"}` or
`{"kind", "count", "token"}`, one for each kind that has something to ask for now, each kind
at most once.

```python
def waiting():
    return [{"kind": "to_review", "ids": [str(one["id"]) for one in flagged()]}]


ctx.ui.needs({"to_review": {"list": "queue", "tone": "danger"}}, waiting)
```

With `ids` the count is how many there are, and a person who sets the row aside sees it come
back when an id joins that they had not set aside.  With only a `count`, give a `token` (a string,
or a list of them) that changes when the need does, such as the version an update is for: the
row stays away until the token is another.  Without a token the row is set aside against its
kind, and a row for a kind that answers a count of nothing is not drawn.

A person sees the row among core's own, with the extension's name where the count of an item
would be, and Dismiss, Undo and Show Again (under Set Aside) like any other row.  Stop Checking is there
too, worded for the row alone ("Only this row from" the extension): it stops this kind from this
extension, moves the row to Set Aside with Check Again, and survives a restart.  The extension is
still running, and switching it off in Settings stops all of it.  What a dismissal recorded is kept while the extension
is stopped or its `read` fails, and is dropped once it answers without it.  A click on an
`action` opens the dialog over no rows, and Overview is drawn again once it closes.

The words are `need.<kind>.label`, required, given `count` so it can have plural forms, and
`need.<kind>.says`, in the extension's catalog.  A `read` that raises, or answers a kind that
was not declared or a shape that is not a list of kinds with ids or a count, leaves out only
this extension's rows, and Overview says that what extensions ask for could not be read.  The
Console reads every running extension's rows from `GET /api/v1/extensions/needs` (needs
`instance:read`).

It raises `ContractError` without `ui:mount`, when called twice, for `kinds` that is empty or
not a dict, for a kind that is empty or has a `:`, `/` or a space in it, for a kind that does
not name exactly one of `list`, `page` and `action`, for a `tone` that is not one of the four,
and for a `read` that is not a function.  The same check as for any declaration refuses a kind that
opens a list, page or action the extension never offers.  `--check-extension` says each kind and
calls `read` once.

## `ctx.ui.kept`

`ctx.ui.kept(key) -> dict | None`.  Required: `key`.

The last good read core keeps of one of this extension's lists: `{"rows": [...],
"read_at": "<UTC time>"}`, or None before the first good read.  Use it to have your list at
start, before core's first read and whether or not the service answers.

```python
kept = ctx.ui.kept("top")
if kept is not None:
    cache.load(kept["rows"], kept["read_at"])
```

It raises nothing beyond the `ui:mount` check.

## `ctx.ui.action`

`ctx.ui.action(key, dialog, *, label="", description="", tier=LIBRARY)`.  Required: `key`,
`dialog`.  It raises `ContractError` for a `tier` the manifest does not list.

Offer a dialog that core shows.  `dialog` is an object with `ask(step)` and, as far as the
action needs them, `check`, `act`, `run` and `progress`.  See
[Actions and dialogs](actions.md#actions-and-dialogs).

```python
class Reset:
    def ask(self, step):
        return {"confirm": ctx.t("action.reset.confirm")}

    def run(self, values):
        return ctx.t("action.reset.done")


ctx.ui.action("reset", Reset())
```

A person sees a button under Actions on the extension's page, and it opens the dialog.  A list
can open the same dialog from a button above it, from a verb or from an act.  It raises
`ContractError` for a key that is empty or already used, or a `dialog` without a callable
`ask`.

## `ctx.ui.link`

`ctx.ui.link(key, url, *, area="", icon="")`.  Required: `key`, `url`.

Link to a page of your own, for an extension that has more than VPinFE draws: a hardware
tool's web page, a service's dashboard.  `url` is an address, or a function that answers one
each time the Console draws it.  `{host}` in it is filled with the host the Console was opened
at, so `http://{host}:9090/` reaches a port of the extension's own from a laptop as well as at
the cabinet.  Only `http://` and `https://` are drawn.

```python
ctx.ui.link("console", "http://{host}:9090/", area="system")
```

A person sees the link in a menu at the end of the title of the extension's page, in Settings.
With an `area` (`library`, `frontend`, `community` or `system`, as a list's) it is also an
entry in that group of the rail, after core's own and after the extension's lists (and before
About, in System), drawn with `icon` from [Rail icons](#rail-icons) and with a mark that it leaves the Console.  Every link opens a new tab, with `noopener` and `noreferrer`
whatever the address, so the page it opens cannot reach back into the Console.  Nothing is drawn
while the extension is stopped, and a function that raises, or answers something that is not a
web address, leaves out only its own link.  The words are `link.<key>.label`, required, and
`link.<key>.tip`, in the extension's catalog.

It raises `ContractError` without `ui:mount`, for a key that is empty or already used, for an
`area` that is not one of the four, and for a `url` that is neither a function nor a web
address.  A function's answer cannot be checked until it is asked, so `--check-extension` asks
it and fails the extension if the answer is not a web address.

Put a page of your own on another site or on a port of its own.  A page served from VPinFE's
address would run as the Console, so [what core serves](served.md#what-core-serves) answers
anything under `/api/v1/ext/` as a page with no origin of its own.  Anything the page on your
own port changes should sit behind its own sign-in, as VPinFE does not guard a port it did not
open.

## `ctx.ui.account`

`ctx.ui.account(*, read, write=None, acts=None, card=None, read_card=None, available=None,
label="", cards=(), marker="", consent=(), sends_picture=False)`.  Required: `read`.

Say that a player can hold an account with this extension.  Call it once.  See
[Accounts](accounts.md#accounts).

```python
ctx.ui.account(
    read=lambda player_id: {"user_id": "", "claimed": False, "acts": []},
    write=lambda player_id, values: ctx.players.set_account(player_id, values),
    consent=(ctx.t("account.consent.id"),))
```

A person sees the account in each player's panel under Frontend > Players.  It raises
`ContractError` for a second account, a `read` that is not a function, an empty card type, a
marker that is not a plain name, `cards` without `read_card`, or an act that is not a function.
