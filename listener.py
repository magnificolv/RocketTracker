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

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

BASE_DIR = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
DB_PATH = BASE_DIR / "data.db"
CONFIG_PATH = BASE_DIR / "config.yaml"
LOG_PATH = BASE_DIR / "listener.log"
STATUS_PATH = BASE_DIR / "listener_status.json"

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
    needed = "[TAGame.MatchStatsExporter_TA]\nPort=49123\nPacketSendRate=30\n"
    if ini_path.exists() and "TAGame.MatchStatsExporter_TA" in ini_path.read_text() and "PacketSendRate=30" in ini_path.read_text():
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


def update_status(state: str, msg: str = "", player="", friends=None):
    try:
        with open(STATUS_PATH, "w") as f:
            json.dump({
                "state": state, "message": msg, "player": player,
                "friends": friends or [],
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
                 '_prev_demos', '_was_demolished')

    def __init__(self, player_name, friend_names):
        self.player_name = player_name.lower().strip()
        self.friend_names = friend_names
        self._player_cache = {}  # {name_hash: result} for fast lookups
        self._friend_cache = set(f.lower().strip() for f in friend_names if f.strip())
        self._match_recorded = False
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

    def _fast_find(self, players, target):
        """Ultra-fast player lookup - no string slicing."""
        for p in players:
            pname = p.get("Name", "")
            if not pname:
                continue
            # Exact match first (most common case)
            if pname.lower() == target:
                return p
            # Partial match fallback
            pname_l = pname.lower()
            if target in pname_l or pname_l in target:
                return p
        return None

    def handle_update_state(self, data):
        players = data.get("Players", [])
        game = data.get("Game", {})
        self.tick_count += 1

        # Player detection (only run until found)
        if self.user_team_num is None and players:
            p = self._fast_find(players, self.player_name)
            if p:
                self.user_team_num = p.get("TeamNum", -1)
                log(f"FOUND PLAYER: {p.get('Name')} on Team {self.user_team_num} ({'Blue' if self.user_team_num == 0 else 'Orange'}) [scores: {self.scores}]")
                update_status("connected", f"Live - tracking {p.get('Name')}", self.player_name)
                # Fast duo detection (also done on every tick below)
                if self._friend_cache:
                    for fp in players:
                        if fp.get("TeamNum") == self.user_team_num:
                            fpname = fp.get("Name", "").lower().strip()
                            if fpname in self._friend_cache or any(f in fpname or fpname in f for f in self._friend_cache):
                                self.mode = "duo"
                                log(f"Duo detected: {fp.get('Name')}")
                                break

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

        # Player stats (fast path if user_team_num is set)
        if self.user_team_num is not None and players:
            p = self._fast_find(players, self.player_name)
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

                # Duo re-check on every tick (friend may appear after initial detection)
                if self.mode == "solo" and self._friend_cache and players:
                    for fp in players:
                        if fp.get("TeamNum") == self.user_team_num:
                            fpname = fp.get("Name", "").lower().strip()
                            if fpname in self._friend_cache or any(f in fpname or fpname in f for f in self._friend_cache):
                                self.mode = "duo"
                                log(f"Duo detected (late join): {fp.get('Name')}")
                                break

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
        flush_log()
        log(f"RECORDED: {'WIN' if result == 'win' else 'LOSS'}! {self.user_score}-{self.opponent_score} [{self.mode}]")

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
    log("RL Raw TCP Listener (Windows Portable v7 FAST)")
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
                                winner = d.get("WinnerTeamNum", d.get("Winner"))
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
                            scorer = d.get("Scorer", {})
                            sname = scorer.get("Name", "")
                            if not sname:
                                pos += end; continue
                            steam = scorer.get("TeamNum", -1)
                            state.scores[steam] = state.scores[steam] + 1 if steam in (0, 1) else state.scores[steam]
                            gs = d.get("GoalSpeed")
                            speed_kph = round(gs, 1) if gs else None  # GoalSpeed already in km/h
                            state.goals.append({
                                "scored_at": datetime.now(timezone.utc).isoformat(),
                                "scorer": sname, "assister": d.get("Assister", {}).get("Name") or None,
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
                            # RL may send different field names — try them all
                            att = d.get("Attacker") or d.get("attacker") or d.get("AttackerName") or d.get("attacker_name") or ""
                            vic = d.get("Victim") or d.get("victim") or d.get("VictimName") or d.get("victim_name") or ""
                            # If these are dicts, extract Name
                            an = att.get("Name", "") if isinstance(att, dict) else str(att or "")
                            vn = vic.get("Name", "") if isinstance(vic, dict) else str(vic or "")
                            an_l = an.lower(); vn_l = vn.lower()
                            if an_l and (state.player_name in an_l or an_l in state.player_name):
                                state.demos_given += 1
                                log(f"DEMO GIVEN: {an}")
                            elif vn_l and (state.player_name in vn_l or vn_l in state.player_name):
                                state.demos_taken += 1
                                log(f"DEMO TAKEN: {vn}")
                            else:
                                # RAW dump for debugging unknown format
                                log(f"DEMO RAW: attacker={att}, victim={vic}, d={d}")

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

        time.sleep(reconnect_delay)
        reconnect_delay = min(reconnect_delay * 1.5, max_delay)

    flush_log()
    log("Listener stopped")
    update_status("stopped", "Listener stopped", player, friends)
