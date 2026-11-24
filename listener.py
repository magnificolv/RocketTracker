"""
Rocket League Stats API Raw TCP Listener - v4.0 Overdrive
Direct non-blocking TCP connection to RL Stats API (127.0.0.1:49123).
"""
from __future__ import annotations

import json
import os
import re
import select
import socket
import sqlite3
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from coach import CoachEngine
from field_resolver import FieldResolver
from result_logic import (
    DEFAULT_TRACKING_CONFIG,
    accolade_label,
    arena_label,
    classify_match,
    decide_result,
    ensure_schema,
    is_bogus_goal_scored,
    normalize_tracking_config,
    playlist_label,
    reconcile_scores,
    repair_inverted_results,
)
from version import APP_VERSION

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
DB_PATH = BASE_DIR / "data-v2.db"
CONFIG_PATH = BASE_DIR / "config.yaml"
LOG_PATH = BASE_DIR / "listener.log"
STATUS_PATH = BASE_DIR / "listener_status.json"

_coach = CoachEngine(str(DB_PATH))

UU_TO_KPH = 0.036

# Fast buffered logger (never flushes disk inside recv() loop)
_log_queue: List[str] = []
_log_lock = threading.Lock()


def log(msg: str) -> None:
    timestamp = datetime.now().strftime("%H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line, flush=True)
    with _log_lock:
        _log_queue.append(line + "\n")


def flush_log() -> None:
    with _log_lock:
        if not _log_queue:
            return
        lines = list(_log_queue)
        _log_queue.clear()
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.writelines(lines)
    except Exception:
        pass


# Thread-safe live match snapshot for /api/live
_live_lock = threading.Lock()
_live_state: Dict[str, Any] = {
    "version": APP_VERSION,
    "connection_state": "starting",
    "message": "Initializing...",
    "player": "",
    "friends": [],
    "tracking_scope": "competitive",
    "in_match": False,
    "tracking_active": False,
    "skip_reason": "",
    "playlist_id": None,
    "playlist": "Unknown",
    "playlist_category": "",
    "arena": "",
    "arena_name": "",
    "match_guid": "",
    "mode": "solo",
    "friend_name": None,
    "user_team_num": None,
    "user_score": 0,
    "opponent_score": 0,
    "blue_score": 0,
    "orange_score": 0,
    "time_remaining": 300,
    "is_overtime": False,
    "in_replay": False,
    "user_live": {},
    "players": [],
    "goals": [],
    "last_recorded_match_id": None,
    "last_recorded_result": None,
    "last_recorded_score": None,
    "last_recorded_playlist": None,
    "last_recorded_at": None,
    "updated_at": datetime.now(timezone.utc).isoformat(),
}


def get_live_snapshot() -> Dict[str, Any]:
    with _live_lock:
        snap = dict(_live_state)
        snap["friends"] = list(_live_state.get("friends") or [])
        snap["user_live"] = dict(_live_state.get("user_live") or {})
        snap["players"] = [dict(p) for p in (_live_state.get("players") or [])]
        snap["goals"] = [dict(g) for g in (_live_state.get("goals") or [])]
        return snap


def _update_live_fields(**fields: Any) -> None:
    with _live_lock:
        _live_state.update(fields)
        _live_state["updated_at"] = datetime.now(timezone.utc).isoformat()


def find_rl_config_dir() -> Optional[Path]:
    candidates = [
        Path(os.environ.get("USERPROFILE", "")) / "Documents" / "My Games" / "Rocket League" / "TAGame" / "Config",
        Path.home() / "Documents" / "My Games" / "Rocket League" / "TAGame" / "Config",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def find_rl_install_dirs() -> List[Path]:
    found: List[Path] = []
    seen: set[str] = set()

    def _add(p: Path) -> None:
        try:
            rp = str(p.resolve()).lower()
        except Exception:
            rp = str(p).lower()
        if rp not in seen and p.exists():
            seen.add(rp)
            found.append(p)

    # Steam registry
    if sys.platform == "win32":
        try:
            import winreg

            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam\Apps\252950")
            rl_dir_str, _ = winreg.QueryValueEx(key, "InstalledDepots")
            for line in str(rl_dir_str).splitlines():
                parts = line.strip().split()
                if parts and parts[0] == "252950":
                    _add(Path(parts[-1].strip('"')))
        except Exception:
            pass

    # Epic Games manifests
    manifests_dir = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
    if manifests_dir.exists():
        for item_file in manifests_dir.glob("*.item"):
            try:
                data = json.loads(item_file.read_text(encoding="utf-8", errors="replace"))
                app_name = str(data.get("AppName") or "").lower()
                disp = str(data.get("DisplayName") or "").lower()
                loc = str(data.get("InstallLocation") or "")
                if loc and (app_name == "sugar" or "rocket league" in disp or "rocketleague" in loc.lower()):
                    _add(Path(loc))
            except Exception:
                continue

    # Common defaults
    for default_dir in (
        Path(r"C:\Program Files\Epic Games\rocketleague"),
        Path(r"D:\Games\rocketleague"),
        Path(r"D:\Epic Games\rocketleague"),
        Path(r"C:\Program Files (x86)\Steam\steamapps\common\rocketleague"),
        Path(r"D:\SteamLibrary\steamapps\common\rocketleague"),
    ):
        _add(default_dir)

    return found


def ensure_tastatsapi_ini() -> bool:
    config_dir = find_rl_config_dir()
    if not config_dir:
        return False
    ini_path = config_dir / "TAStatsAPI.ini"
    needed = "[TAGame.MatchStatsExporter_TA]\nPort=49123\nPacketSendRate=30\n"
    if ini_path.exists():
        txt = ini_path.read_text(encoding="utf-8", errors="replace")
        has_section = "[TAGame.MatchStatsExporter_TA]" in txt
        has_rate = bool(re.search(r"^\s*PacketSendRate\s*=\s*[1-9]\d*", txt, re.MULTILINE))
        has_port = bool(re.search(r"^\s*Port\s*=\s*49123", txt, re.MULTILINE))
        if has_section and has_rate and has_port:
            log("OK: TAStatsAPI.ini already correct")
            return True
    try:
        ini_path.write_text(needed, encoding="utf-8")
        log("OK: TAStatsAPI.ini created/updated with [TAGame.MatchStatsExporter_TA]")
        return True
    except Exception as e:
        log(f"ERROR: Failed to write TAStatsAPI.ini: {e}")
        return False


def ensure_default_statsapi_ini() -> bool:
    """Fix Epic/Steam install-dir DefaultStatsAPI.ini if PacketSendRate=0 overrides Documents INI."""
    fixed_any = False
    for rl_path in find_rl_install_dirs():
        ini = rl_path / "TAGame" / "Config" / "DefaultStatsAPI.ini"
        if not ini.exists():
            continue
        try:
            content = ini.read_text(encoding="utf-8", errors="replace")
            updated = content
            if "PacketSendRate=0" in updated:
                updated = updated.replace("PacketSendRate=0", "PacketSendRate=30")
            if "[TAGame.MatchStatsExporter_TA]" not in updated:
                updated = updated.rstrip() + "\n\n[TAGame.MatchStatsExporter_TA]\nPort=49123\nPacketSendRate=30\n"
            if updated != content:
                ini.write_text(updated, encoding="utf-8")
                log(f"OK: DefaultStatsAPI.ini fixed at {ini}")
                fixed_any = True
        except Exception as e:
            log(f"WARN: Could not update {ini}: {e}")
    return fixed_any


def _probe_port_open(host: str = "127.0.0.1", port: int = 49123, timeout: float = 0.15) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        return s.connect_ex((host, port)) == 0
    except Exception:
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass


def diagnose_rl_ini() -> Dict[str, Any]:
    cd = find_rl_config_dir()
    res: Dict[str, Any] = {
        "config_dir_found": cd is not None,
        "config_dir": str(cd) if cd else None,
        "ini_path": str(cd / "TAStatsAPI.ini") if cd else None,
        "ini_exists": False,
        "ini_correct": False,
        "ini_read_by_rl": False,
        "ini_preview": "",
        "install_dirs": [str(p) for p in find_rl_install_dirs()],
        "default_ini_issues": [],
        "port_49123_open": _probe_port_open("127.0.0.1", 49123, 0.15),
    }
    if cd:
        ip = cd / "TAStatsAPI.ini"
        res["ini_exists"] = ip.exists()
        if ip.exists():
            txt = ip.read_text(encoding="utf-8", errors="replace")
            res["ini_preview"] = txt.strip()[:500]
            has_section = "[TAGame.MatchStatsExporter_TA]" in txt
            has_rate = bool(re.search(r"^\s*PacketSendRate\s*=\s*[1-9]\d*", txt, re.MULTILINE))
            res["ini_correct"] = has_section and has_rate
            res["ini_read_by_rl"] = "[IniVersion]" in txt

    for rl_path_str in res["install_dirs"]:
        ini = Path(rl_path_str) / "TAGame" / "Config" / "DefaultStatsAPI.ini"
        if ini.exists():
            try:
                txt = ini.read_text(encoding="utf-8", errors="replace")
                if "PacketSendRate=0" in txt or "[TAGame.MatchStatsExporter_TA]" not in txt:
                    res["default_ini_issues"].append(str(ini))
            except Exception:
                pass
    return res


def load_config() -> Dict[str, Any]:
    try:
        import yaml

        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
    except Exception:
        pass
    return {}


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Create tables if they don't exist — safe additive migration order."""
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
        CREATE TABLE IF NOT EXISTS matches_summary (
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
            FOREIGN KEY (match_id) REFERENCES matches(id) ON DELETE CASCADE
        );
    """)
    ensure_schema(conn)
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_summary_played ON matches_summary(played_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_matches_playlist ON matches(playlist)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_matches_mode ON matches(mode)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_matches_guid ON matches(match_guid)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_matches_playlist_id ON matches(playlist_id)")
    except Exception:
        pass
    fixed = repair_inverted_results(conn)
    conn.commit()
    conn.close()
    if fixed:
        log(f"Repaired inverted W/L on match ids: {fixed}")


def _write_summary(match_id: int) -> None:
    """Write pre-computed summary row using personal player_goals."""
    db = get_db()
    match = db.execute(
        "SELECT m.*, md.arena, md.shots, md.saves, md.demos_given, md.demos_taken, "
        "md.player_goals, md.player_score, md.is_mvp, md.forfeit, md.overtime "
        "FROM matches m LEFT JOIN match_details md ON m.id = md.match_id "
        "WHERE m.id = ?",
        (match_id,),
    ).fetchone()
    if not match:
        db.close()
        return

    keys = set(match.keys())
    pgoals = match["player_goals"] if ("player_goals" in keys and match["player_goals"] is not None) else (match["user_score"] or 0)
    demos = match["demos_given"] or 0
    shots = match["shots"] or 0
    saves = match["saves"] or 0

    metrics = [
        ("G", "Goals", pgoals),
        ("D", "Demos", demos),
        ("Sh", "Shots", shots),
        ("Sv", "Saves", saves),
    ]
    metrics.sort(key=lambda x: x[2], reverse=True)
    hi_icon, hi_text, hi_value = metrics[0]

    playlist = match["playlist"] if "playlist" in keys else "Unknown"
    friend_name = match["friend_name"] if "friend_name" in keys else None
    playlist_id = match["playlist_id"] if "playlist_id" in keys else None
    pscore = match["player_score"] if "player_score" in keys else 0
    is_mvp = match["is_mvp"] if "is_mvp" in keys else 0
    forfeit = match["forfeit"] if "forfeit" in keys else 0
    overtime = match["overtime"] if "overtime" in keys else 0

    db.execute(
        """INSERT OR REPLACE INTO matches_summary
           (match_id, session_id, played_at, user_score, opponent_score,
            result, mode, arena, highlight_icon, highlight_text, highlight_value,
            goals, shots, saves, demos_given, demos_taken, playlist, friend_name,
            playlist_id, player_goals, player_score, is_mvp, forfeit, overtime)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            match_id,
            match["session_id"],
            match["played_at"],
            match["user_score"],
            match["opponent_score"],
            match["result"],
            match["mode"],
            match["arena"],
            hi_icon,
            hi_text,
            hi_value,
            pgoals,
            shots,
            saves,
            demos,
            match["demos_taken"] or 0,
            playlist,
            friend_name,
            playlist_id,
            pgoals,
            pscore or 0,
            is_mvp or 0,
            forfeit or 0,
            overtime or 0,
        ),
    )
    db.commit()
    db.close()


