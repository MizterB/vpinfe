# What core serves

Everything declared through `ctx.ui` is served by core under `/api/v1/ext/<name>`, each
route behind a check that the extension is running. `GET` needs `ext:<name>:read`, and `POST`
and `PUT` need `ext:<name>:write`. A request for something the extension did not declare is a
`404`; one for an extension that is not running is a `501` naming the extension and why.

| route | answers |
|---|---|
| `GET /settings` | `{"fields": [...]}`: each `{key, type, label, help, value}`; a secret has `set` instead of `value`; a select has `choices`; a string has `placeholder` |
| `PUT /settings` | Body `{"values": {...}}`. Saves, answers as `GET` does. A refusal is a `400` with the field |
| `GET /lists/{key}` | `{"rows": [...]}` |
| `GET /lists/{key}/about` | `{"status": ..., "acts": [{key, label[, url]}]}` |
| `POST /lists/{key}/about/acts/{act}` | `{"message"?, "url"?}` |
| `POST /lists/{key}/verbs/{verb}` | Body `{"ids": [...]}`. `{"message"?, "url"?}` |
| `GET /actions/{key}?step=` | A step answer |
| `POST /actions/{key}/check` | Body `{values, step}`. A step answer |
| `POST /actions/{key}/act` | Body `{act, values, step}`. A step answer |
| `POST /actions/{key}/run` | Body `{values, step}`. The outcome, or `202` with `{"job_id": ...}` |
| `GET /actions/{key}/progress` | `{stage, message, done, total}` |
| `POST /jobs/{kind}/stop` | `{"stopped": bool}` |
| `GET /accounts/{player_id}` | The account, as `read` answers |
| `PUT /accounts/{player_id}` | Body `{"values": {...}}`. As `GET` |
| `POST /accounts/{player_id}/acts/{act}` | `{"message"?, "url"?}`, or the account |
| `GET /accounts/{player_id}/card` | `{"card": {...}, "filename"}`, or `404` while there is none |
| `POST /accounts/cards` | Body `{"card": {...}}`. `{name, initials, values}` |
| `GET /available?candidate=` | `{"available": bool}` |

Outside `/ext/`, core serves the parts of a player's account that are core's:
`POST /api/v1/players/guests/card`, `POST /api/v1/players/{id}/accounts/{extension}/card` and
`POST /api/v1/players/{id}/accounts/{extension}/picture` (which asks the extension's own
`GET /accounts/{player_id}/picture` route).

A response from any route under `/ext/` has its secrets taken out on the way to the client,
whether core or the extension wrote it. An extension's own routes are mounted at `/api/v1/ext/<name>`
too, behind the same running check and the scope given to `ctx.add_router`.
