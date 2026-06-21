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

# v1.1: Auto-update check against GitHub releases.
APP_VERSION = "1.1.1"
GITHUB_REPO = "magnificolv/RocketTracker"
GITHUB_RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

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
    return jsonify({"ok": True, "app": f"RL Tracker v{APP_VERSION}", "version": APP_VERSION, "player_configured": bool(c.get("player", {}).get("name"))})

# ====== v1.1: Auto-update check ======
def _parse_semver(v):
    """Parse 'v1.0.9' / '1.1' / '1.0.9-rc1' into a tuple of ints for comparison.
    Non-numeric suffixes are stripped, so '1.0.9-rc1' == '1.0.9' numerically."""
    s = str(v).strip().lstrip("vV")
    parts = []
    for p in s.split("."):
        num = ""
        for ch in p:
            if ch.isdigit(): num += ch
            else: break
        parts.append(int(num) if num else 0)
    return tuple(parts)

@app.route("/api/check-update")
def check_update():
    """v1.1: Compare the running APP_VERSION against the latest GitHub release.
    Uses stdlib urllib so PyInstaller builds need no extra deps. Returns 200
    with structured JSON even on failure so the frontend can render a friendly
    message instead of a generic fetch error."""
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

    tag = data.get("tag_name", "") or ""          # e.g. "v1.0.9"
    latest = tag.lstrip("vV")
    # Prefer the .zip asset (portable distribution); fall back to the release page.
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


def _run_cmd(args, timeout=5):
    """Run a subprocess, return stdout string. Never raises."""
    import subprocess as _sp
    try:
        r = _sp.run(args, capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "") + (r.stderr or "")
    except Exception:
        return ""


def _find_rl_install_dir():
    """Locate the Rocket League install directory.

    Tries (1) the ExecutablePath of a running RocketLeague.exe via wmic,
    (2) Steam steamapps libraryfolders, (3) Epic Games install records,
    (4) common hardcoded paths. Returns a Path or None.
    """
    from pathlib import Path
    # 1) Running process path (most reliable when RL is up)
    if sys.platform == "win32":
        out = _run_cmd(
            ["wmic", "process", "where", "name='RocketLeague.exe'", "get", "ExecutablePath", "/format:list"],
            timeout=4,
        )
        for line in out.splitlines():
            line = line.strip()
            if line.lower().endswith("rocketleague.exe"):
                p = Path(line)
                if p.exists():
                    # bin -> .. -> TAGame/Config
                    return p.parent.parent
    # 2) Steam steamapps/common/rocketleague
    candidates_steam = []
    progfiles = _os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    candidates_steam.append(Path(progfiles) / "Steam" / "steamapps" / "common" / "rocketleague")
    # Scan libraryfolders.vdf for additional Steam libraries
    steam_cfg = Path(progfiles) / "Steam" / "steamapps" / "libraryfolders.vdf"
    if steam_cfg.exists():
        try:
            txt = steam_cfg.read_text(encoding="utf-8", errors="replace")
            import re as _re
            for m in _re.finditer(r'"path"\s+"([^"]+)"', txt):
                candidates_steam.append(Path(m.group(1).replace("\\\\", "\\")) / "steamapps" / "common" / "rocketleague")
        except Exception:
            pass
    for c in candidates_steam:
        if (c / "TAGame" / "Config").is_dir():
            return c
    # 3) Epic Games
    epic_data = _os.environ.get("ProgramData", r"C:\ProgramData")
    epic_installs = Path(epic_data) / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
    if epic_installs.is_dir():
        try:
            for mf in epic_installs.glob("*.item"):
                txt = mf.read_text(encoding="utf-8", errors="replace")
                if "Rocket League" in txt or "rocketleague" in txt.lower():
                    import re as _re
                    m = _re.search(r'"InstallLocation"\s+"([^"]+)"', txt)
                    if m:
                        p = Path(m.group(1).replace("\\\\", "\\"))
                        if (p / "TAGame" / "Config").is_dir():
                            return p
        except Exception:
            pass
    # 4) Hardcoded fallbacks
    for hard in [Path(progfiles) / "Epic Games" / "rocketleague",
                 Path(_os.environ.get("ProgramFiles", r"C:\Program Files")) / "Epic Games" / "rocketleague"]:
        if (hard / "TAGame" / "Config").is_dir():
            return hard
    return None


