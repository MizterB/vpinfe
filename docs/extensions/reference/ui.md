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
acts=None, relation=None, tag="", verbs=(), add=())`.  Required: `key`, `rows`, `columns`.

Declare a list.  `rows()` returns the rows, each a dict.  See
[Lists](settings-and-lists.md#lists) for columns, views, acts, relation, tag, verbs and add.

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

After `register` returns, it also raises when the title matches a core page's title or another
running extension's list in the same area, and when a verb, an act or `add` opens a dialog the
extension never declared.

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

## `ctx.ui.state`

`ctx.ui.state(base, label="")`.  Required: `base`.

Say where core reads what the extension is holding: rows with at most two buttons each, shown
on its page.  `base` is a route the extension serves itself with `ctx.add_router`, at
`GET /api/v1/ext/<name><base>`.

```python
@router.get("/held")
def held() -> dict:
    return {"rows": [{"id": "a", "label": "Taxi", "mark": "Pending",
                      "detail": "Waiting to send",
                      "actions": [{"key": "drop", "label": "Drop"}]}],
            "empty": ctx.t("held.empty")}


ctx.ui.state("/held", label=ctx.t("state.label"))
```

A person sees a section on the extension's page headed by `label`, then `state.label` in the
catalog, then the Console's own "Held".  See [What it holds](accounts.md#what-it-holds).  It
raises `ContractError` without `ui:mount`.

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
