"""A player's VPinPlay account: a user id, chosen free and claimed deliberately, and the
key VPinPlay ties it to once it is.

An account is unclaimed while it holds a user id and no key - free to change or drop,
never sent. **Claiming** checks the id is still free, mints the key and registers the pair
with an empty send; nothing before that reaches VPinPlay. Core draws the account on each
player and asks the routes below with the player's id; the values live in this extension's
own file for a kept player, and in memory for a guest.

A refusal is a raise: core words it and shows it under the control that was pressed.
"""

from __future__ import annotations

import secrets
import string
import threading
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from . import client, sync

if TYPE_CHECKING:
    from collections.abc import Callable

    from .sending import Sender


def _on_a_thread(work: Callable[[], object]) -> None:
    threading.Thread(target=work, name="vpinplay-resolve", daemon=True).start()

USER_ID = "user_id"
KEY = "key"
CLAIMED = "claimed"
CONSENTED = "consented"
# What the account has been sent and what is waiting to go, as comma-separated game ids,
# and when a send last went. About the user id they were sent under.
SENT = "sent"
WAITING = "waiting"
LAST_SENT = "last_sent"
BOOKS = (SENT, WAITING, LAST_SENT)

# The card 2.x's Download QR Code saved. Cards are on people's phones, so this is read for
# good and never changes shape.
CARD_TYPE = "vpinplay_identity"
CARD_VERSION = 1
CARD_INITIALS_AT_MOST = 3

SEND_NOW = "send_now"
CLAIM = "claim"
CONSENT = "consent"
DISCONNECT = "disconnect"

PLAYERS_CHANGED = "players.changed"

# The settings the owner's account is made from, and the mark that it has been.
SETTINGS_USER_ID = "user_id"
SETTINGS_MACHINE_ID = "machine_id"
OWNER_ACCOUNT_MADE = "owner_account_made"


def listed(held: Any) -> list[str]:
    """Game ids as the books keep them."""
    return [one for one in str(held or "").split(",") if one.strip()]


def new_key(length: int = 64) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def page_for(site: str, user_id: str) -> str:
    return f"{site}/players.html?userid={quote(user_id)}"


