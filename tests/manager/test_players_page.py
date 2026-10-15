"""Frontend › Players: what each row and the panel say, which acts a player is offered, and
where the page sits and is addressed."""

from __future__ import annotations

import asyncio
import json
import unittest
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import requests
from nicegui import ui

from common import install_identity
from common.i18n import t
from manager import deeplink, grid, page, panel, players, thumbnails, workbench
from manager.api import ApiClient

OWNER = {"id": "p-own", "name": "", "initials": "OWN", "owner": True, "guest": False,
         "up": True, "shares_initials_with": []}


def _player(player_id: str, **more: Any) -> dict[str, Any]:
    return {"id": player_id, "name": "", "initials": "", "owner": False, "guest": False,
            "up": False, "shares_initials_with": [], **more}


class TheRows(unittest.TestCase):
    def test_a_household_of_one_shows_no_up(self) -> None:
        self.assertEqual([row["up"] for row in players.rows([OWNER])], [False])

    def test_up_is_marked_once_someone_else_plays_here(self) -> None:
        made = players.rows([OWNER, _player("p-jor", name="Jordan", initials="ABC")])
        self.assertEqual([row["up"] for row in made], [True, False])

    def test_chips_mark_the_owner_and_guests_and_nobody_else(self) -> None:
        made = players.rows([OWNER, _player("p-jor", name="Jordan"),
                             _player("p-vis", initials="XYZ", guest=True)])
        self.assertEqual([row["kind"] for row in made],
                         [players.OWNER, "", players.GUEST])

    def test_a_name_falls_back_to_initials_and_then_says_there_is_none(self) -> None:
        self.assertEqual([players.shown_name(one) for one in (
            _player("a", name=" Jordan "), _player("b", initials="XYZ"), _player("c"))],
            ["Jordan", "XYZ", t("manager.players.no_name")])

    def test_shared_initials_name_the_other_player_on_both_rows(self) -> None:
        kept = _player("p-jor", name="Jordan", initials="XYZ",
                       shares_initials_with=["p-vis"])
        guest = _player("p-vis", initials="XYZ", guest=True, up=True,
                        shares_initials_with=["p-jor"])
        made = players.rows([OWNER, kept, guest])
        self.assertEqual([row["shared"] for row in made], [
            "", t("manager.players.initials_clash", player="XYZ"),
            t("manager.players.initials_clash", player="Jordan")])

    def test_several_sharing_are_all_named(self) -> None:
        one = _player("a", initials="XYZ", shares_initials_with=["b", "c"])
        said = players.same_initials(one, [one, _player("b", name="Sam", initials="XYZ"),
                                           _player("c", initials="XYZ")])
        self.assertIn("Sam", said)
        self.assertIn("XYZ", said)

    def test_a_guest_row_counts_the_games_played_this_session(self) -> None:
        guest = _player("p-vis", initials="XYZ", guest=True, up=True)
        kept = _player("p-jor", name="Jordan")
        made = players.rows([OWNER, kept, guest], {"p-vis": 3, "p-jor": 5})
        self.assertEqual([row["session"] for row in made],
                         ["", "", t("manager.players.session_total", count=3)])

    def test_a_guest_with_no_games_yet_says_nothing(self) -> None:
        guest = _player("p-vis", initials="XYZ", guest=True)
        self.assertEqual(players.rows([OWNER, guest], {"p-vis": 0})[1]["session"], "")

    def test_games_played_adds_every_game_s_plays(self) -> None:
        self.assertEqual(players.games_played([{"play_count": 2}, {"play_count": 1},
                                               {"rating": 4}]), 3)


