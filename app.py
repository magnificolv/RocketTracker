"""
Rocket League Tracker v4.0 Overdrive - Flask API (Portable Edition)
"""
from __future__ import annotations

import io
import json
import os as _os
import sqlite3
import sys
import tempfile
import threading as _th
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml
from flask import Flask, Response, jsonify, request, send_from_directory

from coach import CoachEngine
from listener import (
    diagnose_rl_ini,
    ensure_default_statsapi_ini,
    ensure_tastatsapi_ini,
    get_live_snapshot,
)
from result_logic import (
    COMPETITIVE_PLAYLIST_IDS,
    DEFAULT_TRACKING_CONFIG,
    arena_label,
    ensure_schema,
    is_competitive_playlist,
    normalize_tracking_config,
    repair_inverted_results,
)
from version import APP_EDITION, APP_VERSION, GITHUB_RELEASES_API, GITHUB_REPO

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent
    STATIC_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR)) / "dashboard"
else:
    BASE_DIR = Path(__file__).parent
    STATIC_DIR = BASE_DIR / "dashboard"

CONFIG_PATH = BASE_DIR / "config.yaml"
DB_PATH = BASE_DIR / "data-v2.db"
LOG_PATH = BASE_DIR / "listener.log"

app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="")

coach = CoachEngine(str(DB_PATH))


@app.after_request
def cors(r):
    r.headers["Access-Control-Allow-Origin"] = "*"
    r.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
    r.headers["Access-Control-Allow-Headers"] = "Content-Type"
    r.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    r.headers["Pragma"] = "no-cache"
    r.headers["Expires"] = "0"
    return r


def load_config() -> Dict[str, Any]:
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}
    return {}


def save_config(c: Dict[str, Any]) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(c, f, sort_keys=False, allow_unicode=True)


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _migrate_columns(conn: sqlite3.Connection) -> None:
    """Additive v3/v4 column migrations — safe on existing DBs."""
    wanted = {
        "matches": [
            ("playlist", "TEXT"),
            ("friend_name", "TEXT"),
        ],
        "match_details": [
            ("playlist", "TEXT"),
            ("teammate_name", "TEXT"),
            ("teammate_shots", "INTEGER DEFAULT 0"),
            ("teammate_saves", "INTEGER DEFAULT 0"),
            ("teammate_assists", "INTEGER DEFAULT 0"),
            ("teammate_touches", "INTEGER DEFAULT 0"),
            ("teammate_demos", "INTEGER DEFAULT 0"),
        ],
        "matches_summary": [
            ("playlist", "TEXT"),
            ("friend_name", "TEXT"),
        ],
    }
    for table, cols in wanted.items():
        existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for name, decl in cols:
            if name not in existing:
                try:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
                except Exception:
                    pass


