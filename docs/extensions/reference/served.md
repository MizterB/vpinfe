# What core serves

Core serves everything you declare through `ctx.ui` under `/api/v1/ext/<name>`, each route
behind a check that the extension is running.  `GET` needs `ext:<name>:read`, and `POST` and
`PUT` need `ext:<name>:write`.  A request for something the extension did not declare gets a
`404`.  A request for an extension that is not running gets a `501` that names the extension
and says why.

| route | answers |
|---|---|
| `GET /settings` | `{"fields": [...]}`: each `{key, type, label, help, value}`; a secret has `set` instead of `value`; a select has `choices`; a string has `placeholder` |
| `PUT /settings` | Body `{"values": {...}}`.  Saves, answers as `GET` does.  A refusal is a `400` with the field |
| `GET /lists/{key}` | `{"rows": [...]}` |
| `GET /pictures/{id}` | A picture one of this extension's list rows named, at list size, as an image.  The rows carry the address; a `404` for anything no row named |
| `GET /lists/{key}/about` | `{"status": ..., "acts": [{key, label[, url][, action]}]}` |
| `POST /lists/{key}/about/acts/{act}` | `{"message"?, "url"?}` |
| `POST /lists/{key}/verbs/{verb}` | Body `{"ids": [...]}`.  `{"message"?, "url"?}` |
| `GET /groups/game/{game_id}` | `{"title", "section"}`: the group's section, or `null` for a game marked Private or a group with nothing in it |
| `GET /groups/table/{game_id}/{table_id}` | As the game's, for one table |
| `PUT /groups/game/{game_id}` | Body `{"values": {...}}`.  Saves, answers as `GET` does.  A `404` for a game marked Private.  Likewise `PUT /groups/table/{game_id}/{table_id}` |
| `GET /actions/{key}?step=&rows=` | A step answer.  `rows` repeats once for each row a verb opened the dialog over |
| `POST /actions/{key}/check` | Body `{values, step}`.  A step answer |
| `POST /actions/{key}/act` | Body `{act, values, step}`.  A step answer |
| `POST /actions/{key}/run` | Body `{values, step}`.  The outcome, or `202` with `{"job_id": ...}` |
| `GET /actions/{key}/progress` | `{stage, message, done, total}` |
| `POST /jobs/{kind}/stop` | `{"stopped": bool}` |
| `GET /accounts/{player_id}` | The account, as `read` answers |
| `PUT /accounts/{player_id}` | Body `{"values": {...}}`.  As `GET` |
| `POST /accounts/{player_id}/acts/{act}` | `{"message"?, "url"?}`, or the account |
| `GET /accounts/{player_id}/card` | `{"card": {...}, "filename"}`, or `404` while there is none |
| `POST /accounts/cards` | Body `{"card": {...}}`.  `{name, initials, values}` |
| `GET /available?candidate=` | `{"available": bool}` |

Outside `/ext/`, core serves the parts of a player's account that are core's:
`POST /api/v1/players/guests/card`, `POST /api/v1/players/{id}/accounts/{extension}/card` and
`POST /api/v1/players/{id}/accounts/{extension}/picture` (which asks the extension's own
`GET /accounts/{player_id}/picture` route).

Every answer under `/ext/`, from a route core wrote or one of the extension's own, carries
`Content-Security-Policy: sandbox allow-scripts allow-forms` and `X-Content-Type-Options:
nosniff`.  A page one of them serves, such as the "you can close this window" a site's sign-in
sends the browser back to, still shows and still runs its script.  It runs as no origin, so it
cannot read the Console's cookie or storage, and what it requests carries no sign-in.  Serve a
UI of your own from another site or a port of its own, and reach it with
[`ctx.ui.link`](ui.md#ctxuilink).

Core takes the secrets out of a response from any route under `/ext/` on the way to the
client, whether core or the extension wrote it.  An extension's own routes are mounted at
`/api/v1/ext/<name>` too, behind the same running check and the scope given to `ctx.add_router`.
