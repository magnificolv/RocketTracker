"""
Rocket League Tracker - Flask API (Portable Edition)
"""
import json, sqlite3, os as _os, sys, io, threading as _th
from datetime import datetime, timezone
from pathlib import Path
import yaml
from flask import Flask, jsonify, request, send_from_directory
from coach import CoachEngine

# DB persistence: store next to exe
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.yaml"
DB_PATH = BASE_DIR / "data-v2.db"

# v1.1: Auto-update check against GitHub releases.
APP_VERSION = "2.0.2"
GITHUB_REPO = "magnificolv/RocketTracker"
GITHUB_RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

app = Flask(__name__, static_folder="dashboard", static_url_path="")

coach = CoachEngine(str(DB_PATH))

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
        CREATE TABLE IF NOT EXISTS matches_summary(id INTEGER PRIMARY KEY AUTOINCREMENT, match_id INTEGER UNIQUE, session_id INTEGER, played_at TEXT, user_score INTEGER, opponent_score INTEGER, result TEXT, mode TEXT, arena TEXT, highlight_icon TEXT, highlight_text TEXT, highlight_value REAL, goals INTEGER, shots INTEGER, saves INTEGER, demos_given INTEGER, demos_taken INTEGER, FOREIGN KEY(match_id) REFERENCES matches(id) ON DELETE CASCADE);
        CREATE INDEX IF NOT EXISTS idx_summary_played ON matches_summary(played_at DESC);
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
    result = "win" if us > os_ else "loss"
    conn = get_db()
    cur = conn.execute("INSERT INTO matches (session_id, played_at, user_score, opponent_score, result, mode) VALUES (?,?,?,?,?,?)", (sid, datetime.now(timezone.utc).isoformat(), us, os_, result, conn.execute("SELECT mode FROM sessions WHERE id=?", (sid,)).fetchone()["mode"]))
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

@app.route("/api/matches/summaries")
def match_summaries():
    """Warm-storage endpoint: paginated match summaries for History tab.
    Hot layer (0-50): existing full-match queries.
    Warm layer (51-200): this endpoint, ~50ms.
    Cold layer (201+): indexed SQLite, lazy-loaded by offset.
    """
    offset = request.args.get("offset", 0, type=int)
    limit = request.args.get("limit", 50, type=int)
    limit = min(limit, 100)  # hard cap

    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM matches_summary").fetchone()[0]
    rows = conn.execute(
        "SELECT * FROM matches_summary ORDER BY played_at DESC LIMIT ? OFFSET ?",
        (limit, offset)
    ).fetchall()
    conn.close()

    return jsonify({
        "summaries": [dict(r) for r in rows],
        "total": total,
        "offset": offset,
    })


@app.route("/api/stats")
def stats():
    conn = get_db()
    o = dict(conn.execute("SELECT COUNT(*) as total, SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) as wins, SUM(CASE WHEN result='loss' THEN 1 ELSE 0 END) as losses FROM matches").fetchone())
    s = dict(conn.execute("SELECT COUNT(*) as total, SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) as wins, SUM(CASE WHEN result='loss' THEN 1 ELSE 0 END) as losses FROM matches WHERE mode='solo'").fetchone())
    d = dict(conn.execute("SELECT COUNT(*) as total, SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) as wins, SUM(CASE WHEN result='loss' THEN 1 ELSE 0 END) as losses FROM matches WHERE mode='duo'").fetchone())
    rec = conn.execute("SELECT result, user_score, opponent_score, mode, played_at FROM matches ORDER BY played_at DESC LIMIT 20").fetchall()
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
    return jsonify({"ok": True, "app": f"RL Tracker v{APP_VERSION}", "version": APP_VERSION, "player_configured": bool(c.get("player", {}).get("name"))})

# ====== v1.1: Auto-update check ======
def _parse_semver(v):
    """Parse 'v1.0.9' / '1.1' / '1.0.9-rc1' into a 3-tuple of ints for comparison.
    Non-numeric suffixes are stripped, so '1.0.9-rc1' == '1.0.9' numerically.
    Pads to exactly 3 components so '1.1' == '1.1.0'."""
    s = str(v).strip().lstrip("vV")
    parts = []
    for p in s.split("."):
        num = ""
        for ch in p:
            if ch.isdigit(): num += ch
            else: break
        parts.append(int(num) if num else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])

