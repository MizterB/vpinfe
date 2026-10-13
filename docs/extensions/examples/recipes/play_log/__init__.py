def register(ctx):
    def played(game_id="", seconds=0, **_rest):
        ctx.logger.info("%s", ctx.t("log.played", game=game_id, minutes=round(seconds / 60)))

    ctx.events.subscribe("table.play_recorded", played)
