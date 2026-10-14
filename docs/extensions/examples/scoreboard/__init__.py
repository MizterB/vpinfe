import json
import urllib.error
import urllib.request

from common.extensions.contract import Unavailable


class PostScore:
    def __init__(self, ctx, call):
        self.ctx = ctx
        self.call = call

    def ask(self, step):
        return {"title": self.ctx.t("dialog.title"),
                "fields": [
                    {"key": "player", "label": self.ctx.t("dialog.player"), "type": "string"},
                    {"key": "table", "label": self.ctx.t("dialog.table"), "type": "string"},
                    {"key": "score", "label": self.ctx.t("dialog.points"), "type": "number"}]}

    def check(self, values, step):
        needed = self.ctx.t("dialog.needed")
        errors = {key: needed for key in ("player", "table")
                  if not str(values.get(key) or "").strip()}
        if int(values.get("score") or 0) <= 0:
            errors["score"] = needed
        if errors:
            return {**self.ask(step), "errors": errors}
        return {"title": self.ctx.t("dialog.sure.title"),
                "confirm": self.ctx.t("dialog.confirm"),
                "summary": [[self.ctx.t("dialog.player"), values["player"]],
                            [self.ctx.t("dialog.table"), values["table"]],
                            [self.ctx.t("dialog.points"), f"{int(values['score']):,}"]]}

    def run(self, values):
        self.call("/scores", "POST", {"player": values["player"], "table": values["table"],
                                      "score": int(values["score"])})
        return self.ctx.t("dialog.posted", table=values["table"])


def register(ctx):
    ctx.ui.settings([
        {"key": "site", "type": "string", "default": "http://127.0.0.1:8790"},
        {"key": "key", "type": "secret"},
    ])

    def call(path, method="GET", body=None):
        request = urllib.request.Request(
            ctx.config.get("site").rstrip("/") + path, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"X-API-Key": ctx.config.get("key"), "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=10) as answer:
                return json.loads(answer.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise Unavailable(ctx.t("error.refused")) from exc
            raise Unavailable(ctx.why(exc, at=request.full_url)) from exc
        except OSError as exc:
            raise Unavailable(ctx.why(exc, at=request.full_url)) from exc

    def rows():
        return [{**one, "page": f"{ctx.config.get('site').rstrip('/')}/scores/{one['id']}",
                 "can_flag": not one["flagged"]} for one in call("/top")]

    columns = [
        {"field": "player"},
        {"field": "table"},
        {"field": "score", "kind": "number"},
    ]

    def flag(picked):
        for one in picked:
            call(f"/scores/{one['id']}/flag", "POST")
        return ctx.t("message.flagged", count=len(picked))

    def remove(picked):
        for one in picked:
            call(f"/scores/{one['id']}", "DELETE")

    verbs = [
        {"key": "open", "link": "page"},
        {"key": "flag", "run": flag, "needs": "can_flag"},
        {"key": "remove", "run": remove, "danger": True},
    ]

    ctx.ui.list("scores", rows, area="community", columns=columns, verbs=verbs,
                acts=lambda: {"site": ctx.config.get("site")})

    ctx.ui.action("post", PostScore(ctx, call))

    def played(game_id="", seconds=0, private=False, **_rest):
        if private:
            return
        ctx.logger.info("%s", ctx.t("log.played", game=game_id, count=round(seconds / 60)))

    ctx.events.subscribe("table.play_recorded", played)
