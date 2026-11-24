"""Pure match classification, scoring, arena, and SQLite schema helpers for RL Tracker v4."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

PLAYLIST_NAMES: Dict[int, str] = {
    # Casual & LTM
    0: "Casual",
    1: "Casual 1v1",
    2: "Casual 2v2",
    3: "Casual 3v3",
    4: "Chaos 4v4",
    15: "Snow Day",
    17: "Hoops",
    18: "Rumble",
    23: "Dropshot",
    38: "Heatseeker",
    43: "Heatseeker 2v2",
    54: "Knockout",
    # Practice / Private / Offline
    6: "Private",
    7: "Season",
    8: "Exhibition",
    9: "Training",
    19: "Workshop",
    20: "Custom Training",
    21: "Custom Training",
    22: "Custom Tournament",
    24: "Local Match",
    # Competitive Core
    10: "Ranked 1v1",
    11: "Ranked 2v2",
    13: "Ranked 3v3",
    61: "Ranked 4v4",
    # Competitive Extra Modes
    27: "Ranked Hoops",
    28: "Ranked Rumble",
    29: "Ranked Dropshot",
    30: "Ranked Snow Day",
    # Competitive Tournaments
    34: "Tournament",
}

COMPETITIVE_CORE_IDS = frozenset({10, 11, 13, 61})
COMPETITIVE_EXTRA_IDS = frozenset({27, 28, 29, 30})
TOURNAMENT_IDS = frozenset({34})
COMPETITIVE_PLAYLIST_IDS = COMPETITIVE_CORE_IDS | COMPETITIVE_EXTRA_IDS | TOURNAMENT_IDS
CASUAL_PLAYLIST_IDS = frozenset({0, 1, 2, 3, 4, 15, 17, 18, 23, 38, 43, 54})
PRIVATE_PLAYLIST_IDS = frozenset({6, 22})
ALWAYS_IGNORED_PLAYLIST_IDS = frozenset({7, 8, 9, 19, 20, 21, 24})

DEFAULT_TRACKING_CONFIG: Dict[str, Any] = {
    "scope": "competitive",
    "include_core_ranked": True,
    "include_extra_ranked": True,
    "include_tournaments": True,
    "include_casual": False,
    "include_private": False,
}

ARENA_NAMES: Dict[str, str] = {
    "stadium_p": "DFH Stadium",
    "stadium_foggy_p": "DFH Stadium (Stormy)",
    "stadium_winter_p": "DFH Stadium (Snowy)",
    "stadium_race_day_p": "DFH Stadium (Day)",
    "stadium_10a_p": "DFH Stadium (10th Anniv)",
    "eurostadium_p": "Mannfield",
    "eurostadium_night_p": "Mannfield (Night)",
    "eurostadium_rainy_p": "Mannfield (Stormy)",
    "eurostadium_snowy_p": "Mannfield (Snowy)",
    "park_p": "Beckwith Park",
    "park_night_p": "Beckwith Park (Midnight)",
    "park_rainy_p": "Beckwith Park (Stormy)",
    "park_snowy_p": "Beckwith Park (Snowy)",
    "trainstation_p": "Urban Central",
    "trainstation_night_p": "Urban Central (Night)",
    "trainstation_dawn_p": "Urban Central (Dawn)",
    "utopiastadium_p": "Utopia Coliseum",
    "utopiastadium_dusk_p": "Utopia Coliseum (Dusk)",
    "utopiastadium_snow_p": "Utopia Coliseum (Snowy)",
    "utopiastadium_lux_p": "Utopia Coliseum (Gilded)",
    "wasteland_s_p": "Wasteland",
    "wasteland_night_s_p": "Wasteland (Night)",
    "neotokyo_standard_p": "Neo Tokyo",
    "neotokyo_comic_p": "Neo Tokyo (Comic)",
    "neotokyo_hacked_p": "Neo Tokyo (Hacked)",
    "underwater_p": "AquaDome",
    "underwater_grs_p": "AquaDome (Salty Shallows)",
    "arc_standard_p": "Starbase ARC",
    "arc_darc_p": "Starbase ARC (Aftermath)",
    "cs_p": "Champions Field",
    "cs_day_p": "Champions Field (Day)",
    "cs_hw_p": "Rivals Arena",
    "farm_p": "Farmstead",
    "farm_night_p": "Farmstead (Night)",
    "farm_grs_p": "Farmstead (Pitched)",
    "beach_p": "Salty Shores",
    "beach_night_p": "Salty Shores (Night)",
    "chn_day_p": "Forbidden Temple",
    "chn_stadium_p": "Forbidden Temple (Day)",
    "chn_stadium_night_p": "Forbidden Temple (Night)",
    "music_p": "Neon Fields",
    "outlaw_p": "Deadeye Canyon",
    "outlaw_oasis_p": "Deadeye Canyon (Oasis)",
    "swoosh_p": "Sovereign Heights",
    "street_p": "Estadio Vida",
    "ff_dusk_p": "Drift Woods",
    "hoopsstadium_p": "Dunk House",
    "hoopsbay_p": "The Block",
    "shattershot_p": "Core 707",
    "throwbackstadium_p": "Throwback Stadium",
}

ACCOLADE_LABELS: Dict[str, str] = {
    "EpicSave": "Epic Save",
    "HatTrick": "Hat Trick",
    "Savior": "Savior",
    "Playmaker": "Playmaker",
    "AerialGoal": "Aerial",
    "BackwardsGoal": "Backwards",
    "BicycleGoal": "Bicycle",
    "LongGoal": "Long Goal",
    "TurtleGoal": "Turtle",
    "PoolShot": "Pool Shot",
    "OvertimeGoal": "OT Goal",
    "Demolition": "Extermination",
    "MVP": "MVP",
    "OwnGoal": "Own Goal",
    "HighFive": "High Five",
    "LowFive": "Low Five",
    "BicycleHit": "Bicycle Hit",
}

SCHEMA_COLUMNS = {
    "matches": [
        ("tags", "TEXT"),
        ("match_guid", "TEXT"),
        ("playlist_id", "INTEGER"),
        ("is_competitive", "INTEGER DEFAULT 1"),
        ("manual_override", "INTEGER DEFAULT 0"),
    ],
    "match_details": [
        ("crossbar_hits", "INTEGER DEFAULT 0"),
        ("boost_pads", "INTEGER DEFAULT 0"),
        ("boost_pills", "INTEGER DEFAULT 0"),
        ("forfeit", "INTEGER DEFAULT 0"),
        ("accolades", "TEXT"),
        ("player_goals", "INTEGER"),
        ("player_score", "INTEGER DEFAULT 0"),
        ("is_mvp", "INTEGER DEFAULT 0"),
        ("powerslide_time_pct", "REAL DEFAULT 0"),
        ("avg_speed_kph", "REAL DEFAULT 0"),
        ("max_speed_kph", "REAL DEFAULT 0"),
        ("duration_sec", "INTEGER DEFAULT 0"),
        ("players_json", "TEXT"),
        ("teammate_goals", "INTEGER DEFAULT 0"),
        ("teammate_score", "INTEGER DEFAULT 0"),
        ("teammate_boost_avg", "REAL DEFAULT 0"),
        ("teammate_air_pct", "REAL DEFAULT 0"),
        ("teammate_wall_pct", "REAL DEFAULT 0"),
        ("teammate_supersonic_pct", "REAL DEFAULT 0"),
    ],
    "matches_summary": [
        ("playlist", "TEXT"),
        ("friend_name", "TEXT"),
        ("playlist_id", "INTEGER"),
        ("player_goals", "INTEGER"),
        ("player_score", "INTEGER DEFAULT 0"),
        ("is_mvp", "INTEGER DEFAULT 0"),
        ("forfeit", "INTEGER DEFAULT 0"),
        ("overtime", "INTEGER DEFAULT 0"),
    ],
}


def normalize_tracking_config(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Return a clean tracking filter config merged with v4 defaults."""
    cfg = dict(DEFAULT_TRACKING_CONFIG)
    if isinstance(raw, dict):
        scope = str(raw.get("scope") or cfg["scope"]).strip().lower()
        if scope in ("competitive", "all_online", "custom"):
            cfg["scope"] = scope
        for key in (
            "include_core_ranked",
            "include_extra_ranked",
            "include_tournaments",
            "include_casual",
            "include_private",
        ):
            if key in raw:
                cfg[key] = bool(raw[key])
    return cfg