def init_db() -> None:
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            mode TEXT NOT NULL DEFAULT 'solo',
            friend_name TEXT,
            notes TEXT
        );
        CREATE TABLE IF NOT EXISTS matches(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            played_at TEXT NOT NULL,
            user_score INTEGER NOT NULL,
            opponent_score INTEGER NOT NULL,
            result TEXT NOT NULL,
            mode TEXT NOT NULL DEFAULT 'solo',
            playlist TEXT,
            friend_name TEXT,
            FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS match_details(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER UNIQUE NOT NULL,
            arena TEXT,
            overtime INTEGER DEFAULT 0,
            touches INTEGER DEFAULT 0,
            car_touches INTEGER DEFAULT 0,
            shots INTEGER DEFAULT 0,
            saves INTEGER DEFAULT 0,
            assists INTEGER DEFAULT 0,
            demos_given INTEGER DEFAULT 0,
            demos_taken INTEGER DEFAULT 0,
            boost_avg REAL DEFAULT 0,
            boost_time_pct REAL DEFAULT 0,
            supersonic_time_pct REAL DEFAULT 0,
            ground_time_pct REAL DEFAULT 0,
            air_time_pct REAL DEFAULT 0,
            wall_time_pct REAL DEFAULT 0,
            fastest_goal_kph REAL DEFAULT 0,
            avg_shot_power REAL DEFAULT 0,
            time_remaining_sec INTEGER,
            playlist TEXT,
            teammate_name TEXT,
            teammate_shots INTEGER DEFAULT 0,
            teammate_saves INTEGER DEFAULT 0,
            teammate_assists INTEGER DEFAULT 0,
            teammate_touches INTEGER DEFAULT 0,
            teammate_demos INTEGER DEFAULT 0,
            FOREIGN KEY(match_id) REFERENCES matches(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS goals(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER NOT NULL,
            scored_at TEXT NOT NULL,
            scorer TEXT NOT NULL,
            assister TEXT,
            team_num INTEGER NOT NULL,
            speed_kph REAL,
            time_remaining_sec INTEGER,
            FOREIGN KEY(match_id) REFERENCES matches(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS ball_hits(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER NOT NULL,
            hit_at TEXT NOT NULL,
            player TEXT NOT NULL,
            player_team INTEGER NOT NULL,
            pre_hit_speed REAL,
            post_hit_speed REAL,
            post_hit_kph REAL,
            FOREIGN KEY(match_id) REFERENCES matches(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS matches_summary(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER UNIQUE,
            session_id INTEGER,
            played_at TEXT,
            user_score INTEGER,
            opponent_score INTEGER,
            result TEXT,
            mode TEXT,
            arena TEXT,
            highlight_icon TEXT,
            highlight_text TEXT,
            highlight_value REAL,
            goals INTEGER,
            shots INTEGER,
            saves INTEGER,
            demos_given INTEGER,
            demos_taken INTEGER,
            playlist TEXT,
            friend_name TEXT,
            FOREIGN KEY(match_id) REFERENCES matches(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_summary_played ON matches_summary(played_at DESC);
    """)
    _migrate_columns(conn)
    ensure_schema(conn)
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_matches_playlist ON matches(playlist)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_matches_mode ON matches(mode)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_matches_guid ON matches(match_guid)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_matches_playlist_id ON matches(playlist_id)")
    except Exception:
        pass
    repair_inverted_results(conn)
    conn.commit()
    conn.close()


def _parse_filter_args() -> Tuple[str, str, Optional[int], Optional[int]]:
    mode = (request.args.get("mode") or "").strip().lower()
    playlist = (request.args.get("playlist") or "").strip()
    days_raw = request.args.get("days", type=int)
    limit_raw = request.args.get("limit", type=int)
    days = days_raw if (days_raw and days_raw > 0) else None
    limit = limit_raw if (limit_raw and limit_raw > 0) else None
    return mode, playlist, days, limit


def _build_where(
    mode: str,
    playlist: str,
    days: Optional[int],
    limit: Optional[int],
    alias: str = "m",
) -> Tuple[str, List[Any]]:
    where: List[str] = []
    params: List[Any] = []
    p = f"{alias}." if alias else ""
    if mode in ("solo", "duo"):
        where.append(f"{p}mode=?")
        params.append(mode)
    if playlist and playlist.lower() not in ("all", "*"):
        where.append(f"COALESCE({p}playlist,'Unknown')=?")
        params.append(playlist)
    if days:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        where.append(f"{p}played_at >= ?")
        params.append(cutoff)
    if limit:
        sub_wh = (" WHERE " + " AND ".join(where).replace(f"{alias}.", "")) if where else ""
        sub_params = list(params)
        where.append(f"{p}id IN (SELECT id FROM matches{sub_wh} ORDER BY played_at DESC LIMIT ?)")
        params.extend(sub_params)
        params.append(limit)
    wh = (" WHERE " + " AND ".join(where)) if where else ""
    return wh, params


@app.route("/")
def index():
    return send_from_directory(str(STATIC_DIR), "index.html")


@app.route("/api/live")
def api_live():
    return jsonify(get_live_snapshot())


@app.route("/api/sessions", methods=["GET", "POST"])
def sessions():
    if request.method == "POST":
        d = request.get_json() or {}
        now = datetime.now(timezone.utc).isoformat()
        conn = get_db()
        # End any empty or lingering active sessions cleanly if user manually starts a new one
        conn.execute(
            "UPDATE sessions SET status='completed', ended_at=COALESCE(ended_at, ?) WHERE status='active'",
            (now,),
        )
        cur = conn.execute(
            "INSERT INTO sessions (started_at, mode, friend_name, notes) VALUES (?,?,?,?)",
            (now, d.get("mode", "solo"), d.get("friend_name"), d.get("notes")),
        )
        sid = cur.lastrowid
        conn.commit()
        conn.close()
        return jsonify({"id": sid, "started_at": now, "mode": d.get("mode", "solo"), "status": "active"}), 201

    conn = get_db()
    rows = conn.execute(
        """SELECT s.*,
                  COUNT(m.id) as match_count,
                  SUM(CASE WHEN m.result='win' THEN 1 ELSE 0 END) as wins,
                  SUM(CASE WHEN m.result='loss' THEN 1 ELSE 0 END) as losses,
                  SUM(CASE WHEN m.result='draw' THEN 1 ELSE 0 END) as draws,
                  COALESCE(SUM(m.user_score), 0) as goals_for,
                  COALESCE(SUM(m.opponent_score), 0) as goals_against,
                  COALESCE(SUM(COALESCE(md.player_goals, m.user_score)), 0) as personal_goals,
                  MIN(m.played_at) as first_match_at,
                  MAX(m.played_at) as last_match_at
           FROM sessions s
           LEFT JOIN matches m ON s.id = m.session_id
           LEFT JOIN match_details md ON md.match_id = m.id
           GROUP BY s.id
           ORDER BY s.started_at DESC"""
    ).fetchall()

    # Fetch chronological match results + playlists per session without N+1 queries
    mrows = conn.execute(
        "SELECT session_id, result, playlist FROM matches ORDER BY played_at ASC, id ASC"
    ).fetchall()
    conn.close()

    by_sid: Dict[int, Dict[str, Any]] = {}
    for mr in mrows:
        sid = mr["session_id"]
        slot = by_sid.setdefault(sid, {"results": [], "playlists": []})
        slot["results"].append(mr["result"])
        pl = mr["playlist"] or "Unknown"
        if pl not in slot["playlists"]:
            slot["playlists"].append(pl)

    out = []
    for r in rows:
        item = dict(r)
        meta = by_sid.get(item["id"], {"results": [], "playlists": []})
        item["recent_results"] = meta["results"][-12:]
        item["playlists"] = meta["playlists"]
        end_ref = item.get("ended_at") or item.get("last_match_at")
        dur_sec = 0
        if item.get("started_at") and end_ref:
            try:
                t0 = datetime.fromisoformat(str(item["started_at"]).replace("Z", "+00:00"))
                t1 = datetime.fromisoformat(str(end_ref).replace("Z", "+00:00"))
                dur_sec = max(0, int((t1 - t0).total_seconds()))
            except Exception:
                dur_sec = 0
        item["duration_sec"] = dur_sec
        out.append(item)
    return jsonify(out)


@app.route("/api/sessions/<int:sid>", methods=["GET", "DELETE"])
def session_detail(sid: int):
    conn = get_db()
    if request.method == "DELETE":
        conn.execute("DELETE FROM matches_summary WHERE session_id=?", (sid,))
        conn.execute("DELETE FROM sessions WHERE id=?", (sid,))
        conn.commit()
        conn.close()
        return jsonify({"deleted": True})

    s = conn.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
    if not s:
        conn.close()
        return jsonify({"error": "Not found"}), 404

    ms = conn.execute(
        """SELECT m.*,
                  COALESCE(md.player_goals, sm.player_goals, sm.goals, m.user_score, 0) AS player_goals,
                  COALESCE(md.player_goals, sm.goals, m.user_score, 0) AS goals,
                  COALESCE(md.player_score, sm.player_score, 0) AS player_score,
                  COALESCE(md.shots, sm.shots, 0) AS shots,
                  COALESCE(md.saves, sm.saves, 0) AS saves,
                  COALESCE(md.assists, 0) AS assists,
                  COALESCE(md.demos_given, sm.demos_given, 0) AS demos_given,
                  COALESCE(md.demos_taken, sm.demos_taken, 0) AS demos_taken,
                  COALESCE(md.is_mvp, sm.is_mvp, 0) AS is_mvp,
                  COALESCE(md.overtime, sm.overtime, 0) AS overtime,
                  COALESCE(md.forfeit, sm.forfeit, 0) AS forfeit,
                  COALESCE(md.boost_avg, 0) AS boost_avg,
                  COALESCE(md.fastest_goal_kph, 0) AS fastest_goal_kph,
                  COALESCE(md.arena, sm.arena) AS arena,
                  sm.highlight_icon, sm.highlight_text, sm.highlight_value
           FROM matches m
           LEFT JOIN match_details md ON md.match_id = m.id
           LEFT JOIN matches_summary sm ON sm.match_id = m.id
           WHERE m.session_id=?
           ORDER BY m.played_at ASC, m.id ASC""",
        (sid,),
    ).fetchall()
    conn.close()

    matches_out = []
    for m in ms:
        mdict = dict(m)
        mdict["arena_name"] = arena_label(mdict.get("arena")) if mdict.get("arena") else ""
        matches_out.append(mdict)

    r = dict(s)
    r["matches"] = matches_out
    r["wins"] = sum(1 for m in matches_out if m["result"] == "win")
    r["losses"] = sum(1 for m in matches_out if m["result"] == "loss")
    return jsonify(r)


@app.route("/api/sessions/<int:sid>/deep")
def session_deep_stats(sid: int):
    conn = get_db()
    md = conn.execute(
        """
        SELECT
            COUNT(*) as total_matches,
            SUM(touches) as total_touches,
            SUM(car_touches) as total_car_touches,
            SUM(shots) as total_shots,
            SUM(saves) as total_saves,
            SUM(assists) as total_assists,
            SUM(demos_given) as total_demos_given,
            SUM(demos_taken) as total_demos_taken,
            SUM(overtime) as total_overtime,
            ROUND(AVG(boost_avg), 1) as avg_boost,
            ROUND(AVG(boost_time_pct), 1) as avg_boost_time,
            ROUND(AVG(supersonic_time_pct), 1) as avg_supersonic_time,
            ROUND(AVG(air_time_pct), 1) as avg_air_time,
            ROUND(AVG(ground_time_pct), 1) as avg_ground_time,
            ROUND(AVG(wall_time_pct), 1) as avg_wall_time,
            ROUND(AVG(powerslide_time_pct), 1) as avg_powerslide_time,
            ROUND(AVG(NULLIF(avg_speed_kph, 0)), 1) as avg_speed_kph,
            ROUND(MAX(max_speed_kph), 1) as max_speed_kph,
            ROUND(AVG(NULLIF(player_score, 0)), 1) as avg_score,
            SUM(COALESCE(is_mvp, 0)) as total_mvps,
            ROUND(MAX(fastest_goal_kph), 1) as all_time_fastest_goal,
            ROUND(AVG(NULLIF(avg_shot_power, 0)), 1) as overall_avg_shot_power,
            SUM(crossbar_hits) as total_crossbars,
            SUM(boost_pads) as total_boost_pads,
            SUM(boost_pills) as total_boost_pills,
            SUM(forfeit) as total_forfeits
        FROM match_details WHERE match_id IN (SELECT id FROM matches WHERE session_id=?)
        """,
        (sid,),
    ).fetchone()
    goals_row = conn.execute(
        """SELECT COALESCE(SUM(COALESCE(md.player_goals, m.user_score)), 0) as personal_goals,
                  COALESCE(SUM(m.user_score), 0) as team_goals
           FROM matches m
           LEFT JOIN match_details md ON md.match_id = m.id
           WHERE m.session_id=?""",
        (sid,),
    ).fetchone()
    conn.close()

    a = dict(md) if md else {}
    pgoals = int(goals_row["personal_goals"] or 0) if goals_row else 0
    tgoals = int(goals_row["team_goals"] or 0) if goals_row else 0
    a["total_goals"] = pgoals
    a["team_goals"] = tgoals
    shots = a.get("total_shots") or 0
    a["shot_accuracy"] = min(round(pgoals / max(shots, 1) * 100, 1), 100.0) if (pgoals > 0 and shots > 0) else 0.0
    return jsonify({"aggregates": {k: (v or 0) for k, v in a.items()}})


@app.route("/api/sessions/<int:sid>/end", methods=["POST"])
def end_session(sid: int):
    conn = get_db()
    s = conn.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
    if not s:
        conn.close()
        return jsonify({"error": "Not found"}), 404
    conn.execute("UPDATE sessions SET status='completed', ended_at=? WHERE id=?", (datetime.now(timezone.utc).isoformat(), sid))
    conn.commit()
    conn.close()
    return jsonify({"ended": True})


@app.route("/api/sessions/<int:sid>/matches", methods=["POST"])
def add_match(sid: int):
    d = request.get_json() or {}
    us, os_ = d.get("user_score"), d.get("opponent_score")
    if us is None or os_ is None:
        return jsonify({"error": "Scores required"}), 400
    result = "win" if us > os_ else ("draw" if us == os_ else "loss")
    conn = get_db()
    srow = conn.execute("SELECT mode FROM sessions WHERE id=?", (sid,)).fetchone()
    if not srow:
        conn.close()
        return jsonify({"error": "Session not found"}), 404
    cur = conn.execute(
        "INSERT INTO matches (session_id, played_at, user_score, opponent_score, result, mode, playlist, manual_override) VALUES (?,?,?,?,?,?,?,1)",
        (sid, datetime.now(timezone.utc).isoformat(), us, os_, result, srow["mode"], d.get("playlist", "Ranked 2v2")),
    )
    mid = cur.lastrowid
    conn.commit()
    conn.close()
    return jsonify({"id": mid, "result": result}), 201


@app.route("/api/matches/<int:mid>", methods=["GET", "PATCH", "DELETE"])
def match_detail(mid: int):
    conn = get_db()
    if request.method == "DELETE":
        conn.execute("DELETE FROM matches_summary WHERE match_id=?", (mid,))
        conn.execute("DELETE FROM matches WHERE id=?", (mid,))
        conn.commit()
        conn.close()
        return jsonify({"deleted": True})

    m = conn.execute("SELECT * FROM matches WHERE id=?", (mid,)).fetchone()
    if not m:
        conn.close()
        return jsonify({"error": "Not found"}), 404

    if request.method == "PATCH":
        d = request.get_json() or {}
        updates = []
        params: List[Any] = []
        if "result" in d and d["result"] in ("win", "loss", "draw"):
            updates.append("result=?")
            params.append(d["result"])
        if "playlist" in d and str(d["playlist"]).strip():
            updates.append("playlist=?")
            params.append(str(d["playlist"]).strip())
        if "tags" in d:
            updates.append("tags=?")
            params.append(str(d["tags"]).strip() or None)
        if "user_score" in d and d["user_score"] is not None:
            updates.append("user_score=?")
            params.append(int(d["user_score"]))
        if "opponent_score" in d and d["opponent_score"] is not None:
            updates.append("opponent_score=?")
            params.append(int(d["opponent_score"]))
        if updates:
            updates.append("manual_override=1")
            params.append(mid)
            conn.execute(f"UPDATE matches SET {', '.join(updates)} WHERE id=?", params)
            # Keep matches_summary & match_details playlist synced
            new_m = conn.execute("SELECT * FROM matches WHERE id=?", (mid,)).fetchone()
            if new_m:
                conn.execute(
                    "UPDATE matches_summary SET result=?, user_score=?, opponent_score=?, playlist=? WHERE match_id=?",
                    (new_m["result"], new_m["user_score"], new_m["opponent_score"], new_m["playlist"], mid),
                )
                conn.execute("UPDATE match_details SET playlist=? WHERE match_id=?", (new_m["playlist"], mid))
            conn.commit()
        updated = conn.execute("SELECT * FROM matches WHERE id=?", (mid,)).fetchone()
        conn.close()
        return jsonify({"updated": True, "match": dict(updated)})

    d = conn.execute("SELECT * FROM match_details WHERE match_id=?", (mid,)).fetchone()
    goals = conn.execute("SELECT * FROM goals WHERE match_id=? ORDER BY id ASC", (mid,)).fetchall()
    conn.close()

    det = dict(d) if d else {}
    players_parsed = []
    if det.get("players_json"):
        try:
            players_parsed = json.loads(det["players_json"])
        except Exception:
            players_parsed = []
    det["players"] = players_parsed
    if det.get("arena"):
        det["arena_name"] = arena_label(det["arena"])

    mdict = dict(m)
    if det.get("arena"):
        mdict["arena_name"] = arena_label(det["arena"])

    return jsonify({"match": mdict, "details": det, "goals": [dict(g) for g in goals]})


@app.route("/api/matches/summaries")
def match_summaries():
    offset = request.args.get("offset", 0, type=int)
    limit = min(request.args.get("limit", 50, type=int), 100)
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM matches_summary").fetchone()[0]
    rows = conn.execute(
        "SELECT * FROM matches_summary ORDER BY played_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    conn.close()
    items = []
    for r in rows:
        item = dict(r)
        if item.get("arena"):
            item["arena_name"] = arena_label(item["arena"])
        items.append(item)
    return jsonify({"summaries": items, "total": total, "offset": offset})


@app.route("/api/stats")
def stats():
    mode, playlist, days, limit = _parse_filter_args()
    wh, params = _build_where(mode, playlist, days, limit, alias="")
    conn = get_db()
    o = dict(
        conn.execute(
            f"SELECT COUNT(*) as total, SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) as wins, SUM(CASE WHEN result='loss' THEN 1 ELSE 0 END) as losses FROM matches{wh}",
            params,
        ).fetchone()
    )
    # Solo / Duo cards always show mode breakdown under selected playlist/days
    s_wh, s_params = _build_where("solo", playlist, days, limit, alias="")
    d_wh, d_params = _build_where("duo", playlist, days, limit, alias="")
    s = dict(
        conn.execute(
            f"SELECT COUNT(*) as total, SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) as wins, SUM(CASE WHEN result='loss' THEN 1 ELSE 0 END) as losses FROM matches{s_wh}",
            s_params,
        ).fetchone()
    )
    d = dict(
        conn.execute(
            f"SELECT COUNT(*) as total, SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) as wins, SUM(CASE WHEN result='loss' THEN 1 ELSE 0 END) as losses FROM matches{d_wh}",
            d_params,
        ).fetchone()
    )

    rec = conn.execute(
        f"SELECT result, user_score, opponent_score, mode, played_at, playlist FROM matches{wh} ORDER BY played_at DESC LIMIT 20",
        params,
    ).fetchall()
    rec_solo = conn.execute(
        f"SELECT result FROM matches{s_wh} ORDER BY played_at DESC LIMIT 20",
        s_params,
    ).fetchall()
    rec_duo = conn.execute(
        f"SELECT result FROM matches{d_wh} ORDER BY played_at DESC LIMIT 20",
        d_params,
    ).fetchall()

    duo_friends = conn.execute(
        """SELECT COALESCE(NULLIF(TRIM(friend_name), ''), 'Random Teammate') as friend_name,
                  COUNT(*) as total,
                  SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) as wins,
                  SUM(CASE WHEN result='loss' THEN 1 ELSE 0 END) as losses
           FROM matches
           WHERE mode='duo'
           GROUP BY COALESCE(NULLIF(TRIM(friend_name), ''), 'Random Teammate')
           ORDER BY total DESC, wins DESC
           LIMIT 10"""
    ).fetchall()

    sc = conn.execute("SELECT COUNT(*) as total FROM sessions").fetchone()["total"]
    cc = conn.execute("SELECT COUNT(*) as total FROM sessions WHERE status='completed'").fetchone()["total"]
    conn.close()

    return jsonify(
        {
            "overall": o,
            "solo": s,
            "duo": d,
            "recent": [dict(r) for r in rec],
            "recent_solo": [r["result"] for r in rec_solo],
            "recent_duo": [r["result"] for r in rec_duo],
            "sessions": {"total": sc, "completed": cc},
            "duo_by_friend": [dict(f) for f in duo_friends],
            "filters": {"mode": mode or "all", "playlist": playlist or "all", "days": days, "limit": limit},
        }
    )


@app.route("/api/stats/deep")
def deep_stats():
    mode, playlist, days, limit = _parse_filter_args()
    wh, params = _build_where(mode, playlist, days, limit, alias="m")
    conn = get_db()
    md = conn.execute(
        f"""
        SELECT
            COUNT(*) as total_matches,
            SUM(md.touches) as total_touches,
            SUM(md.car_touches) as total_car_touches,
            SUM(md.shots) as total_shots,
            SUM(md.saves) as total_saves,
            SUM(md.assists) as total_assists,
            SUM(md.demos_given) as total_demos_given,
            SUM(md.demos_taken) as total_demos_taken,
            SUM(md.overtime) as total_overtime,
            ROUND(AVG(md.boost_avg), 1) as avg_boost,
            ROUND(AVG(md.boost_time_pct), 1) as avg_boost_time,
            ROUND(AVG(md.supersonic_time_pct), 1) as avg_supersonic_time,
            ROUND(AVG(md.air_time_pct), 1) as avg_air_time,
            ROUND(AVG(md.ground_time_pct), 1) as avg_ground_time,
            ROUND(AVG(md.wall_time_pct), 1) as avg_wall_time,
            ROUND(AVG(md.powerslide_time_pct), 1) as avg_powerslide_time,
            ROUND(AVG(NULLIF(md.avg_speed_kph, 0)), 1) as avg_speed_kph,
            ROUND(MAX(md.max_speed_kph), 1) as max_speed_kph,
            ROUND(AVG(NULLIF(md.player_score, 0)), 1) as avg_score,
            SUM(COALESCE(md.is_mvp, 0)) as total_mvps,
            ROUND(MAX(md.fastest_goal_kph), 1) as all_time_fastest_goal,
            ROUND(AVG(NULLIF(md.avg_shot_power, 0)), 1) as overall_avg_shot_power,
            SUM(md.crossbar_hits) as total_crossbars,
            SUM(md.boost_pads) as total_boost_pads,
            SUM(md.boost_pills) as total_boost_pills,
            SUM(md.forfeit) as total_forfeits
        FROM match_details md
        JOIN matches m ON m.id = md.match_id
        {wh}
        """,
        params,
    ).fetchone()

    goals_row = conn.execute(
        f"""SELECT COALESCE(SUM(COALESCE(md.player_goals, m.user_score)), 0) as personal_goals,
                   COALESCE(SUM(m.user_score), 0) as team_goals
            FROM matches m
            LEFT JOIN match_details md ON md.match_id = m.id
            {wh}""",
        params,
    ).fetchone()
    conn.close()

    a = dict(md) if md else {}
    pgoals = int(goals_row["personal_goals"] or 0) if goals_row else 0
    tgoals = int(goals_row["team_goals"] or 0) if goals_row else 0
    a["total_goals"] = pgoals
    a["team_goals"] = tgoals
    shots = a.get("total_shots") or 0
    a["shot_accuracy"] = min(round(pgoals / max(shots, 1) * 100, 1), 100.0) if (pgoals > 0 and shots > 0) else 0.0
    return jsonify(
        {
            "aggregates": {k: (v or 0) for k, v in a.items()},
            "filters": {"mode": mode or "all", "playlist": playlist or "all", "days": days, "limit": limit},
        }
    )


@app.route("/api/stats/analytics")
def stats_analytics():
    mode, playlist, days, limit = _parse_filter_args()
    wh, params = _build_where(mode, playlist, days, limit, alias="m")
    conn = get_db()

    # Chronological match rows for trend + streaks
    rows = conn.execute(
        f"""SELECT m.id, m.played_at, m.result, m.user_score, m.opponent_score, m.playlist,
                   COALESCE(md.player_goals, m.user_score) as player_goals,
                   COALESCE(md.boost_avg, 0) as boost_avg,
                   md.arena
            FROM matches m
            LEFT JOIN match_details md ON md.match_id = m.id
            {wh}
            ORDER BY m.played_at ASC, m.id ASC""",
        params,
    ).fetchall()

    # Arenas breakdown
    arena_rows = conn.execute(
        f"""SELECT COALESCE(NULLIF(md.arena, ''), 'Unknown') as arena,
                   COUNT(*) as total,
                   SUM(CASE WHEN m.result='win' THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN m.result='loss' THEN 1 ELSE 0 END) as losses
            FROM matches m
            LEFT JOIN match_details md ON md.match_id = m.id
            {wh}
            GROUP BY COALESCE(NULLIF(md.arena, ''), 'Unknown')
            ORDER BY total DESC
            LIMIT 12""",
        params,
    ).fetchall()

    # Playlists breakdown
    pl_rows = conn.execute(
        f"""SELECT COALESCE(NULLIF(m.playlist, ''), 'Unknown') as playlist,
                   COUNT(*) as total,
                   SUM(CASE WHEN m.result='win' THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN m.result='loss' THEN 1 ELSE 0 END) as losses
            FROM matches m
            {wh}
            GROUP BY COALESCE(NULLIF(m.playlist, ''), 'Unknown')
            ORDER BY total DESC""",
        params,
    ).fetchall()
    conn.close()

    # Streaks over full filtered sequence
    best_win = 0
    worst_loss = 0
    run_w = 0
    run_l = 0
    for r in rows:
        res = r["result"]
        if res == "win":
            run_w += 1
            run_l = 0
            if run_w > best_win:
                best_win = run_w
        elif res == "loss":
            run_l += 1
            run_w = 0
            if run_l > worst_loss:
                worst_loss = run_l
        else:
            run_w = 0
            run_l = 0

    current_type = "none"
    current_len = 0
    if rows:
        last_res = rows[-1]["result"]
        if last_res in ("win", "loss"):
            current_type = last_res
            for r in reversed(rows):
                if r["result"] == last_res:
                    current_len += 1
                else:
                    break

    # Timeline (last 30 matches chronologically with rolling WR over last 10)
    tail = rows[-30:]
    timeline = []
    window_results: List[str] = []
    for r in tail:
        window_results.append(r["result"])
        if len(window_results) > 10:
            window_results.pop(0)
        w_cnt = sum(1 for x in window_results if x == "win")
        rolling_wr = round(w_cnt / len(window_results) * 100, 1)
        timeline.append(
            {
                "id": r["id"],
                "played_at": r["played_at"],
                "result": r["result"],
                "user_score": r["user_score"],
                "opponent_score": r["opponent_score"],
                "player_goals": r["player_goals"],
                "goal_diff": (r["user_score"] or 0) - (r["opponent_score"] or 0),
                "rolling_wr": rolling_wr,
                "boost_avg": r["boost_avg"],
                "playlist": r["playlist"] or "Unknown",
            }
        )

    arenas = []
    for ar in arena_rows:
        tot = ar["total"] or 0
        wins = ar["wins"] or 0
        raw_ar = ar["arena"]
        arenas.append(
            {
                "arena": raw_ar,
                "name": arena_label(raw_ar) if raw_ar != "Unknown" else "Unknown Arena",
                "total": tot,
                "wins": wins,
                "losses": ar["losses"] or 0,
                "winrate": round(wins / tot * 100, 1) if tot else 0.0,
            }
        )

    playlists = []
    for pr in pl_rows:
        tot = pr["total"] or 0
        wins = pr["wins"] or 0
        playlists.append(
            {
                "playlist": pr["playlist"],
                "total": tot,
                "wins": wins,
                "losses": pr["losses"] or 0,
                "winrate": round(wins / tot * 100, 1) if tot else 0.0,
            }
        )

    wvl = coach.win_vs_loss_diff(mode=mode, playlist=playlist, days=days)

    return jsonify(
        {
            "timeline": timeline,
            "arenas": arenas,
            "playlists": playlists,
            "win_vs_loss": wvl,
            "streaks": {
                "current_type": current_type,
                "current_len": current_len,
                "best_win": best_win,
                "worst_loss": worst_loss,
            },
        }
    )


@app.route("/api/listener-status")
def listener_status():
    t = app.config.get("listener_thread")
    if t and t.is_alive():
        sp = BASE_DIR / "listener_status.json"
        st: Dict[str, Any] = {"state": "running", "thread": t.name}
        if sp.exists():
            try:
                st.update(json.loads(sp.read_text(encoding="utf-8")))
            except Exception:
                pass
        return jsonify(st)
    return jsonify({"state": "stopped"})


@app.route("/api/config", methods=["GET", "POST"])
def player_config():
    c = load_config()
    p = c.get("player") or {}
    tr = normalize_tracking_config(c.get("tracking"))
    if request.method == "POST":
        d = request.get_json() or {}
        new_p = {
            "name": str(d.get("name", p.get("name", "")) or "").strip(),
            "aliases": [str(a).strip() for a in d.get("aliases", p.get("aliases", [])) if str(a).strip()],
            "primary_ids": [str(x).strip() for x in d.get("primary_ids", p.get("primary_ids", [])) if str(x).strip()],
            "friends": [str(f).strip() for f in d.get("friends", p.get("friends", [])) if str(f).strip()],
        }
        new_tr = normalize_tracking_config(d.get("tracking") if "tracking" in d else tr)
        c["player"] = new_p
        c["tracking"] = new_tr
        save_config(c)
        return jsonify({**new_p, "tracking": new_tr})

    return jsonify(
        {
            "name": p.get("name", ""),
            "aliases": p.get("aliases", []),
            "primary_ids": p.get("primary_ids", []),
            "friends": p.get("friends", []),
            "tracking": tr,
        }
    )


@app.route("/api/status")
def api_status():
    c = load_config()
    tr = normalize_tracking_config(c.get("tracking"))
    return jsonify(
        {
            "ok": True,
            "app": f"RL Tracker v{APP_VERSION}",
            "version": APP_VERSION,
            "edition": APP_EDITION,
            "player_configured": bool((c.get("player") or {}).get("name")),
            "tracking_scope": tr["scope"],
        }
    )


def _find_non_competitive_matches(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, session_id, played_at, user_score, opponent_score, result, playlist, playlist_id FROM matches ORDER BY played_at DESC"
    ).fetchall()
    bad = []
    for r in rows:
        pid = r["playlist_id"]
        pname = r["playlist"] or ""
        if not is_competitive_playlist(pid, pname):
            bad.append(dict(r))
    return bad


@app.route("/api/diagnostics")
def api_diagnostics():
    ini = diagnose_rl_ini()
    log_lines: List[str] = []
    if LOG_PATH.exists():
        try:
            lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
            log_lines = lines[-45:]
        except Exception:
            pass
    conn = get_db()
    total_matches = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
    total_sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    non_comp = _find_non_competitive_matches(conn)
    conn.close()
    return jsonify(
        {
            "ini": ini,
            "log_tail": log_lines,
            "db": {
                "path": str(DB_PATH),
                "total_matches": total_matches,
                "total_sessions": total_sessions,
                "non_competitive_count": len(non_comp),
            },
        }
    )


@app.route("/api/maintenance/cleanup-non-competitive", methods=["POST"])
def maintenance_cleanup_non_competitive():
    d = request.get_json() or {}
    dry_run = bool(d.get("dry_run", True))
    del_empty = bool(d.get("delete_empty_sessions", True))
    conn = get_db()
    bad = _find_non_competitive_matches(conn)
    deleted_matches = 0
    deleted_sessions = 0
    if not dry_run and bad:
        ids = [b["id"] for b in bad]
        placeholders = ",".join("?" for _ in ids)
        conn.execute(f"DELETE FROM matches_summary WHERE match_id IN ({placeholders})", ids)
        cur = conn.execute(f"DELETE FROM matches WHERE id IN ({placeholders})", ids)
        deleted_matches = cur.rowcount or len(ids)
        if del_empty:
            cur_s = conn.execute(
                "DELETE FROM sessions WHERE status='completed' AND id NOT IN (SELECT DISTINCT session_id FROM matches)"
            )
            deleted_sessions = cur_s.rowcount or 0
        conn.commit()
    conn.close()
    return jsonify(
        {
            "dry_run": dry_run,
            "count": len(bad),
            "samples": bad[:20],
            "deleted_matches": deleted_matches,
            "deleted_sessions": deleted_sessions,
        }
    )


@app.route("/api/maintenance/repair-results", methods=["POST"])
def maintenance_repair_results():
    conn = get_db()
    flipped = repair_inverted_results(conn)
    conn.commit()
    conn.close()
    return jsonify({"repaired_count": len(flipped), "repaired_ids": flipped})


@app.route("/api/maintenance/backup-db")
def maintenance_backup_db():
    if not DB_PATH.exists():
        return jsonify({"error": "Database not found"}), 404
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".db")
    _os.close(tmp_fd)
    try:
        src = sqlite3.connect(str(DB_PATH))
        dst = sqlite3.connect(tmp_path)
        src.backup(dst)
        dst.close()
        src.close()
        data = Path(tmp_path).read_bytes()
    finally:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    return Response(
        data,
        mimetype="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename=RL-Tracker-backup-{stamp}.db"},
    )


# ====== Auto-update check ======
def _parse_semver(v: str) -> Tuple[int, int, int]:
    s = str(v).strip().lstrip("vV")
    parts: List[int] = []
    for p in s.split("."):
        num = ""
        for ch in p:
            if ch.isdigit():
                num += ch
            else:
                break
        parts.append(int(num) if num else 0)
    while len(parts) < 3:
        parts.append(0)
    return (parts[0], parts[1], parts[2])


@app.route("/api/check-update")
def check_update():
    import urllib.error
    import urllib.request

    try:
        req = urllib.request.Request(
            GITHUB_RELEASES_API,
            headers={"User-Agent": f"RocketTracker/{APP_VERSION}", "Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return jsonify({"ok": False, "error": f"GitHub API returned HTTP {e.code}", "current": APP_VERSION})
    except Exception as e:
        return jsonify({"ok": False, "error": f"Cannot reach GitHub ({e.__class__.__name__})", "current": APP_VERSION})

    tag = data.get("tag_name", "") or ""
    latest = tag.lstrip("vV")
    download_url = None
    for a in data.get("assets", []) or []:
        if (a.get("name") or "").lower().endswith(".zip"):
            download_url = a.get("browser_download_url")
            break
    if not download_url:
        download_url = data.get("html_url")

    return jsonify(
        {
            "ok": True,
            "current": APP_VERSION,
            "latest": latest,
            "latest_tag": tag,
            "update_available": _parse_semver(latest) > _parse_semver(APP_VERSION),
            "release_name": data.get("name") or tag,
            "release_url": data.get("html_url"),
            "download_url": download_url,
            "release_notes": data.get("body") or "",
            "published_at": data.get("published_at"),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
    )


@app.route("/api/update", methods=["POST"])
def update_tracker():
    import shutil
    import urllib.error
    import urllib.request
    import zipfile

    try:
        req = urllib.request.Request(
            GITHUB_RELEASES_API,
            headers={"User-Agent": f"RocketTracker/{APP_VERSION}", "Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            release = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return jsonify({"ok": False, "error": f"GitHub API returned HTTP {e.code}"}), 502
    except Exception as e:
        return jsonify({"ok": False, "error": f"Cannot reach GitHub ({e.__class__.__name__}: {e})"}), 502

    zip_url = None
    for a in release.get("assets", []) or []:
        if (a.get("name") or "").lower().endswith(".zip"):
            zip_url = a.get("browser_download_url")
            break
    if not zip_url:
        zip_url = release.get("zipball_url")
    if not zip_url:
        return jsonify({"ok": False, "error": "No downloadable .zip asset found in latest release"}), 404

    tag = release.get("tag_name", "unknown")
    new_version = tag.lstrip("vV")

    try:
        req = urllib.request.Request(zip_url, headers={"User-Agent": f"RocketTracker/{APP_VERSION}"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            zip_bytes = resp.read()
    except Exception as e:
        return jsonify({"ok": False, "error": f"Download failed ({e.__class__.__name__}: {e})"}), 502

    tmp_root = Path(tempfile.gettempdir()) / "rl-tracker-update"
    if tmp_root.exists():
        shutil.rmtree(str(tmp_root), ignore_errors=True)
    tmp_root.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            zf.extractall(str(tmp_root))
    except Exception as e:
        shutil.rmtree(str(tmp_root), ignore_errors=True)
        return jsonify({"ok": False, "error": f"ZIP extraction failed ({e})"}), 500

    children = list(tmp_root.iterdir())
    if len(children) == 1 and children[0].is_dir():
        tmp_root = children[0]

    new_exe = next(tmp_root.glob("*.exe"), None)
    if new_exe:
        for fname in ["data-v2.db", "config.yaml"]:
            src = BASE_DIR / fname
            if src.exists():
                try:
                    shutil.copy2(str(src), str(tmp_root / fname))
                except Exception:
                    pass

        bat_path = tmp_root / "updater.bat"
        exe_name = new_exe.name
        bat_path.write_text(
            f'@echo off\r\n'
            f'timeout /t 2 /nobreak >nul\r\n'
            f'taskkill /f /im "RL-Tracker*" >nul 2>&1\r\n'
            f'xcopy /Y /E "%~dp0*" "{BASE_DIR}\\\\" >nul\r\n'
            f'start "" "{BASE_DIR}\\\\{exe_name}"\r\n'
            f'rmdir /s /q "%~dp0" >nul 2>&1\r\n'
            f'del "%~f0" >nul 2>&1\r\n'
        )
        try:
            _os.startfile(str(bat_path))
        except Exception:
            import subprocess

            subprocess.Popen(["cmd", "/c", str(bat_path)], shell=True)

        def _do_exit():
            import time as _t

            _t.sleep(0.5)
            _os._exit(0)

        _th.Thread(target=_do_exit, daemon=True).start()
        return jsonify({"ok": True, "message": f"Updating to v{new_version}...", "new_version": new_version})

    app_py = next(tmp_root.glob("**/app.py"), None)
    if not app_py:
        shutil.rmtree(str(tmp_root.parent), ignore_errors=True)
        return jsonify({"ok": False, "error": "No app.py or .exe found in downloaded archive"}), 500

    extract_root = app_py.parent
    copied = 0
    for src_file in extract_root.rglob("*"):
        if src_file.is_dir():
            continue
        rel = src_file.relative_to(extract_root)
        if rel.name in ("data-v2.db", "config.yaml"):
            continue
        dst = BASE_DIR / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src_file), str(dst))
        copied += 1

    shutil.rmtree(str(tmp_root.parent), ignore_errors=True)
    return jsonify({"ok": True, "message": f"Updated to v{new_version} ({copied} files). Restart app.", "new_version": new_version, "source_update": True})


@app.route("/api/rl-config", methods=["GET"])
def rl_config_status():
    diag = diagnose_rl_ini()
    return jsonify(
        {
            "config_dir_found": diag["config_dir_found"],
            "ini_exists": diag["ini_exists"],
            "ini_correct": diag["ini_correct"],
            "ini_read_by_rl": diag["ini_read_by_rl"],
            "port_49123_open": diag["port_49123_open"],
            "default_ini_issues": diag["default_ini_issues"],
        }
    )


@app.route("/api/rl-config", methods=["POST"])
def rl_config_create():
    ok = ensure_tastatsapi_ini()
    ensure_default_statsapi_ini()
    return jsonify({"created": ok, "message": "TAStatsAPI.ini created/updated" if ok else "Could not find RL Config directory"})


@app.route("/api/quit", methods=["POST"])
def quit_tracker():
    ev = app.config.get("listener_stop_event")
    if ev:
        ev.set()
    app.config["_should_exit"] = True
    t = _th.Timer(0.3, lambda: _os._exit(0))
    t.daemon = False
    t.start()
    return jsonify({"shutdown": True, "message": "Tracker shutting down..."})


@app.route("/api/coach/match/<int:match_id>")
def coach_match(match_id: int):
    return jsonify(coach.analyze_match(match_id))


@app.route("/api/coach/session/<int:session_id>")
def coach_session(session_id: int):
    return jsonify(coach.get_session_anomalies(session_id))


@app.route("/api/coach/records")
def coach_records():
    return jsonify(coach.get_all_records())


@app.route("/api/coach/session/<int:session_id>/report")
def coach_session_report(session_id: int):
    cfg = load_config()
    pname = (cfg.get("player") or {}).get("name") or "You"
    return jsonify(coach.session_report(session_id, player_name=pname))


@app.route("/api/stats/playlists")
def stats_playlists():
    conn = get_db()
    rows = conn.execute(
        "SELECT COALESCE(NULLIF(playlist,''), 'Unknown') as playlist, COUNT(*) as total, "
        "SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) as wins, "
        "SUM(CASE WHEN result='loss' THEN 1 ELSE 0 END) as losses "
        "FROM matches GROUP BY COALESCE(NULLIF(playlist,''), 'Unknown') ORDER BY total DESC"
    ).fetchall()
    conn.close()
    return jsonify({"playlists": [dict(r) for r in rows]})


@app.route("/api/sessions/<int:sid>/export.csv")
def session_export_csv(sid: int):
    from session_card import session_to_csv_rows

    conn = get_db()
    s = conn.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
    if not s:
        conn.close()
        return jsonify({"error": "Not found"}), 404
    rows = conn.execute(
        """SELECT m.id as match_id, m.played_at, m.result, m.user_score, m.opponent_score, m.mode,
                  COALESCE(md.player_goals, sm.player_goals, sm.goals, m.user_score, 0) as player_goals,
                  COALESCE(sm.goals, m.user_score, 0) as goals,
                  COALESCE(sm.shots, md.shots, 0) as shots,
                  COALESCE(sm.saves, md.saves, 0) as saves,
                  COALESCE(sm.demos_given, md.demos_given, 0) as demos_given,
                  COALESCE(sm.demos_taken, md.demos_taken, 0) as demos_taken,
                  COALESCE(m.playlist, md.playlist, sm.playlist, 'Unknown') as playlist,
                  COALESCE(md.arena, sm.arena) as arena
           FROM matches m
           LEFT JOIN match_details md ON md.match_id=m.id
           LEFT JOIN matches_summary sm ON sm.match_id=m.id
           WHERE m.session_id=? ORDER BY m.played_at ASC""",
        (sid,),
    ).fetchall()
    conn.close()
    csv_text = session_to_csv_rows([dict(r) for r in rows])
    return Response(
        csv_text,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=session-{sid}.csv"},
    )


@app.route("/api/sessions/<int:sid>/card.png")
def session_card_png(sid: int):
    from session_card import render_session_card

    conn = get_db()
    s = conn.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
    if not s:
        conn.close()
        return jsonify({"error": "Not found"}), 404
    rows = conn.execute(
        """SELECT m.*,
                  COALESCE(md.player_goals, sm.player_goals, sm.goals, m.user_score, 0) as player_goals,
                  COALESCE(sm.goals, m.user_score, 0) as goals,
                  COALESCE(sm.shots, md.shots, 0) as shots,
                  COALESCE(sm.saves, md.saves, 0) as saves,
                  COALESCE(sm.demos_given, md.demos_given, 0) as demos_given,
                  COALESCE(sm.demos_taken, md.demos_taken, 0) as demos_taken,
                  COALESCE(md.fastest_goal_kph, 0) as fastest_goal_kph,
                  COALESCE(m.playlist, md.playlist, sm.playlist, 'Unknown') as playlist
           FROM matches m
           LEFT JOIN match_details md ON md.match_id=m.id
           LEFT JOIN matches_summary sm ON sm.match_id=m.id
           WHERE m.session_id=? ORDER BY m.played_at ASC""",
        (sid,),
    ).fetchall()
    conn.close()
    cfg = load_config()
    pname = (cfg.get("player") or {}).get("name") or "Player"
    try:
        report = coach.session_report(sid, player_name=pname)
    except Exception:
        report = {}
    logo = STATIC_DIR / "logo.png"
    try:
        png = render_session_card(dict(s), [dict(r) for r in rows], coach=report, logo_path=logo, player_name=pname)
    except Exception as e:
        return jsonify({"error": f"Card render failed: {e}"}), 500
    try:
        exp = BASE_DIR / "exports"
        exp.mkdir(exist_ok=True)
        (exp / f"session-{sid}.png").write_bytes(png)
    except Exception:
        pass
    return Response(png, mimetype="image/png", headers={"Content-Disposition": f"inline; filename=session-{sid}.png"})
