"""Where Visual Pinball X's settings are found, and which of them are drawn first.

The areas are the pages of the program's own settings menu, so a setting somebody changed
at the table is where they already look for it. Each area names every setting it holds,
and a few of them as its curated rows; the rest are found by search.
"""

from __future__ import annotations

from common.apps.contract import Heading

DISPLAYS = "displays"
SOUND = "sound"
GRAPHICS = "graphics"
PLUGINS = "plugins"
POINT_OF_VIEW = "point_of_view"
REST = "more"

# In the order the rail draws them.
AREAS = (DISPLAYS, SOUND, GRAPHICS, PLUGINS)


def _window(name: str) -> tuple[str, ...]:
    return tuple(f"{name}.{name}{part}" for part in
                 ("Output", "Display", "FullScreen", "WndX", "WndY", "Width", "Height"))


CURATED: dict[str, tuple[Heading, ...]] = {
    DISPLAYS: (
        # The playfield always shows, so it has no output mode.
        Heading("playfield", ("Player.PlayfieldDisplay", "Player.PlayfieldFullScreen",
                              "Player.PlayfieldWndX", "Player.PlayfieldWndY",
                              "Player.PlayfieldWidth", "Player.PlayfieldHeight")),
        Heading("backglass", _window("Backglass")),
        Heading("scoreview", _window("ScoreView")),
        Heading("topper", _window("Topper")),
        Heading("cabinet", ("Player.BGSet", "Player.CabinetAutofitMode",
                            "Player.CabinetAutofitPos", "Player.ScreenWidth",
                            "Player.ScreenHeight", "Player.ScreenInclination")),
    ),
    SOUND: (
        Heading("backglass", ("Player.PlayMusic", "Player.MusicVolume",
                              "Player.SoundDeviceBG")),
        Heading("playfield", ("Player.PlaySound", "Player.SoundVolume",
                              "Player.SoundDevice", "Player.Sound3D")),
    ),
    GRAPHICS: (
        Heading("", ("Player.SyncMode", "Player.MaxFramerate", "Player.AAFactor",
                     "Player.MSAASamples", "Player.FXAA", "Player.Sharpen",
                     "Player.PFReflection", "Player.ShowFPS")),
    ),
}

# The plugins the catalog has words for, and each one's rows after its Enable. A plugin
# not named here shows Enable alone, under its id.
PLUGIN_ROWS: dict[str, tuple[str, ...]] = {
    "AlphaDMD": (),
    "DOF": (),
    "FlexDMD": (),
    "RemoteControl": (),
    "WMP": (),
    "B2S": ("Plugin.B2S.ShowGrill",
            "Plugin.B2S.BackglassDMDOverlay", "Plugin.B2S.BackglassDMDAutoPos",
            "Plugin.B2S.ScoreViewDMDOverlay", "Plugin.B2S.ScoreViewDMDAutoPos"),
    "B2SLegacy": ("Plugin.B2SLegacy.B2SHideGrill", "Plugin.B2SLegacy.B2SHideB2SDMD",
                  "Plugin.B2SLegacy.B2SHideDMD",
                  "Plugin.B2SLegacy.BackglassDMDOverlay",
                  "Plugin.B2SLegacy.BackglassDMDAutoPos",
                  "Plugin.B2SLegacy.ScoreViewDMDOverlay",
                  "Plugin.B2SLegacy.ScoreViewDMDAutoPos"),
    "ScoreView": ("Plugin.ScoreView.LayoutFolder",),
    "PinMAME": ("Plugin.PinMAME.Sound", "Plugin.PinMAME.PinMAMEPath"),
    "AltSound": ("Plugin.AltSound.Folder",),
    "Serum": ("Plugin.Serum.SerumPath",),
    "VNI": ("Plugin.VNI.VniPath",),
    "PUP": ("Plugin.PUP.PUPFolder", "Plugin.PUP.MainVol"),
    "DMDUtil": ("Plugin.DMDUtil.ZeDMD", "Plugin.DMDUtil.Pixelcade",
                "Plugin.DMDUtil.PIN2DMD", "Plugin.DMDUtil.DMDServer"),
    "UpscaleDMD": ("Plugin.UpscaleDMD.UpscaleMode",),
}

# Plugins for writing plugins, and the program's own entry among them. In the rest.
NOT_PLUGINS = frozenset({"HelloScript", "HelloWorld", "Inspector", "vpx"})

