"""Customize page: colours (main colour, volume graph, backdrop), layout (graph / menu position, borders),
tab animation and the title-screen logo. Same two-pane behaviour as Settings; every change is live."""
from __future__ import annotations

from .. import transitions
from ..colors import PRESET_ACCENTS
from .configitems import config_items
from .settings import Item, SettingsScreen

PRESETS = list(PRESET_ACCENTS)


class CustomizeScreen(SettingsScreen):
    CATS = ("Colors", "Layout", "Animation", "Logo", "Config")
    TITLE = "CUSTOMIZE"

    def _items(self, cat: str) -> list[Item]:
        app, cfg = self.app, self.app.cfg

        def choice_item(label, desc, key, options, after=None):
            def setter(v):
                cfg.set(key, v)
                if after:
                    after()
            return Item("choice", label, desc, lambda: cfg.get(key), setter, options=options)

        def toggle_item(label, desc, key, after=None):
            def setter(v):
                cfg.set(key, v)
                if after:
                    after()
            return Item("toggle", label, desc, lambda: bool(cfg.get(key)), setter)

        if cat == "Config":
            return config_items(app)
        if cat == "Colors":
            def describe(t):
                pt = app.paint_of(t)
                m = pt.effective_mode()
                if t == "accent" and cfg.get("ui.accent") != "custom":
                    return cfg.get("ui.accent")
                return {"solid": f"solid {pt.stops[0][0]}", "rainbow": "rainbow"}.get(m, f"{m} - {len(pt.stops)} colours")

            def reset_colors():
                from config import DEFAULTS
                d = DEFAULTS["ui"]
                for k in ("accent", "accent_paint", "graph_paint", "backdrop", "backdrop_paint"):
                    cfg.set("ui." + k, d[k])
                app.refresh_paints()
                app.notify("ok", "Colours reset")
            return [
                Item("button", "Main color", "The UI colour. Any colour, gradient or rainbow. Opens the colour editor.",
                     get=lambda: describe("accent"), press=lambda: app.open_colors("accent")),
                choice_item("Main color preset", "Quick pick. 'custom' = whatever you made in Main color.", "ui.accent",
                            PRESETS + ["custom"], app.refresh_paints),
                Item("button", "Volume graph colors", "Meters and waveform: zones, solid, gradient or rainbow.",
                     get=lambda: describe("graph"), press=lambda: app.open_colors("graph")),
                choice_item("Backdrop", "terminal = keep your terminal's background. custom = paint your own; Alpha mixes with it.",
                            "ui.backdrop", ["terminal", "custom"], app.refresh_paints),
                Item("button", "Backdrop color", "Background colour (solid or top-to-bottom gradient).",
                     get=lambda: describe("backdrop") if cfg.get("ui.backdrop") == "custom" else "terminal",
                     press=lambda: app.open_colors("backdrop")),
                Item("button", "Reset colors", "Back to the default colors.", get=lambda: "", press=reset_colors),
                choice_item("Color mode", "auto / true (24-bit) / 256 / 16 / mono. Custom colours need true or 256.", "ui.colors",
                            ["auto", "true", "256", "16", "mono"], app.rebuild_theme),
            ]
        if cat == "Layout":
            return [
                choice_item("Graph position", "Where the volume graph sits: left, center or right. Center needs a wide window.",
                            "ui.graph_position", ["left", "center", "right"], app.mark_dirty),
                choice_item("Menu position", "Where the main menu sits on the start screen.",
                            "ui.menu_position", ["left", "center", "right"], app.mark_dirty),
                choice_item("Borders", "rounded (curvy corners) or square.", "ui.borders", ["rounded", "square"],
                            app.rebuild_theme),
            ]
        if cat == "Animation":
            return [
                choice_item("Tab animation", "How screens change. 'none' = instant (default). 'random' picks a new one each time.",
                            "ui.animation", list(transitions.KINDS), app.play_transition),
                choice_item("Animation speed", "fast / normal / slow.", "ui.animation_speed",
                            list(transitions.SPEEDS), app.play_transition),
                Item("button", "Preview animation", "Plays the chosen animation once.",
                     get=lambda: "", press=app.play_transition),
            ]
        return [
            toggle_item("Title screen", "Show the animated logo when the app starts (Enter continues).", "ui.splash"),
            choice_item("Logo glow", "How often the logo glows: off, sometimes or always.", "ui.logo_glow",
                        ["off", "sometimes", "always"]),
            Item("button", "Show title screen", "Go back to the title screen now.", get=lambda: "",
                 press=self._show_title),
        ]

    def _show_title(self):
        self.app.splash = True
        self.app.goto("home")