class ThePicture(unittest.TestCase):
    def test_a_row_addresses_the_picture_at_list_size_with_its_version(self) -> None:
        kept = _player("p-jor", name="Jordan", picture_version="abc123")
        made = players.rows([OWNER, kept])
        self.assertEqual([row["picture"] for row in made],
                         ["", "/api/v1/players/p-jor/picture?size=256&v=abc123"])

    def test_the_panel_asks_for_the_larger_size(self) -> None:
        kept = _player("p-jor", picture_version="abc123")
        self.assertEqual(players.picture_address(kept, 1024),
                         "/api/v1/players/p-jor/picture?size=1024&v=abc123")

    def test_an_id_that_needs_quoting_is_quoted(self) -> None:
        self.assertIn("/players/a%2Fb/picture",
                      players.picture_address(_player("a/b", picture_version="v1")))


class TheCircleInTheGrid(unittest.TestCase):
    """A row's circle is drawn at the height the lists are set to, as the other grids' art is."""

    def _look(self, **chosen: str) -> thumbnails.Look:
        with patch.object(thumbnails, "cfg_get",
                          side_effect=lambda _config, _section, key, *_: chosen.get(key, "")):
            return thumbnails.person_look()

    def test_it_takes_the_height_the_lists_are_set_to(self) -> None:
        sized = {height: grid.with_art(players.COLUMNS, self._look(thumbnail_height=height))
                 for height in ("small", "medium", "large")}

        self.assertEqual({height: grid.base_row_px(columns) for height, columns in sized.items()},
                         {"small": 56, "medium": 64, "large": 88})

    def test_it_is_a_circle_whatever_shape_the_lists_draw(self) -> None:
        for shape in ("auto", "square", "wide"):
            with self.subTest(shape=shape):
                self.assertEqual(self._look(thumbnail_shape=shape).shape, thumbnails.SQUARE)

    def test_it_keeps_its_ground_when_the_lists_are_unframed(self) -> None:
        with patch.object(thumbnails, "cfg_bool", return_value=False):
            self.assertTrue(thumbnails.person_look().framed)

    def test_a_blank_setting_reads_as_the_default_height(self) -> None:
        self.assertEqual(self._look(thumbnail_height="").height, thumbnails.SMALL)


class TheDetails(unittest.TestCase):
    def test_the_picture_comes_after_the_fields(self) -> None:
        roster = [OWNER, _player("p-jor", name="Jordan", initials="JOR")]
        context = {"library": Mock(), "player": roster[1], "roster": roster}

        holder = ui.card()

        async def inside() -> None:
            with holder:
                await players.details(context)

        with patch.object(panel, "facts") as facts:
            asyncio.run(inside())

        drawn = [label for label, _draw in facts.call_args.args[1]]
        self.assertEqual(drawn, [t("word.name"), t("manager.players.initials"),
                                 t("manager.players.up"), t("manager.players.picture")])


class WhatCanBeDone(unittest.TestCase):
    def acts(self, player: dict[str, Any]) -> list:
        return players.acts(object(), {}, [player], lambda: None)  # type: ignore[arg-type]

    def test_the_owner_s_remove_is_offered_and_refused_with_why(self) -> None:
        (verb,) = self.acts(OWNER)
        self.assertEqual((verb.label, verb.run, verb.danger, verb.hint),
                         (t("word.remove"), None, True,
                          t("error.players.owner_not_removable")))

    def test_a_kept_player_can_be_removed(self) -> None:
        (verb,) = self.acts(_player("p-jor", name="Jordan"))
        self.assertEqual(verb.label, t("word.remove"))
        self.assertIsNotNone(verb.run)

    def test_a_guest_signs_out(self) -> None:
        (verb,) = self.acts(_player("p-vis", guest=True))
        self.assertEqual((verb.label, verb.danger), (t("manager.players.sign_out"), True))

    def test_an_account_is_offered_the_verb_its_state_allows(self) -> None:
        async def after() -> None:
            return None

        accounts: list[dict[str, Any]] = [
            {"extension": "vpinplay", "label": "VPinPlay", "user_id": "u-1", "claimed": True},
            {"extension": "other", "label": "Other", "user_id": "u-2", "claimed": False},
            {"extension": "bare", "label": "Bare", "user_id": ""},
            {"extension": "broken", "label": "Broken", "user_id": "u-3", "error": "down"},
        ]
        made = players.acts(object(), {}, [_player("p-jor")], lambda: None,  # type: ignore[arg-type]
                            accounts={"p-jor": accounts}, after=after)
        self.assertEqual([(one.label, one.danger) for one in made], [
            (t("manager.players.menu_disconnect", service="VPinPlay"), True),
            (t("manager.players.menu_remove_id", service="Other"), True),
            (t("word.remove"), True)])

    def test_without_a_way_to_redraw_only_the_player_is_offered(self) -> None:
        made = players.acts(object(), {}, [_player("p-jor")], lambda: None,  # type: ignore[arg-type]
                            accounts={"p-jor": [{"extension": "vpinplay", "user_id": "u-1",
                                            "claimed": True}]})
        self.assertEqual([one.label for one in made], [t("word.remove")])

    def test_removing_says_what_goes_and_offers_the_card_where_there_is_one(self) -> None:
        self.assertEqual(players.removal_detail(None), [t("manager.players.remove_detail")])
        self.assertEqual(players.removal_detail({"extension": "vpinplay",
                                                 "label": "VPinPlay"}),
                         [t("manager.players.remove_detail"),
                          t("manager.players.remove_card_detail", service="VPinPlay")])


