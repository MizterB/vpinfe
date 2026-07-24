## VPinFE Release Notes

### Summary
vpinfe v2.5.1. Adds wheel paging on the second flipper buttons, a relocatable config directory, and a sticky save bar on the Manager UI config pages. Alphabetical sorting now ignores a leading "The", and there are fixes for frontend input suppression and restore-last-table on some themes.

### What's New
- **Frontend** — Wheel paging. Map your second flipper buttons (magna-save) to the Page Up/Page Down actions and the wheel jumps to the next/previous letter of the current Alpha sort. Two new `[Input]` settings control it: `pagingtype` (`alpha` default, or `numeric`) and `pagingsize` (how many tables a numeric jump moves, default 10). Alpha falls back to numeric when the sort isn't Alpha, and every jump is circular and capped at half the list so a press can't wrap past where you started. The core handles it, so all themes get paging with no theme changes.
- **Core** — Relocatable config directory. Set the `VPINFE_CONFIG_DIR` environment variable or pass `--configdir DIR` to keep `vpinfe.ini`, `themes/`, caches, and logs somewhere other than the OS default — useful for a portable install or separate config profiles. The environment variable wins if you set both.
- **Manager UI** — Sticky save bar on the config pages. VPinFE Config, VPX Config, VPX-Plugins, and VPinPlay now share one save bar that slides up from the bottom when there are unsaved edits, shows how many changed, and offers Discard. Save used to sit in a footer that scrolled off on long pages.

### Fixes
- **Frontend + Manager UI** — Alphabetical sorting moves a leading "The" to the end of the title, so "The Addams Family" sorts and displays as "Addams Family, The" instead of bunching every "The" title under T. A title you set yourself with an alternate title is left exactly as entered. Wheel paging groups by the same reordered title, so a letter jump lands where the sort put it. Thanks @Billiam
- **Frontend** — A failed table launch no longer leaves the frontend with input suppressed for the rest of the session. `TableLaunchComplete` now always fires, even when the launch throws.
- **Frontend** — Restore Last Table now works on themes that register their event handler inside `vpin.ready()` — slider and slider-video among them. The core waits for the theme's handler before broadcasting the restore instead of assuming one is already there.
- **Frontend** — A theme calling an unknown or disallowed API method now logs a warning server-side instead of failing silently in the browser.
- **Manager UI** — The Input settings section was missing the pageup/pagedown fields, so they showed as raw key names.

### Notes
- `--configfile` is gone. It appeared in `--help` but was parsed and thrown away, so it never did anything. Use `--configdir` or `VPINFE_CONFIG_DIR`.
- Themes that implement their own paging can opt out of the core behavior with `vpin.enableCorePaging(false)` and keep handling the Page Up/Page Down actions in `handleInput` as before.