# Keys of `[Player]` by the page of the program's menu that holds them. The view mode and
# autofit sit on its Graphic page, and are here because they are about the screen.
_DISPLAYS = frozenset({
    "Player.PlayfieldDisplay", "Player.PlayfieldFullScreen", "Player.PlayfieldWndX",
    "Player.PlayfieldWndY", "Player.PlayfieldWidth", "Player.PlayfieldHeight",
    "Player.PlayfieldFSWidth", "Player.PlayfieldFSHeight", "Player.PlayfieldRefreshRate",
    "Player.PlayfieldColorDepth",
    "Player.BGSet", "Player.CabinetAutofitMode", "Player.CabinetAutofitPos",
    "Player.ScreenWidth", "Player.ScreenHeight", "Player.ScreenInclination",
    "Player.LockbarWidth", "Player.LockbarHeight",
    "Player.ScreenPlayerX", "Player.ScreenPlayerY", "Player.ScreenPlayerZ",
})
_SOUND = frozenset({
    "Player.PlayMusic", "Player.MusicVolume", "Player.SoundDeviceBG",
    "Player.PlaySound", "Player.SoundVolume", "Player.SoundDevice", "Player.Sound3D",
})
_GRAPHICS = frozenset({
    "Player.SyncMode", "Player.MaxFramerate", "Player.MaxPrerenderedFrames",
    "Player.VisualLatencyCorrection", "Player.GfxBackend", "Player.ShowFPS",
    "Player.AAFactor", "Player.MSAASamples", "Player.FXAA", "Player.Sharpen",
    "Player.SSRefl", "Player.PFReflection", "Player.DisableAO", "Player.DynamicAO",
    "Player.MaxTexDimension", "Player.AlphaRampAccuracy", "Player.CompressTextures",
    "Player.HDRDisableToneMapper", "Player.HDRGlobalExposure",
    "Player.ForceAnisotropicFiltering", "Player.ForceBloomOff",
    "Player.ForceMotionBlurOff", "Player.UseNVidiaAPI",
    "Player.SoftwareVertexProcessing", "Player.BallAntiStretch",
    "Player.DisableLightingForBalls", "Player.BallTrail", "Player.BallTrailStrength",
})
_WINDOW_SECTIONS = frozenset({"Backglass", "ScoreView", "Topper"})
POINT_OF_VIEW_KEYS = "TableOverride.View"


def area_of(qualified: str) -> str:
    """The area a setting belongs to, whether or not it is one of its curated rows."""
    section = qualified.rsplit(".", 1)[0]
    if section in _WINDOW_SECTIONS or qualified in _DISPLAYS:
        return DISPLAYS
    if qualified in _SOUND:
        return SOUND
    if qualified in _GRAPHICS:
        return GRAPHICS
    if section.startswith("Plugin.") and plugin_of(qualified) not in NOT_PLUGINS:
        return PLUGINS
    if qualified.startswith(POINT_OF_VIEW_KEYS):
        return POINT_OF_VIEW
    return REST


def plugin_of(qualified: str) -> str:
    """`PinMAME` for `Plugin.PinMAME.Sound`; "" for a key that is not a plugin's."""
    parts = qualified.split(".")
    return parts[1] if len(parts) > 2 and parts[0] == "Plugin" else ""


def plugin_headings(offered: set[str]) -> tuple[Heading, ...]:
    """One heading per plugin the file has, by name, its Enable first and the switch for
    the rest."""
    found: list[Heading] = []
    seen: set[str] = set()
    for qualified in offered:
        plugin = plugin_of(qualified)
        if not plugin or plugin in seen or area_of(qualified) != PLUGINS:
            continue
        seen.add(plugin)
        enable = f"Plugin.{plugin}.Enable"
        keys = tuple(key for key in (enable, *PLUGIN_ROWS.get(plugin, ()))
                     if key in offered)
        if keys:
            found.append(Heading(plugin, keys,
                                 enabled_by=enable if keys[0] == enable else ""))
    return tuple(sorted(found, key=lambda one: one.key.lower()))


_CURATED_KEYS = frozenset({key for headings in CURATED.values() for heading in headings
                           for key in heading.keys}
                          | {key for keys in PLUGIN_ROWS.values() for key in keys})


def is_curated(qualified: str) -> bool:
    return qualified in _CURATED_KEYS or (
        qualified.endswith(".Enable") and area_of(qualified) == PLUGINS)


# Besides the curated rows a table can hold, what the program's own menu saves for one
# table only.
PER_TABLE = frozenset({
    "TableOverride.Difficulty", "TableOverride.Exposure", "TableOverride.ToneMapper",
    "Player.OverrideTableEmissionScale", "Player.EmissionScale",
})
