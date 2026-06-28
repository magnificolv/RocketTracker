"""
Rocket League Stats API Raw TCP Listener - Windows Edition (FAST)
Direct TCP connection to RL Stats API (port 49123).
Optimized for low-latency to prevent TCP backpressure on RL.
"""
import json
import os
import select
import sqlite3
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Active Coach (TRIZ #25): analyse each match right after recording it.
# Instance is created after DB_PATH is defined (see below).
from coach import CoachEngine

from field_resolver import FieldResolver

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
    conn.commit()
    conn.close()
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

    db.execute(
        """INSERT OR REPLACE INTO matches_summary
           (match_id, session_id, played_at, user_score, opponent_score,
            result, mode, arena, highlight_icon, highlight_text, highlight_value,
            goals, shots, saves, demos_given, demos_taken)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (match_id, match["session_id"], match["played_at"],
         goals, match["opponent_score"],
         match["result"], match["mode"], match["arena"],
         hi_icon, hi_text, hi_value,
         goals, shots, saves, demos, match["demos_taken"] or 0)
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
                 'scores', 'mode', 'arena', 'goals', 'ball_hits',
                 'touches', 'car_touches', 'shots', 'saves', 'assists',
                 'demos_given', 'demos_taken', 'is_overtime', 'time_remaining',
                 'tick_count', 'active_tick_count', 'boost_sum', 'boost_count',
                 'boosting_ticks', 'supersonic_ticks',
                 'on_ground_ticks', 'in_air_ticks', 'on_wall_ticks',
                 '_match_recorded', '_player_cache', '_friend_cache',
                 '_prev_demos', '_was_demolished',
                 '_last_update_time', '_poll_interval', '_connected',
                 '_team_confirm_count', '_team_confirm_candidate')

    def __init__(self, player_name, friend_names):
        self.player_name = player_name.lower().strip()
        self.friend_names = friend_names
        self._player_cache = {}  # {name_hash: result} for fast lookups
        self._friend_cache = set(f.lower().strip() for f in friend_names if f.strip())
        self._match_recorded = False
        self._last_update_time = 0.0
        self._poll_interval = 60
        self._connected = False
        self._team_confirm_count = 0
        self._team_confirm_candidate = None
        self.reset()

    def reset(self):
        self.match_guid = ""
        self.user_team_num = None
        self.scores = [0, 0]
        self.mode = "solo"
        self.arena = None
        self.goals = []
        self.ball_hits = []
        self.touches = 0; self.car_touches = 0; self.shots = 0; self.saves = 0
        self.assists = 0; self.demos_given = 0; self.demos_taken = 0
        self.is_overtime = False; self.time_remaining = 300; self.tick_count = 0
        self.active_tick_count = 0
        self.boost_sum = 0; self.boost_count = 0
        self.boosting_ticks = 0; self.supersonic_ticks = 0
        self.on_ground_ticks = 0; self.in_air_ticks = 0; self.on_wall_ticks = 0
        # NOTE: _match_recorded is NOT reset here — it lives until MatchCreated
        self._player_cache.clear()
        self._prev_demos = 0
        self._was_demolished = False
        self._team_confirm_count = 0
        self._team_confirm_candidate = None

    def _fast_find(self, players, target):
        """Two-pass player lookup. Pass 1: exact (case-insensitive) match
        across the WHOLE Players list — wins regardless of iteration order.
        Pass 2: partial-match fallback ONLY if no exact match exists.

        FIX (v1.0.8 team-swap bug): the old single-pass version tried exact
        then partial per-iteration, so a partial-match candidate earlier in
        the array (e.g. target 'mag' vs name 'ImageMag') shadowed an exact
        match later in the array (name 'Mag'), locking user_team_num to the
        WRONG team for the entire match and inverting every score/result.
        """
        # Pass 1: exact match (case-insensitive)
        for p in players:
            pname = p.get("Name", "")
            if pname and pname.lower() == target:
                return p
        # Pass 2: partial match fallback (only if NO exact match exists)
        for p in players:
            pname = p.get("Name", "")
            if not pname:
                continue
            pname_l = pname.lower()
            if target in pname_l or pname_l in target:
                return p
        return None

    def _find_user_player(self, players):
        """Team-locked user lookup for stats capture. Only ever returns a
        player on user_team_num, so partial matching can NEVER pick a
        player from the opposing team and cause team_num/stats to disagree.

        Used AFTER detection has locked user_team_num. Detection itself
        still uses _fast_find (both teams) because the team is unknown yet.
        Two-pass: exact name first, partial fallback — both filtered to
        user_team_num.
        """
        if self.user_team_num is None:
            return None
        # Pass 1: exact name, team-locked
        for p in players:
            pname = p.get("Name", "")
            if (pname and pname.lower() == self.player_name
                    and p.get("TeamNum") == self.user_team_num):
                return p
        # Pass 2: partial name, team-locked
        for p in players:
            pname = p.get("Name", "").lower()
            if not pname:
                continue
            if p.get("TeamNum") == self.user_team_num:
                if self.player_name in pname or pname in self.player_name:
                    return p
        return None

    def handle_update_state(self, data):
        players = data.get("Players", [])
        game = data.get("Game", {})
        self.tick_count += 1
        self._last_update_time = time.time()

        # Team detection via SPECTATOR fields (v1.3.2 fix).
        # RL API docs state SPECTATOR fields are "present only if the client
        # is spectating or on the player's team." SPECTATOR fields include:
        # bHasCar, Speed, Boost, bBoosting, bOnGround, bOnWall, bPowersliding,
        # bDemolished, bSupersonic.
        #
        # We use bHasCar as the team indicator: if ANY player on a team has
        # bHasCar, that team IS the user's team. This is 100% reliable —
        # no name-matching, no guessing TeamNum from the wrong player.
        # Confirmation count (3 ticks) prevents false locks during loading.
        if self.user_team_num is None and players:
            for p in players:
                if "bHasCar" in p:
                    candidate = p.get("TeamNum", -1)
                    if candidate in (0, 1):
                        if candidate == self._team_confirm_candidate:
                            self._team_confirm_count += 1
                            if self._team_confirm_count >= 3:
                                self.user_team_num = candidate
                                team_name = "Blue" if candidate == 0 else "Orange"
                                log(f"Team DETECTED via SPECTATOR (bHasCar): {candidate} ({team_name}) after {self._team_confirm_count} ticks")
                                # Now find the user's actual player on this team
                                up = self._find_user_player(players)
                                if up:
                                    log(f"FOUND PLAYER: {up.get('Name')} on Team {candidate} ({team_name}) [scores: {self.scores}]")
                                    update_status("connected", f"Live - tracking {up.get('Name')}", self.player_name)
                                else:
                                    log(f"WARNING: team {candidate} confirmed but user player '{self.player_name}' not found on that team")
                                # Duo detection at lock time (also re-checked every tick below)
                                if self._friend_cache:
                                    for fp in players:
                                        if fp.get("TeamNum") == self.user_team_num and fp is not up:
                                            fpname = fp.get("Name", "").lower().strip()
                                            if fpname in self._friend_cache or any(f in fpname or fpname in f for f in self._friend_cache):
                                                self.mode = "duo"
                                                log(f"Duo detected: {fp.get('Name')}")
                                                break
                        else:
                            # Different team — reset counter
                            team_name_new = "Blue" if candidate == 0 else "Orange"
                            team_name_old = "Blue" if self._team_confirm_candidate == 0 else "Orange" if self._team_confirm_candidate is not None else "None"
                            log(f"SPECTATOR team CHANGED: {team_name_old} → {team_name_new}; resetting confirmation count")
                            self._team_confirm_candidate = candidate
                            self._team_confirm_count = 1
                    break  # Found a player with bHasCar — team determined, stop scanning

        # Scores (fast)
        teams = game.get("Teams", ())
        for t in teams:
            tnum = t.get("TeamNum", -1)
            if tnum in (0, 1):
                self.scores[tnum] = t.get("Score", 0)

        # Simple fields
        arena = game.get("Arena", "")
        if arena and not self.arena:
            self.arena = arena
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
                if p.get("bOnGround"):
                    self.on_ground_ticks += 1
                elif p.get("bOnWall"):
                    self.on_wall_ticks += 1
                else:
                    self.in_air_ticks += 1

                # Demolish tracking — diff-based from UpdateState (RL doesn't send Demolish events!)
                demos_now = p.get("Demos", 0) or 0
                if demos_now > self._prev_demos:
                    self.demos_given += demos_now - self._prev_demos
                self._prev_demos = demos_now

                if p.get("bDemolished"):
                    if not self._was_demolished:
                        self.demos_taken += 1
                    self._was_demolished = True
                else:
                    self._was_demolished = False

        # Match end detection (only check if player found)
        if self.user_team_num is not None and game.get("bHasWinner") and not self._match_recorded:
            self._match_recorded = True
            winner = game.get("Winner")
            result = "loss"  # default
            if winner is not None:
                if isinstance(winner, str):
                    winner_num = 0 if winner.lower() == "blue" else 1
                else:
                    try:
                        winner_num = int(winner)
                    except (ValueError, TypeError):
                        winner_num = -1
                if winner_num in (0, 1):
                    result = "win" if winner_num == self.user_team_num else "loss"
                else:
                    result = "win" if self.user_score > self.opponent_score else "loss"
            else:
                result = "win" if self.user_score > self.opponent_score else "loss"
            # FIXED: record_match and reset moved OUTSIDE the else block
            log(f"Match ended (bHasWinner): {result.upper()}! {self.scores[0]}-{self.scores[1]}")
            self.record_match(result)
            self.reset()
            return True
        return False

    def record_match(self, result):
        if self.user_team_num is None:
            return
        db = get_db()
        now = datetime.now(timezone.utc).isoformat()
        session = db.execute("SELECT id FROM sessions WHERE status='active' ORDER BY started_at DESC LIMIT 1").fetchone()
        if session:
            session_id = session["id"]
            # Dedup: skip if same scores already recorded in last 60s
            existing = db.execute(
                "SELECT id FROM matches WHERE session_id=? AND user_score=? AND opponent_score=? AND played_at > datetime('now', '-60 seconds')",
                (session_id, self.user_score, self.opponent_score)
            ).fetchone()
            if existing:
                log(f"SKIP DUP: match already recorded (id={existing['id']})")
                db.close()
                return
        else:
            cur = db.execute("INSERT INTO sessions (started_at, mode) VALUES (?, ?)", (now, self.mode))
            session_id = cur.lastrowid

        cur = db.execute(
            "INSERT INTO matches (session_id, played_at, user_score, opponent_score, result, mode) VALUES (?,?,?,?,?,?)",
            (session_id, now, self.user_score, self.opponent_score, result, self.mode))
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
                ground_time_pct, air_time_pct, wall_time_pct, fastest_goal_kph, avg_shot_power, time_remaining_sec)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (match_id, self.arena, int(self.is_overtime), self.touches, self.car_touches,
             self.shots, self.saves, self.assists, self.demos_given, self.demos_taken,
             round(self.boost_sum / max(self.boost_count, 1), 1),
             round(self.boosting_ticks / ticks * 100, 1),
             round(self.supersonic_ticks / ticks * 100, 1),
             round(self.on_ground_ticks / ticks * 100, 1),
             round(self.in_air_ticks / ticks * 100, 1),
             round(self.on_wall_ticks / ticks * 100, 1),
             fastest_goal, avg_power, self.time_remaining))

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
        log(f"RECORDED: {'WIN' if result == 'win' else 'LOSS'}! {self.user_score}-{self.opponent_score} [{self.mode}]")
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
                                state._match_recorded = True
                                res = "win" if state.user_score > state.opponent_score else "loss"
                                log(f"MatchCreated -> auto-recording previous ({res})")
                                state.record_match(res)
                                state.reset()
                            state.match_guid = (raw_data or {}).get("MatchGuid", "") if isinstance(raw_data, dict) else ""
                            state._match_recorded = False  # Allow new match to be recorded

                        elif event in ("MatchEnded", "MatchDestroyed"):
                            if state.user_team_num is not None and not state._match_recorded:
                                state._match_recorded = True
                                d = raw_data if isinstance(raw_data, dict) else (json.loads(raw_data) if isinstance(raw_data, str) else {})
                                winner = FieldResolver.resolve(d, "winner")
                                if winner is not None:
                                    if isinstance(winner, str):
                                        wn = 0 if winner.lower() == "blue" else 1
                                    else:
                                        try:
                                            wn = int(winner)
                                        except (ValueError, TypeError):
                                            wn = -1
                                    if wn in (0, 1):
                                        result = "win" if wn == state.user_team_num else "loss"
                                    else:
                                        result = "win" if state.user_score > state.opponent_score else "loss"
                                else:
                                    result = "win" if state.user_score > state.opponent_score else "loss"
                                log(f"{event}: {result.upper()}! {state.scores[0]}-{state.scores[1]}")
                                state.record_match(result)
                                state.reset()

                        elif event == "GoalScored":
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

                # Flush log to disk every 5s (not on every event!)
                if now - last_flush > 5:
                    flush_log()
                    last_flush = now

            # Connection ended
            state._connected = False
            state._poll_interval = 60
            sock.close()
            if state.user_team_num is not None and state.tick_count > 0:
                res = "win" if state.user_score > state.opponent_score else "loss"
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