def playlist_label(playlist_id: Any, player_count: int = 0, fallback: str = "") -> str:
    """Resolve human-readable playlist name from Psyonix PlaylistId."""
    if playlist_id is None or isinstance(playlist_id, bool):
        return fallback or "Unknown"
    try:
        pid = int(playlist_id)
    except (TypeError, ValueError):
        return fallback or "Unknown"

    if pid == 0 and player_count > 0:
        if player_count <= 2:
            return "Casual 1v1"
        if player_count <= 4:
            return "Casual 2v2"
        if player_count <= 6:
            return "Casual 3v3"
        return f"Casual {player_count}p"

    name = PLAYLIST_NAMES.get(pid)
    if name:
        return name

    if player_count <= 0:
        size = ""
    elif player_count <= 2:
        size = " 1v1"
    elif player_count <= 4:
        size = " 2v2"
    elif player_count <= 6:
        size = " 3v3"
    else:
        size = f" {player_count}p"
    return f"Mode {pid}{size}"


def is_competitive_playlist(playlist_id: Any = None, playlist_name: str = "") -> bool:
    """Return True if playlist_id or playlist label represents a competitive mode."""
    if playlist_id is not None and not isinstance(playlist_id, bool):
        try:
            return int(playlist_id) in COMPETITIVE_PLAYLIST_IDS
        except (TypeError, ValueError):
            pass
    low = (playlist_name or "").strip().lower()
    return low.startswith("ranked") or low == "tournament"