class AnAccountThatIsOnlyFields(unittest.TestCase):
    """An extension that keeps a few values per player and no id: each is drawn as a
    setting is, and saved to that player's account under its own key."""

    def _rows(self, library: Mock, rebuild: AsyncMock, fields: list[dict[str, Any]]):
        drawn: list[tuple[dict[str, Any], Any]] = []

        def control(_client: Any, field: dict[str, Any], save: Any) -> Any:
            drawn.append((field, save))
            return lambda: None

        context = {"library": library, "player": _player("p-jor"), "rebuild": rebuild}
        for target, name, replacement in ((players.ext_page, "control", control),
                                          (players, "on_page", lambda handler: handler)):
            patcher = patch.object(target, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)
        rows = players._field_rows(context, {"extension": "scores"}, fields)
        return rows, drawn

    def test_each_field_is_a_row_under_its_label_with_its_help_after_it(self) -> None:
        rows, drawn = self._rows(Mock(), AsyncMock(), [
            {"key": "handle", "label": "Handle", "help": "Shown on the board"},
            {"key": "key"}])

        self.assertEqual([one[0] for one in rows if isinstance(one, tuple) and len(one) == 2
                          and isinstance(one[0], str)], ["Handle", "key"])
        self.assertEqual([field["key"] for field, _ in drawn], ["handle", "key"])

    def test_saving_a_field_writes_it_to_that_players_account_and_redraws(self) -> None:
        library, rebuild = Mock(), AsyncMock()
        library.put_account.return_value = {"fields": []}
        _, drawn = self._rows(library, rebuild, [{"key": "handle"}, {"key": "token"}])

        asyncio.run(drawn[1][1]("abc"))

        library.put_account.assert_called_once_with("p-jor", "scores", {"token": "abc"})
        rebuild.assert_awaited_once()

    def test_a_refusal_comes_back_for_the_box_to_show(self) -> None:
        library, rebuild = Mock(), AsyncMock()
        library.put_account.side_effect = RuntimeError("That handle is taken")
        _, drawn = self._rows(library, rebuild, [{"key": "handle"}])

        said = asyncio.run(drawn[0][1]("x", under=True))

        self.assertIn("That handle is taken", said)


