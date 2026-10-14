# Words

An extension keeps what it says in `i18n/en.json` beside its code, and a translation is the
same file under the language's name, `i18n/de.json`. The file is served under
`ext.<name>.`, so an extension adds words and never changes one of core's. Keys are flat
strings with dots in them.

| key | names | falls back to |
|---|---|---|
| `name`, `description` | The extension, where the manifest leaves them out | The extension's `name`; nothing |
| `settings.label`, `state.label` | The heading over its settings and over what it holds | The Console's own |
| `settings.<key>.label` | A setting | The key |
| `settings.<key>.help` | A line under the setting; `{default}` is its default | Nothing |
| `settings.<key>.choice.<value>` | A select option | The label given in `choices` |
| `list.<key>.title` | A list's title | The key |
| `list.<key>.column.<field>.header` | A column's header | The field |
| `list.<key>.column.<field>.help` | A column's tooltip | Its header |
| `list.<key>.view.<viewkey>.name` | A view's name | The view's key |
| `list.<key>.view.<viewkey>.help` | A view's tooltip | Nothing |
| `list.<key>.act.<act>.label` | An act in a list's title menu | The act's key |
| `action.<key>.label`, `action.<key>.description` | An action | The key; nothing |
| `action.<key>.result.<field>` | A count a run reports, beside the number | The field |
| `account.label` | The heading over a player's account with it | The extension's name |
| `account.share.help` | What its account's Share makes of what is played, under the switch | The Console's own naming |
| `token.<name>.says` | What a name a command can use stands for | A name with none is refused |
| `app.<id>.name`, `app.<id>.field.<key>.label`, `app.<id>.field.<key>.description` | An app it provides | Core's words for a field it does not name |

Anything else is its own to ask for with `ctx.t("wizard.title")`, and `contract.words(name)`
is the same for a module that is not handed `ctx`. A key the file does not have answers the
full key, `ext.<name>.<key>`, so a gap is visible.

A column with no `help` gets its header as its tooltip, so declare one: it is what the person
hovering the header reads. A word handed over in code, `title="VPinPlay"`, is shown as
written in every language, which is for a product name.

**Slots.** `{name}` in a value is filled from the call's keyword arguments with
`format_map`. **Plurals.** A value that is an object `{"one": "...", "other": "..."}` is
chosen by the `count` argument: `ja`, `zh`, `ko`, `vi` and `th` always use `other`.

```json
{"sent": {"one": "{count} score sent", "other": "{count} scores sent"}}
```

`scripts/i18n.py` reads a bundled extension's file along with core's, and `--record` and
`--pseudo` write its hashes and pseudo-locale. The invariants hold a bundled one's file to
what its code asks for, both ways, and to the rules under "Type" in `docs/conventions.md`,
and fail on a sentence written anywhere in its code outside a docstring, a log line, a query
or a builtin exception. What a `ValueError` says reaches a log and nobody else; what a
setting's `check` or a function core calls raises is read by a person, so it comes from
`ctx.t`, or from `ctx.why` when it is the reason something failed.

**A failure with its reason.** A note or a row's error carries a reason the same way:
`{"text": ctx.t(...), "detail": ctx.why(exc)}`.
