"""
RL Tracker 3.0 — Discord-ready session share card (PNG) + helpers.
Pillow-only, no browser needed.
"""
from __future__ import annotations

import io
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
except ImportError:  # pragma: no cover
    Image = ImageDraw = ImageFont = ImageFilter = None  # type: ignore


W, H = 1200, 675


def _font(size: int, bold: bool = False):
    candidates = []
    if bold:
        candidates += [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/segoeuib.ttf",
        ]
    candidates += [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
    ]
    for p in candidates:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _hex(c: str) -> Tuple[int, int, int]:
    c = c.lstrip("#")
    return tuple(int(c[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore


# Starlight palette
BG = _hex("070712")
CARD = _hex("12122a")
BORDER = _hex("2a2a48")
TEXT = _hex("eef1ff")
MUTED = _hex("9aa3c7")
CYAN = _hex("22d3ee")
VIOLET = _hex("a78bfa")
ORCHID = _hex("e879f9")
GREEN = _hex("4ade80")
RED = _hex("f87171")
ORANGE = _hex("fb923c")
BLUE = _hex("38bdf8")


def _grade_color(grade: str) -> Tuple[int, int, int]:
    g = (grade or "?").upper()[:2]
    if g.startswith("A"):
        return GREEN
    if g.startswith("B"):
        return CYAN
    if g.startswith("C"):
        return ORANGE
    if g.startswith("D") or g.startswith("F"):
        return RED
    return VIOLET


def _draw_gradient_bar(draw, xy, colors):
    x0, y0, x1, y1 = xy
    steps = max(x1 - x0, 1)
    for i in range(steps):
        t = i / steps
        # 3-stop blend cyan -> violet -> orchid
        if t < 0.5:
            u = t / 0.5
            c0, c1 = colors[0], colors[1]
        else:
            u = (t - 0.5) / 0.5
            c0, c1 = colors[1], colors[2]
        col = tuple(int(c0[j] + (c1[j] - c0[j]) * u) for j in range(3))
        draw.line([(x0 + i, y0), (x0 + i, y1)], fill=col)


def render_session_card(
    session: Dict[str, Any],
    matches: List[Dict[str, Any]],
    coach: Optional[Dict[str, Any]] = None,
    logo_path: Optional[Path] = None,
    player_name: str = "Player",
) -> bytes:
    """Return PNG bytes for a 1200x675 session card."""
    if Image is None:
        raise RuntimeError("Pillow is required for session cards")

    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # Soft radial glows
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([ -200, -180, 520, 420], fill=(99, 102, 241, 55))
    gd.ellipse([700, 200, 1400, 900], fill=(232, 121, 249, 40))
    gd.ellipse([400, -100, 1000, 300], fill=(34, 211, 238, 28))
    glow = glow.filter(ImageFilter.GaussianBlur(60))
    img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")
    draw = ImageDraw.Draw(img)

    # Outer frame
    margin = 28
    draw.rounded_rectangle(
        [margin, margin, W - margin, H - margin],
        radius=28,
        outline=BORDER,
        width=2,
        fill=(*CARD, ) if False else CARD,
    )
    # Top gradient accent
    _draw_gradient_bar(draw, (margin + 4, margin + 4, W - margin - 4, margin + 8), [CYAN, VIOLET, ORCHID])

    f_title = _font(42, bold=True)
    f_h = _font(28, bold=True)
    f_big = _font(72, bold=True)
    f_med = _font(22, bold=True)
    f_sm = _font(18)
    f_xs = _font(15)

    # Logo
    lx, ly = margin + 36, margin + 32
    if logo_path and Path(logo_path).exists():
        try:
            logo = Image.open(logo_path).convert("RGBA")
            logo.thumbnail((72, 72), Image.LANCZOS)
            img.paste(logo, (lx, ly), logo)
            draw = ImageDraw.Draw(img)
        except Exception:
            pass

    draw.text((lx + 88, ly + 8), "RL Tracker", font=f_title, fill=TEXT)
    draw.text((lx + 88, ly + 52), "SESSION CARD · v3.0", font=f_xs, fill=MUTED)

    # Meta line
    started = session.get("started_at") or ""
    try:
        dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
        date_s = dt.strftime("%d %b %Y · %H:%M")
    except Exception:
        date_s = started[:16] if started else "—"

    mode = (session.get("mode") or "solo").lower()
    friend = session.get("friend_name") or ""
    mode_label = f"DUO w/ {friend}" if mode == "duo" and friend else mode.upper()
    playlists = sorted({(m.get("playlist") or "Unknown") for m in matches}) if matches else ["—"]
    pl_label = ", ".join(playlists[:3])

    draw.text((lx, ly + 100), f"{player_name}  ·  {date_s}  ·  {mode_label}  ·  {pl_label}", font=f_sm, fill=MUTED)

    # W-L big numbers
    wins = sum(1 for m in matches if m.get("result") == "win")
    losses = sum(1 for m in matches if m.get("result") == "loss")
    total = wins + losses
    wr = round(wins / total * 100) if total else 0

    cx = W // 2
    draw.text((cx - 260, 210), f"{wins}", font=f_big, fill=GREEN, anchor="mm")
    draw.text((cx - 260, 270), "WINS", font=f_xs, fill=MUTED, anchor="mm")
    draw.text((cx - 140, 210), f"{losses}", font=f_big, fill=RED, anchor="mm")
    draw.text((cx - 140, 270), "LOSSES", font=f_xs, fill=MUTED, anchor="mm")
    draw.text((cx + 20, 210), f"{wr}%", font=f_big, fill=CYAN if wr >= 50 else ORANGE, anchor="mm")
    draw.text((cx + 20, 270), "WINRATE", font=f_xs, fill=MUTED, anchor="mm")
    draw.text((cx + 180, 210), f"{total}", font=f_big, fill=VIOLET, anchor="mm")
    draw.text((cx + 180, 270), "MATCHES", font=f_xs, fill=MUTED, anchor="mm")

    # Form dots (last 12 chronological oldest→newest)
    form = list(matches)[-12:]
    if form:
        dots_y = 330
        start_x = cx - (len(form) * 28) // 2
        for i, m in enumerate(form):
            x = start_x + i * 28
            won = m.get("result") == "win"
            col = GREEN if won else RED
            draw.ellipse([x, dots_y, x + 20, dots_y + 20], fill=col)
            draw.text((x + 10, dots_y + 10), "W" if won else "L", font=f_xs, fill=BG, anchor="mm")

    # Coach grade pill
    grade = "—"
    score = None
    summary = ""
    if coach:
        grade = coach.get("overall_grade") or "—"
        score = coach.get("overall_score")
        summary = coach.get("summary") or ""
    gc = _grade_color(grade)
    pill = f"COACH {grade}" + (f"  ·  {score}" if score is not None else "")
    # measure
    bbox = draw.textbbox((0, 0), pill, font=f_med)
    pw = bbox[2] - bbox[0] + 36
    ph = 44
    px = W - margin - 40 - pw
    py = margin + 36
    draw.rounded_rectangle([px, py, px + pw, py + ph], radius=22, fill=(gc[0], gc[1], gc[2],))
    draw.text((px + pw / 2, py + ph / 2), pill, font=f_med, fill=BG, anchor="mm")

    # Highlights row
    goals = sum(int(m.get("user_score") or 0) for m in matches)
    shots = sum(int(m.get("shots") or 0) for m in matches)
    saves = sum(int(m.get("saves") or 0) for m in matches)
    demos = sum(int(m.get("demos_given") or 0) for m in matches)

    stats = [
        ("⚽ Goals", str(goals)),
        ("🎯 Shots", str(shots)),
        ("🛡️ Saves", str(saves)),
        ("💥 Demos", str(demos)),
    ]
    box_w = 220
    box_h = 88
    gap = 18
    total_w = 4 * box_w + 3 * gap
    sx = (W - total_w) // 2
    sy = 390
    for i, (lab, val) in enumerate(stats):
        x = sx + i * (box_w + gap)
        draw.rounded_rectangle([x, sy, x + box_w, sy + box_h], radius=16, outline=BORDER, width=1, fill=_hex("0c0c1c"))
        draw.text((x + box_w / 2, sy + 28), val, font=f_h, fill=TEXT, anchor="mm")
        draw.text((x + box_w / 2, sy + 62), lab, font=f_xs, fill=MUTED, anchor="mm")

    # Summary / tips line
    if summary:
        draw.text((W // 2, 520), summary[:90], font=f_sm, fill=MUTED, anchor="mm")

    # Footer
    draw.text((W // 2, H - margin - 28), "Share your grind · Rocket League Match Tracker 3.0 · Starlight", font=f_xs, fill=MUTED, anchor="mm")

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def session_to_csv_rows(matches: List[Dict[str, Any]]) -> str:
    headers = [
        "match_id", "played_at", "result", "user_score", "opponent_score",
        "mode", "playlist", "shots", "saves", "demos_given", "demos_taken",
        "goals", "arena",
    ]
    lines = [",".join(headers)]
    for m in matches:
        row = []
        for h in headers:
            v = m.get(h, "")
            if v is None:
                v = ""
            s = str(v).replace('"', '""')
            if "," in s or '"' in s:
                s = f'"{s}"'
            row.append(s)
        lines.append(",".join(row))
    return "\n".join(lines) + "\n"