class ThePanel(unittest.TestCase):
    def test_the_header_says_what_the_player_is(self) -> None:
        self.assertEqual([players.kind_word(one) for one in (
            OWNER, _player("a"), _player("b", guest=True))],
            [t("manager.players.owner"), t("manager.players.player"),
             t("manager.players.guest")])

    def test_a_player_s_rail_lands_on_details(self) -> None:
        self.assertEqual(workbench.chosen_section({}, "player"), "player_details")

    def test_the_owner_has_no_plays_section(self) -> None:
        plays = next(one for one in workbench.sections_for("player")
                     if one.key == "player_plays")
        assert plays.shown is not None
        self.assertEqual([plays.shown({"player": one}) for one in (
            OWNER, _player("a"), _player("b", guest=True))], [False, True, True])

    def test_an_account_is_a_section_named_for_its_service(self) -> None:
        key, label, _build = players.account_section(
            {"extension": "vpinplay", "label": "VPinPlay"})
        self.assertEqual((key, label({})), ("player_account_vpinplay", "VPinPlay"))

    def test_share_says_what_the_extension_says_it_does(self) -> None:
        self.assertEqual(players.share_help({"extension": "vpinplay", "label": "VPinPlay",
                                             "share_help": "Makes it public"}),
                         "Makes it public")

    def test_share_says_core_s_words_where_the_extension_says_none(self) -> None:
        self.assertEqual(players.share_help({"extension": "site", "label": "Site"}),
                         t("manager.players.share.help", service="Site"))

    def test_a_card_is_saved_as_an_svg_named_for_the_service_and_the_user_id(self) -> None:
        self.assertEqual([players.card_filename(account) for account in (
            {"extension": "vpinplay", "user_id": "player-one"},
            {"extension": "vpinplay", "user_id": ""})],
            ["vpinplay-player-one.svg", "vpinplay-card.svg"])


class ThePlays(unittest.TestCase):
    def test_count_time_and_when_then_the_best_score(self) -> None:
        said = players.played_line({"play_count": 3, "play_time_seconds": 1500,
                                    "last_played": "2026-09-01T20:00:00+00:00",
                                    "best_score": {"score": 1234560, "text": "1,234,560",
                                                   "prefix": "", "suffix": ""}})
        self.assertTrue(said.startswith("3 plays · 25 min · "))
        self.assertTrue(said.endswith(" · Best 1,234,560"))

    def test_a_score_made_without_being_up_stands_alone(self) -> None:
        self.assertEqual(players.played_line({"play_count": 0, "best_score": {
            "score": 500, "text": "500", "prefix": "", "suffix": ""}}), "Best 500")

    def test_a_game_only_rated_is_not_a_play(self) -> None:
        self.assertEqual(players.played_line({"play_count": 0, "rating": 4,
                                              "best_score": None}), "")


class WhereItSits(unittest.TestCase):
    def test_players_leads_the_frontend(self) -> None:
        groups = dict(page.nav_for(install_identity.FEATURES))
        self.assertEqual([key for key, *_rest in groups[page.NAV_FRONTEND]][0], "players")

    def test_an_install_without_the_frontend_has_no_players(self) -> None:
        keys = [key for _parent, items in page.nav_for([install_identity.LIBRARY])
                for key, *_rest in items]
        self.assertNotIn("players", keys)

    def test_the_address_names_the_player_on_players_only(self) -> None:
        state = {"view": "players", "player": "p-jor", "launcher": "l-1"}
        self.assertEqual(deeplink.query(state), "view=players&player=p-jor")
        self.assertEqual(deeplink.query({**state, "view": "games"}), "view=games")

    def test_an_address_names_the_player_to_open(self) -> None:
        state: dict[str, Any] = {"view": "games"}
        deeplink.apply(state, {"view": "players", "player": " p-jor "},
                       views=["games", "players"], sections=[])
        self.assertEqual((state["view"], state["player"]), ("players", "p-jor"))

    def test_leaving_the_page_drops_the_player(self) -> None:
        state = {"view": "players", "player": "p-jor"}
        with patch.object(page.remembered, "put"):
            page.leave_for(state, "games")
        self.assertIsNone(state["player"])


