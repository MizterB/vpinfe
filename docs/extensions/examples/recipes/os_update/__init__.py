class Updates:
    def __init__(self, ctx):
        self.ctx = ctx

    def says(self, method):
        return next(one["says"] for one in self.ctx.os.methods if one["name"] == method)

    def ask(self, step):
        if not self.ctx.os.available:
            return {"ready": False, "reason": self.ctx.t("dialog.no_helper"),
                    "confirm": self.ctx.t("dialog.install")}
        waiting = self.ctx.os.call("updates.check")
        count = waiting.get("count", 0) if isinstance(waiting, dict) else 0
        return {"summary": [[self.ctx.t("dialog.waiting"), str(count)],
                            [self.ctx.t("dialog.will"), self.says("updates.apply")]],
                "confirm": self.ctx.t("dialog.install")}

    def run(self, values):
        job = self.ctx.jobs.submit("install", lambda job: self.ctx.os.call("updates.apply"))
        return {"job_id": job.id}


def register(ctx):
    ctx.ui.action("updates", Updates(ctx))
