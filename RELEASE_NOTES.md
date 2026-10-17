## VPinFE Release Notes

### Summary
VPinFE 3.0. The Manager is the new place to run your library: games, tables, media,
collections, tags, players, devices, settings and backups, with Setup for a first run and an
import from PinballX, PinballY or PinUP Popper. Every game has an id of its own, a game
folder can hold more than one table, other programs can build on an HTTP API at `/api/v1`,
and every word on screen comes from a translation catalog. An install from an earlier version
upgrades on its first start and VPinFE keeps a copy of everything it rewrites, so read the
next section first.

### Before you upgrade
- **Update the earlier install to v2.6.0 or newer first, even if you plan to stay on 3.0.**
  If you go back, only v2.6.0 or newer knows how to put 3.0's backups back. Earlier
  releases do not look for them.
- The first start rewrites every game's `.info` and moves your collections onto game ids.
  Your settings are read once from `vpinfe.ini` into a new `vpinfe.json` beside it, and the
  ini is left where it is. The original of each `.info` is kept beside it as
  `<name>.info.vpinfe-<timestamp>`, and collections are backed up the same way. Expect a
  burst of writes on the first start and nothing after.
- To undo it, open System > Backups and press Go back to 2.x, or run `--restore-info`.
  That puts back each game's metadata and your collections. Clean up on the same page
  deletes the copies once you are sure you are staying.
- To take a 3.0 development build back off entirely, `--reset-3x-state` removes the
  settings and collections files 3.0 wrote, the `.info` files it made and every backup it
  kept, so the next start migrates from scratch. Settings you changed under 3.0 are lost,
  and so is any rating or play count on a game 3.0 added. It keeps a copy of your device
  list first, because a mobile device you added manually is the one thing nothing
  re-announces. It refuses while VPinFE is running; `--dry-run` lists what would go, and
  `--config-only` leaves the library alone.
- **Other devices sign in once, with a code.** A browser on another device asks for a
  code and VPinFE shows it on this device, where whoever is there chooses Show or Ignore.
  Settings > Security lists the browsers signed in and ends any of them. This device never
  asks. A change that can run programs or cannot be undone, such as installing an update or
  restoring a backup, asks another device for a second Confirm code, and skips it over a
  VPN, behind a proxy or on HTTPS. An authenticator app set up on the same page can give
  both codes. Themes and extensions that are not included with VPinFE stay off until you accept
  them. Traffic on your network is not encrypted, so away from home connect through a VPN.
  Set Reachable From in Settings to This Device Only to keep other devices out altogether, at
  the cost of the Manager and the Remote working from other devices.

### What's New
- **Manager** - Other devices sign in to VPinFE once, with a code shown on this machine
  or with an authenticator app. This device never asks. Settings > Security lists who is
  signed in and signs any of them out, makes tokens for scripts and other programs, and
  names the networks and proxies whose traffic is encrypted. VPinFE can serve HTTPS from a
  certificate you choose.
- **Manager** - A new interface, and the page that opens first. One place for the library,
  media, devices and settings, in grids you can sort, filter and search, with a picture
  beside each name. Column layouts are kept as views of your own. Select a row and its panel
  answers for it; select several and change them together, with one Undo for the lot.
- **Manager** - Overview is the first page: the game last played, what needs you ordered by
  what leaving it costs, the size of the library and the latest jobs. Setup asks the
  first-run questions as a desktop or as a cabinet. What's New opens once after an update
  and again from About.
- **Manager** - Drop a file, a zip or a folder on the Manager to make a game, or on a game
  to add to it, and read what will happen before anything is written. Long work runs as a
  job, so you can leave the page and read how it went in Jobs.
- **Manager** - A page address opens on the same game with the same part of its panel
  showing, so a game can be bookmarked or sent to someone. The Manager can be set to System,
  Synthwave, Dark or Light.
