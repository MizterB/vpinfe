# `ctx.ui`

What an extension offers a person.  You declare it and core serves it: you hand over fields, a
`rows()` function and a dialog object, and core mounts the routes the Console reads.  All of it
needs the `ui:mount` capability, and every call here raises `ContractError` without it.  The
sections after this one describe each declaration in full.

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

`ctx.ui.list(key, rows, *, columns, area="community", title="", views=(), status=None,
acts=None, relation=None, tag="", verbs=(), add=(), detail=None, save=None)`.  Required:
`key`, `rows`, `columns`.

Declare a list.  `rows()` returns the rows, each a dict.  See
[Lists](settings-and-lists.md#lists) for columns, views, acts, relation, tag, verbs, add and
the pane (`detail` and `save`).

```python
ctx.ui.list("top", read_top, title="Example Scores",
            columns=[{"field": "name"}, {"field": "score", "kind": "number"}])
```

A person sees the list in the rail under `area`.  It raises `ContractError` for:

- an unknown area, a missing key or columns, or a repeated key
- `rows` or `status` that is not a function
- `under` on any column but the first, or an unknown column kind
- a view on a column the list does not have
- a relation on a missing field, or with `keys` other than `vps_entry` or `vps_release`
- a `tag` without a relation
- a ranked view that sorts on anything but number or date columns, or has no relation
- a verb that is not a dict, has no key or a key already used, or carries a key core does not
  read
- a verb with more than one of `run`, `link` and `action`, or none of them
- `danger` or `needs` on a `link`, `danger` on an `action`, or `each` without an `action`
- an `add` that is not a key, or names one twice
- a `detail` or `save` that is not a function, or a `save` with no `detail`

After `register` returns, it also raises when the title matches a core page's title or another
running extension's list in the same area, and when a verb, an act or `add` opens a dialog the
extension never declared.

## `ctx.ui.panel_group`

`ctx.ui.panel_group(subject, read, *, title="", save=None)`.  Required: `subject`, `read`.

Put a group on a game's panel (`subject` `"game"`) or on one table's (`"table"`), in Play after
High Scores.  `read(who)` answers the group's one section, the same `{"facts", "fields",
"rows"}` a [pane's](settings-and-lists.md#lists) section holds, and core draws it as it draws
the rest of the panel.  Answer None, or a section with nothing in it, and the group is not
drawn.

`who` is `{"game_id", "vps_id", "name"}`, and for a table also `{"table_id", "vps_file_id",
"version"}`.  A game marked Private is never asked about: core does not call `read` or `save`
for it, so the extension is not told the library holds it.  A game's group is also drawn on each
of its tables' panels, and a table's group only on a table's.

```python
def notes(who):
    return {"fields": [{"key": "note", "type": "string", "label": ctx.t("group.note"),
                        "value": ctx.config.get(f"note.{who['game_id']}")}]}


def keep(who, values):
    ctx.config.set(f"note.{who['game_id']}", values["note"] or "")


ctx.ui.panel_group("game", notes, save=keep)
```

With `save(who, values)` the group's fields can be changed: each is written as it is set, with the
keys that changed, and core reads the group again to draw what was kept.  It is handed only keys
the group offers now, and it refuses a value by raising, as a pane's `save` does.  A group
that is read often should be quick: core reads it each time the panel opens, without holding
the panel back, and a group that raises or does not answer leaves nothing in the panel.

The heading is `title`, else `group.<subject>.title` in the extension's catalog, else the
extension's name.  The group is served at `GET /api/v1/ext/<name>/groups/game/<game_id>` and
`GET /api/v1/ext/<name>/groups/table/<game_id>/<table_id>`, changed with `PUT` at the same
address and `{"values": {...}}`.  They need the extension's read and write scopes.

It raises `ContractError` without `ui:mount` or without `games:read` in the manifest's `scopes`,
for a `subject` that is not `game` or `table`, for a subject declared twice, and for a `read` or
a `save` that is not a function.  `--check-extension` says each group it finds.

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

`ctx.ui.action(key, dialog, *, label="", description="")`.  Required: `key`, `dialog`.

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

`ctx.ui.link(key, url, *, area="")`.  Required: `key`, `url`.

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
About, in System), with a mark that it leaves the Console.  Every link opens a new tab, with `noopener` and `noreferrer`
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
