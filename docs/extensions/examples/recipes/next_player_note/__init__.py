from common.extensions.contract import PLAY


def register(ctx):
    def read():
        return {
            "title": ctx.t("page.note.heading"),
            "sections": [
                {"key": "note", "label": ctx.t("page.note.section"), "fields": [
                    {"key": "note", "type": "string", "label": ctx.t("page.note.field"),
                     "value": ctx.config.get("note") or ""},
                ]},
            ],
        }

    def save(values):
        ctx.config.set("note", values["note"])

    def clear():
        ctx.config.set("note", "")
        return ctx.t("page.note.cleared")

    ctx.ui.page("note", read, area="community", save=save, acts={"clear": clear}, tier=PLAY)
