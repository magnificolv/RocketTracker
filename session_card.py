"""
RL Tracker 4.0 Overdrive — Pro Esports 1200x675 Discord Session Share Card (PNG)
Uses Pillow + bundled Pack PNG icons (zero emoji tofu boxes!).
"""
from __future__ import annotations

import io
import sys
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from version import APP_EDITION, APP_VERSION

try:
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont
except ImportError:  # pragma: no cover
    Image = ImageDraw = ImageFont = ImageFilter = ImageEnhance = None  # type: ignore


W, H = 1200, 675


def _asset_root() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    dash = base / "dashboard"
    if dash.exists():
        return dash
    return Path(__file__).parent / "dashboard"


def _font(size: int, bold: bool = False):
    candidates = []
    if bold:
        candidates += [
            "C:/Windows/Fonts/segoeuib.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
    candidates += [
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
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


BG = _hex("070A12")
CARD = _hex("0F1526")
TILE = _hex("0A0F1D")
BORDER = _hex("23304C")
TEXT = _hex("F1F5F9")
MUTED = _hex("94A3B8")
CYAN = _hex("22D3EE")
BLUE = _hex("38BDF8")
ORANGE = _hex("FB923C")
GREEN = _hex("22C55E")
RED = _hex("EF4444")
GOLD = _hex("FACC15")
VIOLET = _hex("A78BFA")


def _grade_color(grade: str) -> Tuple[int, int, int]:
    g = (grade or "?").upper()[:2]
    if g.startswith("S"):
        return GOLD
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
        if t < 0.5:
            u = t / 0.5
            c0, c1 = colors[0], colors[1]
        else:
            u = (t - 0.5) / 0.5
            c0, c1 = colors[1], colors[2]
        col = tuple(int(c0[j] + (c1[j] - c0[j]) * u) for j in range(3))
        draw.line([(x0 + i, y0), (x0 + i, y1)], fill=col)


def _paste_icon(img: "Image.Image", icon_path: Path, xy: Tuple[int, int], size: int = 28) -> bool:
    if not icon_path.exists():
        return False
    try:
        ic = Image.open(icon_path).convert("RGBA")
        ic = ic.resize((size, size), Image.Resampling.LANCZOS)
        img.paste(ic, xy, ic)
        return True
    except Exception:
        return False


def render_session_card(
    session: Dict[str, Any],
    matches: List[Dict[str, Any]],
    coach: Optional[Dict[str, Any]] = None,
    logo_path: Optional[Path] = None,
    player_name: str = "Player",
) -> bytes:
    """Return PNG bytes for a 1200x675 Overdrive session card."""
    if Image is None:
        raise RuntimeError("Pillow is required for session cards")

    dash = _asset_root()
    icons_dir = dash / "assets" / "icons"

    img = Image.new("RGBA", (W, H), (*BG, 255))

    # Subtle ambient arena backdrop tint
    bg_path = dash / "assets" / "arena-bg-v4.jpg"
    if bg_path.exists():
        try:
            bg = Image.open(bg_path).convert("RGB").resize((W, H), Image.Resampling.LANCZOS)
            bg = bg.filter(ImageFilter.GaussianBlur(10))
            bg = ImageEnhance.Brightness(bg).enhance(0.24)
            img = Image.alpha_composite(img, bg.convert("RGBA"))
        except Exception:
            pass

    # Main rounded panel
    margin = 26
    panel = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    pd = ImageDraw.Draw(panel)
    pd.rounded_rectangle(
        [margin, margin, W - margin, H - margin],
        radius=26,
        fill=(CARD[0], CARD[1], CARD[2], 232),
        outline=(*BORDER, 255),
        width=2,
    )
    img = Image.alpha_composite(img, panel).convert("RGB")
    draw = ImageDraw.Draw(img)

    # Top Blue -> Cyan -> Orange Overdrive energy bar
    _draw_gradient_bar(draw, (margin + 18, margin + 2, W - margin - 18, margin + 7), [BLUE, CYAN, ORANGE])

    f_title = _font(36, bold=True)
    f_kpi = _font(54, bold=True)
    f_stat = _font(28, bold=True)
    f_med = _font(20, bold=True)
    f_sm = _font(17)
    f_xs = _font(14, bold=True)
    f_foot = _font(13)

    # Logo + Header
    lx, ly = margin + 36, margin + 28
    used_logo = logo_path if (logo_path and Path(logo_path).exists()) else (dash / "logo.png")
    if used_logo.exists():
        try:
            logo = Image.open(used_logo).convert("RGBA")
            logo.thumbnail((68, 68), Image.Resampling.LANCZOS)
            img.paste(logo, (lx, ly), logo)
            draw = ImageDraw.Draw(img)
        except Exception:
            pass

    draw.text((lx + 84, ly + 4), "Rocket League Tracker", font=f_title, fill=TEXT)
    draw.text((lx + 84, ly + 48), f"SESSION REPORT  ·  v{APP_VERSION} {APP_EDITION.upper()}", font=f_xs, fill=CYAN)

    # Coach grade pill top-right
    grade = "—"
    score = None
    summary = ""
    if coach:
        grade = coach.get("overall_grade") or "—"
        score = coach.get("overall_score")
        summary = coach.get("summary") or ""
    gc = _grade_color(grade)
    pill = f"COACH {grade}" + (f"  ·  {score}" if score is not None else "")
    bbox = draw.textbbox((0, 0), pill, font=f_med)
    pw = bbox[2] - bbox[0] + 40
    ph = 44
    px = W - margin - 36 - pw
    py = ly + 10
    draw.rounded_rectangle([px, py, px + pw, py + ph], radius=22, fill=gc)
    draw.text((px + pw / 2, py + ph / 2), pill, font=f_med, fill=BG, anchor="mm")

    # Meta strip
    started = session.get("started_at") or ""
    try:
        dt = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
        date_s = dt.strftime("%d %b %Y · %H:%M")
    except Exception:
        date_s = str(started)[:16] if started else "—"

    mode = (session.get("mode") or "solo").lower()
    friend = session.get("friend_name") or ""
    mode_label = f"DUO w/ {friend}" if mode == "duo" and friend else mode.upper()
    playlists = sorted({(m.get("playlist") or "Unknown") for m in matches}) if matches else ["—"]
    pl_label = " · ".join(playlists[:3])
    draw.text((lx, ly + 82), f"{player_name}   •   {date_s}   •   {mode_label}   •   {pl_label}", font=f_sm, fill=MUTED)

    # 4 equal-width KPI cards (zero overlap!)
    wins = sum(1 for m in matches if m.get("result") == "win")
    losses = sum(1 for m in matches if m.get("result") == "loss")
    total = wins + losses
    wr = round(wins / total * 100) if total else 0
    gf = sum(int(m.get("user_score") or 0) for m in matches)
    ga = sum(int(m.get("opponent_score") or 0) for m in matches)
    gd = gf - ga
    gd_str = f"+{gd}" if gd > 0 else str(gd)

    kpis = [
        ("WINS", str(wins), GREEN),
        ("LOSSES", str(losses), RED),
        ("WINRATE", f"{wr}%", CYAN if wr >= 50 else ORANGE),
        ("GOAL DIFF", gd_str, GREEN if gd >= 0 else RED),
    ]
    inner_x0 = margin + 36
    inner_w = W - 2 * inner_x0
    kpi_gap = 18
    kpi_w = (inner_w - 3 * kpi_gap) // 4
    kpi_y = 176
    kpi_h = 108

    for idx, (label, val, col) in enumerate(kpis):
        x0 = inner_x0 + idx * (kpi_w + kpi_gap)
        draw.rounded_rectangle([x0, kpi_y, x0 + kpi_w, kpi_y + kpi_h], radius=16, fill=TILE, outline=BORDER, width=1)
        draw.text((x0 + kpi_w // 2, kpi_y + 44), val, font=f_kpi, fill=col, anchor="mm")
        draw.text((x0 + kpi_w // 2, kpi_y + 92), label, font=f_xs, fill=MUTED, anchor="mm")

    # Form strip (up to 16 chronological oldest -> newest)
    form = list(matches)[-16:]
    if form:
        fy = 304
        dot_s = 26
        dot_gap = 8
        total_fw = len(form) * dot_s + (len(form) - 1) * dot_gap
        fx0 = (W - total_fw) // 2
        for i, m in enumerate(form):
            x = fx0 + i * (dot_s + dot_gap)
            res = m.get("result")
            col = GREEN if res == "win" else (RED if res == "loss" else MUTED)
            ch = "W" if res == "win" else ("L" if res == "loss" else "D")
            draw.rounded_rectangle([x, fy, x + dot_s, fy + dot_s], radius=8, fill=col)
            draw.text((x + dot_s // 2, fy + dot_s // 2), ch, font=f_xs, fill=BG, anchor="mm")

    # 5 stat highlight cards with real PNG Pack icons
    pgoals = sum(int(m.get("player_goals") if m.get("player_goals") is not None else (m.get("user_score") or 0)) for m in matches)
    shots = sum(int(m.get("shots") or 0) for m in matches)
    saves = sum(int(m.get("saves") or 0) for m in matches)
    demos = sum(int(m.get("demos_given") or 0) for m in matches)
    fastest = max((float(m.get("fastest_goal_kph") or 0.0) for m in matches), default=0.0)

    stat_boxes = [
        ("football.png", "YOUR GOALS", str(pgoals), TEXT),
        ("target.png", "SHOTS", str(shots), BLUE),
        ("shield.png", "SAVES", str(saves), CYAN),
        ("fire.png", "DEMOS", str(demos), ORANGE),
        ("rocket.png", "FASTEST GOAL", f"{fastest:.0f} km/h" if fastest > 0 else f"{total} Games", GOLD if fastest > 0 else TEXT),
    ]
    st_gap = 14
    st_w = (inner_w - 4 * st_gap) // 5
    st_y = 358
    st_h = 110

    for i, (icon_name, lab, val, val_col) in enumerate(stat_boxes):
        x = inner_x0 + i * (st_w + st_gap)
        draw.rounded_rectangle([x, st_y, x + st_w, st_y + st_h], radius=16, fill=TILE, outline=BORDER, width=1)
        icon_p = icons_dir / icon_name
        has_icon = _paste_icon(img, icon_p, (x + 14, st_y + 14), size=28)
        draw = ImageDraw.Draw(img)
        tx = x + (50 if has_icon else 16)
        draw.text((tx, st_y + 22), lab, font=f_xs, fill=MUTED)
        draw.text((x + st_w // 2, st_y + 72), val, font=f_stat, fill=val_col, anchor="mm")

    # Wrapped Coach summary box
    if summary:
        sy = 492
        draw.rounded_rectangle([inner_x0, sy, W - inner_x0, sy + 92], radius=14, fill=TILE, outline=BORDER, width=1)
        lines = textwrap.wrap(summary, width=96)[:2]
        if len(lines) == 1:
            draw.text((W // 2, sy + 46), lines[0], font=f_sm, fill=TEXT, anchor="mm")
        else:
            draw.text((W // 2, sy + 32), lines[0], font=f_sm, fill=TEXT, anchor="mm")
            draw.text((W // 2, sy + 62), lines[1], font=f_sm, fill=MUTED, anchor="mm")

    # Footer
    draw.text(
        (W // 2, H - margin - 24),
        f"Rocket League Tracker v{APP_VERSION} · {APP_EDITION}  •  Competitive Telemetry & Coach",
        font=f_foot,
        fill=MUTED,
        anchor="mm",
    )

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def session_to_csv_rows(matches: List[Dict[str, Any]]) -> str:
    headers = [
        "match_id",
        "played_at",
        "result",
        "user_score",
        "opponent_score",
        "player_goals",
        "mode",
        "playlist",
        "shots",
        "saves",
        "demos_given",
        "demos_taken",
        "arena",
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
