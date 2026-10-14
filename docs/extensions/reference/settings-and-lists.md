# Settings and lists

The two declarations most extensions start with: a page of settings, and a list in a rail area.

## Settings

Declare them with `ctx.ui.settings`.  Core shows them on the extension's page and stores them
in the extension's own file.

A field is `{"key", "type", "default", "choices"}`:

| key | meaning |
|---|---|
| `key` | Required.  The name `ctx.config.get` reads it by.  Unique |
| `type` | One of the settings types below.  Left out, `string` |
| `default` | Text.  A switch defaults to `"false"` unless true.  A secret has none.  A select's default is one of its choices, and is the first when left out.  A multi's is a list of them.  A number's is a number |
| `choices` | A select's or a multi's `[[value, label], ...]` |

A settings page offers exactly `SETTINGS_TYPES`: the *settings* column of the table under
[Fields](actions.md#fields).  A `number` takes `min`, `max` and `unit`, a `path` says what it
`wants`, and a `multi` takes `choices` as a select does and may default to a list of them.

Everything is stored as a string.  Give a secret `type: "secret"`, never `string`: core takes
secrets out of every answer it gives for the extension, by that type.  Leaving a secret empty
keeps what was there; only *Clear*, which asks first, empties one.

**`check`.**  `check(values)` receives every setting as it would be after the change, with the
unset ones at their defaults.  Raise to refuse the change, and the person sees your words under
the first field that changed.  It returns nothing.

```python
def check(values):
    if not values["server"].startswith("https://"):
        raise ValueError(ctx.t("error.https"))


ctx.ui.settings([{"key": "server", "type": "string", "default": "https://example.com"}],
                check=check)
```

The words go in the extension's `i18n`:

- `settings.<key>.label` - falls back to the key.
- `settings.<key>.help` - the `{default}` slot is the default.  Falls back to empty.
- `settings.<key>.choice.<value>` - a select option.
- `settings.label` - the heading over the section.

A write for a key you did not declare (`error.extensions.no_setting`) or a select value that is
not a choice (`error.extensions.bad_choice`) is turned down, and the person sees why under the
field.

## Lists

`ctx.ui.list(key, rows, *, columns, area, title, views, status, acts, relation, tag, verbs, add)`.
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
           {"key": "hide", "run": hide, "danger": True},
           {"key": "rename", "action": "rename", "each": True}],
    add="new_table",
    tag="Weekly Challenge")
```

**Key and rows.**  `key` is unique within the extension.  `rows()` returns a list of dicts
that JSON can carry.  If a row cannot be carried, or the result is not a list of dicts, the
list shows that the extension could not answer and the extension keeps running
(`error.extensions.not_data`, `error.extensions.not_rows`).  When a service does not answer,
raise `Unavailable`; see [Unavailable](running.md#unavailable).

**Row ids.**  A row's `id` is a string, unique in the list.  A number is read as its text.  Two
rows with one id mean the extension could not answer
(`error.extensions.duplicate_row_id`), for any list, verbs or not.  A verb finds a row by its
`id`.  A row with no `id` shows, but it cannot be ticked and has no menu.

**Area.**  Which group of the rail the list is in.

| `area` | in the rail under | offered when the install has |
|---|---|---|
| `library` | Library | the `library` feature |
| `frontend` | Frontend | the `frontend` feature |
| `community` (default) | Community | always |
| `system` | System | always |

A list is in the rail only while its extension runs.  A page still open when the extension
stops says Off, or Stopped with the reason, in place of Refresh, and the list is not asked.

**Title.**  `title` is shown as written; left out, it is `list.<key>.title` in the catalog.
It cannot match a core page's title (Overview, Games, Tables, Media, Assets, Collections,
Tags, Discovery, Players, Launchers, Themes, Settings, Devices, Metrics, Logs, Jobs,
Backups, About, Library, Frontend, Community, System), or another running extension's list
title in the same area, compared without regard to case.  Either one raises `ContractError`
from `register`, so the extension fails to start and the log names the clash.

**Columns.**  `{"field", "header", "kind", "help", "under"}`.

| key | meaning |
|---|---|
| `field` | Required.  The row key it shows |
| `kind` | `text` (default), `number` or `date` |
| `header` | Shown as written; left out, `list.<key>.column.<field>.header`, then the field |
| `help` | The tooltip on the header.  Left out, `...help` in the catalog, then the header |
| `under` | First column only.  Row fields shown on the line beneath its value, as a game's maker and year are |

**Views.**  `{"key", "name", "columns", "sort", "help", "ranks"}`.  A view names the columns it
shows (all when left out) and how it sorts: `[{"field", "desc"}]`, one field after another.
`name` and `help` fall back to `list.<key>.view.<viewkey>.name` and `...help`.  A view can only
name columns the list has.

**Ranks.**  `"ranks": True` offers the view as an order for a collection, named for the list's
title and the view's name (*Example Scores: Most Played*).  It puts this library's games in the
view's sort, each field in its own direction, and there is no reversing it.  A game the list
does not rank follows in title order, so the order never drops one.  A ranked view sorts on
`number` or `date` columns only, and its list needs a `relation`.  The order is read with the
tags, on the same schedule, and keeps the last good read if a read fails.  While the extension
is stopped, a collection in its order keeps it and shows its games in title order until the
extension runs again.

**Relation.**  `{"field", "keys"}`.  Core asks which of the rows this library holds and makes
their name a link.  `keys` is `vps_entry` for a link to the game, or `vps_release` for one to
the table; `field` is the row key that holds the id.

**Tag.**  With `tag="Weekly Challenge"` and a relation, core puts that tag on what this library
holds from the list: the game for a `vps_entry` relation, the table for a `vps_release` one, so
a challenge naming one build of a machine tags that build and not the others.  The tag belongs
to the extension.  Nobody can rename, merge or remove it, or put it on by hand, and it goes
when the extension stops.  It is written as given in every language, because it is stored on
games, which makes it data.

**Reading.**  Core asks `rows()` on every visit and on Refresh, so answer with the whole list
as it is now and keep no copy of your own.  Core keeps the last good read on disk
(`ctx.ui.kept`).  The page shows it at once, with how old it is, and asks again behind it.  If
that read fails, the last good list stays on screen, marked stale.  Tags and ranks are read
shortly after start and every 30 minutes after; if a read fails, the last good one stays.

**Status.**  `status()` returns text, or `{"text", "detail", "to"}`.  It is one quiet line in
the bar above the list, or under the reason when the list could not be read.  `detail` shows
on hover.  `to` makes the line a link: `players` opens Frontend > Players, where each player's
accounts and their Share are, and `settings` opens the extension's own page.  Any other `to`
shows no link.  An empty status shows nothing.

**Acts.**  The menu at the end of the page's title, in order, with **Settings** added after
them wherever the extension has settings.  `acts` is a dict `{key: function or address}`, or a
function returning one.  Core calls it each time the page opens and after each act, so you can
offer an act only while it can work (a Send Now with nothing waiting is left out).

- A function runs when the act is pressed.  It returns None, a message string that is said, or
  a dict `{"message", "url"}`: a `url` opens in a new tab.
- A string is an address.  The act is a link that opens that address in a new tab, marked as
  leaving, and the extension is not called.  It has to start with `http://` or `https://`, or
  it is left out.
