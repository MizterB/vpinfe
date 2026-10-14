# Settings and lists

The two declarations most extensions start with: a page of settings, and a list in a rail area.

## Settings

Declared with `ctx.ui.settings`. Core draws them on the extension's page and stores them
in the extension's own file.

A field is `{"key", "type", "default", "choices"}`:

| key | meaning |
|---|---|
| `key` | Required. The name `ctx.config.get` reads it by. Unique |
| `type` | One of the settings types below. Left out, `string` |
| `default` | Text. A switch defaults to `"false"` unless true. A secret may not have one. A select's default must be one of its choices, and is the first when left out. A multi's is a list of them. A number's is a number |
| `choices` | A select's or a multi's `[[value, label], ...]` |

The types a settings page draws are exactly `SETTINGS_TYPES`: the *settings* column of the
table under [Fields](actions.md#fields). A `number` may carry `min`, `max` and `unit`, a `path` says what it
`wants`, and a `multi` takes `choices` as a select does and may default to a list of them.

Everything is stored as a string. A secret takes `type: "secret"`, never `string`: core
removes secrets from every answer it gives for the extension, by that type. A `secret`
write that is empty is skipped, so leaving the field blank keeps what was there; only
*Clear*, which asks first, empties one.

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
answer raises `Unavailable`; see [Unavailable](running.md#unavailable).

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