- **Core** - Every game gets an id, minted once and kept in its `.info`. It survives
  renaming a folder and updating a `.vpx`, which a VPS id does not. Collections hold their
  games by it, so an ordinary table update no longer drops a game out of its collections.
- **Core, Manager** - A game folder can hold several tables. A desktop table and a VR
  table, or a table and a patched variant, are peers: each launches on its own, one is the
  game's default, and any of them can be hidden so it stops being offered. Games lists one
  row per game and Tables one row per `.vpx`.
- **Core, Manager** - Import a library from PinballX, PinballY, PinUP Popper or a plain
  folder of tables. The import shows each page of what it found, asks only what it cannot
  settle, and ends with a summary of exactly what it will do. It runs as a job and keeps a
  report of what needs review afterward. Games are matched to the Virtual Pinball
  Spreadsheet, and several library folders can be kept at once.
- **Manager** - Match a game to the Virtual Pinball Spreadsheet from a picker, see how the
  match was made and go back to the earlier one. Take a game's details from the spreadsheet,
  type your own over any of them, and revert a field with a click. See which tables have a
  newer version on the spreadsheet.
- **Manager** - Collections are smart (filled by rules on letter, theme, type, manufacturer,
  year, rating, tags, favorite and played) or hand-picked, ordered and capped as you choose.
  Tags are your own words on games and tables, with rename, merge, color and a clear-out for
  the unused.
- **Manager, Core** - Media has 22 kinds, including instruction cards, toppers and topper
  videos, loading videos, launch audio, rule sheets and logos, and a game's coverage is laid
  out like the machine. Flyers and instruction cards can have several pages. Pictures and
  videos turn a quarter or a half turn with the original kept. Gaps fill from VPinMediaDB,
  from a game's backglass file, from a file of your own, or by recording the table running.
- **Manager** - Assets lists each supporting file a table needs (backglass, settings, script,
  point of view, score view layout) and what is missing or left over. A table's INI, script,
  point of view or score view layout can be edited there, with a copy kept in Backups each
  time you save. A table's script can be extracted to a `.vbs` to patch, and the community's
  script fixes can be downloaded.
- **Core** - `.dif` patches apply directly, with no external tool. The base file stays on
  disk because the patched table cannot be rebuilt without it, and VPinFE records which base
  and which patch produced the result.
- **Manager, Core** - Players: a list of the people who play, each with a name, initials and
  a picture. Say who is up and the next game counts for them. A high score finds its player
  by the initials entered at the machine, a visitor can join as a guest, and each player has
  plays, time and best scores game by game.
- **Manager** - Launchers run beside each other, each with its own program and settings, and
  can be chosen for a table. Launcher settings can be given to all tables, to one game or
  to one table, and the Manager shows which layer a value comes from.
- **Manager, Core** - Devices: installs find each other on your network and show their
  version, what they can do and what their log says. A device can be updated, restarted,
  powered off, or told to close the table it is playing from another device. Several
  mobile devices running VPX Mobile can be added manually and sent tables. A cabinet can play
  a library held on another device. Windows may ask to let VPinFE through the firewall the
  first time, and a network that filters multicast still takes an address manually.
- **Manager, Core** - Backups: VPinFE keeps a copy before it changes something it cannot
  easily undo, and System > Backups lists, restores or clears them. A backup of your whole
  setup can be taken at any time and carried to another device.
- **Manager** - Settings save as you change them, with a tag on the ones that wait for a
  restart or a reopen. Metrics shows the processor, memory, graphics card and disks of a machine, and Logs shows
  what VPinFE has been doing as a stream or as a digest that collapses repeats.
- **Frontend** - Screens are placed by dragging each one onto the part of your cabinet it
  belongs to, including a topper. Any key or controller button can be bound to an action,
  with chords and holds, and a key can take a picture of the screens during play.