- `{"action": "connect"}` opens the dialog declared as `connect`, with no rows.  The extension
  is not called until the dialog is.  A key that names no declared dialog stops the extension
  from starting, with the key in the reason.

An act's label is `list.<key>.act.<act>.label`, falling back to the act's key.

**Verbs.**  What a person can do to rows: one, or several ticked.  Each verb is in the row's
right-click menu and in the menu the bar shows while any row is ticked.  `{"key", "run",
"link" or "action", "each", "danger", "needs", "one", "label"}`:

| key | meaning |
|---|---|
| `key` | Required, unique in the list.  What the catalog finds its words by |
| `run` | A function, called with the rows as dicts.  It returns None, a message string that is said, or `{"message", "url"}`: a `url` opens in a new tab.  Core reads the list again afterwards |
| `link` | In place of `run`: the row field that holds an address.  The verb opens it in a new tab, marked as leaving, and the extension is not called.  The field has to start with `http://` or `https://`, or the verb is dimmed and says **No address**.  A link is always `one`, and takes no `danger` or `needs` |
| `action` | In place of `run`: the key of a dialog declared with [`ctx.ui.action`](actions.md).  It opens over the rows chosen, and its `ask` is handed their ids (see [Over rows](actions.md#over-rows)).  It takes no `danger`, since the dialog asks for itself.  The list is read again after the dialog runs |
| `each` | With `action`: one dialog for each row chosen, in order, with **Skip** and **Stop** where Cancel would be.  Skip leaves that row as it was and moves on; Stop ends the run.  Without it, one dialog covers every row |
| `danger` | Puts the verb last, under a rule, in red, and asks first.  The question is `list.<key>.verb.<verb>.confirm`, and `{count}` is the number of rows ticked, which can be more than the rows the verb acts on when it also has `needs`.  The Console does the asking; the route runs the verb whenever it is called |
| `needs` | A row field that is true or false.  The verb is dimmed on a row where it is not, with the words `list.<key>.verb.<verb>.needs`.  With several rows ticked, it acts on the rows where the field is true.  Core checks this again when the verb is pressed |
| `one` | The verb makes no sense over several rows.  With several ticked it stays in the menu, dimmed, and says **One at a time**.  Core turns it down for any other number of rows |
| `label` | Shown as written; left out, `list.<key>.verb.<verb>.label`, then the verb's key |

The question a danger verb asks has a singular and a plural, `{"one": "Remove this row?",
"other": "Remove {count} rows?"}`.  Left out, core asks "`<label>` this row?" or "`<label>`
`<count>` rows?".  A verb is not offered while the extension is stopped.  If a verb raises, the
person sees the reason (`Unavailable` is a 502).

**Add.**  `add="new_table"`, or a list of keys, names the dialogs that put something into this
list.  Core puts a button in the bar above the list: its words in full while the list is empty,
and a **+** once it has rows.  With several keys the button opens a menu of the dialogs' labels
(`action.<key>.label`).  The dialog opens with no rows, and the list is read again after it
runs.  A key that names no declared dialog stops the extension from starting, with the key in
the reason.

Words: `list.<key>.title`, `list.<key>.column.<field>.header|help`,
`list.<key>.view.<viewkey>.name|help`, `list.<key>.act.<act>.label`,
`list.<key>.verb.<verb>.label|tip|confirm|needs`.  `tip` is what a hover adds to the label.