def functions(ctx: Any, site: str, sender: Sender,
              endpoint: Callable[[], str]) -> dict[str, Any]:
    """What `ctx.ui.account` is handed: a function for each thing core asks of a player's
    account.

    An act answers what came of it: Send Now a message; Claim, Consent and Disconnect the
    account, as `read` does.
    """
    # Per extension load: a guest's in-memory account resolves again after a restart
    # the way a kept one does.
    resolved: dict[str, bool] = {}
    asking: set[str] = set()
    resolve_lock = threading.Lock()

    def ensure_resolved(user_id: str) -> None:
        with resolve_lock:
            if user_id in resolved or user_id in asking:
                return
            asking.add(user_id)

        def work() -> None:
            where = sync.endpoint_for(endpoint())
            try:
                available = client.check_available(where, user_id)
            except Exception:
                available = False
            with resolve_lock:
                resolved[user_id] = available
                asking.discard(user_id)

        _on_a_thread(work)

    def initials_of(player_id: str) -> str:
        return str((ctx.players.get(player_id) or {}).get("initials") or "").strip().upper()

    def card_for(player_id: str, held: dict[str, str]) -> dict | None:
        user_id, key = held.get(USER_ID, ""), held.get(KEY, "")
        initials = initials_of(player_id)
        if not (user_id and key and initials):
            return None
        return {"card": {"type": CARD_TYPE, "version": CARD_VERSION, "userId": user_id,
                         "initials": initials, "machineId": key},
                "filename": f"vpinplay-{user_id}"}

    def acts(claimed: bool, waiting: int) -> list[dict]:
        if claimed and waiting:
            return [{"key": SEND_NOW, "label": ctx.t("account.act.send_now.label")}]
        return []

    def status(claimed: bool, held: dict[str, str], waiting: int) -> str:
        if not claimed:
            return ""
        if waiting:
            return ctx.t("account.status.waiting", count=waiting)
        return sent_ago(ctx, held.get(LAST_SENT, ""))

    def claimed_of(user_id: str, key: str, held: dict[str, str]) -> bool:
        if not (user_id and key):
            return False
        if held.get(CLAIMED):
            return True
        known = resolved.get(user_id)
        if known is None:
            ensure_resolved(user_id)
            return True
        return not known

    def answer(player_id: str) -> dict:
        held = ctx.players.account(player_id)
        user_id, key = held.get(USER_ID, ""), held.get(KEY, "")
        claimed = claimed_of(user_id, key, held)
        waiting = len(listed(held.get(WAITING)))
        return {
            "fields": [],
            "user_id": user_id,
            "claimed": claimed,
            "needs_consent": not bool(held.get(CONSENTED)),
            "page": page_for(site, user_id) if claimed else "",
            "status": status(claimed, held, waiting),
            "waiting": bool(waiting),
            "waiting_count": waiting,
            "acts": acts(claimed, waiting),
            "card": card_for(player_id, held) is not None,
        }

    def card(player_id: str) -> dict | None:
        return card_for(player_id, ctx.players.account(player_id))

    def claim(player_id: str) -> dict:
        held = dict(ctx.players.account(player_id))
        user_id = held.get(USER_ID, "").strip()
        if not user_id:
            raise ValueError(ctx.t("error.no_account"))
        if held.get(KEY):
            raise ValueError(ctx.t("error.already_claimed"))
        initials = initials_of(player_id)
        if not initials:
            raise ValueError(ctx.t("error.no_initials"))
        where = sync.endpoint_for(endpoint())
        if not client.check_available(where, user_id):
            raise ValueError(ctx.t("error.taken"))
        key = new_key()
        if not client.register(where, user_id, initials, key, ctx.host_version).get("ok"):
            raise RuntimeError(ctx.t("error.claim_failed"))
        with sender.books():
            ctx.players.set_account(player_id, {USER_ID: user_id, KEY: key,
                                                CLAIMED: "true", CONSENTED: "true"})
        return answer(player_id)

    def consent(player_id: str) -> dict:
        """Marks Share's consent seen, with no send - safe to call whether or not the
        account is already claimed."""
        with sender.books():
            held = dict(ctx.players.account(player_id))
            held[CONSENTED] = "true"
            ctx.players.set_account(player_id, {k: v for k, v in held.items() if v})
        return answer(player_id)

    def disconnect(player_id: str) -> dict:
        with sender.books():
            ctx.players.set_account(player_id, {})
        return answer(player_id)

    def available(candidate: str) -> bool:
        return client.check_available(sync.endpoint_for(endpoint()),
                                      candidate.strip().lower())

    def write(player_id: str, offered: dict) -> None:
        """Saves what is chosen; claiming is its own act, never a side effect of a write."""
        with sender.books():
            held = dict(ctx.players.account(player_id))
            was = held.get(USER_ID, "")
            if USER_ID in offered:
                held[USER_ID] = str(offered[USER_ID] or "").strip().lower()
            # No write clears a key, an empty one included. A card writes both at once.
            written_key = str(offered.get(KEY) or "").strip()
            if written_key:
                held[KEY] = written_key
            elif held.get(USER_ID) and held.get(USER_ID) != was:
                held.pop(CLAIMED, None)
            kept = (USER_ID, KEY, CLAIMED, CONSENTED,
                   *(BOOKS if held.get(USER_ID) == was else ()))
            ctx.players.set_account(player_id, {key: value for key, value in held.items()
                                                if key in kept and value})
        written = ctx.players.account(player_id)
        if written.get(USER_ID) and written.get(KEY) and not written.get(CLAIMED):
            ensure_resolved(written[USER_ID])

    def send_now(player_id: str) -> str:
        held = ctx.players.account(player_id)
        if not (held.get(USER_ID) and held.get(KEY)):
            raise ValueError(ctx.t("error.no_account"))
        if not sender.waiting(player_id):
            return ctx.t("account.nothing_waiting")
        went, waiting = sender.send_now(player_id)
        if waiting:
            return ctx.t("account.status.waiting", count=waiting)
        return ctx.t("account.sent", count=went)

    def read_card(scanned: Any) -> dict:
        found = checked(ctx, scanned)
        return {"name": found["userId"], "initials": found["initials"],
                "values": {USER_ID: found["userId"], KEY: found["machineId"]}}

    resolve_unmarked(ctx, ensure_resolved)

    return {"read": answer, "write": write, "card": card, "read_card": read_card,
            "available": available,
            "acts": {CLAIM: claim, CONSENT: consent, DISCONNECT: disconnect,
                     SEND_NOW: send_now}}


