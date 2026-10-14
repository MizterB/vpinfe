MACHINE = {"boot": "play", "checked": "never"}


def register(ctx):
    def read():
        return {
            "title": ctx.t("page.machine.heading"),
            "under": ctx.t("page.machine.under"),
            "sections": [
                {"key": "state", "label": ctx.t("page.machine.state"), "facts": [
                    {"label": ctx.t("page.machine.checked"), "value": MACHINE["checked"]},
                ]},
                {"key": "boot", "label": ctx.t("page.machine.boot"), "fields": [
                    {"key": "boot", "type": "select", "label": ctx.t("page.machine.boot.mode"),
                     "value": MACHINE["boot"],
                     "choices": [["play", ctx.t("page.machine.boot.play")],
                                 ["desk", ctx.t("page.machine.boot.desk")]]},
                ]},
            ],
        }

    def save(values):
        MACHINE.update(values)

    def check():
        MACHINE["checked"] = ctx.t("page.machine.checked.now")
        return ctx.t("page.machine.checked.said")

    ctx.ui.page("machine", read, area="system", save=save,
                acts={"check": check, "manual": "https://machine.example.com/manual"})
