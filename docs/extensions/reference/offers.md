# More to offer

Five things an extension can offer beyond a page of its own: a way to play a table, something
added to every entry, an outside link, a name for a command, and a word on what a game tells
you.

## A way to play a table

VPinFE plays Visual Pinball, and through the generic app anything a person can point at a
binary.  An extension is how another format becomes first class.  It claims its own suffixes,
so a library of them is worth importing rather than read and dropped.  `ctx.apps.provide` needs
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
app's own file is (see "An app's words" in `docs/conventions.md`).  A field that file does not
name takes core's words, so Program reads the same on every launcher.  `name` is given in code
here because Future Pinball is a product name, and is shown as written.

The app is described in plain data because an extension cannot import the app contract.  Its
one door is `common.extensions.contract`, which is what makes the import boundary checkable.
`command` answers with a list of arguments, never a string.  Splitting a string is how a path
with a space in it becomes a crash or an injection, and only the extension knows where its own
arguments end, so a string raises.  Answering with nothing runs the launcher's configured
binary and arguments instead.

Apps this build ships are offered first, so a provided one cannot take `.vpx` out from under
Visual Pinball by loading before somebody looks.  An id already in use is refused, because ids
are stored in a table's record and read back long afterwards.  What an extension provides is
taken back when it unloads, so a disabled extension leaves no suffix claimed by something no
longer there.

A provided app does not get the rest of the app contract: parsing a table, resolving a ROM, a
settings surface, a launch of its own for a recording.  Those are declared absent rather than
half answered, the same way the generic app declares them.

## Something to an entry

A theme reads `entry.ext.<key>`.  It never learns which extension answered, and no extension
gets a method of its own on the theme surface, since that would need a new call for every
connector that follows.

```python
def rating_for(game):
    # game is {game_id, vps_id, name, manufacturer, year, ipdb_id}: a description,
    # never core's object.
    return {"stars": look_it_up(game["vps_id"])}


ctx.entries.contribute("rating", rating_for)
```

Each value in the description is the effective one, so an extension sees the match a user
corrected, not the one the scan found.

**Core makes the call; the browser makes none.**  `fetch` runs on core's thread when the player
moves to a game, so it may block, but it must not raise for a game it simply has no answer
about.  One that raises costs its own key and nothing else.

Core does three more things that no theme author sees:

- The answer is held per process, so one fetch serves every window and survives a reload.
- The games either side are fetched on the same signal.  What somebody sees is the answer
  fetched a step ago, and the gap only shows on the first game of a cold start.
- The message that carries an answer names the game it is about, so one that arrives after the
  wheel has moved lands on the entry it belongs to.

The slot is always present and empty at library load, since a list of four hundred games
cannot wait on four hundred calls to somebody else's server.  A theme written as
`if (entry.ext.rating)` is correct throughout without knowing there is a waiting state.

An answer is held for the rest of the run.  When what an extension knows changes (a fresh list
read, say), `ctx.entries.stale("rating")` drops what core holds under that key, and each game
is asked again the next time it is reached.

An extension that answers from one of its own lists makes no call per game at all.  It holds
the rows its list last answered and reads them back at start with `ctx.ui.kept(key)`.
VPinPlay's rating works that way.

## An outside link

A game, a table or a file can have a page somewhere else, and an extension can say where.

```python
ctx.catalogs.contribute(
    "scores", "Example Scores", "game",
    lambda game: f"https://scores.example.com/tables?vpsid={game['vps_id']}")
```

`subject` is `game`, `table` or `file`, and anything else is refused at registration.  `link`
is handed a plain description of the subject and answers its address there, or `""`.  Core
draws it as a row named for the place, with an open-in-new icon.  A link that raises, or
answers anything but an http or https address, is left out.

## A name a command can use

A user writes commands that run when VPinFE starts and around every table.  Core declares what
one of them may say (`{table}`, `{rom}`, `{program}`), and an extension adds to that list.

```python
def season(values):
    # values is what this context has resolved so far. Answer a string; empty is an
    # answer, and this must not raise on an install that has none.
    return ctx.config.get("season", "")


ctx.tokens.offer("season", (ctx.tokens.TABLE,), season)
```

What it stands for is `token.season.says` in the extension's `i18n/en.json`, or `says=`.  A
name with nothing saying what it stands for is refused.

**The name carries the extension's id.**  You declare `season` and a user writes
`{example_scores.season}`.  The dotted half is built from the manifest rather than spelled
here, so two extensions may offer the same idea without reaching each other, and core's own
names, which never carry a dot, can grow without reaching either.  Who is playing is one of
core's: `{player}` is the initials of the one player up, and blank with several.

`contexts` says where the command runs.  `ctx.tokens.VPINFE` is the pair around VPinFE itself
and `ctx.tokens.TABLE` the pair around every table.  Declare only the ones the name means
anything in, because a name that is always blank costs a reader more than one that was never
offered.

`value` runs while a command is being prepared, so it has to answer quickly.  One that raises
stands for nothing and is logged, and the table still launches.  Pass `after_only=True` for
something only the half that runs afterwards can know.

**A name goes when its extension does.**  A command still holding one is refused by that name,
the same as any name nothing declares.  The alternative is a `--flag` left with nothing after
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

**A Private game's data is never sent anywhere.**  Not its plays, its time, its scores or its
rating, and not the fact that the library holds it: to no service, for no player, whoever was
up and whatever their Share says.  A game is Private when somebody marks it so.  The events
carry `private`, and a game's rows from `ctx.games` carry it too, for anything an extension
sends outside a session.  An extension reads the flag and cannot set it.

A table's events carry `source`, who started it: `frontend`, `remote`, `api`, or `capture` for
a launch that records the table's media.  A recording is not a play.  Nobody is up for it, it
writes no play data and there is no `table.play_recorded` after it, so an extension counting
plays counts on that event or leaves out a `capture` launch.

```python
def on_played(**payload):
    if payload["private"]:
        return
    for credited in payload["new_entries"]:
        post_score(credited["player"]["id"], credited["entries"])


ctx.events.subscribe("table.play_recorded", on_played)
```

**A game counts for who was up.  A new score goes to the player whose initials it has**, up or
not.  An entry with no initials, or `???`, goes to the one player up, and with several up to
nobody.  Core matches them once, so no two extensions disagree about whose a score was.  An
entry is new when the table after the game holds it more times than the table before,
whatever its rank.  A machine that keeps one number has a new entry when it changed, and a
game with no reading before it has nothing new.  `reading` is `{rom, resolved_rom,
score_kind}` with either `entries`, each `{section, rank, initials, score, ...}`, or a single
`value`.

A service that takes one player a game decides for itself what to do with several up, and its
account's status line says so rather than going quiet.
