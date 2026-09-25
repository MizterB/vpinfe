# Launchers

How a table gets played. Two nouns, and the difference between them is the whole model.

- **App** - the program that plays a table, and how to talk to it: which suffixes it claims, how to build a launch command, what its ini means, how to parse a table, how to resolve a ROM. Code, in `common/apps/`.
- **Launcher** - a configured wrapper around an app: an id, a display name, the app it wraps, an enabled flag, and values for that app's settings. User data, in `launchers.json`. No two launchers on an install share a name, whatever their app, compared ignoring case (`launchers.same_name`); Add and Duplicate ask for the name first; Add left blank, Duplicate's offer and the 2.x migration take the next free one (`launchers.free_name`).

A table names a launcher; a launcher names an app. An install ships one launcher wrapping `vpx`, seeded from the configuration it already had.

Because every launcher names an app, VPinFE always knows how to talk to it. A second VPX launcher inherits ROM resolution, table parsing and ini semantics for nothing, which is the property a launcher defined from scratch could not have.

## The apps

`common/apps/__init__.py` is the registry and `common/apps/contract.py` is the `App` contract.

Built-ins are `apps.vpx.VPX` and `apps.generic.GENERIC`, offered in that order. `generic` knows only suffixes, a binary and arguments: a launcher wrapping it can launch a file and nothing else, with no parsing, no ROM resolution, no ini overrides and no per-table configuration. It is a declared app rather than a special case so its reduced capability is visible rather than discovered.

Extensions contribute apps through `contribute()`, and `withdraw()` takes one back when the extension is disabled or reloaded. Contributed apps are always offered after the built-ins, so one cannot take a suffix out from under Visual Pinball by loading first, and an id already in use is refused rather than allowed to win. Ids are stored in a table's record, so two apps answering to one id would make what is stored ambiguous.

- `all_apps()` - every app this install has, in the order they are offered.
- `app_for(filename)` - which app claims a file, or `None`.
- `get(app_id)` - by id. An unknown id is a real state, not an error, because ids are stored.
- `app_name(app_id)` - what to call one on screen. Ids are for the wire.

## Where a launcher's settings live

`launchers.json` in the install's config directory, beside `collections.json`, `devices.json` and `players.json`. Not a config section.

A launcher is an object the user creates, names, duplicates, removes and switches off, rather than one of a fixed set of settings the install has. Nothing in the tree has a dynamically named config section and `config_schema` has no concept of one.

Seven keys left `general` and became four fields on the launcher, shedding the app's name:

| was | is |
|---|---|
| `general.vpx_bin_path` | `bin_path` |
| `general.vpx_ini_path` | `ini_path`, where no override was set |
| `general.global_ini_override` | `ini_path` |
| `general.vpx_launch_env` | `launch_env` |
| `general.vpx_log_delete_on_start` | `log_delete_on_start` |
| `general.global_game_ini_override_enabled`, `general.global_game_ini_override_mask` | retired: each table's `{stem}.{mask}.ini` became its `{stem}.ini`, where it had none |

A second launcher's fields are then the same names, which is what lets its editor be generated from the app's settings schema instead of hand-written per app. A 2.x config is migrated once rather than carrying seven permanent key aliases.

`ini_path` is the **Settings File**: the `VPinballX.ini` a table starts with and the one the Console's settings change. One that is not Visual Pinball's own is passed as `-ini`. Empty means Visual Pinball's own, which VPinFE finds where the program keeps it: the newest version folder under its preferences folder (`~/.local/share/VPinballX/10.8/` on Linux, `~/Library/Application Support/VPinballX/10.8/` on macOS, `%APPDATA%\VPinballX\10.8\` on Windows), then beside the program, then the layouts from before version folders.

`owns_ini` records whether VPinFE created the file `ini_path` names.

**A launcher is per install.** A binary path and an ini path are facts about one machine; `common/launcher_path.py` exists only because macOS hands you a `.app` bundle and Linux hands you an executable.

## Per-table assignment

A table pointed at a specific launcher is recorded in `launchers.json` under `MAPPINGS_KEY`, not in the table's `.info`.