def classify_match(
    playlist_id: Any,
    match_guid: Optional[str],
    max_opponents: int,
    is_spectator_or_replay: bool,
    tracking_cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Classify a match and decide whether it should be recorded to SQLite."""
    cfg = normalize_tracking_config(tracking_cfg)
    scope = cfg["scope"]

    pid: Optional[int] = None
    if playlist_id is not None and not isinstance(playlist_id, bool):
        try:
            pid = int(playlist_id)
        except (TypeError, ValueError):
            pid = None

    label = playlist_label(pid)

    if is_spectator_or_replay:
        return {
            "should_record": False,
            "category": "replay",
            "reason": "Spectator or saved replay",
            "label": label,
            "is_competitive": pid in COMPETITIVE_PLAYLIST_IDS if pid is not None else False,
        }

    if not match_guid or not str(match_guid).strip():
        return {
            "should_record": False,
            "category": "practice",
            "reason": "Offline / Freeplay / Training (no MatchGuid)",
            "label": label,
            "is_competitive": False,
        }

    if pid in ALWAYS_IGNORED_PLAYLIST_IDS:
        return {
            "should_record": False,
            "category": "practice",
            "reason": f"Practice / Offline mode ({label})",
            "label": label,
            "is_competitive": False,
        }

    if (max_opponents or 0) <= 0:
        return {
            "should_record": False,
            "category": "practice",
            "reason": "No opponents present (Freeplay / Practice)",
            "label": label,
            "is_competitive": False,
        }

    if pid in COMPETITIVE_CORE_IDS:
        allowed = (scope == "all_online") or bool(cfg["include_core_ranked"])
        return {
            "should_record": allowed,
            "category": "competitive",
            "reason": "Competitive Core match" if allowed else f"Core Ranked disabled ({label})",
            "label": label,
            "is_competitive": True,
        }

    if pid in COMPETITIVE_EXTRA_IDS:
        allowed = (scope == "all_online") or bool(cfg["include_extra_ranked"])
        return {
            "should_record": allowed,
            "category": "competitive",
            "reason": "Competitive Extra Mode match" if allowed else f"Extra Ranked disabled ({label})",
            "label": label,
            "is_competitive": True,
        }

    if pid in TOURNAMENT_IDS:
        allowed = (scope == "all_online") or bool(cfg["include_tournaments"])
        return {
            "should_record": allowed,
            "category": "competitive",
            "reason": "Competitive Tournament match" if allowed else "Tournaments disabled in filter",
            "label": label,
            "is_competitive": True,
        }

    if pid in CASUAL_PLAYLIST_IDS:
        allowed = (scope == "all_online") or (scope == "custom" and bool(cfg["include_casual"]))
        return {
            "should_record": allowed,
            "category": "casual",
            "reason": "Casual match" if allowed else f"Casual ignored ({label}; Competitive-only filter)",
            "label": label,
            "is_competitive": False,
        }

    if pid in PRIVATE_PLAYLIST_IDS:
        allowed = scope == "custom" and bool(cfg["include_private"])
        return {
            "should_record": allowed,
            "category": "private",
            "reason": "Private match" if allowed else f"Private match ignored ({label})",
            "label": label,
            "is_competitive": False,
        }

    # Unknown or missing PlaylistId
    if scope == "all_online":
        return {
            "should_record": True,
            "category": "unknown",
            "reason": "Online match (unrecognized playlist ID)",
            "label": label,
            "is_competitive": False,
        }
    return {
        "should_record": False,
        "category": "unknown",
        "reason": "Unknown / non-competitive playlist (Competitive-only mode)",
        "label": label,
        "is_competitive": False,
    }


def arena_label(raw: Optional[str]) -> str:
    """Resolve RL arena asset name to human-readable stadium name."""
    if not raw or not str(raw).strip():
        return "Unknown Arena"
    s = str(raw).strip()
    hit = ARENA_NAMES.get(s.lower())
    if hit:
        return hit
    cleaned = re.sub(r"_[pP]$", "", s)
    cleaned = re.sub(r"([a-z])([A-Z])", r"\1 \2", cleaned)
    cleaned = cleaned.replace("_", " ").strip()
    return cleaned or s


def is_bogus_goal_scored(data: Dict[str, Any]) -> bool:
    """Detect zeroed replay-ghost GoalScored events emitted by RL Stats API."""
    if not isinstance(data, dict):
        return True
    scorer = data.get("Scorer")
    sname = ""
    shortcut = 0
    if isinstance(scorer, dict):
        sname = str(scorer.get("Name") or scorer.get("name") or "").strip()
        try:
            shortcut = int(scorer.get("Shortcut") or 0)
        except (TypeError, ValueError):
            shortcut = 0
    elif isinstance(scorer, str):
        sname = scorer.strip()

    try:
        speed = float(data.get("GoalSpeed") or 0.0)
    except (TypeError, ValueError):
        speed = 0.0
    try:
        gtime = float(data.get("GoalTime") or 0.0)
    except (TypeError, ValueError):
        gtime = 0.0

    if not sname and speed <= 0.0 and gtime <= 0.0 and shortcut == 0:
        return True
    if not sname and speed <= 0.0:
        return True
    return False


def reconcile_scores(
    goal_event_scores: Sequence[int],
    team_delta_scores: Optional[Sequence[int]] = None,
    player_goals_by_team: Optional[Sequence[int]] = None,
) -> Tuple[int, int]:
    """Reconcile GoalScored counters against delta Game.Teams scores and player goals."""
    b0 = max(0, int(goal_event_scores[0] or 0))
    b1 = max(0, int(goal_event_scores[1] or 0))

    if team_delta_scores is not None and len(team_delta_scores) >= 2:
        try:
            d0 = int(team_delta_scores[0])
            d1 = int(team_delta_scores[1])
            if 0 <= d0 <= 30 and 0 <= d1 <= 30:
                b0 = max(b0, d0)
                b1 = max(b1, d1)
        except (TypeError, ValueError):
            pass

    if player_goals_by_team is not None and len(player_goals_by_team) >= 2:
        try:
            p0 = int(player_goals_by_team[0])
            p1 = int(player_goals_by_team[1])
            if 0 <= p0 <= 30 and 0 <= p1 <= 30:
                b0 = max(b0, p0)
                b1 = max(b1, p1)
        except (TypeError, ValueError):
            pass

    return b0, b1


def _compact(value: Any) -> str:
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


def winner_team_num(winner: Any, team_names: Optional[Dict[int, str]] = None) -> Optional[int]:
    """Return 0, 1, or None. Never guesses Orange for unknown strings."""
    if winner is None or isinstance(winner, bool):
        return None
    if isinstance(winner, (int, float)):
        n = int(winner)
        return n if n in (0, 1) else None
    raw = str(winner).strip()
    if not raw:
        return None
    low = raw.lower()
    if low in ("-1", "none", "draw", "tie", "nocontest", "no contest"):
        return None
    if low in ("0", "1"):
        return int(low)
    compact = _compact(raw)
    if compact.startswith("blue"):
        return 0
    if compact.startswith("orange"):
        return 1
    if team_names:
        for num, name in team_names.items():
            nn = _compact(name)
            if nn and (nn == compact or compact in nn or nn in compact):
                try:
                    tn = int(num)
                    return tn if tn in (0, 1) else None
                except (TypeError, ValueError):
                    continue
    return None


def decide_result(
    user_team: Optional[int],
    match_ended_winner: Any = None,
    game_winner: Any = None,
    scores: Sequence[int] = (0, 0),
    team_names: Optional[Dict[int, str]] = None,
    is_overtime: bool = False,
    time_remaining: Optional[float] = None,
) -> Tuple[str, bool]:
    """Decide ('win'|'loss'|'draw'|'no_contest', is_forfeit) with clear authority hierarchy."""
    if user_team not in (0, 1):
        return "draw", False

    if match_ended_winner is not None and not isinstance(match_ended_winner, bool):
        try:
            mew = int(match_ended_winner)
        except (TypeError, ValueError):
            mew = None
        if mew == -1:
            return "no_contest", False
    else:
        mew = None

    us = int(scores[user_team] or 0)
    opp = int(scores[1 - user_team] or 0)
    if us > opp:
        score_res = "win"
    elif us < opp:
        score_res = "loss"
    else:
        score_res = "draw"

    try:
        remaining = float(time_remaining) if time_remaining is not None else 0.0
    except (TypeError, ValueError):
        remaining = 0.0
    early_clock = (not is_overtime) and (remaining > 5.0)

    # Authority 1: MatchEnded.WinnerTeamNum (authoritative integer from RL)
    if mew in (0, 1):
        res = "win" if mew == user_team else "loss"
        is_ff = early_clock or (score_res == "draw") or (score_res != res)
        return res, is_ff

    # Authority 2: Game.Winner string matched strictly against Blue/Orange/team_names
    wn = winner_team_num(game_winner, team_names)
    if wn in (0, 1):
        res = "win" if wn == user_team else "loss"
        is_ff = early_clock or (score_res == "draw") or (score_res != res)
        return res, is_ff

    # Authority 3: Score fallback
    return score_res, False


def accolade_label(event_name: Any) -> Optional[str]:
    if not event_name:
        return None
    return ACCOLADE_LABELS.get(str(event_name))


def ensure_schema(conn) -> None:
    """Add v3/v4 columns cleanly to existing SQLite tables without touching rows."""
    for table, cols in SCHEMA_COLUMNS.items():
        try:
            existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        except Exception:
            continue
        if not existing:
            continue
        for name, decl in cols:
            if name not in existing:
                try:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
                except Exception:
                    pass


def repair_inverted_results(conn) -> list[int]:
    """Flip W/L rows contradicting a decisive score, skipping forfeits & manual overrides."""
    flipped: list[int] = []
    try:
        rows = conn.execute(
            """SELECT m.id, m.result, m.user_score, m.opponent_score
               FROM matches m
               LEFT JOIN match_details md ON md.match_id = m.id
               WHERE COALESCE(m.manual_override, 0) = 0
                 AND COALESCE(md.forfeit, 0) = 0
                 AND ((m.result='loss' AND m.user_score > m.opponent_score)
                   OR (m.result='win' AND m.user_score < m.opponent_score))"""
        ).fetchall()
    except Exception:
        return flipped

    for row in rows:
        mid = row[0]
        us, opp = row[2], row[3]
        new_res = "win" if us > opp else "loss"
        conn.execute("UPDATE matches SET result=? WHERE id=?", (new_res, mid))
        try:
            conn.execute("UPDATE matches_summary SET result=? WHERE match_id=?", (new_res, mid))
        except Exception:
            pass
        flipped.append(mid)
    return flipped


__all__ = [
    "PLAYLIST_NAMES",
    "COMPETITIVE_CORE_IDS",
    "COMPETITIVE_EXTRA_IDS",
    "TOURNAMENT_IDS",
    "COMPETITIVE_PLAYLIST_IDS",
    "CASUAL_PLAYLIST_IDS",
    "PRIVATE_PLAYLIST_IDS",
    "ALWAYS_IGNORED_PLAYLIST_IDS",
    "DEFAULT_TRACKING_CONFIG",
    "ARENA_NAMES",
    "ACCOLADE_LABELS",
    "SCHEMA_COLUMNS",
    "normalize_tracking_config",
    "playlist_label",
    "is_competitive_playlist",
    "classify_match",
    "arena_label",
    "is_bogus_goal_scored",
    "reconcile_scores",
    "winner_team_num",
    "decide_result",
    "accolade_label",
    "ensure_schema",
    "repair_inverted_results",
]