@app.route("/api/check-update")
def check_update():
    """v1.1: Compare the running APP_VERSION against the latest GitHub release."""
    import urllib.request, urllib.error
    try:
        req = urllib.request.Request(GITHUB_RELEASES_API, headers={
            "User-Agent": f"RocketTracker/{APP_VERSION}",
            "Accept": "application/vnd.github+json",
        })
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
            download_url = a.get("browser_download_url"); break
    if not download_url:
        download_url = data.get("html_url")

    return jsonify({
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
    })

@app.route("/api/update", methods=["POST"])
def update_tracker():
    """v1.3.0: One-click seamless update.
    Downloads the latest release ZIP from GitHub, extracts to temp,
    copies data-v2.db + config.yaml, writes updater.bat, launches it, exits."""
    import urllib.request, urllib.error
    import zipfile, tempfile, shutil

    try:
        req = urllib.request.Request(GITHUB_RELEASES_API, headers={
            "User-Agent": f"RocketTracker/{APP_VERSION}",
            "Accept": "application/vnd.github+json",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            release = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return jsonify({"ok": False, "error": f"GitHub API returned HTTP {e.code}"}), 502
    except Exception as e:
        return jsonify({"ok": False, "error": f"Cannot reach GitHub ({e.__class__.__name__}: {e})"}), 502

    zip_url = None
    for a in release.get("assets", []) or []:
        name = (a.get("name") or "").lower()
        if name.endswith(".zip"):
            zip_url = a.get("browser_download_url")
            break
    if not zip_url:
        zip_url = release.get("zipball_url")
    if not zip_url:
        return jsonify({"ok": False, "error": "No downloadable .zip asset found in the latest release"}), 404

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

    new_exe = None
    for f in tmp_root.glob("*.exe"):
        new_exe = f
        break
    if not new_exe:
        shutil.rmtree(str(tmp_root.parent), ignore_errors=True)
        return jsonify({"ok": False, "error": "No .exe found in the downloaded archive"}), 500

    # Preserve user data
    for fname in ["data-v2.db", "config.yaml"]:
        src = BASE_DIR / fname
        if src.exists():
            try:
                shutil.copy2(str(src), str(tmp_root / fname))
            except Exception:
                pass

    # Write updater.bat
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

@app.route("/api/rl-config", methods=["GET"])
def rl_config_status():
    from listener import find_rl_config_dir
    cd = find_rl_config_dir(); r = {"config_dir_found": cd is not None, "ini_exists": False, "ini_correct": False}
    if cd:
        ip = cd / "TAStatsAPI.ini"; r["ini_exists"] = ip.exists()
        if ip.exists(): r["ini_correct"] = "PacketSendRate=30" in ip.read_text()
    return jsonify(r)

@app.route("/api/rl-config", methods=["POST"])
def rl_config_create():
    from listener import ensure_tastatsapi_ini, ensure_default_statsapi_ini
    ok = ensure_tastatsapi_ini()
    ensure_default_statsapi_ini()
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

@app.route("/api/quit", methods=["POST"])
def quit_tracker():
    """Graceful shutdown: sets stop_event, returns response, then hard-exits.
    Uses a non-daemon Timer so the thread is guaranteed to fire even if
    the WSGI server tries to clean up daemon threads. The main.py run loop
    also checks app.config['_should_exit'] after serve() returns as a
    belt-and-suspenders fallback."""
    ev = app.config.get("listener_stop_event")
    if ev: ev.set()
    app.config["_should_exit"] = True
    # Non-daemon Timer — survives WSGI worker thread cleanup
    t = _th.Timer(0.3, lambda: _os._exit(0))
    t.daemon = False
    t.start()
    return jsonify({"shutdown": True, "message": "Tracker shutting down..."})

@app.route("/api/coach/match/<int:match_id>")
def coach_match(match_id):
    return jsonify(coach.analyze_match(match_id))

@app.route("/api/coach/session/<int:session_id>")
def coach_session(session_id):
    return jsonify(coach.get_session_anomalies(session_id))

@app.route("/api/coach/records")
def coach_records():
    return jsonify(coach.get_all_records())