- **Frontend** - The wheel pages by the groups in whatever it is sorted by: the next letter
  under title order, the next year under year order, and a fixed number where every game has
  a value of its own. The Main Menu rates the game on the wheel, chooses who is up and
  records media, and the collection menu narrows the wheel and can save the narrowing as a
  smart collection. A library on a drive or share that is not connected yet is waited for,
  and the wheel fills when it is.
- **Frontend** - VPinFE can ask before it quits or powers off the machine. It is off by
  default, which is how it has always behaved; turn on Confirm Before Exit. The
  question appears on whatever you used to ask, and every other screen is told what is about
  to happen.
- **Core** - VPinFE is localization ready. Every word it puts on screen comes from a
  translation catalog: the Manager, the cabinet's menus and overlays, the settings, the
  column headers and the messages the API sends back. English is the only language that
  ships and nothing looks any different, but adding another is a JSON file rather than a
  patch. Your library's own words, such as game names and manufacturers, are never
  translated. Titles that are not plain English sort and group as you would expect.
- **Core, Themes** - A theme declares the oldest VPinFE it runs on as `min_vpinfe` in its
  `manifest.json`. Installing one that needs a newer build than yours is refused before
  anything downloads, and the message names the version it wants. Themes install, update
  and take their options from Themes, from sources you can add and order.
- **Core** - What a theme or an overlay throws now reaches `vpinfe.log`, tagged with the
  window it came from. A browser log is not shown anywhere anyone reads on a cabinet, so a theme
  that broke looked like a frontend that had stopped answering the buttons.
- **Core** - An HTTP API at `/api/v1` with a written contract: games and tables, launch,
  media, assets, collections, uploads, VPS search and export, one error format and a
  permission scope on every endpoint. A live event stream at `/api/v1/events` replaces
  asking once a second, and the frontend listens to it for launch state. Documented in
  `docs/`.
- **Core** - Extensions add a feature without changing VPinFE, with a page of their own under
  Extensions in Settings. The Library Importer and VPinPlay, which adds community ratings
  and top lists, are extensions.

### Changes you may notice
These are deliberate. `docs/compatibility-3.0.md` has the full list with the reasoning.

- **Frontend** - A folder with several `.vpx` files may launch a different one than before.
  VPinFE now picks the file the game's metadata describes; it used to take whatever the
  filesystem listed first, so the metadata you saw could describe a different table than
  the one that started.
- **Core** - Launches from the Remote page and the API count as plays now. Start count, last
  played, runtime and NVRAM score were only ever recorded for wheel launches.
- **Core** - Settings live in `vpinfe.json`, read once from `vpinfe.ini` on the first start.
  A setting's older spelling keeps working, and the comments you wrote in the ini are not
  carried over.
- **Core** - An install is described by the features it has switched on: Library, Frontend,
  Devices and Overview, all on by default.
- **Core** - Media resolves through a precedence chain: `(Wheel) <game file>.png` over
  `(Wheel) <folder>.png` over `wheel.png`, and a `.jpg` counts where the old code only ever
  looked for one exact `.png`. Media you placed manually that was silently ignored now appears.
  Imported media keeps its real extension.
- **Core** - Your own media is protected by hash rather than by claiming it. A file already
  on disk is compared against the MD5 VPinMediaDB publishes; a match is ours, and anything
  else is left alone. `--claim-user-media` does nothing now.
- **Core** - Games whose folders are not all lowercase start reporting the PUP packs,
  colorizations, VNI and altsound they always had. The scan compared folder names exactly,
  so `PUPVideos`, the casing PinUP Popper itself writes, went undetected.
- **Core** - A game's export is one table: the chosen `.vpx`, its companions, `pinmame/`,
  `music/`, colorization and sound folders and the author's readme files. Readme and `.nfo`
  files are recognized on import and travel with the game.
- **Core** - The command line takes `--game` to name a folder. `--table` still works for a
  script that uses it.
