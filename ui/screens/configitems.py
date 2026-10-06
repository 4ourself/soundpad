"""Settings items for exporting / importing a config file (shared by Settings and Customize, identical in
Voicer and Soundpad)."""
from __future__ import annotations

import os

import configfile
from config import DEFAULTS

from ..modals import Prompt
from .settings import Item


def _short(path: str, n: int = 44) -> str:
    return path if len(path) <= n else "..." + path[-(n - 3):]


def config_items(app) -> list[Item]:
    name = "soundpad" if hasattr(app.ctl, "soundpad") else "voicer"
    other = "Voicer" if name == "soundpad" else "Soundpad"

    def do_export(text: str) -> None:
        try:
            path, n = configfile.export_file(app.cfg, DEFAULTS, name, text)
        except configfile.ConfigFileError as e:
            app.notify("error", str(e))
            return
        app.notify("ok", f"Exported {n} settings to {_short(path)}")

    def do_import(text: str) -> None:
        try:
            rep = configfile.import_file(app.cfg, DEFAULTS, text)
        except configfile.ConfigFileError as e:
            app.notify("error", str(e))
            return
        configfile.apply_changes(app, rep.changed)
        app.notify("ok" if not rep.rejected else "warn", rep.summary())

    def export_press():
        app.open_modal(Prompt("EXPORT CONFIG", "File to write (colors + settings, no devices):",
                              initial=configfile.default_path(), on_ok=do_export, path=True, new_ok=True,
                              ok="EXPORT", width=74,
                              validator=lambda v: "" if v.strip() else "Type a file name"))

    def import_press():
        default = configfile.default_path()

        def check(v):
            p = configfile.clean_path(v)
            if not p:
                return "Paste a file path first"
            return "" if os.path.isfile(p) or os.path.isfile(os.path.join(p, configfile.DEFAULT_NAME)) else "File not found"
        app.open_modal(Prompt("IMPORT CONFIG", f"Config file from {other} or from here:",
                              initial=default if os.path.isfile(default) else "", on_ok=do_import, path=True,
                              ok="IMPORT", width=74, validator=check))

    return [
        Item("button", "Export config", "Save colors and settings to a file. The same file works in Voicer and Soundpad.",
             get=lambda: "", press=export_press),
        Item("button", "Import config", f"Load a config file made by {other} or by this app. Applies at once.",
             get=lambda: "", press=import_press),
        Item("info", "Never included", "Devices (input / output / speaker), audio API, folders, sounds and presets stay yours.",
             lambda: "devices, sounds"),
    ]
