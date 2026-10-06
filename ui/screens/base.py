from __future__ import annotations

from ..canvas import Canvas, Rect


class BaseScreen:
    """A screen draws into a body Rect each frame and handles keys. It holds UI state only;
    every audio/soundpad action goes through app.ctl (Controller)."""

    def __init__(self, app):
        self.app = app

    @property
    def th(self):
        return self.app.theme

    @property
    def ctl(self):
        return self.app.ctl

    def on_show(self) -> None:
        pass

    def tick(self) -> None:
        pass

    def draw(self, cv: Canvas, r: Rect) -> None:
        pass

    def on_key(self, key) -> bool:
        return False

    def captures_text(self) -> bool:
        return False
