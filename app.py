"""
Rocket League Tracker - Flask API (Portable Edition)
"""
import json, sqlite3, os as _os, sys, threading as _th
from datetime import datetime, timezone
from pathlib import Path
import yaml
from flask import Flask, jsonify, request, send_from_directory

# DB persistence: store next to exe
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.yaml"
DB_PATH = BASE_DIR / "data.db"

app = Flask(__name__, static_folder="dashboard", static_url_path="")

@app.after_request
def cors(r):
    r.headers["Access-Control-Allow-Origin"] = "*"
    r.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    r.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return r

def load_config():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f: return yaml.safe_load(f)
        except Exception: return {}
    return {}

def save_config(c):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f: yaml.dump(c, f, sort_keys=False)

def get_db():
    conn = sqlite3.connect(str(DB_PATH)); conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL"); conn.execute("PRAGMA synchronous=OFF"); conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions(id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL, ended_at TEXT, status TEXT NOT NULL DEFAULT 'active', mode TEXT NOT NULL DEFAULT 'solo', friend_name TEXT, notes TEXT);
        CREATE TABLE IF NOT EXISTS matches(id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER NOT NULL, played_at TEXT NOT NULL, user_score INTEGER NOT NULL, opponent_score INTEGER NOT NULL, result TEXT NOT NULL, mode TEXT NOT NULL DEFAULT 'solo', FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS match_details(id INTEGER PRIMARY KEY AUTOINCREMENT, match_id INTEGER UNIQUE NOT NULL, arena TEXT, overtime INTEGER DEFAULT 0, touches INTEGER DEFAULT 0, car_touches INTEGER DEFAULT 0, shots INTEGER DEFAULT 0, saves INTEGER DEFAULT 0, assists INTEGER DEFAULT 0, demos_given INTEGER DEFAULT 0, demos_taken INTEGER DEFAULT 0, boost_avg REAL DEFAULT 0, boost_time_pct REAL DEFAULT 0, supersonic_time_pct REAL DEFAULT 0, ground_time_pct REAL DEFAULT 0, air_time_pct REAL DEFAULT 0, wall_time_pct REAL DEFAULT 0, fastest_goal_kph REAL DEFAULT 0, avg_shot_power REAL DEFAULT 0, time_remaining_sec INTEGER, FOREIGN KEY(match_id) REFERENCES matches(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS goals(id INTEGER PRIMARY KEY AUTOINCREMENT, match_id INTEGER NOT NULL, scored_at TEXT NOT NULL, scorer TEXT NOT NULL, assister TEXT, team_num INTEGER NOT NULL, speed_kph REAL, time_remaining_sec INTEGER, FOREIGN KEY(match_id) REFERENCES matches(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS ball_hits(id INTEGER PRIMARY KEY AUTOINCREMENT, match_id INTEGER NOT NULL, hit_at TEXT NOT NULL, player TEXT NOT NULL, player_team INTEGER NOT NULL, pre_hit_speed REAL, post_hit_speed REAL, post_hit_kph REAL, FOREIGN KEY(match_id) REFERENCES matches(id) ON DELETE CASCADE);
    """)
    conn.commit(); conn.close()

@app.route("/")
def index(): return send_from_directory("dashboard", "index.html")

@app.route("/api/sessions", methods=["GET", "POST"])
def sessions():
    if request.method == "POST":
        d = request.get_json() or {}
        conn = get_db()
        cur = conn.execute("INSERT INTO sessions (started_at, mode, friend_name, notes) VALUES (?,?,?,?)", (datetime.now(timezone.utc).isoformat(), d.get("mode","solo"), d.get("friend_name"), d.get("notes")))
        sid = cur.lastrowid; conn.commit(); conn.close()
        return jsonify({"id": sid, "started_at": datetime.now(timezone.utc).isoformat(), "mode": d.get("mode","solo"), "status": "active"}), 201
    conn = get_db()
    rows = conn.execute("SELECT s.*, COUNT(m.id) as match_count, SUM(CASE WHEN m.result='win' THEN 1 ELSE 0 END) as wins, SUM(CASE WHEN m.result='loss' THEN 1 ELSE 0 END) as losses FROM sessions s LEFT JOIN matches m ON s.id=m.session_id GROUP BY s.id ORDER BY s.started_at DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/sessions/<int:sid>", methods=["GET", "DELETE"])
def session_detail(sid):
    conn = get_db()
    if request.method == "DELETE":
        conn.execute("DELETE FROM sessions WHERE id=?", (sid,)); conn.commit(); conn.close()
        return jsonify({"deleted": True})
    s = conn.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
    if not s: conn.close(); return jsonify({"error": "Not found"}), 404
    ms = conn.execute("SELECT * FROM matches WHERE session_id=? ORDER BY played_at ASC", (sid,)).fetchall()
    conn.close()
    r = dict(s); r["matches"] = [dict(m) for m in ms]; r["wins"] = sum(1 for m in ms if m["result"]=="win"); r["losses"] = sum(1 for m in ms if m["result"]=="loss")
    return jsonify(r)

@app.route("/api/sessions/<int:sid>/end", methods=["POST"])
def end_session(sid):
    conn = get_db()
    s = conn.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
    if not s: conn.close(); return jsonify({"error": "Not found"}), 404
    conn.execute("UPDATE sessions SET status='completed', ended_at=? WHERE id=?", (datetime.now(timezone.utc).isoformat(), sid))
    conn.commit(); conn.close()
    return jsonify({"ended": True})

@app.route("/api/sessions/<int:sid>/matches", methods=["POST"])
def add_match(sid):
    d = request.get_json() or {}
    us, os_ = d.get("user_score"), d.get("opponent_score")
    if us is None or os_ is None: return jsonify({"error": "Scores required"}), 400
    try:
        us, os_ = int(us), int(os_)
    except (ValueError, TypeError):
        return jsonify({"error": "Scores must be integers"}), 400
    if us == os_: return jsonify({"error": "Ties are not supported — Rocket League matches always have a winner"}), 400
    result = "win" if us > os_ else "loss"
    conn = get_db()
    srow = conn.execute("SELECT mode FROM sessions WHERE id=?", (sid,)).fetchone()
    if not srow:
        conn.close()
        return jsonify({"error": "Session not found"}), 404
    cur = conn.execute("INSERT INTO matches (session_id, played_at, user_score, opponent_score, result, mode) VALUES (?,?,?,?,?,?)", (sid, datetime.now(timezone.utc).isoformat(), us, os_, result, srow["mode"]))
    mid = cur.lastrowid; conn.commit(); conn.close()
    return jsonify({"id": mid, "result": result}), 201

@app.route("/api/matches/<int:mid>", methods=["GET", "DELETE"])
def match_detail(mid):
    conn = get_db()
    if request.method == "DELETE":
        conn.execute("DELETE FROM matches WHERE id=?", (mid,)); conn.commit(); conn.close()
        return jsonify({"deleted": True})
    m = conn.execute("SELECT * FROM matches WHERE id=?", (mid,)).fetchone()
    if not m: conn.close(); return jsonify({"error": "Not found"}), 404
    d = conn.execute("SELECT * FROM match_details WHERE match_id=?", (mid,)).fetchone()
    goals = conn.execute("SELECT * FROM goals WHERE match_id=?", (mid,)).fetchall()
    conn.close()
    return jsonify({
        "match": dict(m),
        "details": dict(d) if d else {},
        "goals": [dict(g) for g in goals]
    })

@app.route("/api/stats")
def stats():
    conn = get_db()
    o = dict(conn.execute("SELECT COUNT(*) as total, SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) as wins, SUM(CASE WHEN result='loss' THEN 1 ELSE 0 END) as losses FROM matches").fetchone())
    s = dict(conn.execute("SELECT COUNT(*) as total, SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) as wins, SUM(CASE WHEN result='loss' THEN 1 ELSE 0 END) as losses FROM matches WHERE mode='solo'").fetchone())
    d = dict(conn.execute("SELECT COUNT(*) as total, SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) as wins, SUM(CASE WHEN result='loss' THEN 1 ELSE 0 END) as losses FROM matches WHERE mode='duo'").fetchone())
    rec = conn.execute("SELECT result, user_score, opponent_score, mode, played_at FROM matches ORDER BY played_at DESC, id DESC LIMIT 20").fetchall()
    sc = conn.execute("SELECT COUNT(*) as total FROM sessions").fetchone()["total"]; cc = conn.execute("SELECT COUNT(*) as total FROM sessions WHERE status='completed'").fetchone()["total"]
    conn.close()
    return jsonify({"overall": o, "solo": s, "duo": d, "recent": [dict(r) for r in rec], "sessions": {"total": sc, "completed": cc}, "duo_by_friend": []})

@app.route("/api/listener-status")
def listener_status():
    t = app.config.get("listener_thread")
    if t and t.is_alive():
        sp = BASE_DIR / "listener_status.json"; st = {"state": "running", "thread": t.name}
        if sp.exists():
            try: st.update(json.loads(sp.read_text()))
            except Exception: pass
        return jsonify(st)
    return jsonify({"state": "stopped"})

@app.route("/api/config", methods=["GET", "POST"])
def player_config():
    c = load_config(); p = c.get("player", {})
    if request.method == "POST":
        d = request.get_json() or {}; c["player"] = {"name": d.get("name",""), "friends": d.get("friends",[])}; save_config(c)
        return jsonify(c["player"])
    return jsonify(p)

@app.route("/api/status")
def api_status():
    c = load_config()
    return jsonify({"ok": True, "app": "RL Tracker v1.0.4", "version": "1.0.4", "player_configured": bool(c.get("player", {}).get("name"))})

@app.route("/api/rl-config", methods=["GET"])
def rl_config_status():
    from listener import find_rl_config_dir
    cd = find_rl_config_dir(); r = {"config_dir_found": cd is not None, "ini_exists": False, "ini_correct": False}
    if cd:
        ip = cd / "TAStatsAPI.ini"; r["ini_exists"] = ip.exists()
        if ip.exists():
            try:
                r["ini_correct"] = "PacketSendRate=30" in ip.read_text()
            except Exception:
                r["ini_correct"] = False
    return jsonify(r)

@app.route("/api/rl-config", methods=["POST"])
def rl_config_create():
    from listener import ensure_tastatsapi_ini
    ok = ensure_tastatsapi_ini()
    return jsonify({"created": ok, "message": "TAStatsAPI.ini created" if ok else "Could not create"})

@app.route("/api/stats/deep")
def deep_stats():
    conn = get_db()
    md = conn.execute("""
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
            MAX(fastest_goal_kph) as all_time_fastest_goal,
            ROUND(AVG(avg_shot_power), 1) as overall_avg_shot_power
        FROM match_details
    """).fetchone()
    total_goals = conn.execute("SELECT COUNT(*) as cnt FROM goals").fetchone()["cnt"]
    total_user_goals = conn.execute("SELECT SUM(user_score) FROM matches").fetchone()[0] or 0
    conn.close()

    a = dict(md) if md else {}
    a["total_goals"] = total_user_goals  # Only user's goals, not all match goals
    # Shot accuracy = user goals / user shots * 100
    a["shot_accuracy"] = min(round(total_user_goals / max(a.get("total_shots") or 1, 1) * 100, 1), 100.0) if total_user_goals > 0 else 0
    return jsonify({"aggregates": {k: (v or 0) for k, v in a.items()}})

@app.route("/api/sessions/<int:sid>/deep")
def session_deep_stats(sid):
    conn = get_db()
    md = conn.execute("""
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
            MAX(fastest_goal_kph) as all_time_fastest_goal,
            ROUND(AVG(avg_shot_power), 1) as overall_avg_shot_power
        FROM match_details WHERE match_id IN (SELECT id FROM matches WHERE session_id=?)
    """, (sid,)).fetchone()
    total_user_goals = conn.execute("SELECT SUM(user_score) FROM matches WHERE session_id=?", (sid,)).fetchone()[0] or 0
    conn.close()

    a = dict(md) if md else {}
    a["total_goals"] = total_user_goals
    a["shot_accuracy"] = min(round(total_user_goals / max(a.get("total_shots") or 1, 1) * 100, 1), 100.0) if total_user_goals > 0 else 0
    return jsonify({"aggregates": {k: (v or 0) for k, v in a.items()}})

@app.route("/api/quit", methods=["POST"])
def quit_tracker():
    ev = app.config.get("listener_stop_event")
    if ev: ev.set()
    def _exit(): import time as _t; _t.sleep(0.5); _os._exit(0)
    _th.Thread(target=_exit, daemon=True).start()
    return jsonify({"shutdown": True, "message": "Tracker shutting down..."})