A table's **Launcher** picker shows the launcher that plays it. It lists the table's own app's launchers first, its default marked *Default*, then *Other Programs* (`launchers.launcher_offer` in the Console). A switched-off launcher is left out unless the table names it. A table that chose its own carries a dot, amber where the one it chose is switched off, and **Clear** takes it back to the default. One played by another program's launcher says what it gives up, where its own app has settings: *Runs with Generic - Visual Pinball X's settings, ROM and start-up check don't apply*.

## Resolution

Two functions in `common/games/launchers.py`, and the second is the one that decides.

- `launcher_for_entry(app_id, table_id, launchers, mappings)` - what the entry names, then the default for its app. By app rather than by filename, because an entry with no file has no suffix to resolve through.
- `launcher_for_table(filename, table_id, launchers, mappings)` - for callers holding a name off a directory listing. It resolves the app from the suffix and delegates.

The default for an app is the first enabled launcher wrapping it, so the file's order answers "which is the default". Making one the default, from its **Default** switch or `POST /launchers/{id}/default`, moves it to the front (`LauncherStore.to_front`). A switched-off launcher cannot be made the default, and the default's own switch cannot be turned off: another launcher is made the default instead.

One path, so the grid's effective-launcher column and the launch path cannot disagree.

## Enable, disable and fallback

Disabling is non-destructive: it hides a launcher from pickers, and tables already assigned to it keep their assignment. Removal is the destructive one and asks about its tables.

A table assigned to a disabled launcher **falls back** to the default for its app rather than refusing to launch. The fallback is honest and silence about it is what turns a configuration choice into a mystery, so it is said in three places:

1. At the transition, a confirm dialog naming the impact, count first: *"Switch off “VPX (4K)”? 4 tables use it. Switched off, they launch with Visual Pinball X."* A launcher no table uses goes off without asking. Where its tables would go to a launcher with no program, or to none, switching it off is refused and the switch stays on: *"Switched off, its tables would go to Visual Pinball X, which has no program."* `GET /api/v1/launchers/{id}/fallback` answers the same question without switching anything. Making a launcher with no program the default is the other way to send tables to nothing, and it is refused the same way: its **Default** switch is disabled, *“VPX (4K)” has no program*.
2. While the state persists, a mark on the row: not *set here and in effect*, not *following the default*, but *set here and overridden*. The Launcher column's dot, which says a table chose its own, turns amber beside the name of the launcher that plays it instead, and the table's picker marks it the same way. A table row carries it as `launcher_falls_back`.
3. At launch, a log record saying which table, which launcher it asked for, why that did not happen, and what ran instead.

## The API

`docs/http_api.md` documents the endpoints, in its Endpoints table and its Launcher settings section.

## The Console

Launchers is a subject under Frontend, beside Themes. Both are gated on the `frontend` feature, so an install without it shows neither. It is not a group in Settings, because Settings is label-and-value pairs and a launcher is an object to manage.

The grid says how many tables each launcher plays (`tables` on `GET /launchers`, counted through `launcher_for_entry`), and a state only where one cannot play them: *No Program*, *Program Missing* or *Switched Off*. A ready launcher's state is blank.

A launcher's panel opens on **Details**: its name, whether it is the default and whether it is on, then what it runs and how. Then a section for each area its app declares, drawing only the rows the app curates for it (`ConfigGroup.curated`), under its sub-headings. A heading led by a switch (`Heading.enabled_by`, as every plugin is by its *Enable*) draws its other rows only while the switch is on. An area ends with how many of its settings it does not draw, which opens All Settings on that area, and a search box at its top carries what is typed into All Settings. An area the app curates nothing for is drawn whole.

Then **All Settings**: every setting the program keeps, in the program's own words. Its search matches the label, the key and the program's description, each word anywhere, so a key copied out of the ini finds its row. Three filters narrow it: **Set Here** (in this launcher's settings file), **Different from Default**, and the area, where *Other* holds the settings no area does. Results sit under the program's section names made readable - *Player*, *Score View*, *Plugin: PinMAME* - a plugin taking the name its area gives it.