def resolve_unmarked(ctx: Any, ensure_resolved: Callable[[str], None]) -> None:
    """Every held account with a key and no `claimed` marker gets the same one-time
    resolve a fresh write does."""
    for player in ctx.players.roster():
        held = ctx.players.account(str(player.get("id") or ""))
        user_id, key = held.get(USER_ID, ""), held.get(KEY, "")
        if user_id and key and not held.get(CLAIMED):
            ensure_resolved(user_id)


def sent_ago(ctx: Any, when: str) -> str:
    """When the last send went, in words; nothing where none has."""
    try:
        then = datetime.fromisoformat(str(when or "").replace("Z", "+00:00"))
    except ValueError:
        return ""
    seconds = max(0, int((datetime.now(UTC) - then).total_seconds()))
    if seconds < 60:
        return ctx.t("account.status.age_now")
    if seconds < 3600:
        return ctx.t("account.status.age_minutes", count=seconds // 60)
    if seconds < 86400:
        return ctx.t("account.status.age_hours", count=seconds // 3600)
    return ctx.t("account.status.age_days", count=seconds // 86400)


def checked(ctx: Any, card: Any) -> dict[str, Any]:
    """A card as 2.x read one: the same checks, in the same order, in 2.x's words."""
    def refused(said: str) -> ValueError:
        return ValueError(said)

    if not isinstance(card, dict):
        raise refused(ctx.t("error.card.not_an_object"))
    kind = str(card.get("type", "") or "").strip()
    user_id = str(card.get("userId", "") or "").strip()
    initials = str(card.get("initials", "") or "").strip().upper()
    machine_id = str(card.get("machineId", "") or "").strip()
    try:
        version = int(card.get("version", 0))
    except (TypeError, ValueError):
        raise refused(ctx.t("error.card.version_invalid")) from None
    if kind != CARD_TYPE:
        raise refused(ctx.t("error.card.type", kind=kind) if kind
                      else ctx.t("error.card.type_missing"))
    if version != CARD_VERSION:
        raise refused(ctx.t("error.card.version", version=version))
    if not user_id:
        raise refused(ctx.t("error.card.no_user_id"))
    if not initials:
        raise refused(ctx.t("error.card.no_initials"))
    if len(initials) > CARD_INITIALS_AT_MOST:
        raise refused(ctx.t("error.card.initials_length"))
    if not machine_id:
        raise refused(ctx.t("error.card.no_machine_id"))
    return {"type": kind, "version": version, "userId": user_id, "initials": initials,
            "machineId": machine_id}


def move_owner_account(ctx: Any) -> None:
    """Make the owner's account from this extension's own settings, once there is an
    owner, and only once."""
    lock = threading.Lock()
    settled = False

    def make(owner_id: str) -> None:
        user_id = str(ctx.config.get(SETTINGS_USER_ID, "") or "").strip()
        if not user_id:
            return
        if not ctx.players.account(owner_id):
            key = str(ctx.config.get(SETTINGS_MACHINE_ID, "") or "").strip()
            ctx.players.set_account(owner_id, {USER_ID: user_id, KEY: key or new_key()})
            ctx.logger.info("Made the owner's VPinPlay account from its settings")
        ctx.config.set(OWNER_ACCOUNT_MADE, "true")

    def move(**_payload: Any) -> None:
        nonlocal settled
        with lock:
            if settled:
                return
            try:
                if str(ctx.config.get(OWNER_ACCOUNT_MADE, "") or "").strip():
                    settled = True
                    return
                owner = next((one for one in ctx.players.roster() if one.get("owner")),
                             None)
                if owner is None:
                    return
                settled = True
                make(str(owner["id"]))
            except Exception:
                settled = True
                ctx.logger.exception("Could not make the owner's VPinPlay account; "
                                     "trying again at the next start")

    move()
    ctx.events.subscribe(PLAYERS_CHANGED, move)