- **Core** - A collection whose filter picked a single digit or symbol as its letter matches
  nothing now, because digits and symbols share the `#` group. Open it and save its filter
  again against `#`.
- **Core** - The log is much quieter at INFO. Routine chatter moved to DEBUG.
- **Frontend** - Page-up moves the wheel backward now, and page-down forward. The keys are
  unchanged; what they mean is. If you prefer the old feel, swap the two bindings.

### Fixes
- **Frontend** - Tables no longer start paused on Windows. VPX pauses whenever its window
  loses focus, and Windows will not let one program hand the foreground to another it
  started, so a table came up paused until you alt-tabbed. The frontend windows now get out
  of the way and come back when you are done.
- **Frontend** - Holding a direction no longer freezes the wheel.
- **Frontend** - Chromium no longer leaves a profile directory behind for every window on
  every launch. On a cabinet where `/tmp` is a tmpfs, that was RAM.
- **Core** - A `.info` is written through a temporary file and renamed into place, so an
  interrupted write cannot leave a truncated one behind.
- **Core** - One unreadable `.info` no longer stops the whole library from loading. That
  game is left out and named in the log, and its file is not touched.
- **Core** - A collection from an earlier version that filters on type keeps its type. It came
  across from `collections.ini` selecting every game.
- **Core** - Remote launch failures are logged instead of failing silently, and a remote
  launch no longer raises on Linux.

### For theme and API authors
- **Themes** - The selection surface keeps the names earlier versions published: `get_tables`,
  `launch_table`, `TableIndexUpdate`, `vpin.tableData` and the rest. A row on the wheel is a
  table, because a collection may hold two tables of one game and both are rows.
- **Themes** - Nothing changes unless you opt in. The payload is served in the shape your
  `manifest.json` declares as `contract`, and no declaration means the shape earlier versions served.
  `min_vpinfe` says the oldest VPinFE a theme runs on.
- **Themes** - Core owns the wheel's list and cursor, and the menus run on the same one, so a
  theme can open the collection picker and let core apply the choice and announce it.
  `vpin.enableCorePaging(false)` still hands paging back to you. Core takes the wheel's
  previous and next only from a theme that says it runs on 3.0; a theme that wants core
  navigation without declaring 3.0 sets `navigation.enabled` in its `theme.json`.
- **Themes** - Core's files are served at `/core/` now, against `/themes/` for what a theme
  provides. `/web/` still serves the same files, so an existing theme has nothing to change.
- **Themes** - The paging actions are `page_previous` and `page_next`, not `page_up` and
  `page_down`. A contract 1 theme still receives `joypageup` and `joypagedown`.
- **Themes** - `vpin.endpoints.player` is `vpin.endpoints.device`, and the window url
  carries `devicePort` rather than `playerPort`. It is the address of the machine a game
  launches on, as against `endpoints.library`, which is where the catalog lives. A theme that
  read the old key gets no error, so it is worth checking.
- **Core** - Breaking: `/api/v1/players` is `/api/v1/devices`, its scopes are `devices:read`
  and `devices:write`, and a capability's residency says `device` where it said `player`. A
  device is something a game can be launched on; a player is a person.
- **Core** - Breaking: the endpoints that predate `/api/v1` are removed, not aliased.
  `/api/remote-launch`, `/api/asset-upload/*` and `/api/download-table-vpxz` are gone and
  their replacements live under `/api/v1`.
- **Core** - Breaking: the WS bridge method `update_frontend_dof_for_table` is now
  `notify_table_selected`. It drove DOF and the real DMD both, so the old name was wrong.
- **Core** - The `.info` is reshaped: `VPXFile` becomes `game_files` with one entry per
  `.vpx`, `Medias` becomes `assets`, the `VPinFE` section becomes `vpinfe` with snake_case
  keys, and `Info` gives up `Rom` and `Authors` to the game file that owns them.

### Notes
Back up your library before you upgrade and keep a v2.6.0 build to hand.
