"""Keeps another computer out of every page until a browser on it has signed in.

This computer is never asked. Another one is sent to `/signin`, a page served here by
hand: it must work with none of the Console's scripts, because those are behind this gate.
The API passes through untouched and answers by scope.
"""

from __future__ import annotations

import base64
import html
import json
import mimetypes
import posixpath
import secrets
from urllib.parse import quote

from starlette.datastructures import Headers
from starlette.requests import HTTPConnection, Request
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from common import accepted, paths, players
from common.i18n import t
from common.install_identity import display_name
from httpapi import API_PREFIX, auth

PAGE = "/signin"
PICTURE_SIZE = 96


def next_page(raw: str) -> str:
    """Where to go after signing in. Only a path on this server: anything that names another
    site would make the sign-in page a way to send someone there."""
    if raw.startswith("/") and not raw.startswith("//") and "\\" not in raw \
            and raw.isprintable():
        return raw
    return "/"


def theme_served(path: str) -> bool:
    """Whether a path under /themes/ is a theme that may run: a folder nobody accepted is
    files, and a page served from it would speak with this address's trust."""
    parts = posixpath.normpath(path).split("/")
    if len(parts) < 3 or parts[1] != "themes":
        return True
    return accepted.theme_runs(parts[2])


def admitted(connection: HTTPConnection) -> bool:
    return auth.caller_is_local(connection) or auth.session_for(connection) is not None


class SignInGate:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        path = scope["path"]
        if path == PAGE or path == API_PREFIX or path.startswith(API_PREFIX + "/"):
            await self.app(scope, receive, send)
            return
        connection = HTTPConnection(scope)
        if admitted(connection):
            if scope["type"] == "http" and not theme_served(path):
                await PlainTextResponse("", status_code=404)(scope, receive, send)
                return
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await receive()
            await send({"type": "websocket.close", "code": 1008})
            return
        await _refusal(scope)(scope, receive, send)


def _refusal(scope: Scope) -> Response:
    headers = Headers(scope=scope)
    wants_page = scope["method"] in ("GET", "HEAD") and "text/html" in headers.get("accept", "")
    if not wants_page:
        return PlainTextResponse(t("error.signin.required"), status_code=401)
    target = scope["path"] + (f"?{scope['query_string'].decode('latin-1')}"
                              if scope.get("query_string") else "")
    return RedirectResponse(f"{PAGE}?next={quote(target, safe='')}", status_code=303)


def _owner_card() -> tuple[str, str]:
    """The Owner's name and picture as a data address, either of which may be empty."""
    try:
        roster = players.get_roster()
        owner = roster.owner()
        if owner is None:
            return "", ""
        name = owner.name or owner.initials
        try:
            served = roster.picture(owner.player_id, PICTURE_SIZE)
            kind = mimetypes.guess_type(served.path.name)[0] or "image/png"
            data = base64.b64encode(served.path.read_bytes()).decode("ascii")
            return name, f"data:{kind};base64,{data}"
        except Exception:
            return name, ""
    except Exception:
        return "", ""


def sign_in_page(request: Request) -> Response:
    if auth.caller_is_local(request) or auth.session_for(request) is not None:
        return RedirectResponse(next_page(request.query_params.get("next", "/")),
                                status_code=303)
    device = display_name(paths.get_ini_config())
    name, picture = _owner_card()
    nonce = secrets.token_urlsafe(16)
    words = {key: t(f"signin.page.{key}", device=device) for key in (
        "get_code", "look", "code", "submit", "cant_see", "cant_see_body", "failed")}
    heading = t("signin.page.title", device=device)
    owner = ""
    if picture:
        owner += f'<img class="owner" src="{html.escape(picture)}" alt="">'
    if name:
        owner += f'<p class="name">{html.escape(name)}</p>'
    body = _PAGE.format(
        lang=html.escape(_language()), heading=html.escape(heading), owner=owner,
        line=html.escape(t("signin.page.line", device=device)),
        get_code=html.escape(words["get_code"]), code=html.escape(words["code"]),
        submit=html.escape(words["submit"]), cant_see=html.escape(words["cant_see"]),
        cant_see_body=html.escape(words["cant_see_body"]), nonce=nonce,
        words=_script_value({"look": words["look"], "failed": words["failed"]}),
        next=_script_value(next_page(request.query_params.get("next", "/"))),
        api=_script_value(API_PREFIX))
    return HTMLResponse(body, headers={
        "Content-Security-Policy": (
            f"default-src 'none'; style-src 'nonce-{nonce}'; script-src 'nonce-{nonce}'; "
            "img-src data:; connect-src 'self'; form-action 'none'; base-uri 'none'; "
            "frame-ancestors 'none'"),
        "X-Frame-Options": "DENY", "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer"})