class TheClient(unittest.TestCase):
    """Each call goes to the route that does it, with the id made safe for a path."""

    def asked(self, call: Any) -> tuple[str, str, Any]:
        seen: list[tuple[str, str, Any]] = []

        def answer(_session: Any, method: str, url: str, **kwargs: Any) -> Any:
            seen.append((method, url.split("/api/v1", 1)[1], kwargs.get("json")))
            response = requests.Response()
            response.status_code = 200
            response._content = json.dumps({"players": [], "accounts": [], "games": []}) \
                .encode()
            return response

        with patch.object(requests.Session, "request", answer):
            call(ApiClient("http://127.0.0.1:1"))
        return seen[0]

    def test_each_route(self) -> None:
        cases = [
            (lambda c: c.add_player("Jordan", "ABC"),
             ("POST", "/players", {"name": "Jordan", "initials": "ABC"})),
            (lambda c: c.add_guest("XYZ"), ("POST", "/players/guests", {"initials": "XYZ"})),
            (lambda c: c.add_guest_from_card("{}"),
             ("POST", "/players/guests/card", {"card": "{}"})),
            (lambda c: c.change_player("a/b", initials="XYZ"),
             ("PATCH", "/players/a%2Fb", {"initials": "XYZ"})),
            (lambda c: c.remove_player("p-1"), ("DELETE", "/players/p-1", None)),
            (lambda c: c.set_player_up("p-1", True), ("PUT", "/players/p-1/up", {"up": True})),
            (lambda c: c.put_account("p-1", "vpinplay", {"user_id": "u"}),
             ("PUT", "/players/p-1/accounts/vpinplay", {"values": {"user_id": "u"}})),
            (lambda c: c.put_share("p-1", "vpinplay", False),
             ("PUT", "/players/p-1/accounts/vpinplay/share", {"share": False})),
            (lambda c: c.use_card("p-1", "vpinplay", "{}"),
             ("POST", "/players/p-1/accounts/vpinplay/card", {"card": "{}"})),
            (lambda c: c.account_act("p-1", "vpinplay", "claim"),
             ("POST", "/players/p-1/accounts/vpinplay/acts/claim", {})),
            (lambda c: c.player_card("p-1", "vpinplay"),
             ("GET", "/players/p-1/accounts/vpinplay/card", None)),
            (lambda c: c.use_account_picture("p-1", "vpinplay"),
             ("POST", "/players/p-1/accounts/vpinplay/picture", {})),
            (lambda c: c.set_player_picture("a/b", "me.png", b"x"),
             ("PUT", "/players/a%2Fb/picture", None)),
            (lambda c: c.clear_player_picture("p-1"), ("DELETE", "/players/p-1/picture", None)),
            (lambda c: c.player_picture_bytes("p-1"), ("GET", "/players/p-1/picture", None)),
            (lambda c: c.account_available("vpinplay", "/available", "jordan"),
             ("GET", "/ext/vpinplay/available?candidate=jordan", None)),
        ]
        for call, wanted in cases:
            with self.subTest(wanted[1]):
                self.assertEqual(self.asked(call), wanted)


class ChoosingAUserId(unittest.TestCase):
    def test_the_id_field_is_left_as_typed(self) -> None:
        """The id is a handle, so a mobile keyboard may not capitalize or correct it."""
        holder = ui.card()
        fields: list[ui.input] = []
        real_field = players.frame.field

        def kept(*args: Any, **kwargs: Any) -> ui.input:
            fields.append(real_field(*args, **kwargs))
            return fields[-1]

        async def asked() -> None:
            account = {"extension": "vpinplay", "label": "VPinPlay", "check": "", "user_id": ""}
            context = {"library": Mock(), "rebuild": AsyncMock()}
            with holder:
                task = asyncio.ensure_future(players.choose_user_id(context, account))
                await asyncio.sleep(0)
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        with patch.object(players, "_of", return_value=_player("p-1")), \
                patch.object(players.frame, "field", kept), \
                patch.object(players.frame, "enter_presses"):
            asyncio.run(asked())

        (field,) = fields
        self.assertEqual({key: field.props.get(key) for key in (
            "spellcheck", "autocorrect", "autocapitalize", "autocomplete")},
            {"spellcheck": "false", "autocorrect": "off", "autocapitalize": "off",
             "autocomplete": "off"})


if __name__ == "__main__":
    unittest.main()
