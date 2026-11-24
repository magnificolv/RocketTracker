"""
RL Tracker 4.0 Overdrive — Active Coach Engine
===============================================
- Personal-stat match anomaly insights vs last 20 matches
- Coach 4.0 session reports with 5-axis Radar vs baseline & full Duo teammate
- Win vs Loss telemetry diff diagnostics
- Career Trophy Cabinet records with match_id, date, playlist & longest streak
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

WINDOW = 20

TYPE_GOALS = "goals"
TYPE_DEMOS = "demos"
TYPE_SPEED = "speed_record"
TYPE_BOOST = "boost_warning"
TYPE_SAVES = "saves"
TYPE_MVP = "mvp"


def _clamp(n: float, lo: float = 0, hi: float = 100) -> float:
    return max(lo, min(hi, n))


def _grade(score: float) -> str:
    s = float(score)
    if s >= 95:
        return "S"
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


def _effective_goals(row: Dict[str, Any]) -> float:
    pg = row.get("player_goals")
    if pg is not None:
        try:
            return float(pg)
        except (TypeError, ValueError):
            pass
    try:
        return float(row.get("user_score") or 0)
    except (TypeError, ValueError):
        return 0.0


class CoachEngine:
    """Analyse matches, Win-vs-Loss deltas, records, and Coach 4.0 session reports."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _get_match(self, conn: sqlite3.Connection, match_id: int):
        return conn.execute(
            "SELECT m.*, md.*, "
            "COALESCE(md.player_goals, m.user_score) as effective_goals, "
            "(SELECT COUNT(*) FROM goals g WHERE g.match_id=m.id) as goals_in_match "
            "FROM matches m "
            "LEFT JOIN match_details md ON md.match_id = m.id "
            "WHERE m.id=?",
            (match_id,),
        ).fetchone()

    def _recent_matches(self, conn: sqlite3.Connection, before_match_id: int, limit: int = WINDOW):
        cur = conn.execute("SELECT played_at FROM matches WHERE id=?", (before_match_id,)).fetchone()
        if not cur:
            return []
        played_at = cur["played_at"]
        return conn.execute(
            "SELECT m.*, md.*, COALESCE(md.player_goals, m.user_score) as effective_goals "
            "FROM matches m "
            "LEFT JOIN match_details md ON md.match_id = m.id "
            "WHERE m.played_at < ? ORDER BY m.played_at DESC LIMIT ?",
            (played_at, limit),
        ).fetchall()

    def analyze_match(self, match_id: int) -> Dict[str, Any]:
        conn = self._conn()
        try:
            match = self._get_match(conn, match_id)
            if not match:
                return {"error": "Match not found", "insights": []}
            recent = self._recent_matches(conn, match_id, WINDOW)
            insights, baseline = self._analyse(dict(match), [dict(r) for r in recent])
            return {"match_id": match_id, "insights": insights, "baseline": baseline}
        finally:
            conn.close()

    def get_session_anomalies(self, session_id: int) -> Dict[str, Any]:
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

    def get_all_records(self) -> Dict[str, Any]:
        conn = self._conn()
        try:
            totals = conn.execute(
                "SELECT COUNT(*) as total_matches, "
                "SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) as wins, "
                "SUM(CASE WHEN result='loss' THEN 1 ELSE 0 END) as losses "
                "FROM matches"
            ).fetchone()

            def _top_record(expr: str, where: str = "1=1", round_dp: Optional[int] = None) -> Dict[str, Any]:
                try:
                    r = conn.execute(
                        f"""SELECT ({expr}) as val, m.id as match_id, m.played_at, m.playlist
                            FROM matches m
                            LEFT JOIN match_details md ON md.match_id = m.id
                            WHERE {where} AND ({expr}) IS NOT NULL
                            ORDER BY val DESC, m.played_at DESC
                            LIMIT 1"""
                    ).fetchone()
                    if not r or r["val"] is None:
                        return {"value": 0, "match_id": None, "played_at": None, "playlist": None}
                    val = round(float(r["val"]), round_dp) if round_dp is not None else int(round(float(r["val"])))
                    return {
                        "value": val,
                        "match_id": r["match_id"],
                        "played_at": r["played_at"],
                        "playlist": r["playlist"] or "Unknown",
                    }
                except Exception:
                    return {"value": 0, "match_id": None, "played_at": None, "playlist": None}

            # Longest win streak across chronological matches
            streak_rows = conn.execute(
                "SELECT id, result, played_at, playlist FROM matches ORDER BY played_at ASC, id ASC"
            ).fetchall()
            best_streak = 0
            cur_streak = 0
            best_streak_row = None
            for sr in streak_rows:
                if sr["result"] == "win":
                    cur_streak += 1
                    if cur_streak >= best_streak:
                        best_streak = cur_streak
                        best_streak_row = sr
                else:
                    cur_streak = 0

            return {
                "records": {
                    "most_goals": _top_record("COALESCE(md.player_goals, m.user_score)"),
                    "highest_score": _top_record("COALESCE(md.player_score, 0)", "COALESCE(md.player_score, 0) > 0"),
                    "most_demos": _top_record("md.demos_given"),
                    "most_saves": _top_record("md.saves"),
                    "most_shots": _top_record("md.shots"),
                    "most_touches": _top_record("md.touches"),
                    "most_assists": _top_record("md.assists"),
                    "fastest_goal_kph": _top_record("md.fastest_goal_kph", "md.fastest_goal_kph > 0", round_dp=1),
                    "highest_boost_avg": _top_record("md.boost_avg", "md.boost_avg > 0", round_dp=1),
                    "highest_boost_time_pct": _top_record("md.boost_time_pct", "md.boost_time_pct > 0", round_dp=1),
                    "highest_supersonic_time_pct": _top_record("md.supersonic_time_pct", "md.supersonic_time_pct > 0", round_dp=1),
                    "highest_avg_shot_power": _top_record("md.avg_shot_power", "md.avg_shot_power > 0", round_dp=1),
                    "longest_win_streak": {
                        "value": best_streak,
                        "match_id": best_streak_row["id"] if best_streak_row else None,
                        "played_at": best_streak_row["played_at"] if best_streak_row else None,
                        "playlist": best_streak_row["playlist"] if best_streak_row else None,
                    },
                    "total_matches": totals["total_matches"] or 0,
                    "total_wins": totals["wins"] or 0,
                    "total_losses": totals["losses"] or 0,
                }
            }
        finally:
            conn.close()

    def win_vs_loss_diff(
        self,
        mode: str = "",
        playlist: str = "",
        days: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Compare average telemetry between Wins and Losses and emit concrete insights."""
        where = ["m.result IN ('win', 'loss')"]
        params: List[Any] = []
        mode_l = (mode or "").strip().lower()
        if mode_l in ("solo", "duo"):
            where.append("m.mode=?")
            params.append(mode_l)
        pl = (playlist or "").strip()
        if pl and pl.lower() not in ("all", "*"):
            where.append("COALESCE(m.playlist, md.playlist, 'Unknown')=?")
            params.append(pl)
        if days and days > 0:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=int(days))).isoformat()
            where.append("m.played_at >= ?")
            params.append(cutoff)

        wh = " WHERE " + " AND ".join(where)
        conn = self._conn()
        try:
            rows = conn.execute(
                f"""
                SELECT m.result,
                       COUNT(*) as n,
                       ROUND(AVG(COALESCE(md.player_goals, m.user_score)), 2) as player_goals,
                       ROUND(AVG(m.opponent_score), 2) as opponent_score,
                       ROUND(AVG(md.shots), 2) as shots,
                       ROUND(AVG(md.saves), 2) as saves,
                       ROUND(AVG(md.assists), 2) as assists,
                       ROUND(AVG(md.demos_given), 2) as demos_given,
                       ROUND(AVG(md.demos_taken), 2) as demos_taken,
                       ROUND(AVG(md.boost_avg), 1) as boost_avg,
                       ROUND(AVG(md.boost_time_pct), 1) as boost_time_pct,
                       ROUND(AVG(md.supersonic_time_pct), 1) as supersonic_time_pct,
                       ROUND(AVG(md.air_time_pct), 1) as air_time_pct,
                       ROUND(AVG(md.wall_time_pct), 1) as wall_time_pct,
                       ROUND(SUM(COALESCE(md.player_goals, m.user_score)) * 100.0 / NULLIF(SUM(md.shots), 0), 1) as shot_accuracy
                FROM matches m
                LEFT JOIN match_details md ON md.match_id = m.id
                {wh}
                GROUP BY m.result
                """,
                params,
            ).fetchall()
        finally:
            conn.close()

        by_res = {r["result"]: dict(r) for r in rows}
        w = by_res.get("win", {})
        l = by_res.get("loss", {})
        w_n = int(w.get("n") or 0)
        l_n = int(l.get("n") or 0)

        spec = [
            ("player_goals", "Personal Goals / Match", ""),
            ("opponent_score", "Goals Conceded / Match", ""),
            ("shot_accuracy", "Shot Conversion", "%"),
            ("shots", "Shots / Match", ""),
            ("saves", "Saves / Match", ""),
            ("boost_avg", "Average Boost", "%"),
            ("boost_time_pct", "Time Boosting", "%"),
            ("supersonic_time_pct", "Supersonic Time", "%"),
            ("air_time_pct", "Air Time", "%"),
            ("wall_time_pct", "Wall Time", "%"),
            ("demos_given", "Demos Given", ""),
            ("demos_taken", "Demos Taken", ""),
        ]

        metrics = []
        for key, label, unit in spec:
            wv = float(w.get(key) or 0.0)
            lv = float(l.get(key) or 0.0)
            if key == "shot_accuracy":
                wv = min(wv, 100.0)
                lv = min(lv, 100.0)
            metrics.append(
                {
                    "key": key,
                    "label": label,
                    "unit": unit,
                    "win": round(wv, 1),
                    "loss": round(lv, 1),
                    "delta": round(wv - lv, 1),
                }
            )

        insights: List[Dict[str, str]] = []
        if w_n >= 1 and l_n >= 1:
            m_map = {m["key"]: m for m in metrics}
            if m_map["boost_avg"]["win"] - m_map["boost_avg"]["loss"] >= 3.0:
                insights.append(
                    {
                        "severity": "good",
                        "text": f"In Wins you hold {m_map['boost_avg']['win']}% avg boost vs {m_map['boost_avg']['loss']}% in Losses — boost discipline pays off.",
                    }
                )
            elif m_map["boost_avg"]["loss"] - m_map["boost_avg"]["win"] >= 3.0:
                insights.append(
                    {
                        "severity": "info",
                        "text": f"You hold more reserve boost in Losses ({m_map['boost_avg']['loss']}%) than Wins ({m_map['boost_avg']['win']}%) — challenge sooner instead of hoarding.",
                    }
                )

            if m_map["opponent_score"]["loss"] - m_map["opponent_score"]["win"] >= 1.5:
                insights.append(
                    {
                        "severity": "warn",
                        "text": f"Conceding {m_map['opponent_score']['loss']} goals/loss vs {m_map['opponent_score']['win']} goals/win — prioritize back-post rotation when behind.",
                    }
                )

            if m_map["shot_accuracy"]["win"] - m_map["shot_accuracy"]["loss"] >= 8.0:
                insights.append(
                    {
                        "severity": "good",
                        "text": f"Shooting accuracy jumps from {m_map['shot_accuracy']['loss']}% in Losses to {m_map['shot_accuracy']['win']}% in Wins — quality shots win games.",
                    }
                )

            if m_map["supersonic_time_pct"]["win"] - m_map["supersonic_time_pct"]["loss"] >= 2.0:
                insights.append(
                    {
                        "severity": "good",
                        "text": f"Faster recovery in Wins ({m_map['supersonic_time_pct']['win']}% supersonic vs {m_map['supersonic_time_pct']['loss']}% in Losses).",
                    }
                )

            if m_map["demos_taken"]["loss"] - m_map["demos_taken"]["win"] >= 0.5:
                insights.append(
                    {
                        "severity": "warn",
                        "text": f"Demoed more in Losses ({m_map['demos_taken']['loss']}/game vs {m_map['demos_taken']['win']}/game) — check peripheral awareness on rotation.",
                    }
                )

        if not insights:
            if w_n == 0 or l_n == 0:
                insights.append(
                    {
                        "severity": "info",
                        "text": "Play both wins and losses under this filter to unlock Win-vs-Loss telemetry comparisons.",
                    }
                )
            else:
                insights.append(
                    {
                        "severity": "info",
                        "text": "Win and Loss telemetry profiles are closely balanced — focus on reducing opponent counter-attacks.",
                    }
                )

        return {
            "wins_count": w_n,
            "losses_count": l_n,
            "metrics": metrics,
            "insights": insights[:4],
        }

    # ------------------------------------------------------------------ #
    # Coach 4.0 Session Report
    # ------------------------------------------------------------------ #
    def session_report(self, session_id: int, player_name: str = "You") -> Dict[str, Any]:
        conn = self._conn()
        try:
            sess = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
            if not sess:
                return {"error": "Session not found"}

            rows = conn.execute(
                """
                SELECT m.*,
                       md.shots, md.saves, md.assists, md.touches, md.car_touches,
                       md.demos_given, md.demos_taken, md.boost_avg, md.boost_time_pct,
                       md.supersonic_time_pct, md.air_time_pct, md.ground_time_pct,
                       md.wall_time_pct, md.powerslide_time_pct, md.fastest_goal_kph,
                       md.avg_shot_power, md.overtime, md.arena, md.playlist as md_playlist,
                       md.boost_pads, md.boost_pills, md.crossbar_hits, md.forfeit,
                       md.player_goals, md.player_score, md.is_mvp,
                       md.teammate_name, md.teammate_shots, md.teammate_saves,
                       md.teammate_assists, md.teammate_touches, md.teammate_demos,
                       md.teammate_goals, md.teammate_score, md.teammate_boost_avg,
                       md.teammate_air_pct, md.teammate_wall_pct, md.teammate_supersonic_pct,
                       COALESCE(md.player_goals, m.user_score) as effective_goals
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
                    "radar": {
                        "labels": ["Scoring", "Defense", "Boost", "Mechanics", "Pressure"],
                        "session": [0, 0, 0, 0, 0],
                        "baseline": [0, 0, 0, 0, 0],
                    },
                }

            first_at = matches[0]["played_at"]
            baseline_rows = conn.execute(
                """
                SELECT m.*, md.shots, md.saves, md.assists, md.touches,
                       md.demos_given, md.demos_taken, md.boost_avg, md.boost_time_pct,
                       md.supersonic_time_pct, md.air_time_pct, md.wall_time_pct,
                       md.powerslide_time_pct, md.fastest_goal_kph, md.avg_shot_power,
                       md.player_goals, COALESCE(md.player_goals, m.user_score) as effective_goals
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

            # Compute pure baseline category scores for the 5-axis radar overlay
            if baseline:
                base_rep = self._player_report(
                    name="Baseline",
                    role="baseline",
                    matches=baseline,
                    baseline=[],
                    use_user_fields=True,
                )
                base_cats = base_rep["categories"]
            else:
                base_cats = you["categories"]

            radar = {
                "labels": ["Scoring", "Defense", "Boost", "Mechanics", "Pressure"],
                "session": [
                    you["categories"]["scoring"]["score"],
                    you["categories"]["defense"]["score"],
                    you["categories"]["boost"]["score"],
                    you["categories"]["movement"]["score"],
                    you["categories"]["aggression"]["score"],
                ],
                "baseline": [
                    base_cats["scoring"]["score"],
                    base_cats["defense"]["score"],
                    base_cats["boost"]["score"],
                    base_cats["movement"]["score"],
                    base_cats["aggression"]["score"],
                ],
            }

            players = [you]
            mode = (sess["mode"] or matches[0].get("mode") or "solo").lower()
            friend = sess["friend_name"] or matches[0].get("friend_name") or ""
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
                    baseline=[],
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
                "radar": radar,
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
            goals = self._avg(matches, "effective_goals")
            shots = self._avg(matches, "shots")
            saves = self._avg(matches, "saves")
            assists = self._avg(matches, "assists")
            demos = self._avg(matches, "demos_given")
            demos_t = self._avg(matches, "demos_taken")
            boost = self._avg(matches, "boost_avg")
            boost_t = self._avg(matches, "boost_time_pct")
            air = self._avg(matches, "air_time_pct")
            wall = self._avg(matches, "wall_time_pct")
            super_ = self._avg(matches, "supersonic_time_pct")
            powerslide = self._avg(matches, "powerslide_time_pct")
            pads = self._avg(matches, "boost_pads")
            pills = self._avg(matches, "boost_pills")

            b_goals = self._avg(baseline, "effective_goals") if baseline else goals
            b_saves = self._avg(baseline, "saves") if baseline else saves
            b_demos = self._avg(baseline, "demos_given") if baseline else demos
            b_boost_t = self._avg(baseline, "boost_time_pct") if baseline else boost_t
            b_air = self._avg(baseline, "air_time_pct") if baseline else air
            b_wall = self._avg(baseline, "wall_time_pct") if baseline else wall
            limited = False
        else:
            # Duo teammate — full v4 telemetry when available, graceful fallback on v3 rows
            goals = self._avg(matches, "teammate_goals")
            shots = self._avg(matches, "teammate_shots")
            saves = self._avg(matches, "teammate_saves")
            assists = self._avg(matches, "teammate_assists")
            demos = self._avg(matches, "teammate_demos")
            demos_t = 0.0
            boost = self._avg(matches, "teammate_boost_avg")
            boost_t = 0.0
            air = self._avg(matches, "teammate_air_pct")
            wall = self._avg(matches, "teammate_wall_pct")
            super_ = self._avg(matches, "teammate_supersonic_pct")
            powerslide = 0.0
            pads = pills = 0.0
            b_goals = b_saves = b_demos = b_boost_t = b_air = b_wall = 0.0
            has_spec = boost > 0 or air > 0 or wall > 0 or super_ > 0
            limited = not has_spec

        wins = sum(1 for m in matches if m.get("result") == "win")
        total = len(matches)
        wr = (wins / total * 100) if total else 0.0

        acc = min((goals / max(shots, 0.5)) * 100, 100.0) if (use_user_fields or not limited) else 50.0
        scoring = _clamp(35 + goals * 18 + acc * 0.25 + assists * 6)
        if baseline and use_user_fields and b_goals > 0:
            scoring = _clamp(scoring * 0.7 + _clamp(50 + (goals / b_goals - 1) * 40) * 0.3)

        defense = _clamp(42 + saves * 14 - demos_t * 4)
        if baseline and use_user_fields and b_saves > 0:
            defense = _clamp(defense * 0.75 + _clamp(50 + (saves / max(b_saves, 0.1) - 1) * 35) * 0.25)

        if use_user_fields:
            boost_score = _clamp(28 + boost * 0.9 + boost_t * 1.1)
            movement = _clamp(24 + air * 1.1 + wall * 1.4 + super_ * 1.1 + powerslide * 1.2)
        elif not limited:
            boost_score = _clamp(28 + boost * 1.25)
            movement = _clamp(24 + air * 1.15 + wall * 1.4 + super_ * 1.1)
        else:
            boost_score = 50.0
            movement = 50.0

        aggression = _clamp(40 + demos * 16 + shots * 2.5)
        wr_score = _clamp(wr)

        weights = {
            "scoring": 0.25,
            "defense": 0.20,
            "boost": 0.15,
            "movement": 0.15,
            "aggression": 0.10,
            "results": 0.15,
        }
        overall = round(
            _clamp(
                scoring * weights["scoring"]
                + defense * weights["defense"]
                + boost_score * weights["boost"]
                + movement * weights["movement"]
                + aggression * weights["aggression"]
                + wr_score * weights["results"]
            )
        )

        cats = {
            "scoring": {
                "score": round(scoring),
                "trend": _trend(goals, b_goals) if use_user_fields else "flat",
                "note": f"{goals:.1f} goals/g · {assists:.1f} ast · {acc:.0f}% acc"
                if (use_user_fields or not limited)
                else f"{shots:.1f} shots/g (legacy match)",
            },
            "defense": {
                "score": round(defense),
                "trend": _trend(saves, b_saves) if use_user_fields else "flat",
                "note": f"{saves:.1f} saves/g" + (f" · {demos_t:.1f} demoed" if use_user_fields else ""),
            },
            "boost": {
                "score": round(boost_score),
                "trend": _trend(boost_t, b_boost_t) if use_user_fields else "flat",
                "note": f"Avg {boost:.0f}% · {boost_t:.0f}% active"
                if use_user_fields
                else (f"Avg boost {boost:.0f}%" if not limited else "Boost telemetry unavailable"),
            },
            "movement": {
                "score": round(movement),
                "trend": _trend(air + wall, b_air + b_wall) if use_user_fields else "flat",
                "note": f"Air {air:.0f}% · Wall {wall:.0f}% · Super {super_:.0f}%"
                if (use_user_fields or not limited)
                else "Movement telemetry unavailable",
            },
            "aggression": {
                "score": round(aggression),
                "trend": _trend(demos, b_demos) if use_user_fields else "flat",
                "note": f"{demos:.1f} demos/g · {shots:.1f} shots/g",
            },
        }

        tips = self._tips_for_player(
            cats,
            use_user_fields,
            goals,
            shots,
            saves,
            boost_t,
            air,
            wall,
            demos,
            demos_t,
            super_,
            powerslide,
            pads,
            pills,
            wr,
            limited,
        )

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
        self,
        cats,
        is_you,
        goals,
        shots,
        saves,
        boost_t,
        air,
        wall,
        demos,
        demos_t,
        super_,
        powerslide,
        pads,
        pills,
        wr,
        limited,
    ) -> List[dict]:
        tips: List[dict] = []
        if not is_you:
            if cats["scoring"]["score"] >= 75:
                tips.append({"severity": "good", "icon": "⚽", "text": f"Teammate finishing strong ({goals:.1f} goals/game) — feed mid passes."})
            if cats["defense"]["score"] >= 75:
                tips.append({"severity": "good", "icon": "🛡️", "text": f"Teammate anchoring defense ({saves:.1f} saves/game) — safe to pressure 1st man."})
            elif cats["aggression"]["score"] < 55:
                tips.append({"severity": "info", "icon": "🤝", "text": "Teammate play looks passive — communicate challenges and boost steals."})
            if not tips:
                tips.append({"severity": "info", "icon": "👥", "text": "Duo synergy balanced — stagger rotations to avoid double-commits." if not limited else "Legacy match lacks teammate telemetry."})
            return tips[:4]

        if boost_t < 12 and cats["boost"]["trend"] == "down":
            tips.append({"severity": "warn", "icon": "⛽", "text": "Boost time dropped vs baseline — route small pads through mid instead of chasing corners."})
        elif pills > 0 and pads > 0 and pads < pills * 1.5:
            tips.append({"severity": "info", "icon": "⛽", "text": f"Heavy big-pill reliance ({pills:.0f} pills vs {pads:.0f} small pads/g) — weave small pads to stay in play."})
        elif cats["boost"]["score"] >= 80:
            tips.append({"severity": "good", "icon": "⛽", "text": "Boost economy is sharp — pad routing keeps momentum alive."})

        if super_ >= 16 and powerslide >= 2.5:
            tips.append({"severity": "good", "icon": "⚡", "text": f"High tempo mechanics ({super_:.0f}% supersonic, {powerslide:.1f}% powerslide recoveries)."})
        elif wall < 3 and air < 20:
            tips.append({"severity": "warn", "icon": "🧱", "text": "Ground-heavy session — add backboard/wall clears and fast aerial challenges."})
        elif wall >= 8 or air >= 30:
            tips.append({"severity": "good", "icon": "✈️", "text": "Strong aerial/wall presence — mix in low fakes to punish pre-jumpers."})

        acc = (goals / max(shots, 0.5)) * 100
        if shots >= 3 and acc < 24:
            tips.append({"severity": "warn", "icon": "🎯", "text": f"Conversion at {acc:.0f}% across {shots:.1f} shots/g — look for infield passes or bounce shots."})
        elif goals >= 1.5:
            tips.append({"severity": "good", "icon": "⚽", "text": f"Clinical finishing ({goals:.1f} personal goals/game) — keep taking high-% touches."})

        if saves >= 2.2:
            tips.append({"severity": "good", "icon": "🛡️", "text": f"Brick wall in net ({saves:.1f} saves/game) — strong last-man shadow defense."})
        elif saves < 0.5 and wr < 48:
            tips.append({"severity": "info", "icon": "🛡️", "text": "Low save volume — rotate back-post earlier when teammate is 1st man."})

        if demos - demos_t >= 1.5:
            tips.append({"severity": "good", "icon": "💥", "text": f"Physical edge (+{demos - demos_t:.1f} demo diff/g) — disruptions are opening empty nets."})
        elif demos_t >= 1.5 and demos_t > demos:
            tips.append({"severity": "warn", "icon": "💥", "text": f"Getting demoed {demos_t:.1f}/g — use quick camera checks on goal-line rotations."})

        if wr >= 60:
            tips.append({"severity": "good", "icon": "🔥", "text": "Hot winrate — lock in this pace and positioning."})
        elif wr < 40 and len(tips) < 3:
            tips.append({"severity": "warn", "icon": "📉", "text": "Tough W/L stretch — slow 50/50s and force opponents to beat two defenders."})

        if len(tips) < 2:
            tips.append({"severity": "info", "icon": "🧠", "text": "Keep grinding competitive games so Coach calibrates tighter personal baselines."})
        return tips[:5]

    def _session_summary(self, you: dict, matches: list, mode: str, friend: str) -> str:
        wr = you.get("winrate", 0)
        g = you.get("grade", "—")
        n = len(matches)
        if wr >= 60:
            tone = "Dominant session"
        elif wr >= 45:
            tone = "Competitive session"
        else:
            tone = "Gritty session"
        duo = f" w/ {friend}" if mode == "duo" and friend else ""
        weak = min(you["categories"].items(), key=lambda kv: kv[1]["score"])[0]
        strong = max(you["categories"].items(), key=lambda kv: kv[1]["score"])[0]
        gword = "game" if n == 1 else "games"
        return f"{tone}{duo} — Grade {g} ({n} {gword}). Peak: {strong}. Next focus: {weak}."

    def _session_level_tips(self, you: dict, matches: list) -> List[dict]:
        tips = []
        ot = sum(1 for m in matches if m.get("overtime"))
        if ot >= 2:
            tips.append({"severity": "info", "icon": "⏱️", "text": f"{ot} overtimes this session — stay patient on kickoff and zero-second clears."})
        if len(matches) >= 3 and all(m.get("result") == "loss" for m in matches[-3:]):
            tips.append({"severity": "warn", "icon": "🛑", "text": "3-loss skid at session end — take a 5-minute reset in Freeplay before re-queueing."})
        if you.get("categories", {}).get("boost", {}).get("trend") == "down":
            tips.append({"severity": "warn", "icon": "⛽", "text": "Boost usage dipped below your 20-game baseline — watch out for starved rotations."})
        return tips[:3]

    def _analyse(self, match: dict, recent: List[dict]):
        insights = []

        def col(row, name, default=0):
            try:
                v = row[name] if row is not None else default
            except (KeyError, IndexError, TypeError):
                v = default
            return v if v is not None else default

        goals_val = _effective_goals(match)
        demos_val = col(match, "demos_given")
        saves_val = col(match, "saves")
        boost_t = col(match, "boost_time_pct")
        fastest_goal = col(match, "fastest_goal_kph")
        is_mvp = bool(col(match, "is_mvp"))

        if is_mvp:
            insights.append(self._insight(TYPE_MVP, "👑", "Match MVP!", "good", 1))

        n = len(recent)
        if n == 0:
            if fastest_goal and fastest_goal > 0:
                insights.append(self._insight(TYPE_SPEED, "🚀", f"Top goal speed: {round(fastest_goal, 1)} km/h!", "info", round(fastest_goal, 1)))
            return insights, {"matches_compared": 0}

        avg_goals = sum(_effective_goals(r) for r in recent) / n
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

        if goals_val > avg_goals * 1.4 and goals_val >= 2:
            insights.append(self._insight(TYPE_GOALS, "⚽", f"{int(goals_val)} personal goals (avg {avg_goals:.1f})", "good" if goals_val >= avg_goals * 2 else "info", goals_val))
        if demos_val >= 2 and demos_val > avg_demos * 1.5:
            insights.append(self._insight(TYPE_DEMOS, "💥", f"{int(demos_val)} demolitions!", "good" if demos_val >= 4 else "info", demos_val))
        if saves_val >= 3 and saves_val > avg_saves * 2:
            insights.append(self._insight(TYPE_SAVES, "🛡️", f"{int(saves_val)} clutch saves!", "good", saves_val))
        if avg_boost_t > 0 and boost_t < avg_boost_t * 0.60:
            insights.append(self._insight(TYPE_BOOST, "⚠️", f"Boost time dropped to {round(boost_t, 1)}% (avg {avg_boost_t:.1f}%)", "warn", round(boost_t, 1)))
        if fastest_goal and fastest_goal > 0:
            prev_max = max((col(r, "fastest_goal_kph") for r in recent), default=0)
            if fastest_goal > prev_max:
                insights.append(self._insight(TYPE_SPEED, "🚀", f"New personal speed record: {round(fastest_goal, 1)} km/h!", "good", round(fastest_goal, 1)))
        return insights, baseline

    def _insight(self, type_, icon, text, severity, value):
        return {
            "type": type_,
            "icon": icon,
            "text": text,
            "severity": severity,
            "value": value,
        }