def update_status(
    state: str,
    msg: str = "",
    player: str = "",
    friends: Optional[List[str]] = None,
    poll_interval: Optional[int] = None,
    poll_mode: Optional[str] = None,
    tracking_scope: Optional[str] = None,
) -> None:
    _update_live_fields(
        connection_state=state,
        message=msg,
        player=player,
        friends=friends or [],
        **({"tracking_scope": tracking_scope} if tracking_scope else {}),
    )
    try:
        with open(STATUS_PATH, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "state": state,
                    "message": msg,
                    "player": player,
                    "friends": friends or [],
                    "poll_interval": poll_interval,
                    "poll_mode": poll_mode,
                    "tracking_scope": tracking_scope,
                    "updated": datetime.now(timezone.utc).isoformat(),
                },
                f,
            )
    except Exception:
        pass


# =============================================================================
# Match state - PRE-ALLOCATED for zero-backpressure speed
# =============================================================================


class MatchState:
    __slots__ = (
        "player_name",
        "aliases",
        "primary_ids",
        "friend_names",
        "tracking_cfg",
        "match_guid",
        "match_started_at",
        "pending_end_at",
        "game_winner_str",
        "user_team_num",
        "goal_scores",
        "team_score_base",
        "team_score_latest",
        "player_goals_sum",
        "mode",
        "arena",
        "playlist",
        "playlist_id",
        "friend_name",
        "goals",
        "user_hit_kphs",
        "player_score",
        "player_goals",
        "touches",
        "car_touches",
        "shots",
        "saves",
        "assists",
        "demos_given",
        "demos_taken",
        "is_overtime",
        "time_remaining",
        "tick_count",
        "active_tick_count",
        "boost_sum",
        "boost_count",
        "boosting_ticks",
        "supersonic_ticks",
        "powerslide_ticks",
        "on_ground_ticks",
        "in_air_ticks",
        "on_wall_ticks",
        "speed_sum",
        "max_speed_kph",
        "teammate_name",
        "teammate_goals",
        "teammate_score",
        "teammate_shots",
        "teammate_saves",
        "teammate_assists",
        "teammate_touches",
        "teammate_demos",
        "teammate_demos_base",
        "teammate_demos_baselined",
        "teammate_active_ticks",
        "teammate_boost_sum",
        "teammate_boost_count",
        "teammate_air_ticks",
        "teammate_wall_ticks",
        "teammate_supersonic_ticks",
        "players_snapshot",
        "user_live_stats",
        "max_opponents",
        "is_spectator_or_replay",
        "learned_primary_id",
        "_match_recorded",
        "_friend_cache",
        "_friend_norm_cache",
        "_demos_baselined",
        "_prev_demos",
        "_was_demolished",
        "_last_update_time",
        "_last_live_publish",
        "_poll_interval",
        "_connected",
        "_team_confirm_count",
        "_team_confirm_candidate",
        "_cross_check_fails",
        "_both_teams_spec_ticks",
        "_last_roster_log",
        "_spec_only_lock",
        "_last_target_shortcut",
        "_last_goal_sig",
        "_last_goal_ts",
        "_last_recorded_guid",
        "team_names",
        "in_replay",
        "paused",
        "crossbar_hits",
        "boost_pads",
        "boost_pills",
        "accolades",
        "forfeit",
    )

    def __init__(
        self,
        player_name: str,
        friend_names: Optional[List[str]] = None,
        aliases: Optional[List[str]] = None,
        primary_ids: Optional[List[str]] = None,
        tracking_cfg: Optional[Dict[str, Any]] = None,
    ):
        self.player_name = (player_name or "").lower().strip()
        self.aliases = [str(a).lower().strip() for a in (aliases or []) if a and str(a).strip()]
        self.primary_ids = {str(x).strip() for x in (primary_ids or []) if x and str(x).strip()}
        self.friend_names = [str(f).strip() for f in (friend_names or []) if f and str(f).strip()]
        self._friend_cache = {f.lower() for f in self.friend_names}
        self._friend_norm_cache = {self._norm_name(f) for f in self.friend_names if self._norm_name(f)}
        self.tracking_cfg = normalize_tracking_config(tracking_cfg)
        self._match_recorded = False
        self._last_recorded_guid = ""
        self._last_update_time = 0.0
        self._last_live_publish = 0.0
        self._poll_interval = 60
        self._connected = False
        self._last_roster_log = 0.0
        self.reset()

    def reset(self) -> None:
        self.match_guid = ""
        self.match_started_at = time.time()
        self.pending_end_at = None
        self.game_winner_str = None
        self.user_team_num = None
        self.goal_scores = [0, 0]
        self.team_score_base = None
        self.team_score_latest = [0, 0]
        self.player_goals_sum = [0, 0]
        self.mode = "solo"
        self.arena = None
        self.playlist = "Unknown"
        self.playlist_id = None
        self.friend_name = None
        self.goals = []
        self.user_hit_kphs = []
        self.player_score = 0
        self.player_goals = 0
        self.touches = 0
        self.car_touches = 0
        self.shots = 0
        self.saves = 0
        self.assists = 0
        self.demos_given = 0
        self.demos_taken = 0
        self.is_overtime = False
        self.time_remaining = 300
        self.tick_count = 0
        self.active_tick_count = 0
        self.boost_sum = 0.0
        self.boost_count = 0
        self.boosting_ticks = 0
        self.supersonic_ticks = 0
        self.powerslide_ticks = 0
        self.on_ground_ticks = 0
        self.in_air_ticks = 0
        self.on_wall_ticks = 0
        self.speed_sum = 0.0
        self.max_speed_kph = 0.0
        self.teammate_name = None
        self.teammate_goals = 0
        self.teammate_score = 0
        self.teammate_shots = 0
        self.teammate_saves = 0
        self.teammate_assists = 0
        self.teammate_touches = 0
        self.teammate_demos = 0
        self.teammate_demos_base = 0
        self.teammate_demos_baselined = False
        self.teammate_active_ticks = 0
        self.teammate_boost_sum = 0.0
        self.teammate_boost_count = 0
        self.teammate_air_ticks = 0
        self.teammate_wall_ticks = 0
        self.teammate_supersonic_ticks = 0
        self.players_snapshot = {}
        self.user_live_stats = {}
        self.max_opponents = 0
        self.is_spectator_or_replay = False
        self.learned_primary_id = None
        # NOTE: _match_recorded is NOT cleared inside reset() — only in MatchCreated / MatchGuid change
        self._demos_baselined = False
        self._prev_demos = 0
        self._was_demolished = False
        self._team_confirm_count = 0
        self._team_confirm_candidate = None
        self._cross_check_fails = 0
        self._both_teams_spec_ticks = 0
        self._spec_only_lock = False
        self._last_target_shortcut = None
        self._last_goal_sig = None
        self._last_goal_ts = 0.0
        self.team_names = {}
        self.in_replay = False
        self.paused = False
        self.crossbar_hits = 0
        self.boost_pads = 0
        self.boost_pills = 0
        self.accolades = []
        self.forfeit = False

    @staticmethod
    def _norm_name(name: Any) -> str:
        if not name:
            return ""
        s = str(name).lower().strip()
        s = re.sub(r"^[\(\[\{<][^\)\]\}>]+[\)\]\}>]\s*", "", s)
        return "".join(ch for ch in s if ch.isalnum())

    def set_config(
        self,
        player_name: str,
        friend_names: Optional[List[str]] = None,
        aliases: Optional[List[str]] = None,
        primary_ids: Optional[List[str]] = None,
        tracking_cfg: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Hot-reload Settings without restarting listener."""
        new_name = (player_name or "").lower().strip()
        new_aliases = [str(a).lower().strip() for a in (aliases or []) if a and str(a).strip()]
        new_pids = {str(x).strip() for x in (primary_ids or []) if x and str(x).strip()}
        new_friends = [str(f).strip() for f in (friend_names or []) if f and str(f).strip()]
        new_fcache = {f.lower() for f in new_friends}
        new_tracking = normalize_tracking_config(tracking_cfg)

        identity_changed = (
            new_name != self.player_name
            or new_aliases != self.aliases
            or new_pids != self.primary_ids
            or new_fcache != self._friend_cache
        )
        tracking_changed = new_tracking != self.tracking_cfg

        self.tracking_cfg = new_tracking
        if not identity_changed:
            if tracking_changed:
                log(f"Tracking filter updated: scope={new_tracking['scope']}")
                _update_live_fields(tracking_scope=new_tracking["scope"])
            return False

        old = self.player_name
        self.player_name = new_name
        self.aliases = new_aliases
        self.primary_ids = new_pids
        self.friend_names = new_friends
        self._friend_cache = new_fcache
        self._friend_norm_cache = {self._norm_name(f) for f in new_friends if self._norm_name(f)}

        self.user_team_num = None
        self._team_confirm_count = 0
        self._team_confirm_candidate = None
        self._cross_check_fails = 0
        self._spec_only_lock = False
        log(f"Config identity updated: '{old}' -> '{new_name}' (friends={len(new_friends)}); team unlocked")
        _update_live_fields(tracking_scope=new_tracking["scope"])
        return True

    def _candidate_names(self) -> List[str]:
        out = []
        if self.player_name:
            out.append(self.player_name)
        for a in self.aliases:
            if a not in out:
                out.append(a)
        return out

    def _is_friend_name(self, name: str) -> bool:
        if not name or not self._friend_cache:
            return False
        nl = name.lower().strip()
        nn = self._norm_name(nl)
        if nl in self._friend_cache or (nn and nn in self._friend_norm_cache):
            return True
        return any(
            (f in nl or nl in f) or (fn and nn and (fn in nn or nn in fn))
            for f, fn in ((fc, self._norm_name(fc)) for fc in self._friend_cache)
        )

    def _fast_find(self, players: List[Dict[str, Any]], targets: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
        """Two-pass exact-first player lookup across PrimaryIds and candidate names."""
        if not players:
            return None
        if self.primary_ids:
            for p in players:
                pid = str(p.get("PrimaryId") or "").strip()
                if pid and pid in self.primary_ids:
                    return p

        names = targets if targets is not None else self._candidate_names()
        for target in names:
            tl = target.lower().strip()
            tn = self._norm_name(tl)
            # Pass 1: exact case-insensitive
            for p in players:
                pname = p.get("Name") or p.get("name") or ""
                if pname and pname.lower().strip() == tl:
                    return p
            # Pass 2: normalized exact (ignores clan tags)
            if tn:
                for p in players:
                    pname = p.get("Name") or p.get("name") or ""
                    if pname and self._norm_name(pname) == tn:
                        return p
            # Pass 3: partial match fallback
            for p in players:
                pname = p.get("Name") or p.get("name") or ""
                if not pname:
                    continue
                pl = pname.lower().strip()
                pn = self._norm_name(pl)
                if tl in pl or pl in tl or (tn and pn and (tn in pn or pn in tn)):
                    return p
        return None

    def _roster_summary(self, players: List[Dict[str, Any]]) -> str:
        parts = []
        for p in players or []:
            nm = p.get("Name") or p.get("name") or "?"
            tn = p.get("TeamNum", "?")
            spec = "S" if ("bHasCar" in p or "Boost" in p) else "-"
            parts.append(f"{nm}|T{tn}|{spec}")
        return ", ".join(parts) if parts else "(empty)"

    def _own_team_spec_players(self, players: List[Dict[str, Any]], team_num: int) -> List[Dict[str, Any]]:
        out = []
        for p in players or []:
            if p.get("TeamNum") == team_num and ("bHasCar" in p or "Boost" in p or "Speed" in p):
                out.append(p)
        return out

    def _pick_local_user(self, players: List[Dict[str, Any]], team_num: int) -> Optional[Dict[str, Any]]:
        own = [p for p in (players or []) if p.get("TeamNum") == team_num]
        if not own:
            return None

        # 1) PrimaryId or configured name/alias match on own team
        up = self._fast_find(own)
        if up is not None:
            return up

        # 2) Sole player on team (1v1)
        if len(own) == 1:
            return own[0]

        # 3) Exclude known friends on own team — if 1 non-friend remains, it's the user!
        if self._friend_cache:
            non_friends = [p for p in own if not self._is_friend_name(p.get("Name") or p.get("name") or "")]
            if len(non_friends) == 1:
                return non_friends[0]

        # 4) Game.Target shortcut if on own team
        if self._last_target_shortcut is not None:
            for p in own:
                if p.get("Shortcut") == self._last_target_shortcut:
                    return p

        # 5) Sole SPECTATOR player on own team
        spec = self._own_team_spec_players(players, team_num)
        if len(spec) == 1:
            return spec[0]
        return None

    def _lock_team(self, candidate: int, players: List[Dict[str, Any]], up: Optional[Dict[str, Any]] = None, reason: str = "SPECTATOR") -> None:
        self.user_team_num = candidate
        self._cross_check_fails = 0
        self._name_miss_streak_reset()
        team_name = "Blue" if candidate == 0 else "Orange"
        if up is None:
            up = self._pick_local_user(players, candidate)
        if up is not None:
            rl_name = up.get("Name") or up.get("name") or ""
            pid = str(up.get("PrimaryId") or "").strip()
            if pid:
                self.learned_primary_id = pid
            if rl_name and self._norm_name(rl_name) and (
                not self.player_name
                or (
                    self._norm_name(rl_name) != self._norm_name(self.player_name)
                    and not self._is_friend_name(rl_name)
                    and not self._fast_find([up], self.aliases)
                )
            ):
                # Auto-learn alt account name when sole/non-friend player identified
                own = [p for p in players if p.get("TeamNum") == candidate]
                if len(own) == 1 or (self._friend_cache and len([p for p in own if not self._is_friend_name(p.get("Name") or "")]) == 1):
                    old = self.player_name
                    self.player_name = rl_name.lower().strip()
                    log(f"Auto-learned RL name: '{old}' -> '{self.player_name}'")
            log(f"Team LOCKED via {reason}: {candidate} ({team_name}) | User: {rl_name}")
            update_status("connected", f"Live - tracking {rl_name}", self.player_name, self.friend_names, tracking_scope=self.tracking_cfg["scope"])
        else:
            log(f"Team LOCKED via {reason}: {candidate} ({team_name}) — player pending ({self._roster_summary(players)})")
            update_status("connected", f"Live - team {team_name} locked", self.player_name, self.friend_names, tracking_scope=self.tracking_cfg["scope"])

    def _name_miss_streak_reset(self) -> None:
        pass

    def _find_user_player(self, players: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if self.user_team_num is None:
            return None
        return self._pick_local_user(players, self.user_team_num)

    def _reconcile_live_scores(self) -> tuple[int, int]:
        team_delta = None
        if self.team_score_base is not None:
            team_delta = [
                self.team_score_latest[0] - self.team_score_base[0],
                self.team_score_latest[1] - self.team_score_base[1],
            ]
        return reconcile_scores(self.goal_scores, team_delta, self.player_goals_sum)

    @property
    def user_score(self) -> int:
        if self.user_team_num not in (0, 1):
            return 0
        s0, s1 = self._reconcile_live_scores()
        return s0 if self.user_team_num == 0 else s1

    @property
    def opponent_score(self) -> int:
        if self.user_team_num not in (0, 1):
            return 0
        s0, s1 = self._reconcile_live_scores()
        return s1 if self.user_team_num == 0 else s0

    def _current_classification(self) -> Dict[str, Any]:
        return classify_match(
            self.playlist_id,
            self.match_guid,
            self.max_opponents,
            self.is_spectator_or_replay,
            self.tracking_cfg,
        )

    def publish_live(self, force: bool = False) -> None:
        now = time.time()
        if not force and (now - self._last_live_publish) < 0.25:
            return
        self._last_live_publish = now
        post_match_podium = bool(
            self._match_recorded and self.match_guid and self.match_guid == self._last_recorded_guid
        )
        in_match = (not post_match_podium) and bool(
            self.tick_count > 0 or self.match_guid or self.user_team_num is not None
        )
        if not in_match:
            _update_live_fields(
                in_match=False,
                tracking_active=False,
                skip_reason="",
                playlist_id=None,
                playlist="Unknown",
                playlist_category="",
                arena="",
                arena_name="",
                match_guid="",
                user_team_num=None,
                user_score=0,
                opponent_score=0,
                blue_score=0,
                orange_score=0,
                time_remaining=300,
                is_overtime=False,
                in_replay=False,
                user_live={},
                players=[],
                goals=[],
            )
            return

        cls = self._current_classification()
        s0, s1 = self._reconcile_live_scores()
        us = (s0 if self.user_team_num == 0 else s1) if self.user_team_num in (0, 1) else 0
        opp = (s1 if self.user_team_num == 0 else s0) if self.user_team_num in (0, 1) else 0
        plist = sorted(
            self.players_snapshot.values(),
            key=lambda x: (x.get("team_num", 9), -int(x.get("score") or 0), x.get("name") or ""),
        )
        _update_live_fields(
            in_match=True,
            tracking_active=bool(cls["should_record"]),
            skip_reason="" if cls["should_record"] else cls["reason"],
            playlist_id=self.playlist_id,
            playlist=self.playlist,
            playlist_category=cls["category"],
            arena=self.arena or "",
            arena_name=arena_label(self.arena) if self.arena else "",
            match_guid=self.match_guid,
            mode=self.mode,
            friend_name=self.friend_name,
            user_team_num=self.user_team_num,
            user_score=us,
            opponent_score=opp,
            blue_score=s0,
            orange_score=s1,
            time_remaining=self.time_remaining,
            is_overtime=self.is_overtime,
            in_replay=self.in_replay,
            user_live=dict(self.user_live_stats),
            players=plist,
            goals=list(self.goals),
        )

    def handle_update_state(self, data: Dict[str, Any]) -> bool:
        players = data.get("Players") or []
        game = data.get("Game") or {}

        new_guid = str(data.get("MatchGuid") or "").strip()
        if new_guid and self._last_recorded_guid and new_guid != self._last_recorded_guid and self._match_recorded:
            self._match_recorded = False
        if new_guid and self.match_guid and new_guid != self.match_guid:
            if self.pending_end_at is not None and not self._match_recorded:
                self.finalize_match(match_ended_winner=None, source="MatchGuidChanged")
            else:
                self.reset()
            self._match_recorded = False
        if new_guid:
            self.match_guid = new_guid
        if self._match_recorded and self.match_guid and self.match_guid == self._last_recorded_guid:
            # Trailing podium ticks of the match already recorded
            self._last_update_time = time.time()
            return False

        self.tick_count += 1
        self._last_update_time = time.time()

        if "bReplay" in game:
            self.in_replay = bool(game.get("bReplay"))

        if game.get("bHasTarget") and isinstance(game.get("Target"), dict):
            sc = game["Target"].get("Shortcut")
            if sc is not None and not isinstance(sc, bool):
                self._last_target_shortcut = sc

        # Team names & score delta baseline
        teams = game.get("Teams") or []
        tmap: Dict[int, int] = {}
        for t in teams:
            if not isinstance(t, dict):
                continue
            tn = t.get("TeamNum")
            nm = t.get("Name")
            if tn in (0, 1):
                if nm:
                    self.team_names[int(tn)] = str(nm)
                try:
                    tmap[int(tn)] = int(t.get("Score") or 0)
                except (TypeError, ValueError):
                    pass
        if 0 in tmap and 1 in tmap:
            if self.team_score_base is None:
                self.team_score_base = [tmap[0], tmap[1]]
            self.team_score_latest = [tmap[0], tmap[1]]

        # Arena & Playlist
        arena = game.get("Arena")
        if arena:
            self.arena = str(arena)

        pid = game.get("PlaylistId")
        if pid is not None and not isinstance(pid, bool):
            try:
                self.playlist_id = int(pid)
                self.playlist = playlist_label(self.playlist_id, len(players), self.playlist)
            except (TypeError, ValueError):
                pass
        elif not self.playlist or self.playlist == "Unknown":
            for key in ("Playlist", "PlaylistName", "MatchType", "GameMode", "Mode"):
                val = game.get(key)
                if val not in (None, "", 0):
                    self.playlist = str(val)
                    break

        if game.get("bOvertime"):
            self.is_overtime = True
        if "TimeSeconds" in game:
            try:
                self.time_remaining = int(game["TimeSeconds"])
            except (TypeError, ValueError):
                pass

        # Spectator vs player detection (bHasCar/Boost/Speed on BOTH teams = Replay/Spectator!)
        spec_teams = {
            p.get("TeamNum")
            for p in players
            if p.get("TeamNum") in (0, 1) and any(k in p for k in ("bHasCar", "Boost", "Speed"))
        }
        if len(spec_teams) >= 2:
            self._both_teams_spec_ticks += 1
            if self._both_teams_spec_ticks >= 5 and not self.is_spectator_or_replay:
                self.is_spectator_or_replay = True
                log("Detected SPECTATOR/REPLAY (telemetry present on both teams) — match will be ignored")
        else:
            self._both_teams_spec_ticks = 0

        # Team detection
        if self.user_team_num is None and players and not self.is_spectator_or_replay:
            if len(spec_teams) == 1:
                candidate = next(iter(spec_teams))
                if candidate == self._team_confirm_candidate:
                    self._team_confirm_count += 1
                    if self._team_confirm_count >= 3:
                        up = self._fast_find(players)
                        if up and up.get("TeamNum") in (0, 1) and up.get("TeamNum") != candidate:
                            log(f"SPECTATOR candidate {candidate} conflicts with user '{self.player_name}' on team {up.get('TeamNum')} — retrying")
                            self._team_confirm_count = 0
                            self._team_confirm_candidate = None
                        else:
                            self._spec_only_lock = up is None
                            self._lock_team(candidate, players, up=up if (up and up.get("TeamNum") == candidate) else None, reason="SPECTATOR")
                else:
                    self._team_confirm_candidate = candidate
                    self._team_confirm_count = 1
            elif self.tick_count >= 30 and self.player_name:
                up = self._fast_find(players)
                tnum = up.get("TeamNum", -1) if up else -1
                if up and tnum in (0, 1):
                    self._team_confirm_candidate = tnum
                    self._team_confirm_count = 3
                    self._spec_only_lock = False
                    self._lock_team(tnum, players, up=up, reason="name-fallback")

        # Post-lock sanity check (never unlock once pending_end_at started)
        if self.user_team_num is not None and players and self.pending_end_at is None:
            up = self._find_user_player(players)
            own_spec = self._own_team_spec_players(players, self.user_team_num)
            if up is None and not own_spec:
                self._cross_check_fails += 1
                if self._cross_check_fails >= 15:
                    log(f"Team {self.user_team_num} lost evidence for {self._cross_check_fails} ticks — unlocking")
                    self.user_team_num = None
                    self._team_confirm_count = 0
                    self._team_confirm_candidate = None
                    self._cross_check_fails = 0
                    self._spec_only_lock = False
            else:
                self._cross_check_fails = 0
                if up is not None and self._spec_only_lock:
                    self._spec_only_lock = False
                    rl_name = up.get("Name") or up.get("name") or ""
                    if rl_name and not self._is_friend_name(rl_name):
                        self.player_name = rl_name.lower().strip()
                    update_status("connected", f"Live - tracking {rl_name}", self.player_name, self.friend_names, tracking_scope=self.tracking_cfg["scope"])

        # Per-team player goals sum & max_opponents
        pg0 = 0
        pg1 = 0
        t0_cnt = 0
        t1_cnt = 0
        for p in players:
            tn = p.get("TeamNum")
            if tn == 0:
                t0_cnt += 1
                pg0 += int(p.get("Goals") or 0)
            elif tn == 1:
                t1_cnt += 1
                pg1 += int(p.get("Goals") or 0)
        self.player_goals_sum = [pg0, pg1]
        if self.user_team_num in (0, 1):
            opp_cnt = t1_cnt if self.user_team_num == 0 else t0_cnt
            if opp_cnt > self.max_opponents:
                self.max_opponents = opp_cnt
        elif t0_cnt > 0 and t1_cnt > 0:
            self.max_opponents = max(self.max_opponents, min(t0_cnt, t1_cnt))

        # Capture full roster snapshot + user & teammate telemetry
        if self.user_team_num is not None and players:
            user_p = self._find_user_player(players)
            teammate_p = None

            for fp in players:
                fname = str(fp.get("Name") or fp.get("name") or "").strip()
                if not fname:
                    continue
                ftn = fp.get("TeamNum", -1)
                is_user = fp is user_p
                is_friend = (not is_user) and (ftn == self.user_team_num) and self._is_friend_name(fname)
                if is_friend and self.mode == "solo":
                    self.mode = "duo"
                    self.friend_name = fname
                    log(f"Duo detected: {fname}")

                if (not is_user) and (ftn == self.user_team_num):
                    if teammate_p is None or is_friend:
                        teammate_p = fp

                pkey = str(fp.get("PrimaryId") or f"{ftn}:{fname.lower()}")
                self.players_snapshot[pkey] = {
                    "name": fname,
                    "primary_id": str(fp.get("PrimaryId") or ""),
                    "team_num": ftn,
                    "score": int(fp.get("Score") or 0),
                    "goals": int(fp.get("Goals") or 0),
                    "assists": int(fp.get("Assists") or 0),
                    "saves": int(fp.get("Saves") or 0),
                    "shots": int(fp.get("Shots") or 0),
                    "touches": int(fp.get("Touches") or 0),
                    "demos": int(fp.get("Demos") or 0),
                    "is_user": is_user,
                    "is_friend": is_friend,
                }

            live_play = (not self.in_replay) and (not self.paused) and (self.pending_end_at is None)

            if user_p is not None:
                self.player_score = int(user_p.get("Score") or 0)
                self.player_goals = int(user_p.get("Goals") or 0)
                self.touches = int(user_p.get("Touches") or 0)
                self.car_touches = int(user_p.get("CarTouches") or 0)
                self.shots = int(user_p.get("Shots") or 0)
                self.saves = int(user_p.get("Saves") or 0)
                self.assists = int(user_p.get("Assists") or 0)

                demos_now = int(user_p.get("Demos") or 0)
                if not self._demos_baselined:
                    self._prev_demos = demos_now
                    self._demos_baselined = True
                elif demos_now > self._prev_demos:
                    self.demos_given += demos_now - self._prev_demos
                self._prev_demos = demos_now

                if live_play and user_p.get("bHasCar", True):
                    self.active_tick_count += 1
                    boost = float(user_p.get("Boost") or 0.0)
                    self.boost_sum += boost
                    self.boost_count += 1
                    if boost > 0 and user_p.get("bBoosting"):
                        self.boosting_ticks += 1
                    if user_p.get("bSupersonic"):
                        self.supersonic_ticks += 1
                    if user_p.get("bPowersliding"):
                        self.powerslide_ticks += 1
                    # Wall BEFORE Ground (RL sends both True on walls)
                    if user_p.get("bOnWall"):
                        self.on_wall_ticks += 1
                    elif user_p.get("bOnGround"):
                        self.on_ground_ticks += 1
                    else:
                        self.in_air_ticks += 1

                    spd_kph = float(user_p.get("Speed") or 0.0) * UU_TO_KPH
                    self.speed_sum += spd_kph
                    if spd_kph > self.max_speed_kph:
                        self.max_speed_kph = spd_kph

                    if user_p.get("bDemolished"):
                        if not self._was_demolished:
                            self.demos_taken += 1
                        self._was_demolished = True
                    else:
                        self._was_demolished = False

                    self.user_live_stats = {
                        "name": user_p.get("Name") or self.player_name,
                        "boost": round(boost),
                        "speed_kph": round(spd_kph, 1),
                        "supersonic": bool(user_p.get("bSupersonic")),
                        "score": self.player_score,
                        "goals": self.player_goals,
                        "assists": self.assists,
                        "saves": self.saves,
                        "shots": self.shots,
                        "demos": self.demos_given,
                    }

            if teammate_p is not None:
                self.teammate_name = teammate_p.get("Name") or self.teammate_name
                self.teammate_goals = int(teammate_p.get("Goals") or 0)
                self.teammate_score = int(teammate_p.get("Score") or 0)
                self.teammate_shots = int(teammate_p.get("Shots") or 0)
                self.teammate_saves = int(teammate_p.get("Saves") or 0)
                self.teammate_assists = int(teammate_p.get("Assists") or 0)
                self.teammate_touches = int(teammate_p.get("Touches") or 0)
                tdemos_now = int(teammate_p.get("Demos") or 0)
                if not self.teammate_demos_baselined:
                    self.teammate_demos_base = tdemos_now
                    self.teammate_demos_baselined = True
                elif tdemos_now > self.teammate_demos_base:
                    self.teammate_demos += tdemos_now - self.teammate_demos_base
                self.teammate_demos_base = tdemos_now

                if self.mode == "duo" and not self.friend_name:
                    self.friend_name = self.teammate_name

                if live_play and teammate_p.get("bHasCar", True) and "Boost" in teammate_p:
                    self.teammate_active_ticks += 1
                    self.teammate_boost_sum += float(teammate_p.get("Boost") or 0.0)
                    self.teammate_boost_count += 1
                    if teammate_p.get("bOnWall"):
                        self.teammate_wall_ticks += 1
                    elif not teammate_p.get("bOnGround"):
                        self.teammate_air_ticks += 1
                    if teammate_p.get("bSupersonic"):
                        self.teammate_supersonic_ticks += 1

        # Match end detection: enter pending_end_at so MatchEnded (with WinnerTeamNum) gets 2.5s window
        if self.user_team_num is not None and game.get("bHasWinner") and not self._match_recorded:
            if game.get("Winner") not in (None, ""):
                self.game_winner_str = game.get("Winner")
            if self.pending_end_at is None:
                self.pending_end_at = time.time()
                log(f"bHasWinner seen (winner={self.game_winner_str!r}) — waiting briefly for MatchEnded")

        self.publish_live()
        return False

    def _matches_user_ref(self, ref: Any) -> bool:
        if not isinstance(ref, dict):
            return False
        nm = str(ref.get("Name") or ref.get("name") or "").lower().strip()
        if not nm:
            return False
        for c in self._candidate_names():
            if c == nm or self._norm_name(c) == self._norm_name(nm):
                return True
        return False

    def handle_goal_scored(self, d: Dict[str, Any]) -> None:
        if self.in_replay or is_bogus_goal_scored(d):
            return

        scorer = FieldResolver.resolve_raw(d, "scorer") or {}
        if isinstance(scorer, dict):
            sname = str(scorer.get("Name") or scorer.get("name") or "").strip()
            steam = scorer.get("TeamNum", -1)
        else:
            sname = str(scorer or "").strip()
            steam = FieldResolver.resolve(d, "team_num")
            if steam is None:
                steam = -1

        if not sname:
            return

        gs = FieldResolver.resolve(d, "goal_speed")
        speed_kph = round(float(gs), 1) if gs else None  # GoalSpeed already in km/h

        # Deduplicate duplicate goal payloads arriving within 3.5s
        now_ts = time.time()
        sig = (sname.lower(), steam, round(speed_kph or 0.0, 0))
        if sig == self._last_goal_sig and (now_ts - self._last_goal_ts) < 3.5:
            return
        self._last_goal_sig = sig
        self._last_goal_ts = now_ts

        if steam in (0, 1):
            self.goal_scores[steam] += 1
        else:
            log(FieldResolver.raw_dump(d, f"GOAL UNKNOWN TEAM: scorer='{sname}' team={steam}"))

        assister = FieldResolver.resolve_raw(d, "assister")
        aname = (assister.get("Name") or assister.get("name")) if isinstance(assister, dict) else (assister or None)
        if aname:
            aname = str(aname).strip() or None

        self.goals.append(
            {
                "scored_at": datetime.now(timezone.utc).isoformat(),
                "scorer": sname,
                "assister": aname,
                "team_num": steam,
                "speed_kph": speed_kph,
                "time_remaining": self.time_remaining,
                "is_overtime": self.is_overtime,
            }
        )
        self.publish_live(force=True)

    def handle_ball_hit(self, d: Dict[str, Any]) -> None:
        players = d.get("Players") or []
        if not players:
            return
        ph = players[0]
        if not self._matches_user_ref(ph):
            return
        ball = d.get("Ball") or {}
        post_kph = round(float(ball.get("PostHitSpeed") or 0.0) * UU_TO_KPH, 1)
        if post_kph >= 55.0:
            self.user_hit_kphs.append(post_kph)

    def finalize_match(self, match_ended_winner: Any = None, source: str = "MatchEnded") -> Optional[int]:
        """Classify, reconcile scores, decide W/L, and persist to SQLite if allowed."""
        if self._match_recorded:
            return None

        cls = self._current_classification()
        if not cls["should_record"]:
            log(f"SKIPPED ({cls['category']}): {cls['reason']}")
            self._match_recorded = True
            self.reset()
            self.publish_live(force=True)
            return None

        if self.user_team_num not in (0, 1):
            log(f"SKIPPED ({source}): user_team_num unresolved")
            self._match_recorded = True
            self.reset()
            self.publish_live(force=True)
            return None

        s0, s1 = self._reconcile_live_scores()
        result, is_ff = decide_result(
            self.user_team_num,
            match_ended_winner=match_ended_winner,
            game_winner=self.game_winner_str,
            scores=(s0, s1),
            team_names=self.team_names,
            is_overtime=self.is_overtime,
            time_remaining=self.time_remaining,
        )

        if result == "no_contest":
            log(f"SKIPPED ({source}): No-Contest (WinnerTeamNum=-1)")
            self._match_recorded = True
            self.reset()
            self.publish_live(force=True)
            return None

        us = s0 if self.user_team_num == 0 else s1
        opp = s1 if self.user_team_num == 0 else s0

        if result == "draw" and us == 0 and opp == 0:
            log(f"SKIPPED ({source}): empty 0-0 draw")
            self._match_recorded = True
            self.reset()
            self.publish_live(force=True)
            return None

        if is_ff:
            self.forfeit = True
            if "Forfeit" not in self.accolades:
                self.accolades.append("Forfeit")
        if self.is_overtime and "Overtime" not in self.accolades:
            self.accolades.append("Overtime")

        self._match_recorded = True
        if self.match_guid:
            self._last_recorded_guid = self.match_guid
        log(
            f"Match ended ({source}): {result.upper()}! "
            f"score={us}-{opp} (raw={s0}-{s1}) playlist={cls['label']} "
            f"winner_num={match_ended_winner!r} game_winner={self.game_winner_str!r} "
            f"team={self.user_team_num} ot={self.is_overtime} ff={self.forfeit}"
        )
        mid = self._record_to_db(result, us, opp, cls)
        self.reset()
        self.publish_live(force=True)
        return mid

    def _record_to_db(self, result: str, user_score: int, opponent_score: int, cls: Dict[str, Any]) -> Optional[int]:
        db = get_db()
        now = datetime.now(timezone.utc).isoformat()

        # MatchGuid dedup
        if self.match_guid:
            existing_guid = db.execute("SELECT id FROM matches WHERE match_guid=?", (self.match_guid,)).fetchone()
            if existing_guid:
                log(f"SKIP DUP (MatchGuid): {self.match_guid} already id={existing_guid['id']}")
                db.close()
                return None

        session = db.execute("SELECT id FROM sessions WHERE status='active' ORDER BY started_at DESC LIMIT 1").fetchone()
        if session:
            session_id = session["id"]
            cutoff = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
            existing = db.execute(
                "SELECT id FROM matches WHERE session_id=? AND user_score=? AND opponent_score=? AND played_at > ?",
                (session_id, user_score, opponent_score, cutoff),
            ).fetchone()
            if existing:
                log(f"SKIP DUP (60s window): id={existing['id']}")
                db.close()
                return None
        else:
            cur = db.execute(
                "INSERT INTO sessions (started_at, mode, friend_name) VALUES (?, ?, ?)",
                (now, self.mode, self.friend_name),
            )
            session_id = cur.lastrowid

        if self.mode == "duo" and self.friend_name:
            try:
                db.execute(
                    "UPDATE sessions SET mode='duo', friend_name=COALESCE(friend_name, ?) WHERE id=? AND status='active'",
                    (self.friend_name, session_id),
                )
            except Exception:
                pass

        ensure_schema(db)

        # Compute MVP from own team snapshot when win
        is_mvp = 0
        own_scores = [
            int(p.get("score") or 0)
            for p in self.players_snapshot.values()
            if p.get("team_num") == self.user_team_num
        ]
        if result == "win" and self.player_score > 0 and own_scores and self.player_score >= max(own_scores):
            is_mvp = 1
            if "MVP" not in self.accolades:
                self.accolades.append("MVP")

        tags = ", ".join(self.accolades) if self.accolades else None
        playlist_name = cls["label"] or self.playlist or "Unknown"
        is_comp = 1 if cls["is_competitive"] else 0

        cur = db.execute(
            """INSERT INTO matches
               (session_id, played_at, user_score, opponent_score, result, mode, playlist, friend_name,
                tags, match_guid, playlist_id, is_competitive)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                session_id,
                now,
                user_score,
                opponent_score,
                result,
                self.mode,
                playlist_name,
                self.friend_name,
                tags,
                self.match_guid or None,
                self.playlist_id,
                is_comp,
            ),
        )
        match_id = cur.lastrowid
        if not match_id:
            db.close()
            return None

        ticks = max(self.active_tick_count, 1)
        tticks = max(self.teammate_active_ticks, 1)

        # Personal goals fall back to user_score only when player lookup didn't happen
        pgoals = self.player_goals if self.player_goals is not None else 0

        fast_goal_kphs = [float(g["speed_kph"]) for g in self.goals if g.get("speed_kph")]
        fastest_goal = round(max(fast_goal_kphs), 1) if fast_goal_kphs else 0.0
        if fast_goal_kphs:
            avg_power = round(sum(fast_goal_kphs) / len(fast_goal_kphs), 1)
        elif self.user_hit_kphs:
            top_hits = sorted(self.user_hit_kphs, reverse=True)[:5]
            avg_power = round(sum(top_hits) / len(top_hits), 1)
        else:
            avg_power = 0.0

        duration_sec = int(max(0, min(time.time() - self.match_started_at, 3600)))
        players_list = sorted(
            self.players_snapshot.values(),
            key=lambda x: (x.get("team_num", 9), -int(x.get("score") or 0), x.get("name") or ""),
        )

        db.execute(
            """INSERT INTO match_details
               (match_id, arena, overtime, touches, car_touches, shots, saves, assists,
                demos_given, demos_taken, boost_avg, boost_time_pct, supersonic_time_pct,
                ground_time_pct, air_time_pct, wall_time_pct, fastest_goal_kph, avg_shot_power,
                time_remaining_sec, playlist, teammate_name, teammate_shots, teammate_saves,
                teammate_assists, teammate_touches, teammate_demos,
                crossbar_hits, boost_pads, boost_pills, forfeit, accolades,
                player_goals, player_score, is_mvp, powerslide_time_pct, avg_speed_kph,
                max_speed_kph, duration_sec, players_json,
                teammate_goals, teammate_score, teammate_boost_avg, teammate_air_pct,
                teammate_wall_pct, teammate_supersonic_pct)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                match_id,
                self.arena,
                int(self.is_overtime),
                self.touches,
                self.car_touches,
                self.shots,
                self.saves,
                self.assists,
                self.demos_given,
                self.demos_taken,
                round(self.boost_sum / max(self.boost_count, 1), 1),
                round(self.boosting_ticks / ticks * 100, 1),
                round(self.supersonic_ticks / ticks * 100, 1),
                round(self.on_ground_ticks / ticks * 100, 1),
                round(self.in_air_ticks / ticks * 100, 1),
                round(self.on_wall_ticks / ticks * 100, 1),
                fastest_goal,
                avg_power,
                self.time_remaining,
                playlist_name,
                self.teammate_name,
                self.teammate_shots,
                self.teammate_saves,
                self.teammate_assists,
                self.teammate_touches,
                self.teammate_demos,
                self.crossbar_hits,
                self.boost_pads,
                self.boost_pills,
                int(self.forfeit),
                tags,
                pgoals,
                self.player_score,
                is_mvp,
                round(self.powerslide_ticks / ticks * 100, 1),
                round(self.speed_sum / ticks, 1),
                round(self.max_speed_kph, 1),
                duration_sec,
                json.dumps(players_list, ensure_ascii=False),
                self.teammate_goals,
                self.teammate_score,
                round(self.teammate_boost_sum / max(self.teammate_boost_count, 1), 1) if self.teammate_boost_count else 0.0,
                round(self.teammate_air_ticks / tticks * 100, 1) if self.teammate_active_ticks else 0.0,
                round(self.teammate_wall_ticks / tticks * 100, 1) if self.teammate_active_ticks else 0.0,
                round(self.teammate_supersonic_ticks / tticks * 100, 1) if self.teammate_active_ticks else 0.0,
            ),
        )

        for g in self.goals:
            db.execute(
                "INSERT INTO goals (match_id, scored_at, scorer, assister, team_num, speed_kph, time_remaining_sec) VALUES (?,?,?,?,?,?,?)",
                (
                    match_id,
                    g.get("scored_at", now),
                    g["scorer"],
                    g.get("assister"),
                    g.get("team_num", self.user_team_num),
                    g.get("speed_kph"),
                    g.get("time_remaining"),
                ),
            )

        db.commit()
        db.close()
        _write_summary(match_id)
        flush_log()

        _update_live_fields(
            last_recorded_match_id=match_id,
            last_recorded_result=result,
            last_recorded_score=f"{user_score}-{opponent_score}",
            last_recorded_playlist=playlist_name,
            last_recorded_at=now,
        )

        label = "WIN" if result == "win" else ("DRAW" if result == "draw" else "LOSS")
        log(f"RECORDED #{match_id}: {label}! {user_score}-{opponent_score} (you:{pgoals}G/{self.assists}A/{self.saves}Sv/{self.shots}Sh) [{self.mode}/{playlist_name}]")

        try:
            res = _coach.analyze_match(match_id)
            n = len(res.get("insights", []))
            if n:
                log(f"COACH: {n} insights for match {match_id}")
        except Exception as e:
            log(f"COACH WARN: analyze_match failed for {match_id}: {e}")

        return match_id


# =============================================================================
# FAST listener loop - non-blocking with select
# =============================================================================


def _apply_config_to_state(state: MatchState) -> tuple[str, List[str]]:
    cfg = load_config() or {}
    pcfg = cfg.get("player") or {}
    tcfg = cfg.get("tracking") or DEFAULT_TRACKING_CONFIG
    new_name = str(pcfg.get("name") or "")
    new_friends = list(pcfg.get("friends") or [])
    new_aliases = list(pcfg.get("aliases") or [])
    new_pids = list(pcfg.get("primary_ids") or [])
    state.set_config(
        new_name,
        friend_names=new_friends,
        aliases=new_aliases,
        primary_ids=new_pids,
        tracking_cfg=tcfg,
    )
    return new_name, new_friends


def run_listener(player: str, friends: list, stop_event) -> None:
    host = "127.0.0.1"
    port = 49123
    cfg_init = load_config() or {}
    pcfg_init = cfg_init.get("player") or {}
    tcfg_init = normalize_tracking_config(cfg_init.get("tracking"))
    update_status("starting", "Initializing...", player, friends, tracking_scope=tcfg_init["scope"])

    log("=" * 56)
    log(f"RL Raw TCP Listener v{APP_VERSION} Overdrive (Competitive Guard)")
    log(f"   Player: {player or '(not set)'} | Friends: {', '.join(friends) if friends else 'none'} | Scope: {tcfg_init['scope']}")
    log("=" * 56)

    if not player:
        update_status("no_player", "Player name not configured - enter it in Settings", tracking_scope=tcfg_init["scope"])
        log("No player name configured. Waiting for config...")
        while not stop_event.is_set():
            time.sleep(2)
            cfg = load_config()
            p = cfg.get("player") or {}
            if p.get("name"):
                player = str(p["name"])
                friends = list(p.get("friends") or [])
                pcfg_init = p
                tcfg_init = normalize_tracking_config(cfg.get("tracking"))
                log(f"Player config loaded: {player}")
                update_status("connecting", f"Starting for {player}...", player, friends, tracking_scope=tcfg_init["scope"])
                break
        else:
            return

    state = MatchState(
        player,
        friend_names=friends,
        aliases=pcfg_init.get("aliases") or [],
        primary_ids=pcfg_init.get("primary_ids") or [],
        tracking_cfg=tcfg_init,
    )
    init_db()
    update_status("connecting", "Connecting to Rocket League...", player, friends, tracking_scope=state.tracking_cfg["scope"])

    reconnect_delay = 3
    decoder = json.JSONDecoder()

    while not stop_event.is_set():
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        try:
            sock.connect((host, port))
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2 * 1024 * 1024)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 128 * 1024)
            sock.settimeout(0)  # Non-blocking for recv()

            log("Connected to Rocket League Stats API!")
            update_status("connected", "Live - waiting for match", player, friends, tracking_scope=state.tracking_cfg["scope"])
            state._connected = True
            state.publish_live(force=True)

            buffer = ""
            pos = 0
            last_heartbeat = time.time()
            last_flush = time.time()
            last_config_check = 0.0
            event_count = 0
            stall_count = 0
            first_data = True

            while not stop_event.is_set():
                try:
                    ready, _, _ = select.select([sock], [], [], 0.010)
                except (ValueError, OSError):
                    break

                if ready:
                    try:
                        chunk = sock.recv(65536)
                    except (BlockingIOError, socket.timeout):
                        continue
                    except (ConnectionResetError, BrokenPipeError, OSError) as e:
                        log(f"Connection lost: {e}")
                        break

                    if not chunk:
                        log("Connection closed by game")
                        break

                    if first_data:
                        log(f"DATA FLOWING: received {len(chunk)} bytes in first chunk")
                        first_data = False

                    buffer += chunk.decode("utf-8", errors="replace")

                    while True:
                        while pos < len(buffer) and buffer[pos] in " \t\r\n":
                            pos += 1
                        if pos >= len(buffer):
                            break

                        try:
                            obj, end = decoder.raw_decode(buffer[pos:])
                        except json.JSONDecodeError:
                            break

                        event = obj.get("Event", "")
                        event_count += 1
                        raw_data = obj.get("Data")

                        if event == "UpdateState":
                            data = json.loads(raw_data) if isinstance(raw_data, str) else (raw_data or {})
                            state.handle_update_state(data)

                        elif event == "MatchCreated":
                            if state.pending_end_at is not None and not state._match_recorded:
                                state.finalize_match(match_ended_winner=None, source="MatchCreated_prev")
                            else:
                                state.reset()
                            d = raw_data if isinstance(raw_data, dict) else {}
                            state.match_guid = str(d.get("MatchGuid") or "").strip()
                            state._match_recorded = False
                            state.publish_live(force=True)

                        elif event == "MatchInitialized":
                            if state.team_score_base is None:
                                state.team_score_base = list(state.team_score_latest) if state.team_score_latest else None

                        elif event == "MatchEnded":
                            d = raw_data if isinstance(raw_data, dict) else (json.loads(raw_data) if isinstance(raw_data, str) else {})
                            winner = d.get("WinnerTeamNum")
                            if winner is None:
                                winner = d.get("Winner")
                            state.finalize_match(match_ended_winner=winner, source="MatchEnded")

                        elif event == "PodiumStart":
                            if state.pending_end_at is not None and not state._match_recorded:
                                state.finalize_match(match_ended_winner=None, source="PodiumStart")

                        elif event == "MatchDestroyed":
                            if state.pending_end_at is not None and not state._match_recorded:
                                state.finalize_match(match_ended_winner=None, source="MatchDestroyed")
                            else:
                                # Left mid-match / left Freeplay / Training — NEVER record incomplete non-ended state
                                state.reset()
                                state.publish_live(force=True)

                        elif event == "GoalScored":
                            d = raw_data if isinstance(raw_data, dict) else (json.loads(raw_data) if isinstance(raw_data, str) else {})
                            state.handle_goal_scored(d)

                        elif event == "BallHit":
                            d = raw_data if isinstance(raw_data, dict) else (json.loads(raw_data) if isinstance(raw_data, str) else {})
                            state.handle_ball_hit(d)

                        elif event == "OverTimeBegin":
                            state.is_overtime = True

                        elif event == "ClockUpdatedSeconds":
                            if isinstance(raw_data, dict):
                                if "TimeSeconds" in raw_data:
                                    try:
                                        state.time_remaining = int(raw_data["TimeSeconds"])
                                    except (TypeError, ValueError):
                                        pass
                                if raw_data.get("bOvertime"):
                                    state.is_overtime = True

                        elif event in ("GoalReplayStart", "ReplayStart"):
                            state.in_replay = True
                        elif event in ("GoalReplayEnd", "ReplayEnd", "RoundStarted"):
                            state.in_replay = False
                        elif event == "MatchPaused":
                            state.paused = True
                        elif event == "MatchUnpaused":
                            state.paused = False

                        elif event == "StatfeedEvent":
                            d = raw_data if isinstance(raw_data, dict) else {}
                            label = accolade_label(d.get("EventName"))
                            target = d.get("MainTarget") or {}
                            if label and state._matches_user_ref(target):
                                if label not in state.accolades:
                                    state.accolades.append(label)
                                    log(f"ACCOLADE: {label} ({target.get('Name')})")

                        elif event == "CrossbarHit":
                            d = raw_data if isinstance(raw_data, dict) else {}
                            touch = (d.get("BallLastTouch") or {}).get("Player") or {}
                            if state._matches_user_ref(touch):
                                state.crossbar_hits += 1

                        elif event == "BoostPickup":
                            d = raw_data if isinstance(raw_data, dict) else {}
                            who = d.get("Player") or {}
                            if not d.get("bReplay") and state._matches_user_ref(who):
                                kind = str(d.get("BoostType") or "")
                                if "Pill" in kind:
                                    state.boost_pills += 1
                                else:
                                    state.boost_pads += 1

                        pos += end

                    if pos > 0:
                        buffer = buffer[pos:]
                        pos = 0
                    elif len(buffer) > 0:
                        stall_count += 1
                        if stall_count > 1000:
                            log(f"Buffer stalled ({len(buffer)}B), flushing")
                            buffer = ""
                            stall_count = 0
                    else:
                        stall_count = 0
                else:
                    stall_count = 0

                now = time.time()

                # Finalize match if bHasWinner arrived without MatchEnded within 2.5s
                if state.pending_end_at is not None and not state._match_recorded and (now - state.pending_end_at) >= 2.5:
                    state.finalize_match(match_ended_winner=None, source="bHasWinner_timeout")

                if now - last_heartbeat > 30:
                    log(
                        f"Heartbeat: {event_count} events, tick={state.tick_count}, "
                        f"team={state.user_team_num}, playlist={state.playlist}({state.playlist_id}), "
                        f"buf={len(buffer)}B"
                    )
                    last_heartbeat = now

                if now - last_config_check > 2:
                    last_config_check = now
                    try:
                        player, friends = _apply_config_to_state(state)
                    except Exception as e:
                        log(f"Config reload warn: {e}")

                if now - last_flush > 5:
                    flush_log()
                    last_flush = now

            # Connection ended cleanly
            state._connected = False
            state._poll_interval = 60
            sock.close()
            if state.pending_end_at is not None and not state._match_recorded:
                state.finalize_match(match_ended_winner=None, source="SocketDisconnect")
            else:
                state.reset()
            state.publish_live(force=True)

        except (ConnectionRefusedError, socket.timeout):
            update_status("disconnected", "RL not running", player, friends, tracking_scope=state.tracking_cfg["scope"])
            state.reset()
            state.publish_live(force=True)
            log(f"RL not available - retrying in {reconnect_delay}s...")
        except Exception as e:
            log(f"Error: {e}")

        try:
            sock.close()
        except Exception:
            pass
        if stop_event.is_set():
            break

        try:
            player, friends = _apply_config_to_state(state)
        except Exception:
            pass

        now = time.time()
        if state._connected and state._last_update_time > 0:
            gap = now - state._last_update_time
            state._poll_interval = 2 if gap < 5 else 15 if gap < 30 else 60
        else:
            state._poll_interval = 60
        poll_mode = "hot" if state._poll_interval == 2 else "warm" if state._poll_interval == 15 else "cold"
        update_status(
            "disconnected" if not state._connected else "connected",
            "RL not running (port 49123 closed)" if not state._connected else f"Polling ({poll_mode})",
            player,
            friends,
            poll_interval=state._poll_interval,
            poll_mode=poll_mode,
            tracking_scope=state.tracking_cfg["scope"],
        )
        time.sleep(min(state._poll_interval, 2))

    flush_log()
    log("Listener stopped")
    update_status("stopped", "Listener stopped", player, friends, tracking_scope=state.tracking_cfg["scope"])
