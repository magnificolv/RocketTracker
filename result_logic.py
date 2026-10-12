"""Win/loss and playlist helpers for the RL Stats API (v2.72+ / v2.76).

Full-time: the goals we counted are the authority. An unknown Winner string
must never be treated as Orange — that inverted a real 1-0 win (2026-10-02).

Early end (clock still running): WinnerTeamNum is a forfeit. Trust that.
"""

PLAYLIST_NAMES = {
    0: "Casual",
    1: "Casual 1v1",
    2: "Casual 2v2",
    3: "Casual 3v3",
    4: "Chaos 4v4",
    6: "Private",
    7: "Season",
    8: "Exhibition",
    10: "Ranked 1v1",
    11: "Ranked 2v2",
    13: "Ranked 3v3",
    15: "Snow Day",
    17: "Hoops",
    18: "Rumble",
    23: "Dropshot",
    27: "Ranked Hoops",
    28: "Ranked Rumble",
    29: "Ranked Dropshot",
    30: "Ranked Snow Day",
    34: "Tournament",
    38: "Heatseeker",
    43: "Heatseeker 2v2",
    54: "Knockout",
    61: "Ranked 4v4",
}

# Noteworthy ticker events only. Plain Goal/Save/Shot/Demolish are already counted.
ACCOLADE_LABELS = {
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
    "matches": [("tags", "TEXT")],
    "match_details": [
        ("crossbar_hits", "INTEGER DEFAULT 0"),
        ("boost_pads", "INTEGER DEFAULT 0"),
        ("boost_pills", "INTEGER DEFAULT 0"),
        ("forfeit", "INTEGER DEFAULT 0"),
        ("accolades", "TEXT"),
    ],
}


def _compact(value):
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


def winner_team_num(winner, team_names=None):
    """Return 0, 1, or None. None means unknown or no-contest (-1)."""
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
                    return int(num)
                except (TypeError, ValueError):
                    continue
    return None


def decide_result(user_team, winner, scores, team_names=None, time_remaining=None):
    """Return 'win', 'loss', or 'draw'."""
    if user_team not in (0, 1):
        return "draw"
    us = int(scores[user_team] or 0)
    opp = int(scores[1 - user_team] or 0)
    if us > opp:
        score_result = "win"
    elif us < opp:
        score_result = "loss"
    else:
        score_result = "draw"
    wn = winner_team_num(winner, team_names)
    if wn not in (0, 1):
        return score_result
    winner_result = "win" if wn == user_team else "loss"
    if score_result == "draw" or winner_result == score_result:
        return winner_result if score_result == "draw" else score_result
    try:
        remaining = float(time_remaining) if time_remaining is not None else 0
    except (TypeError, ValueError):
        remaining = 0
    # Clock still running + winner disagrees with the score → forfeit.
    if remaining > 20:
        return winner_result
    return score_result


def playlist_label(playlist_id, player_count=0, fallback=""):
    try:
        pid = int(playlist_id)
    except (TypeError, ValueError):
        return fallback or "Unknown"
    if pid == 0 and player_count:
        if player_count <= 2:
            return "Casual 1v1"
        if player_count <= 4:
            return "Casual 2v2"
        if player_count <= 6:
            return "Casual 3v3"
        return "Casual %dp" % player_count
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
        size = " %dp" % player_count
    return "Mode %s%s" % (pid, size)


def accolade_label(event_name):
    if not event_name:
        return None
    return ACCOLADE_LABELS.get(str(event_name))


def ensure_schema(conn):
    for table, cols in SCHEMA_COLUMNS.items():
        try:
            existing = {r[1] for r in conn.execute("PRAGMA table_info(%s)" % table).fetchall()}
        except Exception:
            continue
        for name, decl in cols:
            if name not in existing:
                try:
                    conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, name, decl))
                except Exception:
                    pass


def repair_inverted_results(conn):
    """Flip W/L rows that contradict a decisive score. Leaves 0-0 alone."""
    flipped = []
    try:
        rows = conn.execute(
            """SELECT id, result, user_score, opponent_score FROM matches
               WHERE (result='loss' AND user_score > opponent_score)
                  OR (result='win' AND user_score < opponent_score)"""
        ).fetchall()
    except Exception:
        return flipped
    for row in rows:
        us, opp = row[2], row[3]
        new = "win" if us > opp else "loss"
        mid = row[0]
        conn.execute("UPDATE matches SET result=? WHERE id=?", (new, mid))
        try:
            conn.execute("UPDATE matches_summary SET result=? WHERE match_id=?", (new, mid))
        except Exception:
            pass
        flipped.append(mid)
    return flipped
