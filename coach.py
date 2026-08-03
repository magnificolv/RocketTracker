"""
RL Tracker 3.0 — Active Coach Engine + Coach 2.0 session reports
================================================================
After each match: anomaly insights vs last 20.
Session report: grades, category scores, tips for you (+ teammate if duo).
"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Tuple

WINDOW = 20

TYPE_GOALS = "goals"
TYPE_DEMOS = "demos"
TYPE_SPEED = "speed_record"
TYPE_BOOST = "boost_warning"
TYPE_SAVES = "saves"


def _clamp(n, lo=0, hi=100):
    return max(lo, min(hi, n))


def _grade(score: float) -> str:
    s = float(score)
    if s >= 93:
        return "A+"
    if s >= 90:
        return "A"
    if s >= 87:
        return "A-"
    if s >= 83:
        return "B+"
    if s >= 80:
        return "B"
    if s >= 77:
        return "B-"
    if s >= 73:
        return "C+"
    if s >= 70:
        return "C"
    if s >= 67:
        return "C-"
    if s >= 60:
        return "D"
    return "F"


def _trend(cur: float, base: float) -> str:
    if base <= 0 and cur <= 0:
        return "flat"
    if base <= 0:
        return "up"
    ratio = cur / base
    if ratio >= 1.12:
        return "up"
    if ratio <= 0.88:
        return "down"
    return "flat"


class CoachEngine:
    """Analyse matches and build Coach 2.0 session reports."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _get_match(self, conn, match_id):
        return conn.execute(
            "SELECT m.*, md.*, "
            "(SELECT COUNT(*) FROM goals g WHERE g.match_id=m.id) as goals_in_match "
            "FROM matches m "
            "LEFT JOIN match_details md ON md.match_id = m.id "
            "WHERE m.id=?",
            (match_id,),
        ).fetchone()

    def _recent_matches(self, conn, before_match_id, limit=WINDOW):
        cur = conn.execute("SELECT played_at FROM matches WHERE id=?", (before_match_id,)).fetchone()
        if not cur:
            return []
        played_at = cur["played_at"]
        return conn.execute(
            "SELECT m.*, md.* FROM matches m "
            "LEFT JOIN match_details md ON md.match_id = m.id "
            "WHERE m.played_at < ? ORDER BY m.played_at DESC LIMIT ?",
            (played_at, limit),
        ).fetchall()

    def analyze_match(self, match_id):
        conn = self._conn()
        try:
            match = self._get_match(conn, match_id)
            if not match:
                return {"error": "Match not found", "insights": []}
            recent = self._recent_matches(conn, match_id, WINDOW)
            insights, baseline = self._analyse(match, recent)
            return {"match_id": match_id, "insights": insights, "baseline": baseline}
        finally:
            conn.close()

    def get_session_anomalies(self, session_id):
        conn = self._conn()
        try:
            sess = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
            if not sess:
                return {"error": "Session not found", "insights": []}
            matches = conn.execute(
                "SELECT id FROM matches WHERE session_id=? ORDER BY played_at ASC",
                (session_id,),
            ).fetchall()
            all_insights = []
            for m in matches:
                res = self.analyze_match(m["id"])
                for ins in res.get("insights", []):
                    ins["match_id"] = m["id"]
                    all_insights.append(ins)
            return {
                "session_id": session_id,
                "match_count": len(matches),
                "insights": all_insights,
            }
        finally:
            conn.close()

    def get_all_records(self):
        conn = self._conn()
        try:
            md = conn.execute(
                """
                SELECT
                    MAX(demos_given) as most_demos,
                    MAX(saves) as most_saves,
                    MAX(shots) as most_shots,
                    MAX(touches) as most_touches,
                    MAX(assists) as most_assists,
                    MAX(boost_avg) as highest_boost_avg,
                    MAX(boost_time_pct) as highest_boost_time,
                    MAX(supersonic_time_pct) as highest_supersonic_time,
                    MAX(fastest_goal_kph) as fastest_goal_kph,
                    MAX(avg_shot_power) as highest_avg_shot_power
                FROM match_details
                """
            ).fetchone()
            goals_row = conn.execute(
                "SELECT MAX(user_score) as most_goals, "
                "COUNT(*) as total_matches, "
                "SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) as wins, "
                "SUM(CASE WHEN result='loss' THEN 1 ELSE 0 END) as losses "
                "FROM matches"
            ).fetchone()

            def _find_match(sql, params=()):
                r = conn.execute(sql, params).fetchone()
                return r["match_id"] if r else None

            most_goals_id = (
                _find_match(
                    "SELECT id as match_id FROM matches "
                    "WHERE user_score = (SELECT MAX(user_score) FROM matches) "
                    "ORDER BY played_at DESC LIMIT 1"
                )
                if goals_row["most_goals"]
                else None
            )
            most_demos_id = _find_match(
                "SELECT match_id FROM match_details "
                "WHERE demos_given = (SELECT MAX(demos_given) FROM match_details) "
                "ORDER BY match_id DESC LIMIT 1"
            )
            most_saves_id = _find_match(
                "SELECT match_id FROM match_details "
                "WHERE saves = (SELECT MAX(saves) FROM match_details) "
                "ORDER BY match_id DESC LIMIT 1"
            )
            fastest_goal_id = _find_match(
                "SELECT match_id FROM match_details "
                "WHERE fastest_goal_kph = (SELECT MAX(fastest_goal_kph) FROM match_details) "
                "ORDER BY match_id DESC LIMIT 1"
            )

            return {
                "records": {
                    "most_goals": {"value": goals_row["most_goals"] or 0, "match_id": most_goals_id},
                    "most_demos": {"value": md["most_demos"] or 0, "match_id": most_demos_id},
                    "most_saves": {"value": md["most_saves"] or 0, "match_id": most_saves_id},
                    "most_shots": {"value": md["most_shots"] or 0, "match_id": None},
                    "most_touches": {"value": md["most_touches"] or 0, "match_id": None},
                    "most_assists": {"value": md["most_assists"] or 0, "match_id": None},
                    "fastest_goal_kph": {
                        "value": round(md["fastest_goal_kph"] or 0, 1),
                        "match_id": fastest_goal_id,
                    },
                    "highest_boost_avg": {
                        "value": round(md["highest_boost_avg"] or 0, 1),
                        "match_id": None,
                    },
                    "highest_boost_time_pct": {
                        "value": round(md["highest_boost_time"] or 0, 1),
                        "match_id": None,
                    },
                    "highest_supersonic_time_pct": {
                        "value": round(md["highest_supersonic_time"] or 0, 1),
                        "match_id": None,
                    },
                    "highest_avg_shot_power": {
                        "value": round(md["highest_avg_shot_power"] or 0, 1),
                        "match_id": None,
                    },
                    "total_matches": goals_row["total_matches"] or 0,
                    "total_wins": goals_row["wins"] or 0,
                    "total_losses": goals_row["losses"] or 0,
                }
            }
        finally:
            conn.close()

    # ------------------------------------------------------------------ #
    # Coach 2.0
    # ------------------------------------------------------------------ #
    def session_report(self, session_id: int, player_name: str = "You") -> Dict[str, Any]:
        """Full Coach 2.0 report for a session (solo + optional teammate)."""
        conn = self._conn()
        try:
            sess = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
            if not sess:
                return {"error": "Session not found"}

            rows = conn.execute(
                """
                SELECT m.*, md.shots, md.saves, md.assists, md.touches, md.car_touches,
                       md.demos_given, md.demos_taken, md.boost_avg, md.boost_time_pct,
                       md.supersonic_time_pct, md.air_time_pct, md.ground_time_pct,
                       md.wall_time_pct, md.fastest_goal_kph, md.avg_shot_power,
                       md.overtime, md.arena, md.playlist as md_playlist,
                       md.teammate_name, md.teammate_shots, md.teammate_saves,
                       md.teammate_assists, md.teammate_touches, md.teammate_demos
                FROM matches m
                LEFT JOIN match_details md ON md.match_id = m.id
                WHERE m.session_id=?
                ORDER BY m.played_at ASC
                """,
                (session_id,),
            ).fetchall()
            matches = [dict(r) for r in rows]
            if not matches:
                return {
                    "session_id": session_id,
                    "mode": sess["mode"],
                    "overall_grade": "—",
                    "overall_score": 0,
                    "summary": "No matches in this session yet.",
                    "players": [],
                    "session_tips": [],
                }

            # Personal baseline: last 20 matches before this session
            first_at = matches[0]["played_at"]
            baseline_rows = conn.execute(
                """
                SELECT m.*, md.shots, md.saves, md.assists, md.touches,
                       md.demos_given, md.demos_taken, md.boost_avg, md.boost_time_pct,
                       md.supersonic_time_pct, md.air_time_pct, md.wall_time_pct,
                       md.fastest_goal_kph, md.avg_shot_power
                FROM matches m
                LEFT JOIN match_details md ON md.match_id = m.id
                WHERE m.played_at < ?
                ORDER BY m.played_at DESC LIMIT ?
                """,
                (first_at, WINDOW),
            ).fetchall()
            baseline = [dict(r) for r in baseline_rows]

            you = self._player_report(
                name=player_name or "You",
                role="you",
                matches=matches,
                baseline=baseline,
                use_user_fields=True,
            )

            players = [you]
            mode = (sess["mode"] or matches[0].get("mode") or "solo").lower()
            friend = sess["friend_name"] or matches[0].get("friend_name") or ""
            # teammate from details if present
            tname = friend
            for m in matches:
                if m.get("teammate_name"):
                    tname = m["teammate_name"]
                    break
            if mode == "duo" and tname:
                tm = self._player_report(
                    name=tname,
                    role="teammate",
                    matches=matches,
                    baseline=[],  # no historical teammate baseline
                    use_user_fields=False,
                )
                players.append(tm)

            overall_score = you["score"]
            overall_grade = you["grade"]
            summary = self._session_summary(you, matches, mode, tname if mode == "duo" else "")
            session_tips = self._session_level_tips(you, matches)

            return {
                "session_id": session_id,
                "mode": mode,
                "friend_name": tname if mode == "duo" else None,
                "overall_grade": overall_grade,
                "overall_score": overall_score,
                "summary": summary,
                "players": players,
                "session_tips": session_tips,
                "match_count": len(matches),
                "wins": sum(1 for m in matches if m.get("result") == "win"),
                "losses": sum(1 for m in matches if m.get("result") == "loss"),
            }
        finally:
            conn.close()

    def _avg(self, rows: List[dict], key: str) -> float:
        vals = []
        for r in rows:
            v = r.get(key)
            if v is None:
                continue
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                pass
        return sum(vals) / len(vals) if vals else 0.0

    def _player_report(
        self,
        name: str,
        role: str,
        matches: List[dict],
        baseline: List[dict],
        use_user_fields: bool,
    ) -> Dict[str, Any]:
        if use_user_fields:
            goals = self._avg(matches, "user_score")
            shots = self._avg(matches, "shots")
            saves = self._avg(matches, "saves")
            demos = self._avg(matches, "demos_given")
            demos_t = self._avg(matches, "demos_taken")
            boost = self._avg(matches, "boost_avg")
            boost_t = self._avg(matches, "boost_time_pct")
            air = self._avg(matches, "air_time_pct")
            wall = self._avg(matches, "wall_time_pct")
            super_ = self._avg(matches, "supersonic_time_pct")
            power = self._avg(matches, "avg_shot_power")
            b_goals = self._avg(baseline, "user_score") if baseline else goals
            b_shots = self._avg(baseline, "shots") if baseline else shots
            b_saves = self._avg(baseline, "saves") if baseline else saves
            b_demos = self._avg(baseline, "demos_given") if baseline else demos
            b_boost = self._avg(baseline, "boost_avg") if baseline else boost
            b_boost_t = self._avg(baseline, "boost_time_pct") if baseline else boost_t
            b_air = self._avg(baseline, "air_time_pct") if baseline else air
            b_wall = self._avg(baseline, "wall_time_pct") if baseline else wall
            limited = False
        else:
            # teammate fields
            goals = 0.0  # not tracked per teammate reliably
            shots = self._avg(matches, "teammate_shots")
            saves = self._avg(matches, "teammate_saves")
            demos = self._avg(matches, "teammate_demos")
            demos_t = 0.0
            boost = 0.0
            boost_t = 0.0
            air = 0.0
            wall = 0.0
            super_ = 0.0
            power = 0.0
            b_goals = b_shots = b_saves = b_demos = b_boost = b_boost_t = b_air = b_wall = 0.0
            limited = shots == 0 and saves == 0 and demos == 0

        wins = sum(1 for m in matches if m.get("result") == "win")
        total = len(matches)
        wr = (wins / total * 100) if total else 0

        # Category scores 0-100 (heuristic)
        # Scoring: goals/game + accuracy
        acc = min((goals / max(shots, 0.5)) * 100, 100) if use_user_fields else 50
        scoring = _clamp(35 + goals * 18 + acc * 0.25)
        if baseline and use_user_fields and b_goals > 0:
            scoring = _clamp(scoring * 0.7 + _clamp(50 + (goals / b_goals - 1) * 40) * 0.3)

        defense = _clamp(40 + saves * 14 - demos_t * 4)
        if baseline and use_user_fields and b_saves > 0:
            defense = _clamp(defense * 0.75 + _clamp(50 + (saves / max(b_saves, 0.1) - 1) * 35) * 0.25)

        boost_score = _clamp(boost * 0.9 + boost_t * 0.8) if use_user_fields else 50
        movement = _clamp(air * 1.1 + wall * 1.4 + super_ * 0.9) if use_user_fields else 50
        aggression = _clamp(40 + demos * 16 + (shots * 2))

        # Winrate influence on overall
        wr_score = _clamp(wr)

        weights = {
            "scoring": 0.25,
            "defense": 0.2,
            "boost": 0.15,
            "movement": 0.15,
            "aggression": 0.1,
            "results": 0.15,
        }
        overall = (
            scoring * weights["scoring"]
            + defense * weights["defense"]
            + boost_score * weights["boost"]
            + movement * weights["movement"]
            + aggression * weights["aggression"]
            + wr_score * weights["results"]
        )
        overall = round(_clamp(overall))

        cats = {
            "scoring": {
                "score": round(scoring),
                "trend": _trend(goals, b_goals) if use_user_fields else "flat",
                "note": f"{goals:.1f} goals/game · {acc:.0f}% shot accuracy"
                if use_user_fields
                else f"{shots:.1f} shots/game (limited teammate data)",
            },
            "defense": {
                "score": round(defense),
                "trend": _trend(saves, b_saves) if use_user_fields else "flat",
                "note": f"{saves:.1f} saves/game"
                + (f" · {demos_t:.1f} demos taken" if use_user_fields else ""),
            },
            "boost": {
                "score": round(boost_score),
                "trend": _trend(boost_t, b_boost_t) if use_user_fields else "flat",
                "note": f"Avg boost {boost:.0f}% · boosting {boost_t:.0f}% of time"
                if use_user_fields
                else "Boost data only available for you",
            },
            "movement": {
                "score": round(movement),
                "trend": _trend(air + wall, b_air + b_wall) if use_user_fields else "flat",
                "note": f"Air {air:.0f}% · Wall {wall:.0f}% · Super {super_:.0f}%"
                if use_user_fields
                else "Movement data only available for you",
            },
            "aggression": {
                "score": round(aggression),
                "trend": _trend(demos, b_demos) if use_user_fields else "flat",
                "note": f"{demos:.1f} demos/game · {shots:.1f} shots/game",
            },
        }

        tips = self._tips_for_player(cats, use_user_fields, goals, shots, saves, boost_t, air, wall, demos, wr)

        return {
            "role": role,
            "name": name,
            "grade": _grade(overall),
            "score": overall,
            "winrate": round(wr),
            "categories": cats,
            "tips": tips,
            "limited_data": limited,
        }

    def _tips_for_player(
        self, cats, is_you, goals, shots, saves, boost_t, air, wall, demos, wr
    ) -> List[dict]:
        tips = []
        if not is_you:
            if cats["aggression"]["score"] >= 75:
                tips.append(
                    {
                        "severity": "good",
                        "icon": "💥",
                        "text": "Teammate pressure looks solid — demos/shots are contributing.",
                    }
                )
            elif cats["aggression"]["score"] < 55:
                tips.append(
                    {
                        "severity": "info",
                        "icon": "🤝",
                        "text": "Teammate stats look quiet — call for boosts and challenge together.",
                    }
                )
            if not tips:
                tips.append(
                    {
                        "severity": "info",
                        "icon": "👥",
                        "text": "Limited teammate telemetry — coach focuses on your habits in duo.",
                    }
                )
            return tips[:4]

        # YOU tips — concrete, ranked
        if boost_t < 12 and cats["boost"]["trend"] == "down":
            tips.append(
                {
                    "severity": "warn",
                    "icon": "⛽",
                    "text": "Boost time is low vs your baseline — pad earlier and avoid dry challenges.",
                }
            )
        elif cats["boost"]["score"] >= 80:
            tips.append(
                {
                    "severity": "good",
                    "icon": "⛽",
                    "text": "Boost economy looks sharp — keep that pad route discipline.",
                }
            )

        if wall < 3 and air < 20:
            tips.append(
                {
                    "severity": "warn",
                    "icon": "🧱",
                    "text": "Very ground-heavy session — add wall reads and light aerials to open angles.",
                }
            )
        elif wall >= 8 or air >= 30:
            tips.append(
                {
                    "severity": "good",
                    "icon": "✈️",
                    "text": "Good vertical game (air/wall) — use it to fake and cut rotations.",
                }
            )

        acc = (goals / max(shots, 0.5)) * 100
        if shots >= 3 and acc < 25:
            tips.append(
                {
                    "severity": "warn",
                    "icon": "🎯",
                    "text": "Lots of shots, low conversion — wait for corners / pass plays instead of low % spam.",
                }
            )
        elif goals >= 1.5:
            tips.append(
                {
                    "severity": "good",
                    "icon": "⚽",
                    "text": "Scoring rate is healthy — keep finding those high-percentage touches.",
                }
            )

        if saves >= 2.5:
            tips.append(
                {
                    "severity": "good",
                    "icon": "🛡️",
                    "text": "Strong save volume — last-man positioning is carrying possessions.",
                }
            )
        elif saves < 0.4 and wr < 45:
            tips.append(
                {
                    "severity": "info",
                    "icon": "🛡️",
                    "text": "Few saves this session — shadow a bit deeper when teammate is committed.",
                }
            )

        if demos >= 2:
            tips.append(
                {
                    "severity": "good",
                    "icon": "💥",
                    "text": "Demo pressure is up — clear the goalie then rotate out fast.",
                }
            )
        elif demos < 0.3 and cats["aggression"]["score"] < 55:
            tips.append(
                {
                    "severity": "info",
                    "icon": "💥",
                    "text": "Low demo count — occasional bumps on kickoffs can free 50s.",
                }
            )

        if wr >= 60:
            tips.append(
                {
                    "severity": "good",
                    "icon": "🔥",
                    "text": "Winning session — bank the habits (boost + first touch) before queueing ranked.",
                }
            )
        elif wr < 40 and len(tips) < 3:
            tips.append(
                {
                    "severity": "warn",
                    "icon": "📉",
                    "text": "Rough W/L — slow the game: safe touches mid, force opponents to beat two layers.",
                }
            )

        # Ensure at least 2 tips
        if len(tips) < 2:
            tips.append(
                {
                    "severity": "info",
                    "icon": "🧠",
                    "text": "Track 5 more matches so Coach can compare tighter against your baseline.",
                }
            )
        return tips[:5]

    def _session_summary(self, you: dict, matches: list, mode: str, friend: str) -> str:
        wr = you.get("winrate", 0)
        g = you.get("grade", "—")
        n = len(matches)
        if wr >= 60:
            tone = "Strong session"
        elif wr >= 45:
            tone = "Mixed session"
        else:
            tone = "Tough session"
        duo = f" with {friend}" if mode == "duo" and friend else ""
        weak = min(you["categories"].items(), key=lambda kv: kv[1]["score"])[0]
        strong = max(you["categories"].items(), key=lambda kv: kv[1]["score"])[0]
        return (
            f"{tone}{duo} — grade {g} over {n} games. "
            f"Best: {strong}. Focus next: {weak}."
        )

    def _session_level_tips(self, you: dict, matches: list) -> List[dict]:
        tips = []
        ot = sum(1 for m in matches if m.get("overtime"))
        if ot >= 2:
            tips.append(
                {
                    "severity": "info",
                    "icon": "⏱️",
                    "text": f"{ot} overtimes — fatigue risk. Stretch, hydrate, keep first-man challenges clean.",
                }
            )
        # late tilt: last 3 all losses
        if len(matches) >= 3 and all(m.get("result") == "loss" for m in matches[-3:]):
            tips.append(
                {
                    "severity": "warn",
                    "icon": "🛑",
                    "text": "Last 3 were losses — consider a short break before another queue.",
                }
            )
        if you.get("categories", {}).get("boost", {}).get("trend") == "down":
            tips.append(
                {
                    "severity": "warn",
                    "icon": "⛽",
                    "text": "Boost trend down vs baseline across the session — pad starvation is compounding.",
                }
            )
        return tips[:3]

    # ------------------------------------------------------------------ #
    def _analyse(self, match, recent):
        insights = []

        def col(row, name, default=0):
            try:
                v = row[name] if row is not None else default
            except (KeyError, IndexError, TypeError):
                v = default
            return v if v is not None else default

        goals_val = col(match, "user_score")
        demos_val = col(match, "demos_given")
        saves_val = col(match, "saves")
        boost_t = col(match, "boost_time_pct")
        fastest_goal = col(match, "fastest_goal_kph")

        n = len(recent)
        if n == 0:
            if fastest_goal and fastest_goal > 0:
                insights.append(
                    self._insight(
                        TYPE_SPEED,
                        "🚀",
                        f"New speed record: {round(fastest_goal, 1)} km/h!",
                        "info",
                        round(fastest_goal, 1),
                    )
                )
            return insights, {"matches_compared": 0}

        avg_goals = sum(col(r, "user_score") for r in recent) / n
        avg_demos = sum(col(r, "demos_given") for r in recent) / n
        avg_saves = sum(col(r, "saves") for r in recent) / n
        avg_boost_t = sum(col(r, "boost_time_pct") for r in recent) / n

        baseline = {
            "matches_compared": n,
            "avg_goals": round(avg_goals, 2),
            "avg_demos": round(avg_demos, 2),
            "avg_saves": round(avg_saves, 2),
            "avg_boost_time_pct": round(avg_boost_t, 2),
        }

        if goals_val > avg_goals * 1.4 and goals_val > 0:
            insights.append(
                self._insight(
                    TYPE_GOALS,
                    "⚽",
                    f"{goals_val} goals (avg {avg_goals:.1f})",
                    "good" if goals_val >= avg_goals * 2 else "info",
                    goals_val,
                )
            )
        if demos_val >= 2 and demos_val > avg_demos * 1.5:
            insights.append(
                self._insight(
                    TYPE_DEMOS,
                    "💥",
                    f"{demos_val} demolishes!",
                    "good" if demos_val >= 4 else "info",
                    demos_val,
                )
            )
        if saves_val >= 3 and saves_val > avg_saves * 2:
            insights.append(
                self._insight(TYPE_SAVES, "🛡️", f"{saves_val} saves!", "good", saves_val)
            )
        if avg_boost_t > 0 and boost_t < avg_boost_t * 0.60:
            insights.append(
                self._insight(
                    TYPE_BOOST,
                    "⚠️",
                    f"Boost time dropped to {round(boost_t, 1)}% (avg {avg_boost_t:.1f}%)",
                    "warn",
                    round(boost_t, 1),
                )
            )
        if fastest_goal and fastest_goal > 0:
            prev_max = max((col(r, "fastest_goal_kph") for r in recent), default=0)
            if fastest_goal > prev_max:
                insights.append(
                    self._insight(
                        TYPE_SPEED,
                        "🚀",
                        f"New speed record: {round(fastest_goal, 1)} km/h!",
                        "good",
                        round(fastest_goal, 1),
                    )
                )
        return insights, baseline

    def _insight(self, type_, icon, text, severity, value):
        return {
            "type": type_,
            "icon": icon,
            "text": text,
            "severity": severity,
            "value": value,
        }