@app.route("/api/rl-diagnostics")
def rl_diagnostics():
    """Deep architecture diagnostics for the 'port 49123 closed' problem.

    v1.0.7: WSL2 port-forwarding interference detection. wslrelay.exe /
    wslhost.exe can grab 127.0.0.1:49123 on Windows when something inside WSL2
    binds that port, silently intercepting SYNs meant for RocketLeague.exe and
    producing TimeoutError. Now detects: wsl.exe presence, running distros,
    relay processes, relay holding 49123 (PID resolved to process name), parses
    %UserProfile%\\.wslconfig (networkingMode, localhostForwarding,
    hostAddressLoopback, ignoredPorts), checks for vEthernet (WSL) adapter,
    and scans Windows excluded port ranges (netsh) — Hyper-V/Docker can reserve
    49123 so RL.exe cannot bind it at all.

    v1.0.6: distinguishes TimeoutError (filter driver drops SYN silently)
    from ConnectionRefused (no listener), probes IPv6 ::1, runs netstat to
    see what is actually bound, scans for VPN/TAP adapters that intercept
    loopback traffic, and checks the install-dir DefaultStatsAPI.ini that
    Psyonix's official docs actually reference.
    """
    import socket as _sock
    from listener import find_rl_config_candidates, find_rl_config_dir

    diag = {
        "config_dir_found": False,
        "config_dir_path": None,
        "ini_exists": False,
        "ini_correct": False,
        "ini_read_by_rl": False,
        "ini_full_content": None,
        "port_49123_open": False,
        "port_49123_error": None,
        "port_49123_error_class": None,   # timeout | refused | other | none
        "port_49123_ipv6_open": False,    # ::1 probe
        "netstat_listeners": [],          # PIDs listening on 49123
        "netstat_49123_processes": [],    # v1.0.7: resolved process names for those PIDs
        "rl_process_running": False,
        "rl_processes_found": [],
        "rl_install_dir": None,
        "default_stats_ini_exists": False,
        "default_stats_ini_path": None,
        "default_stats_ini_content": None,
        "default_stats_ini_correct": False,
        "vpn_adapters": [],               # suspicious filter-driver adapters
        "all_adapters": [],               # raw adapter names for power users
        # v1.0.7: WSL2 port-forwarding interference detection.
        # wslrelay.exe / wslhost.exe listens on Windows 127.0.0.1:PORT for every
        # port that has a listener inside WSL2 — silently intercepting SYNs that
        # were meant for a native Windows service on the same port. This is the
        # most likely root cause of TimeoutError-to-127.0.0.1:49123 on machines
        # where WSL2 is installed but no VPN/AV is present.
        "wsl_installed": False,           # wsl.exe present on PATH
        "wsl_version": None,              # output of `wsl --version`
        "wsl_running_distros": [],        # `wsl --list --running`
        "wsl_relay_processes": [],        # wslrelay.exe / wslhost.exe tasklist hits
        "wsl_relay_holding_49123": False, # relay PID matches a 49123 netstat listener
        "wsl_config_path": None,          # %UserProfile%\.wslconfig
        "wsl_config_exists": False,
        "wsl_config_content": None,
        "wsl_networking_mode": None,      # NAT (default) | mirrored | virtioproxy
        "wsl_localhost_forwarding": None, # true (default) | false
        "wsl_host_address_loopback": None,# true (default) | false
        "wsl_ignored_ports": [],          # parsed from ignoredPorts=49123,5000
        "wsl_49123_excluded": False,      # 49123 in wsl_ignored_ports
        "wsl_veth_adapter": False,        # vEthernet (WSL) Hyper-V adapter present
        # v1.0.7: Windows reserved port ranges (Hyper-V/Docker/WSL reserve chunks of
        # the dynamic port range; if 49123 falls in one, RL.exe cannot bind it).
        "port_exclusion_ranges": [],      # raw `netsh int ipv4 show excludedportrange` rows
        "port_49123_excluded": False,     # 49123 falls inside an exclusion range
        "suggestions": [],
        "alternative_paths_checked": [],
        "diagnostics_version": "1.0.7",
    }

    # --- Config dir + INI (user Documents) ---
    candidates = find_rl_config_candidates()
    diag["alternative_paths_checked"] = [str(c) for c in candidates]
    cd = find_rl_config_dir()
    if cd:
        diag["config_dir_found"] = True
        diag["config_dir_path"] = str(cd)
        ip = cd / "TAStatsAPI.ini"
        diag["ini_exists"] = ip.exists()
        if ip.exists():
            try:
                content = ip.read_text(encoding="utf-8", errors="replace")
                diag["ini_full_content"] = content
                diag["ini_correct"] = (
                    "TAGame.MatchStatsExporter_TA" in content
                    and "Port=49123" in content
                    and "PacketSendRate=30" in content
                )
                diag["ini_read_by_rl"] = "[IniVersion]" in content
            except Exception as e:
                diag["ini_correct"] = False
                diag["ini_full_content"] = f"(read error: {e})"

    # --- RL install dir + DefaultStatsAPI.ini (official Psyonix location) ---
    install_dir = _find_rl_install_dir()
    if install_dir:
        diag["rl_install_dir"] = str(install_dir)
        dsi = install_dir / "TAGame" / "Config" / "DefaultStatsAPI.ini"
        diag["default_stats_ini_path"] = str(dsi)
        diag["default_stats_ini_exists"] = dsi.exists()
        if dsi.exists():
            try:
                dcontent = dsi.read_text(encoding="utf-8", errors="replace")
                diag["default_stats_ini_content"] = dcontent
                diag["default_stats_ini_correct"] = (
                    "PacketSendRate=30" in dcontent
                    and "Port=49123" in dcontent
                )
            except Exception as e:
                diag["default_stats_ini_content"] = f"(read error: {e})"

    # --- Port 49123 probe (IPv4 127.0.0.1) ---
    try:
        s = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
        s.settimeout(2)
        s.connect(("127.0.0.1", 49123))
        s.close()
        diag["port_49123_open"] = True
        diag["port_49123_error_class"] = "none"
    except _sock.timeout:
        diag["port_49123_open"] = False
        diag["port_49123_error"] = "TimeoutError: [Errno 110] Connection timed out"
        diag["port_49123_error_class"] = "timeout"
    except ConnectionRefusedError as e:
        diag["port_49123_open"] = False
        diag["port_49123_error"] = f"ConnectionRefusedError: {e}"
        diag["port_49123_error_class"] = "refused"
    except Exception as e:
        diag["port_49123_open"] = False
        diag["port_49123_error"] = f"{type(e).__name__}: {e}"
        diag["port_49123_error_class"] = "other"

    # --- IPv6 ::1 probe (RL may bind IPv6-only on some Windows configs) ---
    try:
        s6 = _sock.socket(_sock.AF_INET6, _sock.SOCK_STREAM)
        s6.settimeout(2)
        s6.connect(("::1", 49123))
        s6.close()
        diag["port_49123_ipv6_open"] = True
    except Exception:
        diag["port_49123_ipv6_open"] = False

    # --- netstat: who is actually listening on 49123? ---
    if sys.platform == "win32":
        ns = _run_cmd(["netstat", "-ano", "-p", "TCP"], timeout=5)
        for line in ns.splitlines():
            ll = line.lower()
            if ":49123" in ll and "listen" in ll:
                diag["netstat_listeners"].append(line.strip())

    # --- Rocket League process check ---
    procs = []
    try:
        if sys.platform == "win32":
            out = _run_cmd(["tasklist", "/FO", "CSV", "/NH"], timeout=5)
            for line in out.splitlines():
                ll = line.lower()
                if "rocketleague" in ll or "rocket league" in ll:
                    try:
                        name = line.split('","')[0].strip('"')
                    except Exception:
                        name = line.split(",")[0].strip('"')
                    procs.append(name)
        else:
            out = _run_cmd(["ps", "-A"], timeout=5)
            for line in out.splitlines():
                ll = line.lower()
                if "rocketleague" in ll or "rocket league" in ll:
                    procs.append(line.strip())
    except Exception:
        pass
    diag["rl_process_running"] = len(procs) > 0
    diag["rl_processes_found"] = procs

    # --- VPN / filter-driver adapter scan ---
    #   These adapters install WFP filters that can silently drop loopback
    #   SYNs to 49123, producing TimeoutError instead of ConnectionRefused.
    if sys.platform == "win32":
        ga = _run_cmd(
            ["powershell", "-NoProfile", "-Command",
             "Get-NetAdapter | Select-Object Name,InterfaceDescription,Status | Format-Table -AutoSize | Out-String -Width 256"],
            timeout=6,
        )
        vpn_keywords = ("vpn", "tap", "tun", "wireguard", "nord", "express",
                        "proton", "mullvad", "openvpn", "cisco", "anyconnect",
                        "globalprotect", "zscaler", "forticlient", "sandboxie")
        for line in ga.splitlines():
            line_s = line.strip()
            if not line_s or line_s.startswith("Name") or line_s.startswith("---"):
                continue
            diag["all_adapters"].append(line_s)
            ll = line_s.lower()
            if any(kw in ll for kw in vpn_keywords):
                diag["vpn_adapters"].append(line_s)

    # --- v1.0.7: WSL2 port-forwarding interference detection ---
    # WSL2's localhost forwarding works via wslrelay.exe / wslhost.exe, which opens
    # a listening socket on Windows 127.0.0.1:PORT for every port that has a
    # listener inside the WSL2 VM. If something inside WSL2 binds 49123 (or WSL's
    # state gets confused), the relay grabs 127.0.0.1:49123 on Windows. RocketLeague.exe
    # then either fails to bind, or its SYNs get intercepted by the relay and silently
    # dropped — producing TimeoutError instead of ConnectionRefused. This is the
    # strongest hypothesis for the friend's "TimeoutError on 127.0.0.1:49123 with
    # no VPN/AV" symptom, because WSL2 ships with Docker Desktop / dev tooling.
    # Refs:
    #   https://learn.microsoft.com/en-us/windows/wsl/wsl-config (ignoredPorts, networkingMode)
    #   https://github.com/microsoft/WSL/issues/5942  (localhost forwarding bugs)
    #   https://github.com/microsoft/WSL/issues/9515  (127.0.0.1 mapping interference)
    if sys.platform == "win32":
        # 1) Is wsl.exe installed? (present on PATH = WSL feature enabled)
        wsl_where = _run_cmd(["where", "wsl"], timeout=3)
        if wsl_where.strip() and "could not find" not in wsl_where.lower():
            diag["wsl_installed"] = True
            # `wsl --version` requires a recent WSL; older builds return nonzero.
            diag["wsl_version"] = _run_cmd(["wsl", "--version"], timeout=4).strip() or None
            # `wsl --list --running` tells us if the VM is currently up (relay active).
            running_out = _run_cmd(["wsl", "--list", "--running"], timeout=4)
            for line in running_out.splitlines():
                ls = line.strip()
                if ls and not ls.lower().startswith("there are no running"):
                    # Strip UTF-8 BOM that wsl.exe emits on the first line.
                    if ls.startswith("\ufeff"):
                        ls = ls[1:]
                    if ls.lower() not in ("windows subsystem for linux", ""):
                        diag["wsl_running_distros"].append(ls)

        # 2) Find wslrelay.exe / wslhost.exe / wslservice.exe processes.
        #    wslrelay.exe is the actual port-relay process on Win10/11 NAT mode.
        tasklist_csv = _run_cmd(["tasklist", "/FO", "CSV", "/NH"], timeout=5)
        relay_pids = []  # PIDs that are WSL relay processes
        for line in tasklist_csv.splitlines():
            ll = line.lower()
            if "wslrelay" in ll or "wslhost" in ll or "wslservice" in ll:
                # CSV row: "Name","PID","SessionName","Session#","MemUsage"
                try:
                    cells = [c.strip('"') for c in line.split('","')]
                    name = cells[0]
                    pid = cells[1] if len(cells) > 1 else ""
                    diag["wsl_relay_processes"].append(f"{name} (PID {pid})")
                    if pid.isdigit():
                        relay_pids.append(pid)
                except Exception:
                    diag["wsl_relay_processes"].append(line.strip())

        # 3) Resolve the PID of every netstat listener on 49123 to a process name.
        #    If wslrelay.exe or wslhost.exe is the one holding 49123, we have a
        #    smoking gun: WSL2 has grabbed the port out from under RocketLeague.exe.
        pid_to_name = {}
        for row in tasklist_csv.splitlines():
            try:
                cells = [c.strip('"') for c in row.split('","')]
                if len(cells) >= 2 and cells[1].isdigit():
                    pid_to_name[cells[1]] = cells[0]
            except Exception:
                pass
        for listener_line in diag["netstat_listeners"]:
            parts = listener_line.split()
            if parts:
                pid = parts[-1]
                if pid.isdigit():
                    pname = pid_to_name.get(pid, "(unknown)")
                    diag["netstat_49123_processes"].append(f"{pname} (PID {pid})")
                    if pname.lower() in ("wslrelay.exe", "wslhost.exe", "wslservice.exe") or pid in relay_pids:
                        diag["wsl_relay_holding_49123"] = True

        # 4) Parse %UserProfile%\.wslconfig (the official user-tunable WSL2 config).
        #    Key knobs we care about:
        #      networkingMode=mirrored        — Win11 mirrored mode (more aggressive port sharing)
        #      localhostForwarding=false      — disable the relay entirely (Win10 default true)
        #      hostAddressLoopback=false      — disable host loopback into WSL2
        #      ignoredPorts=49123,5000        — official per-port exclusion (the fix!)
        userprofile = _os.environ.get("USERPROFILE", "")
        if userprofile:
            wsl_cfg_path = Path(userprofile) / ".wslconfig"
            diag["wsl_config_path"] = str(wsl_cfg_path)
            diag["wsl_config_exists"] = wsl_cfg_path.exists()
            if wsl_cfg_path.exists():
                try:
                    cfg_text = wsl_cfg_path.read_text(encoding="utf-8", errors="replace")
                    diag["wsl_config_content"] = cfg_text
                    # Naive but sufficient: parse key=value lines under [wsl2].
                    in_wsl2 = False
                    for raw in cfg_text.splitlines():
                        line = raw.strip()
                        if not line or line.startswith("#") or line.startswith(";"):
                            continue
                        if line.startswith("[") and line.endswith("]"):
                            in_wsl2 = line.lower() == "[wsl2]"
                            continue
                        if "=" not in line:
                            continue
                        key, _, val = line.partition("=")
                        key = key.strip().lower()
                        val = val.strip()
                        if not in_wsl2 and key not in ("networkingmode", "localhostforwarding",
                                                       "hostaddressloopback", "ignoredports"):
                            continue
                        if key == "networkingmode":
                            diag["wsl_networking_mode"] = val.lower() or "nat"
                        elif key == "localhostforwarding":
                            diag["wsl_localhost_forwarding"] = val.lower() in ("true", "1", "yes", "on")
                        elif key == "hostaddressloopback":
                            diag["wsl_host_address_loopback"] = val.lower() in ("true", "1", "yes", "on")
                        elif key == "ignoredports":
                            for tok in val.replace(";", ",").split(","):
                                tok = tok.strip()
                                if tok.isdigit():
                                    diag["wsl_ignored_ports"].append(int(tok))
                    diag["wsl_49123_excluded"] = 49123 in diag["wsl_ignored_ports"]
                except Exception as e:
                    diag["wsl_config_content"] = f"(read error: {e})"

        # 5) Check for the vEthernet (WSL) Hyper-V virtual adapter. Present whenever
        #    WSL2 has been enabled, even when no distro is running.
        ga_lower = "\n".join(diag["all_adapters"]).lower()
        if "vethernet (wsl)" in ga_lower or "wsl" in ga_lower:
            diag["wsl_veth_adapter"] = True

        # 6) Windows reserved port ranges — Hyper-V / Docker Desktop / WSL2 reserve
        #    chunks of the dynamic port range via `netsh int ipv4 show excludedportrange`.
        #    If 49123 falls inside one, RL.exe cannot bind it at all (WSAEADDRINUSE /
        #    WSAEACCES), regardless of whether WSL is currently running.
        excl_out = _run_cmd(
            ["netsh", "int", "ipv4", "show", "excludedportrange", "protocol=tcp"],
            timeout=5,
        )
        for raw in excl_out.splitlines():
            ls = raw.strip()
            if not ls or ls.startswith("Start Port") or ls.startswith("---") or "protocol" in ls.lower():
                continue
            # Row format: "10701      10751"  (start end) — possibly with a label column.
            nums = [int(t) for t in ls.split() if t.isdigit()]
            if len(nums) >= 2:
                start, end = nums[0], nums[1]
                if start <= 49123 <= end:
                    diag["port_49123_excluded"] = True
                diag["port_exclusion_ranges"].append(f"{start}-{end}")

    # --- Suggestions (ordered by likelihood, keyed to error class) ---
    sugg = []
    ec = diag["port_49123_error_class"]

    if not diag["config_dir_found"]:
        sugg.append("❌ RL config folder not found. Launch Rocket League at least once so it creates the Documents/My Games/Rocket League/TAGame/Config folder.")

    if diag["config_dir_found"] and not diag["ini_exists"]:
        sugg.append("⚠️ TAStatsAPI.ini is missing in the detected config folder. Open Settings → '📝 Auto-Create' to generate it, then restart Rocket League.")

    if diag["ini_exists"] and not diag["ini_correct"]:
        sugg.append("⚠️ TAStatsAPI.ini exists but its content is wrong (needs Port=49123 + PacketSendRate=30 under [TAGame.MatchStatsExporter_TA]). Open Settings → '📝 Auto-Create' to fix it, then restart Rocket League.")

    # TimeoutError-specific guidance (the friend's actual symptom)
    if ec == "timeout":
        sugg.append("⏱️ TIMEOUT (not ConnectionRefused) — something is silently dropping SYN packets to 127.0.0.1:49123. On localhost this is almost always a Windows Filtering Platform driver or a port-relay process intercepting the SYN, NOT a missing listener. Top causes in order:")

        # --- WSL2 port-relay interference (v1.0.7 — primary hypothesis) ---
        # Highest-priority check: the relay is literally holding 49123.
        if diag.get("wsl_relay_holding_49123"):
            sugg.append(
                "🚨 SMOKING GUN: wslrelay.exe / wslhost.exe is LISTENING on 127.0.0.1:49123 right now "
                f"(processes: {'; '.join(diag['netstat_49123_processes'])}). WSL2's localhost forwarder "
                "has grabbed port 49123 out from under RocketLeague.exe. SYNs from RL.exe are being "
                "absorbed by the relay and silently dropped because nothing inside WSL2 is actually "
                "serving them — hence the TIMEOUT (not REFUSED). "
                "FIX (pick one, in order of preference):\n"
                "   A) Quickest test — open PowerShell and run:  wsl --shutdown\n"
                "      Then re-launch Rocket League and re-run Diagnostics. If the port opens, WSL2 was the culprit.\n"
                "   B) Permanent fix — add port 49123 to WSL's ignore list. Create or edit "
                "%USERPROFILE%\\.wslconfig and add under [wsl2]:\n"
                "        [wsl2]\n"
                "        ignoredPorts=49123\n"
                "      Then run 'wsl --shutdown' once. WSL2 will never touch 49123 again.\n"
                "   C) Nuclear option (if you don't actively use WSL2): disable the 'Windows Subsystem for Linux' "
                "Windows feature (Turn Windows features on or off → uncheck WSL → reboot)."
            )
        elif diag.get("wsl_installed") and diag.get("wsl_running_distros"):
            # WSL2 is installed AND a distro is currently running — relay is active
            # even if it hasn't grabbed 49123 right now (state can change at any time).
            mode = diag.get("wsl_networking_mode") or "nat"
            sugg.append(
                f"⚠️ WSL2 is INSTALLED and a distro is RUNNING ({', '.join(diag['wsl_running_distros'])}). "
                f"Networking mode: {mode}. WSL2's localhost forwarder (wslrelay.exe) opens Windows-side "
                "sockets for ports used inside WSL2 — it can grab 127.0.0.1:49123 at any time if a WSL "
                "process happens to bind it, silently intercepting SYNs meant for RocketLeague.exe. "
                "Even when the relay isn't currently holding 49123, its WFP filters can drop loopback SYNs. "
                "FIX: run 'wsl --shutdown' in PowerShell and re-test. For a permanent fix, add "
                "'ignoredPorts=49123' under [wsl2] in %USERPROFILE%\\.wslconfig, then 'wsl --shutdown'."
            )
        elif diag.get("wsl_installed"):
            sugg.append(
                "⚠️ WSL2 is INSTALLED on this machine but no distro is currently running. The Hyper-V "
                "virtual switch and WFP filters installed by WSL2 can still interfere with loopback traffic "
                "even when WSL is idle. If 'wsl --shutdown' doesn't help, try adding 'ignoredPorts=49123' "
                "under [wsl2] in %USERPROFILE%\\.wslconfig and reboot."
            )

        # Mirrored networking mode is a separate, more aggressive failure mode on Win11.
        if diag.get("wsl_networking_mode") == "mirrored":
            sugg.append(
                "🌐 WSL2 is in MIRRORED networking mode. Mirrored mode shares the Windows host's network "
                "stack with WSL2 — WSL processes can directly bind Windows 127.0.0.1 ports, which causes "
                "hard conflicts with native Windows services. If the fix above doesn't work, switch back "
                "to NAT mode by removing 'networkingMode=mirrored' from %USERPROFILE%\\.wslconfig, then "
                "'wsl --shutdown'."
            )

        # Windows reserved port range (Hyper-V/Docker reserve chunks of dynamic range).
        if diag.get("port_49123_excluded"):
            ranges = diag.get("port_exclusion_ranges") or []
            sugg.append(
                f"🚫 Port 49123 is inside a Windows EXCLUDED port range (reserved by Hyper-V / WSL2 / "
                f"Docker Desktop). Reserved ranges on this machine: {', '.join(ranges[:8])}. "
                "Windows will not allow ANY app to bind to a port in these ranges — RL.exe silently fails "
                "to open the Stats API. Verify in admin PowerShell:  netsh int ipv4 show excludedportrange protocol=tcp\n"
                "FIX: either (a) reboot (Hyper-V re-randomizes its reservations on boot, sometimes freeing 49123), "
                "(b) stop the Hyper-V Host Compute Service (cmd as admin:  net stop winnat  →  net start winnat), "
                "or (c) permanently reserve 49123 for RL BEFORE Hyper-V grabs it:  "
                "netsh int ipv4 add excludedportrange protocol=tcp startport=49123 numberofports=1  (admin cmd)."
            )

        if diag.get("vpn_adapters"):
            sugg.append(f"🚨 VPN/TUN adapter DETECTED: {'; '.join(diag['vpn_adapters'][:3])}. Fully QUIT the VPN app (system tray → Exit), then re-run diagnostics. Even disconnected VPNs leave filter drivers active that intercept loopback traffic.")
        else:
            sugg.append("📋 VPN check: open Windows system tray and look for NordVPN / ExpressVPN / ProtonVPN / Mullvad / WireGuard / Cisco AnyConnect / GlobalProtect / Zscaler. Fully EXIT any you find (not just disconnect) and re-test — filter drivers stay loaded even when the VPN is 'off'.")
        sugg.append("🛡️ Windows Defender: open 'Windows Security' → 'App & browser control' → 'Smart App Control' (if enabled, disable). Also check 'Firewall & network protection' → 'Advanced settings' → 'Inbound Rules' for any rule blocking port 49123.")
        sugg.append("🏢 Corporate / enterprise security (CrowdStrike, SentinelOne, Defender for Endpoint) — these install WFP filters that can drop loopback. Ask IT to whitelist 127.0.0.1:49123.")
        sugg.append("🔌 Third-party firewall (even uninstalled AVs sometimes leave filter drivers). Run 'Get-NetAdapter' in PowerShell and look for any adapter you don't recognise.")
        sugg.append("♻️ Restart the PC. WFP filters and the WSL relay state can get into a bad state that only a reboot clears.")

    if ec == "refused":
        sugg.append("✋ CONNECTION REFUSED — RL has not opened port 49123. The TCP stack is healthy (kernel sent RST). Focus on getting RL to actually read TAStatsAPI.ini and open the port:")
        if not diag["ini_read_by_rl"]:
            sugg.append("⚠️ FATAL: TAStatsAPI.ini is correct but Rocket League has NEVER read it ([IniVersion] missing). RL reads TAStatsAPI.ini ONLY at startup. Fully quit Rocket League (system tray → Exit, or Task Manager → End Task) and launch it again. Auto-Create was probably clicked while RL was already running.")
        else:
            sugg.append("🔄 TAStatsAPI.ini is correct and RL has read it before ([IniVersion] present) but port 49123 is closed right now. Causes: (a) RL was started BEFORE the INI was created — restart RL; (b) you are testing from the main menu — the Stats API only opens the port DURING a match (per Psyonix docs). Enter a freeplay/exhibition match and re-run diagnostics; (c) Steam Cloud reverted the INI — see below.")

    # RL-running but port closed
    if diag["rl_process_running"] and not diag["port_49123_open"] and diag["ini_correct"]:
        sugg.append("🛡️ RL is running and the INI is correct, but the port is closed. CRITICAL: the official Psyonix Stats API docs say the port opens 'during a match'. Enter an exhibition match or freeplay, THEN re-run diagnostics. If still closed in-match, see the Timeout/Refused guidance above.")

    # RL not running
    if not diag["rl_process_running"] and not diag["port_49123_open"]:
        sugg.append("🎮 Rocket League does not appear to be running. Launch it, ENTER A MATCH (port only opens during matches per official docs), then re-run diagnostics.")

    # DefaultStatsAPI.ini (official install-dir location)
    if diag["rl_install_dir"] and not diag["default_stats_ini_exists"]:
        sugg.append(f"📄 DefaultStatsAPI.ini is MISSING in the RL install dir ({diag['rl_install_dir']}\\TAGame\\Config\\). Psyonix's official docs reference THIS file, not the user-documents TAStatsAPI.ini. Create it there with the same [TAGame.MatchStatsExporter_TA] Port=49123 / PacketSendRate=30 content, then restart RL. (Magnifico's machine works with only TAStatsAPI.ini, so this is a fallback, but it has fixed the issue for some users.)")
    elif diag["default_stats_ini_exists"] and not diag["default_stats_ini_correct"]:
        sugg.append(f"⚠️ DefaultStatsAPI.ini EXISTS in the RL install dir but has wrong content (needs Port=49123 + PacketSendRate=30). Fix: {diag['default_stats_ini_path']}")

    # IPv6-only bind hint
    if not diag["port_49123_open"] and diag["port_49123_ipv6_open"]:
        sugg.append("🌐 IPv4 127.0.0.1:49123 is closed but IPv6 [::1]:49123 is OPEN — RL has bound IPv6-only. This is rare but happens on some Windows configs with Hyper-V/WSL2. Tell Magnifico (the tracker currently only dials 127.0.0.1).")

    # Steam Cloud warning (Steam version only — heuristic: Steam install dir found)
    if diag["rl_install_dir"] and "steamapps" in diag["rl_install_dir"].lower():
        sugg.append("☁️ Steam install detected. Steam Cloud syncs the Documents\\My Games\\Rocket League folder and can silently revert TAStatsAPI.ini to an older version on every RL launch. Fix: in Steam → Rocket League → Properties → General → DISABLE 'Keep games saves in the Steam Cloud'. Then re-create the INI and restart RL.")

    # OneDrive / alt-path hint
    if diag["config_dir_found"]:
        existing = diag["config_dir_path"]
        others = [p for p in diag["alternative_paths_checked"] if p != existing]
        if others:
            sugg.append(f"ℹ️ Config found at: {existing}. Also checked {len(others)} other location(s) (e.g. OneDrive Documents). If RL still won't open the port, the INI may need to live in one of those — copy TAStatsAPI.ini there too and restart RL.")

    # netstat hint
    if not diag["port_49123_open"] and diag["netstat_listeners"]:
        sugg.append(f"🔍 netstat reports a listener on 49123: {diag['netstat_listeners']}. But our probe still failed — this confirms a filter driver is dropping the SYN (the port IS open at the OS level, but something intercepts the connect). See the Timeout guidance above.")
    elif not diag["port_49123_open"] and not diag["netstat_listeners"] and ec == "timeout":
        sugg.append("🔍 netstat reports NO listener on 49123 yet the probe TIMED OUT (instead of refused). This is unusual — a filter driver is dropping SYNs even though nothing is listening. Reboot the PC and re-test; if it persists, the WFP stack needs resetting ('netsh winsock reset' in an admin PowerShell, then reboot).")

    if not sugg:
        sugg.append("✅ Everything looks good! Port 49123 is open and the INI is correct. You should be tracked automatically.")
    diag["suggestions"] = sugg
    return jsonify(diag)

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
