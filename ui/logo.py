"""Title-screen logos (figlet 'bloody' font, pre-rendered) and the glowing logo painter."""
from __future__ import annotations

import math

from .colors import clamp, lerp, with_alpha

LOGOS = {
    "voicer": [
        ' ██▒   █▓ ▒█████   ██▓ ▄████▄  ▓█████  ██▀███  ',
        '▓██░   █▒▒██▒  ██▒▓██▒▒██▀ ▀█  ▓█   ▀ ▓██ ▒ ██▒',
        ' ▓██  █▒░▒██░  ██▒▒██▒▒▓█    ▄ ▒███   ▓██ ░▄█ ▒',
        '  ▒██ █░░▒██   ██░░██░▒▓▓▄ ▄██▒▒▓█  ▄ ▒██▀▀█▄  ',
        '   ▒▀█░  ░ ████▓▒░░██░▒ ▓███▀ ░░▒████▒░██▓ ▒██▒',
        '   ░ ▐░  ░ ▒░▒░▒░ ░▓  ░ ░▒ ▒  ░░░ ▒░ ░░ ▒▓ ░▒▓░',
        '   ░ ░░    ░ ▒ ▒░  ▒ ░  ░  ▒    ░ ░  ░  ░▒ ░ ▒░',
        '     ░░  ░ ░ ░ ▒   ▒ ░░           ░     ░░   ░ ',
        '      ░      ░ ░   ░  ░ ░         ░  ░   ░     ',
        '     ░                ░                        ',
    ],
    "soundpad": [
        '  ██████  ▒█████   █    ██  ███▄    █ ▓█████▄  ██▓███   ▄▄▄      ▓█████▄ ',
        '▒██    ▒ ▒██▒  ██▒ ██  ▓██▒ ██ ▀█   █ ▒██▀ ██▌▓██░  ██▒▒████▄    ▒██▀ ██▌',
        '░ ▓██▄   ▒██░  ██▒▓██  ▒██░▓██  ▀█ ██▒░██   █▌▓██░ ██▓▒▒██  ▀█▄  ░██   █▌',
        '  ▒   ██▒▒██   ██░▓▓█  ░██░▓██▒  ▐▌██▒░▓█▄   ▌▒██▄█▓▒ ▒░██▄▄▄▄██ ░▓█▄   ▌',
        '▒██████▒▒░ ████▓▒░▒▒█████▓ ▒██░   ▓██░░▒████▓ ▒██▒ ░  ░ ▓█   ▓██▒░▒████▓ ',
        '▒ ▒▓▒ ▒ ░░ ▒░▒░▒░ ░▒▓▒ ▒ ▒ ░ ▒░   ▒ ▒  ▒▒▓  ▒ ▒▓▒░ ░  ░ ▒▒   ▓▒█░ ▒▒▓  ▒ ',
        '░ ░▒  ░ ░  ░ ▒ ▒░ ░░▒░ ░ ░ ░ ░░   ░ ▒░ ░ ▒  ▒ ░▒ ░       ▒   ▒▒ ░ ░ ▒  ▒ ',
        '░  ░  ░  ░ ░ ░ ▒   ░░░ ░ ░    ░   ░ ░  ░ ░  ░ ░░         ░   ▒    ░ ░  ░ ',
        '      ░      ░ ░     ░              ░    ░                   ░  ░   ░    ',
        '                                       ░                          ░      ',
    ],
}
TAGLINES = {"voicer": "real-time voice changer", "soundpad": "background soundboard"}
ASCII_MAP = str.maketrans({"█": "#", "▓": "%", "▒": "=", "░": ".", "▄": "_", "▀": "'", "▐": "|", "▌": "|"})
WEIGHT = {"█": 1.0, "▓": 0.86, "▒": 0.64, "░": 0.44, "▄": 0.95, "▀": 0.95, "▐": 0.9, "▌": 0.9}
QPOS, QGLOW = 24, 8


def logo_size(name: str) -> tuple[int, int]:
    rows = LOGOS[name]
    return len(rows[0]), len(rows)


def glow_amount(t: float, mode: str) -> tuple[float, float, float]:
    """-> (overall glow 0..1, shimmer centre in logo columns as a fraction of width or -1, shimmer strength)."""
    if mode == "off":
        return 0.0, -1.0, 0.0
    if mode == "always":
        return 0.5 + 0.5 * math.sin(t * 2.4), (t * 0.35) % 1.4 - 0.2, 1.0
    period, start, length = 7.0, 3.6, 2.4         # a glow + a light sweep every 7 s, lasting 2.4 s
    ph = t % period
    if ph < start or ph > start + length:
        return 0.0, -1.0, 0.0
    k = (ph - start) / length
    return math.sin(math.pi * k) ** 2, k * 1.3 - 0.15, 1.0


def draw_logo(cv, th, name: str, x: int, y: int, t: float, mode: str = "sometimes", reveal: float = 1.0) -> None:
    """Paint the logo at (x, y). Colour = the accent paint (solid / gradient / rainbow) across the logo width;
    block glyphs keep their shading; the glow brightens towards white. Style count is bounded (quantised)."""
    rows = LOGOS[name]
    w = len(rows[0])
    p = th.accent_paint
    phase = p.phase_at(t)
    glow, centre, strength = glow_amount(t, mode)
    cols_shown = int(w * clamp(reveal, 0.0, 1.0)) if reveal < 1.0 else w
    cache = {}
    for ry, line in enumerate(rows):
        for cx, ch in enumerate(line):
            if ch == " " or cx >= cols_shown:
                continue
            pos = cx / max(1, w - 1)
            qp = int(pos * (QPOS - 1))
            lift = glow * 0.38
            if centre >= 0:
                lift = max(lift, strength * max(0.0, 1.0 - abs(pos - centre) / 0.12) * 0.85)
            qg = int(round(clamp(lift, 0.0, 0.9) * (QGLOW - 1) / 0.9))
            key = (qp, qg, ch)
            sid = cache.get(key)
            if sid is None:
                col = p.color_at(qp / (QPOS - 1), phase=phase)
                col = lerp(col, (255, 255, 255), qg * 0.9 / (QGLOW - 1))
                wt = WEIGHT.get(ch, 0.8)
                col = with_alpha(col, 35 + 65 * wt, p.base) if wt < 1.0 else col
                sid = cache[key] = th.style(col, None, qg >= QGLOW - 3 and wt >= 0.9)
            cv.put(x + cx, y + ry, ch if th.unicode else ch.translate(ASCII_MAP), sid)
