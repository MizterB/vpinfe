# Scopes and the gate

Core attaches the gate.  An extension that adds its own routes names one of two scopes and core
puts it on every route in the router.  You cannot ship a route without a gate, because you
never attach one.

| scope | gates |
|---|---|
| `ext:<name>:read` | Every `GET` core serves for the extension, and a router added with `ctx.scope("read")` |
| `ext:<name>:write` | Every `POST` and `PUT` core serves for the extension, and a router added with `ctx.scope("write")` |

A scope belonging to an extension is granted only while that extension is running.

## What `scopes` in the manifest asks for

The manifest's `scopes` are the core scopes the extension asks to use.  The extension's page
lists them in plain words for whoever installs it, and they decide which `ctx.games` and
`ctx.players` calls work.  Asking for a scope that does not exist fails the extension with
"Asks for scopes that do not exist".

| scope | lets the extension |
|---|---|
| `games:read` | Read the library through `ctx.games` |
| `games:write` | Create games, add tables and media, change details, ratings and tags through `ctx.games` |
| `games:export_full` | Export the library in full |
| `collections:read`, `collections:write` | Read, change collections through `ctx.collections` |
| `play:read`, `launch:invoke`, `play:stop` | See what is playing, start a game, stop one.  Three separate permissions |
| `uploads:write` | Upload files |
| `vps:read` | Read the VPS catalog |
| `filesystem:read` | Browse folders |
| `capture:run` | Record media |
| `config:read`, `config:write` | Read, change VPinFE's configuration |
| `system:read`, `system:admin` | Read system state, administer it.  `system:admin` is what lets `ctx.system` restart VPinFE, reboot or power off this computer |
| `events:subscribe` | Subscribe to the event stream over the API |
| `jobs:read` | Read jobs |
| `input:act` | Send input |
| `devices:read`, `devices:write` | Read, change devices |
| `preferences:read`, `preferences:write` | Read, change preferences |
| `instance:read` | Read the install's identity and the list of extensions |
| `players:read`, `players:write` | Read, change players.  `ctx.players.roster` and the calls beside it need `players:read` |
| `apps:provide` | Provide an app with `ctx.apps.provide` |

## Capabilities

A capability is what an extension asks of the machine, as opposed to of the domain.  The list
is what a person consents to, so a capability nobody has heard of cannot be consented to.

| capability | reaches |
|---|---|
| `ui:mount` | Needed for every `ctx.ui` call: settings, lists, actions, an account, what it holds |
| `config:own` | Its own settings file |
| `net:outbound` | The network.  A declaration for the person installing, and what lets a list column show a web picture; see below |
| `proc:spawn` | Starting programs.  A declaration for the person installing |
| `hardware:usb` | USB devices.  A declaration for the person installing |
| `fs:read` | `ctx.files.set_roots`: the folders core will take a path from |
| `fs:write` | Moving a file out of those folders with `ctx.games.add_table(..., move=True)` |
| `os:updates` | `ctx.os.call("updates.check")` and `ctx.os.call("updates.apply")`: looking for system updates and installing them.  Where the system ships a helper; see [`ctx.os`](context.md#ctxos) |

**Capabilities are advisory.**  An extension runs in VPinFE's process, and Python in the same
process can always open a file, open a socket or start a program.  What the declaration does is
make the extension say what it intends, show that to whoever installs it, and hold the calls
that go through `ctx` to it.  Core enforces `ui:mount`, `fs:read`, `fs:write`, `os:` areas and the scopes
where it is the one acting, and `net:outbound` where core fetches a web picture for a list
column.  It does not enforce `proc:spawn` or `hardware:usb` at all.  Once extensions run out of process, the same declarations become the boundary.