def _script_value(value: object) -> str:
    """JSON that is safe inside a script element: no `</script>` can end it early."""
    return json.dumps(value).replace("<", "\\u003c")


def _language() -> str:
    from common import i18n
    return i18n.language() or "en"


_PAGE = """<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{heading}</title>
<style nonce="{nonce}">
:root {{ color-scheme: light dark; --bg:#f4f5f7; --fg:#15171b; --dim:#5b6270; --line:#c9ced8;
  --accent:#0a7c91; --bad:#b3261e; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#101216; --fg:#e8eaee; --dim:#9aa2b1;
  --line:#2c313b; --accent:#3cc4dd; --bad:#ff8a80; }} }}
body {{ margin:0; min-height:100vh; display:grid; place-items:center; background:var(--bg);
  color:var(--fg); font:16px/1.5 system-ui, sans-serif; }}
main {{ width:min(24rem, 100% - 2rem); padding:2rem 0; }}
h1 {{ margin:0 0 .25rem; font-size:1.4rem; color:var(--accent); }}
.owner {{ width:4rem; height:4rem; border-radius:50%; object-fit:cover; margin:.5rem 0 0; }}
.name {{ margin:.25rem 0 0; font-weight:600; }}
p {{ margin:.75rem 0; color:var(--dim); }}
button, input {{ font:inherit; padding:.7rem 1rem; border-radius:.5rem;
  border:1px solid var(--line); background:transparent; color:var(--fg); width:100%;
  box-sizing:border-box; }}
button {{ background:var(--accent); border-color:var(--accent); color:#fff; cursor:pointer; }}
button:disabled {{ opacity:.5; cursor:default; }}
input {{ letter-spacing:.4em; text-align:center; font-size:1.4rem; margin-bottom:.75rem; }}
.error {{ color:var(--bad); min-height:1.5em; }}
details {{ margin-top:1.5rem; color:var(--dim); }} summary {{ cursor:pointer; }}
[hidden] {{ display:none !important; }}
</style></head><body><main>
<h1>{heading}</h1>
{owner}
<p>{line}</p>
<button id="ask" type="button">{get_code}</button>
<form id="enter" hidden>
<p id="look"></p>
<input id="code" inputmode="numeric" autocomplete="one-time-code" maxlength="6"
 pattern="[0-9]*" aria-label="{code}" placeholder="{code}">
<button id="send" type="submit">{submit}</button>
</form>
<p class="error" id="error" role="alert"></p>
<details><summary>{cant_see}</summary><p>{cant_see_body}</p></details>
</main>
<script nonce="{nonce}">
const words = {words}, after = {next}, api = {api};
const $ = id => document.getElementById(id);
let request = "";
async function call(path, body) {{
  const answer = await fetch(api + path, {{method: "POST", credentials: "same-origin",
    headers: {{"Content-Type": "application/json"}}, body: body ? JSON.stringify(body) : null}});
  const data = await answer.json().catch(() => ({{}}));
  if (!answer.ok) {{
    const error = new Error((data.error && data.error.message) || words.failed);
    error.reason = data.error && data.error.details && data.error.details.reason;
    throw error;
  }}
  return data;
}}
$("ask").addEventListener("click", async () => {{
  $("error").textContent = "";
  try {{
    request = (await call("/auth/code")).request_id;
    $("ask").hidden = true; $("enter").hidden = false; $("look").textContent = words.look;
    $("code").focus();
  }} catch (e) {{ $("error").textContent = e.message; }}
}});
$("enter").addEventListener("submit", async event => {{
  event.preventDefault();
  $("error").textContent = "";
  try {{
    await call("/auth/session", {{request_id: request, code: $("code").value}});
    location.replace(after);
  }} catch (e) {{
    $("error").textContent = e.message; $("code").value = ""; $("code").focus();
    if (e.reason === "no_code" || e.reason === "used_up") {{
      $("enter").hidden = true; $("ask").hidden = false;
    }}
  }}
}});
</script></body></html>
"""
