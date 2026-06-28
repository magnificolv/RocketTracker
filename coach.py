"""
RL Tracker 2.0 - Active Coach Engine (TRIZ #25: Self-Service)
=============================================================
After each match, the tracker analyses itself against the last 20 matches
and surfaces anomalies (records, slumps, spikes) as 'insights'.

All thresholds are deliberately simple and explained in the message text -
the goal is a useful nudge, not a statistical model.
"""
import sqlite3
from datetime import datetime, timezone

# Number of past matches to compare against. Spec: "last 20 matches".
WINDOW = 20

# Insight types - emitted as {type, icon, text, severity, value}
TYPE_GOALS = "goals"
TYPE_DEMOS = "demos"
TYPE_SPEED = "speed_record"
TYPE_BOOST = "boost_warning"
TYPE_SAVES = "saves"


class CoachEngine:
    """Analyse a single match or session against historical baselines."""

    def __init__(self, db_path):
        self.db_path = db_path

    # ------------------------------------------------------------------ #
    # DB helpers
    # ------------------------------------------------------------------ #
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
        """Return the `limit` matches played strictly BEFORE the given match,
        ordered most-recent-first. Excludes the analysed match itself."""
        # Get played_at of the analysed match so we only compare against
        # the actual past (not the future).
        cur = conn.execute(
            "SELECT played_at FROM matches WHERE id=?", (before_match_id,)
        ).fetchone()
        if not cur:
            return []
        played_at = cur["played_at"]
        rows = conn.execute(
            "SELECT m.*, md.* "
            "FROM matches m "
            "LEFT JOIN match_details md ON md.match_id = m.id "
            "WHERE m.played_at < ? "
            "ORDER BY m.played_at DESC "
            "LIMIT ?",
            (played_at, limit),
        ).fetchall()
        return rows

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def analyze_match(self, match_id):
        """Compare one match vs the last 20. Returns:
            {match_id, insights: [...], baseline: {matches_compared, ...}}
        baseline echoes the averages so the dashboard can show context.
        """
        conn = self._conn()
        try:
            match = self._get_match(conn, match_id)
            if not match:
                return {"error": "Match not found", "insights": []}

            recent = self._recent_matches(conn, match_id, WINDOW)
            insights, baseline = self._analyse(match, recent)
            return {
                "match_id": match_id,
                "insights": insights,
                "baseline": baseline,
            }
        finally:
            conn.close()

    def get_session_anomalies(self, session_id):
        """All insights across every match in a session. Returns:
            {session_id, match_count, insights: [...]}
        Each insight carries match_id so the dashboard can link back.
        """
        conn = self._conn()
        try:
            sess = conn.execute(
                "SELECT * FROM sessions WHERE id=?", (session_id,)
            ).fetchone()
            if not sess:
                return {"error": "Session not found", "insights": []}

            matches = conn.execute(
                "SELECT id FROM matches WHERE session_id=? ORDER BY played_at ASC",
                (session_id,),
            ).fetchall()

            all_insights = []
            for m in matches:
                # Reuse the baseline computed for each match vs its own past.
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
        """All-time personal records across the entire DB."""
        conn = self._conn()
        try:
            md = conn.execute(
                """
                SELECT
                    MAX(demos_given) as most_demos,
                    MAX(saves)       as most_saves,
                    MAX(saves)       FILTER (WHERE saves IS NOT NULL) as most_saves_2,
                    MAX(shots)       as most_shots,
                    MAX(touches)     as most_touches,
                    MAX(assists)     as most_assists,
                    MAX(boost_avg)   as highest_boost_avg,
                    MAX(boost_time_pct) as highest_boost_time,
                    MAX(supersonic_time_pct) as highest_supersonic_time,
                    MAX(fastest_goal_kph) as fastest_goal_kph,
                    MAX(avg_shot_power)   as highest_avg_shot_power
                FROM match_details
                """
            ).fetchone()
            # Most goals in a single match = MAX(user_score) over matches
            goals_row = conn.execute(
                "SELECT MAX(user_score) as most_goals, "
                "COUNT(*) as total_matches, "
                "SUM(CASE WHEN result='win'  THEN 1 ELSE 0 END) as wins, "
                "SUM(CASE WHEN result='loss' THEN 1 ELSE 0 END) as losses "
                "FROM matches"
            ).fetchone()

            # Locate the match_id that set each record (so the dashboard can
            # link to "the match where this happened"). One query per record
            # is fine - get_all_records runs once per dashboard open.
            def _find_match(sql, params):
                r = conn.execute(sql, params).fetchone()
                return r["match_id"] if r else None

            most_goals_id = _find_match(
                "SELECT id as match_id FROM matches "
                "WHERE user_score = (SELECT MAX(user_score) FROM matches) "
                "ORDER BY played_at DESC LIMIT 1", (),
            ) if goals_row["most_goals"] else None

            most_demos_id = _find_match(
                "SELECT match_id FROM match_details "
                "WHERE demos_given = (SELECT MAX(demos_given) FROM match_details) "
                "ORDER BY match_id DESC LIMIT 1", (),
            )
            most_saves_id = _find_match(
                "SELECT match_id FROM match_details "
                "WHERE saves = (SELECT MAX(saves) FROM match_details) "
                "ORDER BY match_id DESC LIMIT 1", (),
            )
            fastest_goal_id = _find_match(
                "SELECT match_id FROM match_details "
                "WHERE fastest_goal_kph = (SELECT MAX(fastest_goal_kph) FROM match_details) "
                "ORDER BY match_id DESC LIMIT 1", (),
            )

            records = {
                "most_goals": {
                    "value": goals_row["most_goals"] or 0,
                    "match_id": most_goals_id,
                },
                "most_demos": {
                    "value": md["most_demos"] or 0,
                    "match_id": most_demos_id,
                },
                "most_saves": {
                    "value": md["most_saves"] or 0,
                    "match_id": most_saves_id,
                },
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
            return {"records": records}
        finally:
            conn.close()

    # ------------------------------------------------------------------ #
    # Core analysis
    # ------------------------------------------------------------------ #
    def _analyse(self, match, recent):
        """Return ([insight, ...], baseline_dict).

        Thresholds (per spec):
            goals      - value > 1.4x average AND value > avg
            demos      - value >= 2 AND value > 1.5x average
            speed      - new personal record (beats previous max)
            boost warn - value < 60% of average
            saves      - value >= 3 AND value > 2x average
        """
        insights = []

        # Pull per-match detail columns with safe fallbacks.
        def col(row, name, default=0):
            v = row[name] if row and name in row.keys() else default
            return v if v is not None else default

        goals_val = col(match, "user_score")
        demos_val = col(match, "demos_given")
        saves_val = col(match, "saves")
        boost_t = col(match, "boost_time_pct")
        fastest_goal = col(match, "fastest_goal_kph")

        n = len(recent)
        if n == 0:
            # No baseline yet - just emit the speed record if any.
            if fastest_goal and fastest_goal > 0:
                insights.append(self._insight(
                    TYPE_SPEED, "🚀",
                    f"New speed record: {round(fastest_goal,1)} km/h!",
                    "info", round(fastest_goal, 1)))
            return insights, {"matches_compared": 0}

        # Compute baselines from the recent window.
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

        # --- Goals spike -------------------------------------------------
        # Spec: "X goals (avg Y.Z)" - ja >1.4x vid.
        if goals_val > avg_goals * 1.4 and goals_val > 0:
            insights.append(self._insight(
                TYPE_GOALS, "⚽",
                f"{goals_val} goals (avg {avg_goals:.1f})",
                "good" if goals_val >= avg_goals * 2 else "info",
                goals_val))

        # --- Demolishes --------------------------------------------------
        # Spec: >=2 un >1.5x vid.
        if demos_val >= 2 and demos_val > avg_demos * 1.5:
            insights.append(self._insight(
                TYPE_DEMOS, "💥",
                f"{demos_val} demolishes!",
                "good" if demos_val >= 4 else "info", demos_val))

        # --- Saves hero --------------------------------------------------
        # Spec: >=3 un >2x vid.
        if saves_val >= 3 and saves_val > avg_saves * 2:
            insights.append(self._insight(
                TYPE_SAVES, "🛡️",
                f"{saves_val} saves!",
                "good", saves_val))

        # --- Boost warning ----------------------------------------------
        # Spec: <60% no videja. Compare to avg_boost_t (a percentage itself).
        if avg_boost_t > 0 and boost_t < avg_boost_t * 0.60:
            insights.append(self._insight(
                TYPE_BOOST, "⚠️",
                f"Boost time dropped to {round(boost_t,1)}% "
                f"(avg {avg_boost_t:.1f}%)",
                "warn", round(boost_t, 1)))

        # --- Speed record ------------------------------------------------
        # Spec: new record if it beats the previous max across all matches
        # before this one.
        if fastest_goal and fastest_goal > 0:
            prev_max = max(
                (col(r, "fastest_goal_kph") for r in recent), default=0
            )
            if fastest_goal > prev_max:
                insights.append(self._insight(
                    TYPE_SPEED, "🚀",
                    f"New speed record: {round(fastest_goal,1)} km/h!",
                    "good", round(fastest_goal, 1)))

        return insights, baseline

    # ------------------------------------------------------------------ #
    def _insight(self, type_, icon, text, severity, value):
        return {
            "type": type_,
            "icon": icon,
            "text": text,
            "severity": severity,  # good | info | warn
            "value": value,
        }
