# Extensions

An extension adds a feature to an install without being part of VPinFE. It ships as a
directory, declares what it needs in a manifest, and is handed a context it reaches
everything through. It never receives the application.

The word is **extension** throughout. *Plugin* means a Visual Pinball standalone plugin,
which is a different thing with its own page.

## What one looks like

```
my-extension/
    extension.json
    __init__.py
```

The directory name is the extension's name, and the manifest has to agree: the name
addresses it in a URL, a scope, a log namespace, a config file and the Python package
core imports, so two answers to what it is called would each be right somewhere.

`__init__.py` defines `register(ctx)`. Core calls it once at startup and never again.

Two places are searched, in this order: `extensions/` under the config directory, then the
`extensions/` the build ships. An installed extension with the same name as a bundled one
answers, and the bundled one is left alone.

```python
from fastapi import APIRouter


def register(ctx):
    router = APIRouter()

    @router.get("/rating/{game_id}")
    def rating(game_id: str) -> dict:
        return {"stars": ctx.config.get("default_stars", "0")}

    ctx.add_router(router, scope=ctx.scope("read"))
    ctx.events.subscribe("game.selected", lambda **payload: ctx.logger.debug("%s", payload))
```

## The manifest

`extension.json`, snake_case like every other JSON we write.

| key | what it is |
|---|---|
| `name` | Lowercase letters, digits and `_`, starting with a letter. Matches the directory, and is the Python package core imports - so it has to be a legal module name |
| `display_name` | What to call it on screen. Defaults to `name` |
| `version` | The extension's own version. Shown, never interpreted |
| `description` | One line, shown beside it |
| `requires_platform` | The platform ABI it was built against. This build offers `1` |
| `scopes` | Core scopes it asks to use, e.g. `games:read` |
| `provides` | The actions it gates its own routes on. Core mints `ext:<name>:<action>` |
| `capabilities` | What it asks of the machine: `ui:mount`, `config:own`, `net:outbound`, `proc:spawn`, `hardware:usb`, `fs:read`, `fs:write` |
| `requires_features` | Install features it needs: `library`, `frontend`, `devices`, `overview` |
| `platforms` | `linux`, `windows`, `macos`. Empty means every one |
| `events` | Event names it publishes, without its namespace |

Everything in it is a declaration a person can be shown before installing, which is why an
unknown capability, feature or platform is refused rather than ignored: a name nobody has
heard of is not something anybody could have agreed to.

An extension whose manifest names a platform this machine is not, or a feature this
install does not have, is not loaded. It is still listed, with the reason.

## The context

`ctx` is the whole of an extension's reach. There is no way to get from it to the
application, and that is the guarantee the model rests on.

| on `ctx` | what it does |
|---|---|
| `ctx.name`, `ctx.manifest` | What this extension is and what it declared |
| `ctx.logger` | A logger in `vpinfe.ext.<name>` |
| `ctx.config` | `get`, `set`, `all` over its own settings |
| `ctx.events` | `subscribe` to a core event; `publish` one of its own |
| `ctx.scope(action)` | The scope name for one of its declared actions |
| `ctx.add_router(router, scope=...)` | Serve routes under `/api/v1/ext/<name>/` |

There is deliberately no hook seam yet. A hook can stop a core operation, and handing that
out before the isolation story for it is designed would let a broken extension stop a
launch.

Routers are collected during `register` and mounted once. One added afterwards would never
be reachable, so it is refused rather than left to answer nothing.

## Scopes and the gate

Core attaches the gate. An extension names an action it declared; core turns that into
`ext:<name>:<action>` and puts it on every route in the router. An extension cannot ship a
route without a gate, because it never attaches one.

A scope belonging to an extension is granted only while that extension is running.

## Config

Settings live in `extensions.json` in the config directory, under the extension's name.
Never `vpinfe.ini` - that file holds what core is configured with, and it is where a token
would go.

The `enabled` key in the same file is the user's switch. An extension switched off is not
loaded at all.

## Logs

`vpinfe.ext.<name>`, issued by the context. An extension never logs into a core namespace,
because the namespace is how "which extension did this?" stays answerable.

## When one breaks

Reading the manifest, importing the package and calling `register` are each somebody
else's code, and any of them failing costs one extension. Afterwards, an unhandled error
out of one of its routes, or out of a handler it subscribed, takes that extension out:

- its subscriptions are dropped, so it is told nothing more
- its scopes go with it, so nothing holds a grant into something that is not running
- its routes keep their paths and answer `501` naming the extension and the reason,
  because a `404` reads as a typo

That is for the run it happened in. It is not written down: a fault that happened once
must not take an extension away until somebody notices a setting they never set.

An error an extension raises deliberately - a `NotFoundError`, an `HTTPException` - is an
answer, not a fault, and changes nothing.

## Where the code is

- `common/extensions/contract.py` - the manifest and the shape of the context. The only
  module of ours an extension imports.
- `common/extensions/context.py` - what `register(ctx)` is handed.
- `common/extensions/host.py` - loading, the registry, and the kill switch.
- `common/extensions/store.py` - `extensions.json`.
- `httpapi/extensions.py` - the gate, the mount, and `GET /api/v1/extensions`.

`tests/fixtures/extensions/sample/` is a worked example that uses all of it.
