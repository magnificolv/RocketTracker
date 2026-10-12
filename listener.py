"""
Rocket League Stats API Raw TCP Listener - Windows Edition (FAST)
Direct TCP connection to RL Stats API (port 49123).
Optimized for low-latency to prevent TCP backpressure on RL.
"""
import json
import os
import re
import select
import sqlite3
import socket
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Active Coach (TRIZ #25): analyse each match right after recording it.
# Instance is created after DB_PATH is defined (see below).
from coach import CoachEngine

from field_resolver import FieldResolver
from result_logic import (
    accolade_label,
    decide_result,
    ensure_schema,
    playlist_label,
    repair_inverted_results,
)

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

BASE_DIR = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
DB_PATH = BASE_DIR / "data-v2.db"
CONFIG_PATH = BASE_DIR / "config.yaml"
LOG_PATH = BASE_DIR / "listener.log"
STATUS_PATH = BASE_DIR / "listener_status.json"

# CoachEngine needs DB_PATH - instantiate it now that the path is known.
_coach = CoachEngine(str(DB_PATH))

UU_TO_KPH = 0.036

# Fast log buffer - don't block the read loop
_log_queue = []
def log(msg: str):
    timestamp = datetime.now().strftime("%H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line, flush=True)
    _log_queue.append(line + "\n")
def flush_log():
    if _log_queue:
        try:
            with open(LOG_PATH, "a") as f:
                f.writelines(_log_queue)
            _log_queue.clear()
        except Exception:
            _log_queue.clear()


def find_rl_config_dir():
    candidates = [
        Path(os.environ.get("USERPROFILE", "")) / "Documents" / "My Games" / "Rocket League" / "TAGame" / "Config",
        Path.home() / "Documents" / "My Games" / "Rocket League" / "TAGame" / "Config",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def ensure_tastatsapi_ini():
    config_dir = find_rl_config_dir()
    if not config_dir:
        return False
    ini_path = config_dir / "TAStatsAPI.ini"
    needed = "[System]\nPacketSendRate=30\n"
    if ini_path.exists() and "PacketSendRate=30" in ini_path.read_text():
        log("OK: TAStatsAPI.ini already correct")
        return True
    try:
        ini_path.write_text(needed)
        log("OK: TAStatsAPI.ini created/updated")
        return True
    except Exception as e:
        log(f"ERROR: Failed to write TAStatsAPI.ini: {e}")
        return False


def ensure_default_statsapi_ini():
    """v1.3.0: Fix Epic Games bug — DefaultStatsAPI.ini in RL install dir
    sometimes has PacketSendRate=0. This overrides the Documents INI."""
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
            r"Software\Valve\Steam\Apps\252950")
        rl_dir_str, _ = winreg.QueryValueEx(key, "InstalledDepots")
        for line in rl_dir_str.splitlines():
            parts = line.strip().split()
            if parts and parts[0] == "252950":
                rl_path = Path(parts[-1].strip('"'))
                if rl_path.exists():
                    ini = rl_path / "TAGame" / "Config" / "DefaultStatsAPI.ini"
                    if ini.exists():
                        content = ini.read_text()
                        if "PacketSendRate=0" in content:
                            ini.write_text(content.replace("PacketSendRate=0", "PacketSendRate=30"))
                            log("OK: DefaultStatsAPI.ini fixed (PacketSendRate 0→30)")
                        else:
                            log("OK: DefaultStatsAPI.ini already correct")
                    else:
                        log("INFO: DefaultStatsAPI.ini not found in RL install dir")
                    return True
    except Exception:
        pass
    return False


def load_config():
    try:
        import yaml
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
    except Exception:
        pass
    return {}


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create tables if they don't exist — called once at startup."""
    conn = get_db()
    conn.executescript("""
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
            FOREIGN KEY (match_id) REFERENCES matches(id)
        );
        CREATE INDEX IF NOT EXISTS idx_summary_played ON matches_summary(played_at DESC);
    """)
    ensure_schema(conn)
    fixed = repair_inverted_results(conn)
    conn.commit()
    conn.close()
    if fixed:
        log(f"Repaired inverted W/L on match ids: {fixed}")
    log("DB initialized: matches_summary table ready")


def _write_summary(match_id: int):
    """Write a pre-computed summary row for fast warm-storage queries.
    Picks the best metric (goals/demos/shots/saves) as the highlight.
    """
    db = get_db()
    match = db.execute(
        "SELECT m.*, md.arena, md.shots, md.saves, md.demos_given, md.demos_taken "
        "FROM matches m LEFT JOIN match_details md ON m.id = md.match_id "
        "WHERE m.id = ?", (match_id,)
    ).fetchone()
    if not match:
        db.close()
        return

    goals = match["user_score"] or 0
    demos = match["demos_given"] or 0
    shots = match["shots"] or 0
    saves = match["saves"] or 0

    # Pick the best metric as the highlight
    metrics = [
        ("⚽", "Goals", goals),
        ("💥", "Demos", demos),
        ("🎯", "Shots", shots),
        ("🛡️", "Saves", saves),
    ]
    metrics.sort(key=lambda x: x[2], reverse=True)
    hi_icon, hi_text, hi_value = metrics[0]

    playlist = match["playlist"] if "playlist" in match.keys() else "Unknown"
    friend_name = match["friend_name"] if "friend_name" in match.keys() else None
    db.execute(
        """INSERT OR REPLACE INTO matches_summary
           (match_id, session_id, played_at, user_score, opponent_score,
            result, mode, arena, highlight_icon, highlight_text, highlight_value,
            goals, shots, saves, demos_given, demos_taken, playlist, friend_name)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (match_id, match["session_id"], match["played_at"],
         goals, match["opponent_score"],
         match["result"], match["mode"], match["arena"],
         hi_icon, hi_text, hi_value,
         goals, shots, saves, demos, match["demos_taken"] or 0,
         playlist, friend_name)
    )
    db.commit()
    db.close()


def update_status(state: str, msg: str = "", player="", friends=None, poll_interval=None, poll_mode=None):
    try:
        with open(STATUS_PATH, "w") as f:
            json.dump({
                "state": state, "message": msg, "player": player,
                "friends": friends or [],
                "poll_interval": poll_interval,
                "poll_mode": poll_mode,
                "updated": datetime.now(timezone.utc).isoformat()
            }, f)
    except Exception:
        pass


# =============================================================================
# Match state - PRE-ALLOCATED for speed
# =============================================================================

class MatchState:
    __slots__ = ('player_name', 'friend_names', 'match_guid', 'user_team_num',
                 'scores', 'mode', 'arena', 'playlist', 'friend_name', 'goals', 'ball_hits',
                 'touches', 'car_touches', 'shots', 'saves', 'assists',
                 'demos_given', 'demos_taken', 'is_overtime', 'time_remaining',
                 'tick_count', 'active_tick_count', 'boost_sum', 'boost_count',
                 'boosting_ticks', 'supersonic_ticks',
                 'on_ground_ticks', 'in_air_ticks', 'on_wall_ticks',
                 'teammate_name', 'teammate_shots', 'teammate_saves',
                 'teammate_assists', 'teammate_touches', 'teammate_demos',
                 '_match_recorded', '_player_cache', '_friend_cache',
                 '_prev_demos', '_was_demolished',
                 '_last_update_time', '_poll_interval', '_connected',
                 '_team_confirm_count', '_team_confirm_candidate',
                 '_cross_check_fails', '_last_roster_log', '_name_miss_streak',
                 '_spec_only_lock', 'team_names', 'playlist_id', 'in_replay',
                 'crossbar_hits', 'boost_pads', 'boost_pills', 'accolades',
                 'forfeit', '_demos_baselined')

    def __init__(self, player_name, friend_names):
        self.player_name = (player_name or "").lower().strip()
        self.friend_names = friend_names or []
        self._player_cache = {}  # {name_hash: result} for fast lookups
        self._friend_cache = set(f.lower().strip() for f in self.friend_names if f and str(f).strip())
        self._match_recorded = False
        self._last_update_time = 0.0
        self._poll_interval = 60
        self._connected = False
        self._team_confirm_count = 0
        self._team_confirm_candidate = None
        self._cross_check_fails = 0
        self._last_roster_log = 0.0
        self._name_miss_streak = 0
        self._spec_only_lock = False
        self.reset()

    def reset(self):
        self.match_guid = ""
        self.user_team_num = None
        self.scores = [0, 0]
        self.mode = "solo"
        self.arena = None
        self.playlist = "Unknown"
        self.friend_name = None
        self.teammate_name = None
        self.teammate_shots = 0
        self.teammate_saves = 0
        self.teammate_assists = 0
        self.teammate_touches = 0
        self.teammate_demos = 0
        self.goals = []
        self.ball_hits = []
        self.touches = 0; self.car_touches = 0; self.shots = 0; self.saves = 0
        self.assists = 0; self.demos_given = 0; self.demos_taken = 0
        self.is_overtime = False; self.time_remaining = 300; self.tick_count = 0
        self.active_tick_count = 0
        self.boost_sum = 0; self.boost_count = 0
        self.boosting_ticks = 0; self.supersonic_ticks = 0
        self.on_ground_ticks = 0; self.in_air_ticks = 0; self.on_wall_ticks = 0
        self.team_names = {}
        self.playlist_id = None
        self.in_replay = False
        self.crossbar_hits = 0
        self.boost_pads = 0
        self.boost_pills = 0
        self.accolades = []
        self.forfeit = False
        # NOTE: _match_recorded is NOT reset here — it lives until MatchCreated
        self._player_cache.clear()
        self._prev_demos = 0
        self._demos_baselined = False
        self._was_demolished = False
        self._team_confirm_count = 0
        self._team_confirm_candidate = None
        self._cross_check_fails = 0
        self._name_miss_streak = 0
        self._spec_only_lock = False

    @staticmethod
    def _norm_name(name):
        """Normalize RL display names for matching (clan tags, spaces, punct)."""
        if not name:
            return ""
        s = str(name).lower().strip()
        # Strip common clan-tag prefixes: [TAG], (TAG), {TAG}, <TAG>
        s = re.sub(r"^[\(\[\{<][^\)\]\}>]+[\)\]\}>]\s*", "", s)
        # Keep alnum only for fuzzy compare
        return "".join(ch for ch in s if ch.isalnum())

    def set_player_identity(self, player_name, friend_names=None):
        """Hot-reload Settings name/friends without restarting the listener."""
        new_name = (player_name or "").lower().strip()
        friends = friend_names if friend_names is not None else self.friend_names
        new_friends = [f for f in (friends or []) if f and str(f).strip()]
        new_cache = set(f.lower().strip() for f in new_friends)
        changed = (new_name != self.player_name) or (new_cache != self._friend_cache)
        if not changed:
            return False
        old = self.player_name
        self.player_name = new_name
        self.friend_names = new_friends
        self._friend_cache = new_cache
        self._player_cache.clear()
        # Force re-detect team for the new identity (alt account switch)
        self.user_team_num = None
        self._team_confirm_count = 0
        self._team_confirm_candidate = None
        self._cross_check_fails = 0
        self._name_miss_streak = 0
        self._spec_only_lock = False
        log(f"Config identity updated: '{old}' → '{new_name}' (friends={len(new_friends)}); team unlocked for re-detect")
        return True

    def _fast_find(self, players, target):
        """Two-pass player lookup. Pass 1: exact (case-insensitive) match
        across the WHOLE Players list — wins regardless of iteration order.
        Pass 2: normalized / partial-match fallback ONLY if no exact match exists.

        FIX (v1.0.8 team-swap bug): the old single-pass version tried exact
        then partial per-iteration, so a partial-match candidate earlier in
        the array (e.g. target 'mag' vs name 'ImageMag') shadowed an exact
        match later in the array (name 'Mag'), locking user_team_num to the
        WRONG team for the entire match and inverting every score/result.
        """
        if not target:
            return None
        target_l = target.lower().strip()
        target_n = self._norm_name(target_l)
        # Pass 1: exact match (case-insensitive)
        for p in players:
            pname = p.get("Name") or p.get("name") or ""
            if pname and pname.lower() == target_l:
                return p
        # Pass 2: normalized exact (strips clan tags / punctuation)
        if target_n:
            for p in players:
                pname = p.get("Name") or p.get("name") or ""
                if pname and self._norm_name(pname) == target_n:
                    return p
        # Pass 3: partial match fallback (only if NO exact match exists)
        for p in players:
            pname = p.get("Name") or p.get("name") or ""
            if not pname:
                continue
            pname_l = pname.lower()
            pname_n = self._norm_name(pname_l)
            if (target_l in pname_l or pname_l in target_l
                    or (target_n and pname_n and (target_n in pname_n or pname_n in target_n))):
                return p
        return None

    def _roster_summary(self, players):
        parts = []
        for p in players or []:
            nm = p.get("Name") or p.get("name") or "?"
            tn = p.get("TeamNum", "?")
            spec = "S" if "bHasCar" in p else "-"
            parts.append(f"{nm}|T{tn}|{spec}")
        return ", ".join(parts) if parts else "(empty)"

    def _own_team_players(self, players, team_num):
        """Players on team_num that expose SPECTATOR fields (local client's team)."""
        out = []
        for p in players or []:
            if p.get("TeamNum") == team_num and "bHasCar" in p:
                out.append(p)
        return out

    def _lock_team(self, candidate, players, up=None, reason="SPECTATOR"):
        self.user_team_num = candidate
        self._cross_check_fails = 0
        self._name_miss_streak = 0
        team_name = "Blue" if candidate == 0 else "Orange"
        if up is None:
            own = self._own_team_players(players, candidate)
            if len(own) == 1:
                up = own[0]
            elif self.player_name:
                up = self._fast_find(own, self.player_name) if own else None
                if up is None:
                    up = self._fast_find(players, self.player_name)
            if up is None and own:
                # Prefer the car that is actively boosting / has boost meter (local feel)
                up = max(own, key=lambda p: (
                    1 if p.get("bBoosting") else 0,
                    p.get("Boost") or 0,
                    p.get("Touches") or 0,
                ))
        if up is not None:
            rl_name = up.get("Name") or up.get("name") or ""
            if rl_name and self._norm_name(rl_name) and (
                not self.player_name
                or self._norm_name(rl_name) != self._norm_name(self.player_name)
            ):
                # Auto-learn the real RL display name (alt accounts / Settings typo)
                old = self.player_name
                self.player_name = rl_name.lower().strip()
                log(f"Auto-learned RL name: '{old}' → '{self.player_name}'")
            log(f"Team DETECTED via {reason}: {candidate} ({team_name}) after {self._team_confirm_count} ticks")
            log(f"FOUND PLAYER: {up.get('Name')} on Team {candidate} ({team_name}) [scores: {self.scores}]")
            update_status("connected", f"Live - tracking {up.get('Name')}", self.player_name)
            # Duo detection
            if self._friend_cache:
                for fp in players:
                    if fp.get("TeamNum") == self.user_team_num and fp is not up:
                        fpname = (fp.get("Name") or "").lower().strip()
                        if fpname in self._friend_cache or any(f in fpname or fpname in f for f in self._friend_cache):
                            self.mode = "duo"
                            self.friend_name = fp.get("Name")
                            log(f"Duo detected: {fp.get('Name')}")
                            break
        else:
            log(f"Team DETECTED via {reason}: {candidate} ({team_name}) — name pending (roster: {self._roster_summary(players)})")
            update_status("connected", f"Live - team {team_name} locked", self.player_name)

    def _find_user_player(self, players):
        """Team-locked user lookup for stats capture. Only ever returns a
        player on user_team_num, so partial matching can NEVER pick a
        player from the opposing team and cause team_num/stats to disagree.

        Used AFTER detection has locked user_team_num. Detection itself
        still uses _fast_find (both teams) because the team is unknown yet.
        Two-pass: exact name first, partial fallback — both filtered to
        user_team_num. SPECTATOR-only lock: if name missing, fall back to
        sole own-team SPECTATOR player (1v1 / solo queue).
        """
        if self.user_team_num is None:
            return None
        own = [p for p in (players or []) if p.get("TeamNum") == self.user_team_num]
        # Pass 1: exact name, team-locked
        if self.player_name:
            for p in own:
                pname = p.get("Name") or p.get("name") or ""
                if pname and pname.lower() == self.player_name:
                    return p
            # Pass 2: normalized / partial name, team-locked
            target_n = self._norm_name(self.player_name)
            for p in own:
                pname = p.get("Name") or p.get("name") or ""
                if not pname:
                    continue
                pname_l = pname.lower()
                pname_n = self._norm_name(pname_l)
                if (self.player_name in pname_l or pname_l in self.player_name
                        or (target_n and pname_n and (target_n in pname_n or pname_n in target_n))):
                    return p
        # Pass 3: sole SPECTATOR player on own team (works without configured name)
        spec = self._own_team_players(players, self.user_team_num)
        if len(spec) == 1:
            return spec[0]
        return None

    def handle_update_state(self, data):
        players = data.get("Players", [])
        game = data.get("Game", {})
        self.tick_count += 1
        self._last_update_time = time.time()

        # Team detection (v3.0.4):
        # SPECTATOR fields (bHasCar) are PRIMARY — present only on local client's team.
        # Name matching is BEST-EFFORT for picking "you" among teammates and for
        # Settings / alt-account identity. A missing/wrong Settings name must NOT
        # block team lock forever (that prevented session auto-create entirely).
        #
        # 1) 3 consistent SPECTATOR ticks → candidate team
        # 2) If configured name is on THAT team → lock + track that player
        # 3) If name is on the OTHER team → reject candidate (true mismatch)
        # 4) If name not in roster → log roster, then SPECTATOR-only lock
        #    (auto-learn sole own-team name; still lock so W/L + session work)
        if self.user_team_num is None and players:
            for p in players:
                if "bHasCar" in p:
                    candidate = p.get("TeamNum", -1)
                    if candidate in (0, 1):
                        if candidate == self._team_confirm_candidate:
                            self._team_confirm_count += 1
                            if self._team_confirm_count >= 3:
                                up = self._fast_find(players, self.player_name) if self.player_name else None
                                if up and up.get("TeamNum") == candidate:
                                    self._spec_only_lock = False
                                    self._lock_team(candidate, players, up=up, reason="SPECTATOR + name")
                                elif up and up.get("TeamNum") in (0, 1) and up.get("TeamNum") != candidate:
                                    # True conflict: name on other team — do not lock SPECTATOR
                                    log(f"SPECTATOR candidate {candidate} but user '{self.player_name}' on team {up.get('TeamNum')} — will retry")
                                    self._team_confirm_count = 0
                                    self._team_confirm_candidate = None
                                    self._name_miss_streak = 0
                                else:
                                    # Name missing from roster (alt account / typo / empty Settings)
                                    self._name_miss_streak += 1
                                    now = time.time()
                                    if now - self._last_roster_log > 15:
                                        self._last_roster_log = now
                                        log(f"Name '{self.player_name or '(empty)'}' not in roster — {self._roster_summary(players)}")
                                    # Lock via SPECTATOR so sessions still auto-create.
                                    # Immediate lock after confirm; name is optional.
                                    self._spec_only_lock = True
                                    self._lock_team(candidate, players, up=None, reason="SPECTATOR-only (name missing)")
                        else:
                            # Different team — reset counter
                            team_name_new = "Blue" if candidate == 0 else "Orange"
                            team_name_old = "Blue" if self._team_confirm_candidate == 0 else "Orange" if self._team_confirm_candidate is not None else "None"
                            log(f"SPECTATOR team CHANGED: {team_name_old} → {team_name_new}; resetting confirmation count")
                            self._team_confirm_candidate = candidate
                            self._team_confirm_count = 1
                        break  # Found valid team candidate — stop scanning
                    # else: TeamNum invalid (-1/None) — skip this player, check next one

            # Fallback: no bHasCar at all after many ticks — try pure name lock
            if self.user_team_num is None and self.player_name and self.tick_count >= 30:
                up = self._fast_find(players, self.player_name)
                tnum = up.get("TeamNum", -1) if up else -1
                if up and tnum in (0, 1):
                    self._team_confirm_candidate = tnum
                    self._team_confirm_count = 3
                    self._spec_only_lock = False
                    self._lock_team(tnum, players, up=up, reason="name-only fallback")

        # Post-lock: only unlock if SPECTATOR evidence for our team disappears
        # for several ticks AND name also cannot be found. Do NOT unlock solely
        # because Settings name differs from RL display name (alt accounts).
        if self.user_team_num is not None and players:
            up = self._find_user_player(players)
            own_spec = self._own_team_players(players, self.user_team_num)
            if up is None and not own_spec:
                self._cross_check_fails += 1
                if self._cross_check_fails >= 15:
                    log(f"Team {self.user_team_num} lost SPECTATOR evidence for {self._cross_check_fails} ticks — unlocking")
                    self.user_team_num = None
                    self._team_confirm_count = 0
                    self._team_confirm_candidate = None
                    self._cross_check_fails = 0
                    self._spec_only_lock = False
            else:
                self._cross_check_fails = 0
                # If we locked SPECTATOR-only and later learn the real name, upgrade status
                if up is not None and self._spec_only_lock:
                    rl_name = (up.get("Name") or up.get("name") or "").lower().strip()
                    if rl_name and rl_name != self.player_name:
                        old = self.player_name
                        self.player_name = rl_name
                        log(f"Auto-learned RL name (post-lock): '{old}' → '{self.player_name}'")
                    self._spec_only_lock = False
                    update_status("connected", f"Live - tracking {up.get('Name')}", self.player_name)

        # v2.0.15: DO NOT use game.Teams[].Score — cumulative / OT-only.
        # v3.1: keep team NAMES so Winner can be matched when colors aren't Blue/Orange.
        for t in (game.get("Teams") or []):
            tn = t.get("TeamNum")
            nm = t.get("Name")
            if tn in (0, 1) and nm:
                self.team_names[int(tn)] = nm
        if "bReplay" in game:
            self.in_replay = bool(game.get("bReplay"))

        # Simple fields
        arena = game.get("Arena", "")
        if arena and not self.arena:
            self.arena = arena
        # PlaylistId is the real mode (ranked vs casual vs extra). Name fields are fallback.
        pid = game.get("PlaylistId")
        if pid not in (None, "", 0) or (pid == 0 and not self.playlist_id):
            if pid not in (None, ""):
                self.playlist_id = pid
                self.playlist = playlist_label(pid, len(players) if players else 0, self.playlist)
        if not self.playlist or self.playlist == "Unknown":
            pl_found = False
            for key in ("Playlist", "PlaylistName", "MatchType", "GameMode", "Mode"):
                val = game.get(key)
                if val not in (None, "", 0):
                    self.playlist = str(val)
                    pl_found = True
                    break
            if not pl_found:
                npl = len(players) if players else 0
                if npl:
                    if npl <= 2:
                        self.playlist = "1v1"
                    elif npl <= 4:
                        self.playlist = "2v2"
                    elif npl <= 6:
                        self.playlist = "3v3"
                    else:
                        self.playlist = f"{npl}p"
        if game.get("bOvertime"):
            self.is_overtime = True
        if "TimeSeconds" in game:
            self.time_remaining = game["TimeSeconds"]

        # Player stats — team-locked lookup.
        # FIX (v1.0.8): _find_user_player only ever returns a player ON
        # user_team_num, so partial matching can NEVER pick a player from
        # the opposing team and cause stats/team_num disagreement.
        if self.user_team_num is not None and players:
            p = self._find_user_player(players)
            if p:
                self.active_tick_count += 1
                self.touches = p.get("Touches", 0) or 0
                self.car_touches = p.get("CarTouches", 0) or 0
                self.shots = p.get("Shots", 0) or 0
                self.saves = p.get("Saves", 0) or 0
                self.assists = p.get("Assists", 0) or 0
                boost = p.get("Boost", 0) or 0
                self.boost_sum += boost
                self.boost_count += 1
                if boost > 0 and p.get("bBoosting"):
                    self.boosting_ticks += 1
                if p.get("bSupersonic"):
                    self.supersonic_ticks += 1
                # Wall before ground: RL often sets BOTH True on walls.
                if p.get("bOnWall"):
                    self.on_wall_ticks += 1
                elif p.get("bOnGround"):
                    self.on_ground_ticks += 1
                else:
                    self.in_air_ticks += 1

                # Demolish tracking — baseline the first tick so a session-cumulative
                # Demos counter is not dumped into this match as 20+ fake demos.
                demos_now = p.get("Demos", 0) or 0
                if not self._demos_baselined:
                    self._prev_demos = demos_now
                    self._demos_baselined = True
                elif demos_now > self._prev_demos:
                    self.demos_given += demos_now - self._prev_demos
                self._prev_demos = demos_now

                if p.get("bDemolished"):
                    if not self._was_demolished:
                        self.demos_taken += 1
                    self._was_demolished = True
                else:
                    self._was_demolished = False

                # Duo re-check every tick (friend may join / appear after lock)
                if self.mode == "solo" and self._friend_cache and players:
                    pname = (self.player_name or "").lower().strip()
                    for fp in players:
                        if fp.get("TeamNum") != self.user_team_num:
                            continue
                        fpname = (fp.get("Name") or "").lower().strip()
                        if not fpname:
                            continue
                        if pname and (pname == fpname or pname in fpname or fpname in pname):
                            continue
                        if fpname in self._friend_cache or any(f in fpname or fpname in f for f in self._friend_cache):
                            self.mode = "duo"
                            self.friend_name = fp.get("Name")
                            log(f"Duo detected (late join): {fp.get('Name')}")
                            break

                # Teammate snapshot (best-effort)
                if players and self.user_team_num is not None:
                    pname = (self.player_name or "").lower().strip()
                    best = None
                    for fp in players:
                        if fp.get("TeamNum") != self.user_team_num:
                            continue
                        fpname = (fp.get("Name") or "").lower().strip()
                        if not fpname:
                            continue
                        if pname and (pname == fpname or pname in fpname or fpname in pname):
                            continue
                        best = fp
                        break
                    if best:
                        self.teammate_name = best.get("Name") or self.teammate_name
                        self.teammate_shots = best.get("Shots", 0) or 0
                        self.teammate_saves = best.get("Saves", 0) or 0
                        self.teammate_assists = best.get("Assists", 0) or 0
                        self.teammate_touches = best.get("Touches", 0) or 0
                        self.teammate_demos = best.get("Demos", 0) or 0
                        if self.mode == "duo" and not self.friend_name:
                            self.friend_name = self.teammate_name

        # Match end. Score is authority at full time; WinnerTeamNum only overrides
        # an early end (forfeit). Never map an unknown Winner string to Orange.
        if self.user_team_num is not None and game.get("bHasWinner") and not self._match_recorded:
            self._match_recorded = True
            winner = game.get("Winner")
            result = decide_result(
                self.user_team_num, winner, self.scores,
                self.team_names, self.time_remaining,
            )
            self._finish_end(result, winner, "bHasWinner")
            return True
        return False

    def _finish_end(self, result, winner, source):
        remaining = self.time_remaining if self.time_remaining is not None else 0
        if remaining > 20 and result in ("win", "loss"):
            self.forfeit = True
            if "Forfeit" not in self.accolades:
                self.accolades.append("Forfeit")
        log(
            f"Match ended ({source}): {result.upper()}! "
            f"user {self.user_score}-{self.opponent_score} raw {self.scores} "
            f"winner={winner!r} team={self.user_team_num} clock={remaining}"
        )
        self.record_match(result)
        self.reset()

    def record_match(self, result):
        if self.user_team_num is None:
            return
        db = get_db()
        now = datetime.now(timezone.utc).isoformat()
        session = db.execute("SELECT id FROM sessions WHERE status='active' ORDER BY started_at DESC LIMIT 1").fetchone()
        if session:
            session_id = session["id"]
            # Dedup: skip if same scores already recorded in last 60s.
            # played_at is ISO-8601 (…T…); SQLite datetime('now') uses a space
            # separator, so lexicographic compare fails. Use Python ISO cutoff.
            cutoff = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
            existing = db.execute(
                "SELECT id FROM matches WHERE session_id=? AND user_score=? AND opponent_score=? AND played_at > ?",
                (session_id, self.user_score, self.opponent_score, cutoff)
            ).fetchone()
            if existing:
                log(f"SKIP DUP: match already recorded (id={existing['id']})")
                db.close()
                return
        else:
            cur = db.execute("INSERT INTO sessions (started_at, mode) VALUES (?, ?)", (now, self.mode))
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
        tags = ", ".join(self.accolades) if self.accolades else None
        cur = db.execute(
            "INSERT INTO matches (session_id, played_at, user_score, opponent_score, result, mode, playlist, friend_name, tags) VALUES (?,?,?,?,?,?,?,?,?)",
            (session_id, now, self.user_score, self.opponent_score, result, self.mode, self.playlist or "Unknown", self.friend_name, tags))
        match_id = cur.lastrowid
        if not match_id:
            db.close()
            return

        ticks = max(self.active_tick_count, 1)  # Use active ticks only (after player found)

        # Compute shot power stats from goals
        fast_goal_kphs = [g.get("speed_kph") for g in self.goals if g.get("speed_kph")]
        fastest_goal = max(fast_goal_kphs) if fast_goal_kphs else 0.0
        avg_power = round(sum(fast_goal_kphs) / len(fast_goal_kphs), 1) if fast_goal_kphs else 0.0

        db.execute(
            """INSERT INTO match_details
               (match_id, arena, overtime, touches, car_touches, shots, saves, assists,
                demos_given, demos_taken, boost_avg, boost_time_pct, supersonic_time_pct,
                ground_time_pct, air_time_pct, wall_time_pct, fastest_goal_kph, avg_shot_power, time_remaining_sec,
                playlist, teammate_name, teammate_shots, teammate_saves, teammate_assists, teammate_touches, teammate_demos,
                crossbar_hits, boost_pads, boost_pills, forfeit, accolades)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (match_id, self.arena, int(self.is_overtime), self.touches, self.car_touches,
             self.shots, self.saves, self.assists, self.demos_given, self.demos_taken,
             round(self.boost_sum / max(self.boost_count, 1), 1),
             round(self.boosting_ticks / ticks * 100, 1),
             round(self.supersonic_ticks / ticks * 100, 1),
             round(self.on_ground_ticks / ticks * 100, 1),
             round(self.in_air_ticks / ticks * 100, 1),
             round(self.on_wall_ticks / ticks * 100, 1),
             fastest_goal, avg_power, self.time_remaining,
             self.playlist or "Unknown", self.teammate_name,
             self.teammate_shots, self.teammate_saves, self.teammate_assists,
             self.teammate_touches, self.teammate_demos,
             self.crossbar_hits, self.boost_pads, self.boost_pills, int(self.forfeit), tags))

        for g in self.goals:
            db.execute("INSERT INTO goals (match_id, scored_at, scorer, assister, team_num, speed_kph, time_remaining_sec) VALUES (?,?,?,?,?,?,?)",
                       (match_id, g.get("scored_at", now), g["scorer"], g.get("assister"),
                        g.get("team_num", self.user_team_num), g.get("speed_kph"), g.get("time_remaining")))
        for bh in self.ball_hits:
            db.execute("INSERT INTO ball_hits (match_id, hit_at, player, player_team, pre_hit_speed, post_hit_speed, post_hit_kph) VALUES (?,?,?,?,?,?,?)",
                       (match_id, bh.get("hit_at", now), bh["player"], bh.get("team", 0),
                        bh.get("pre_hit"), bh.get("post_hit"), bh.get("post_hit_kph")))
        db.commit()
        db.close()
        _write_summary(match_id)
        flush_log()
        label = "WIN" if result == "win" else ("DRAW" if result == "draw" else "LOSS")
        log(f"RECORDED: {label}! {self.user_score}-{self.opponent_score} [{self.mode}/{self.playlist}]")
        # Active Coach (TRIZ #25): self-analyse immediately after recording.
        # Runs after DB close so a coach error can never corrupt the match row.
        # Insights are informational only - failures are logged and swallowed.
        try:
            res = _coach.analyze_match(match_id)
            n = len(res.get("insights", []))
            if n:
                log(f"COACH: {n} insights for match {match_id}")
        except Exception as e:
            log(f"COACH WARN: analyze_match failed for {match_id}: {e}")

    @property
    def user_score(self): return self.scores[self.user_team_num] if self.user_team_num is not None else 0
    @property
    def opponent_score(self):
        opp = 1 - self.user_team_num if self.user_team_num is not None else 1
        return self.scores[opp]


# =============================================================================
# FAST listener loop - non-blocking with select
# =============================================================================

def run_listener(player: str, friends: list, stop_event):
    host = "127.0.0.1"
    port = 49123
    update_status("starting", "Initializing...", player, friends)

    log("=" * 50)
    log("RL Raw TCP Listener (Windows Portable v7 SPECTATOR)")
    log(f"   Player: {player or '(not set)'} | Friends: {', '.join(friends) if friends else 'none'}")
    log("=" * 50)

    if not player:
        update_status("no_player", "Player name not configured - enter it in Settings")
        log("No player name configured. Waiting for config...")
        while not stop_event.is_set():
            time.sleep(2)
            cfg = load_config()
            p = cfg.get("player", {})
            if p.get("name"):
                player = p["name"]
                friends = p.get("friends", [])
                log(f"Player config loaded: {player}")
                update_status("connecting", f"Starting for {player}...", player, friends)
                break
        else:
            return

    state = MatchState(player, friends)
    init_db()
    update_status("connecting", "Connecting to Rocket League...", player, friends)

    reconnect_delay = 3
    max_delay = 30
    decoder = json.JSONDecoder()

    while not stop_event.is_set():
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)  # Only for connect()
        try:
            sock.connect((host, port))
            # CRITICAL: Large receive buffer to prevent TCP backpressure on RL
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2 * 1024 * 1024)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 128 * 1024)
            sock.settimeout(0)  # NON-BLOCKING for recv()
            
            log("Connected to Rocket League Stats API!")
            update_status("connected", "Live - tracking matches", player, friends)
            reconnect_delay = 3
            state._connected = True

            buffer = ""
            pos = 0
            last_heartbeat = time.time()
            last_flush = time.time()
            last_config_check = 0.0
            event_count = 0
            stall_count = 0
            first_data = True

            while not stop_event.is_set():
                # Use select with 10ms timeout for fast polling (was 1000ms!)
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

                    buffer += chunk.decode('utf-8', errors='replace')

                    # Fast parsing loop
                    while True:
                        while pos < len(buffer) and buffer[pos] in ' \t\r\n':
                            pos += 1
                        if pos >= len(buffer):
                            break

                        try:
                            obj, end = decoder.raw_decode(buffer[pos:])
                        except json.JSONDecodeError:
                            break  # Incomplete object, wait for more data

                        event = obj.get("Event", "")
                        event_count += 1
                        raw_data = obj.get("Data")

                        # Fast event dispatch - skip data we don't need
                        if event == "UpdateState":
                            if isinstance(raw_data, str):
                                data = json.loads(raw_data)
                            else:
                                data = raw_data or {}
                            state.handle_update_state(data)

                        elif event == "MatchCreated":
                            if state.user_team_num is not None and not state._match_recorded:
                                if state.user_score == 0 and state.opponent_score == 0 and not state.goals:
                                    log("MatchCreated: skip empty previous match")
                                    state.reset()
                                else:
                                    state._match_recorded = True
                                    res = decide_result(state.user_team_num, None, state.scores, state.team_names, state.time_remaining)
                                    log(f"MatchCreated -> auto-recording previous ({res})")
                                    state.record_match(res)
                                    state.reset()
                            state.match_guid = (raw_data or {}).get("MatchGuid", "") if isinstance(raw_data, dict) else ""
                            state._match_recorded = False  # Allow new match to be recorded

                        elif event in ("MatchEnded", "MatchDestroyed"):
                            if state.user_team_num is not None and not state._match_recorded:
                                state._match_recorded = True
                                d = raw_data if isinstance(raw_data, dict) else (json.loads(raw_data) if isinstance(raw_data, str) else {})
                                winner = d.get("WinnerTeamNum")
                                if winner is None:
                                    winner = d.get("Winner")
                                result = decide_result(
                                    state.user_team_num, winner, state.scores,
                                    state.team_names, state.time_remaining,
                                )
                                state._finish_end(result, winner, event)

                        elif event == "GoalScored":
                            if state.in_replay:
                                pos += end
                                continue
                            d = raw_data if isinstance(raw_data, dict) else (json.loads(raw_data) if isinstance(raw_data, str) else {})
                            scorer = FieldResolver.resolve_raw(d, "scorer") or {}
                            # Scorer var būt dict (ar Name/TeamNum) vai vienkārši string
                            if isinstance(scorer, dict):
                                sname = scorer.get("Name") or scorer.get("name") or ""
                                steam = scorer.get("TeamNum", -1)
                            else:
                                sname = str(scorer or "")
                                steam = -1
                                # Mēģinām uzminēt komandu no top-level
                                steam = FieldResolver.resolve(d, "team_num")
                                if steam is None:
                                    steam = -1
                            if not sname:
                                pos += end; continue
                            if steam in (0, 1):
                                state.scores[steam] = state.scores[steam] + 1
                            else:
                                # v2.0.14: log unknown team for overtime/different format goals
                                log(FieldResolver.raw_dump(d, f"GOAL UNKNOWN TEAM: scorer='{sname}' team={steam}"))
                            gs = FieldResolver.resolve(d, "goal_speed")
                            speed_kph = round(gs, 1) if gs else None  # GoalSpeed already in km/h
                            assister = FieldResolver.resolve_raw(d, "assister")
                            aname = (assister.get("Name") or assister.get("name")) if isinstance(assister, dict) else (assister or None)
                            state.goals.append({
                                "scored_at": datetime.now(timezone.utc).isoformat(),
                                "scorer": sname, "assister": aname,
                                "team_num": steam, "speed_kph": speed_kph,
                                "time_remaining": state.time_remaining})

                        elif event == "BallHit":
                            d = raw_data if isinstance(raw_data, dict) else (json.loads(raw_data) if isinstance(raw_data, str) else {})
                            players = d.get("Players", [])
                            if players:
                                ph = players[0]  # Only first player is the hitter
                                ball = d.get("Ball", {})
                                state.ball_hits.append({
                                    "hit_at": datetime.now(timezone.utc).isoformat(),
                                    "player": ph.get("Name", "?"), "team": ph.get("TeamNum", -1),
                                    "pre_hit": ball.get("PreHitSpeed", 0) or 0,
                                    "post_hit": ball.get("PostHitSpeed", 0) or 0,
                                    "post_hit_kph": round((ball.get("PostHitSpeed", 0) or 0) * UU_TO_KPH, 1)})

                        elif event == "Demolish":
                            d = raw_data if isinstance(raw_data, dict) else {}
                            # Semantiskais field resolver — atrast attacker/victim pēc jebkura zināma nosaukuma
                            an = FieldResolver.resolve(d, "attacker")
                            vn = FieldResolver.resolve(d, "victim")
                            # Ja netika atrasts, mēģinām uzminēt pēc tipa (pirmā divi str lauki)
                            if not an:
                                key, val = FieldResolver.guess_by_type(d, str)
                                if key and val:
                                    an = val
                                    log(FieldResolver.raw_dump(d, "DEMO attacker guessed"))
                            if not vn:
                                keys_to_skip = {"Event"}
                                if an:
                                    keys_to_skip.add(str(an))
                                # Otrais str lauks, izlaižot jau atrasto attacker
                                for k, v in d.items():
                                    if k in keys_to_skip or k.startswith("_") or k.startswith("MatchGuid"):
                                        continue
                                    if isinstance(v, str) and v:
                                        vn = v
                                        break
                                    if isinstance(v, dict) and (v.get("Name") or v.get("name")):
                                        vn = v.get("Name") or v.get("name")
                                        break
                            an_l = (an or "").lower()
                            vn_l = (vn or "").lower()
                            if an_l and (state.player_name in an_l or an_l in state.player_name):
                                state.demos_given += 1
                                log(f"DEMO GIVEN: {an}")
                            elif vn_l and (state.player_name in vn_l or vn_l in state.player_name):
                                state.demos_taken += 1
                                log(f"DEMO TAKEN: {vn}")
                            else:
                                # RAW dump kad nekas nestrādā
                                log(FieldResolver.raw_dump(d, "DEMO UNKNOWN FORMAT"))

                        elif event == "OverTimeBegin":
                            state.is_overtime = True

                        elif event == "ClockUpdatedSeconds":
                            if isinstance(raw_data, dict):
                                state.time_remaining = raw_data.get("TimeSeconds", state.time_remaining)
                                if raw_data.get("bOvertime"):
                                    state.is_overtime = True

                        elif event in ("GoalReplayStart",):
                            state.in_replay = True
                        elif event in ("GoalReplayEnd", "RoundStarted"):
                            state.in_replay = False

                        elif event == "StatfeedEvent":
                            d = raw_data if isinstance(raw_data, dict) else {}
                            label = accolade_label(d.get("EventName"))
                            target = d.get("MainTarget") or {}
                            if label and state.user_team_num is not None and target.get("TeamNum") == state.user_team_num:
                                if label not in state.accolades:
                                    state.accolades.append(label)
                                    log(f"ACCOLADE: {label} ({target.get('Name')})")

                        elif event == "CrossbarHit":
                            d = raw_data if isinstance(raw_data, dict) else {}
                            touch = (d.get("BallLastTouch") or {}).get("Player") or {}
                            if state.user_team_num is None or touch.get("TeamNum") == state.user_team_num:
                                state.crossbar_hits += 1

                        elif event == "BoostPickup":
                            d = raw_data if isinstance(raw_data, dict) else {}
                            who = d.get("Player") or {}
                            if state.user_team_num is not None and who.get("TeamNum") == state.user_team_num and not d.get("bReplay"):
                                kind = str(d.get("BoostType") or "")
                                if "Pill" in kind:
                                    state.boost_pills += 1
                                else:
                                    state.boost_pads += 1

                        pos += end

                    # Move unparsed remainder to front
                    if pos > 0:
                        buffer = buffer[pos:]
                        pos = 0
                    elif len(buffer) > 0:
                        # Stalled: pos==0 but buffer not empty (incomplete JSON)
                        stall_count += 1
                        # Safety: if we stall too long, flush the buffer
                        if stall_count > 1000:
                            log(f"Buffer stalled ({len(buffer)}B), flushing")
                            buffer = ""
                            stall_count = 0
                    else:
                        stall_count = 0

                else:
                    # No data available this tick
                    stall_count = 0

                now = time.time()

                # Heartbeat every 30s
                if now - last_heartbeat > 30:
                    log(f"Heartbeat: {event_count} events, tick={state.tick_count}, team={state.user_team_num}, buf={len(buffer)}B, stall={stall_count}")
                    last_heartbeat = now

                # Hot-reload Settings name/friends (alt account switch without restart)
                if now - last_config_check > 2:
                    last_config_check = now
                    try:
                        cfg = load_config() or {}
                        pcfg = cfg.get("player") or {}
                        new_name = pcfg.get("name") or ""
                        new_friends = pcfg.get("friends") or []
                        if state.set_player_identity(new_name, new_friends):
                            player = new_name
                            friends = new_friends
                            update_status(
                                "connected" if state._connected else "connecting",
                                f"Identity → {new_name or '(empty)'}",
                                player,
                                friends,
                            )
                    except Exception as e:
                        log(f"Config reload warn: {e}")

                # Flush log to disk every 5s (not on every event!)
                if now - last_flush > 5:
                    flush_log()
                    last_flush = now

            # Connection ended
            state._connected = False
            state._poll_interval = 60
            sock.close()
            if state.user_team_num is not None and state.tick_count > 0 and (state.user_score or state.opponent_score or state.goals):
                res = decide_result(state.user_team_num, None, state.scores, state.team_names, state.time_remaining)
                log(f"Saving in-progress match: {res}")
                state.record_match(res)
                state.reset()

        except (ConnectionRefusedError, socket.timeout):
            update_status("disconnected", "RL not running", player, friends)
            log(f"RL not available - retrying in {reconnect_delay}s...")
        except Exception as e:
            log(f"Error: {e}")

        try: sock.close()
        except Exception: pass
        if stop_event.is_set(): break

        # Elpojošs polling — adaptīvs intervāls atkarībā no datu plūsmas
        now = time.time()
        # Also pick up Settings changes while waiting for RL / reconnecting
        try:
            cfg = load_config() or {}
            pcfg = cfg.get("player") or {}
            new_name = pcfg.get("name") or ""
            new_friends = pcfg.get("friends") or []
            if state.set_player_identity(new_name, new_friends):
                player = new_name
                friends = new_friends
        except Exception:
            pass
        if state._connected and state._last_update_time > 0:
            gap = now - state._last_update_time
            state._poll_interval = 2 if gap < 5 else 15 if gap < 30 else 60
        else:
            state._poll_interval = 60
        poll_mode = "hot" if state._poll_interval == 2 else "warm" if state._poll_interval == 15 else "cold"
        update_status("disconnected" if not state._connected else "connected",
                      "Reconnecting..." if not state._connected else f"Polling ({poll_mode})",
                      player, friends,
                      poll_interval=state._poll_interval, poll_mode=poll_mode)
        time.sleep(min(state._poll_interval, 2))

    flush_log()
    log("Listener stopped")
    update_status("stopped", "Listener stopped", player, friends)
