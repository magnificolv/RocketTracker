"""Comprehensive automated tests for RocketTracker v4.0.0 Overdrive."""

import io
import json
import os
import shutil
import sqlite3
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app as app_mod
import coach as coach_mod
import listener as listener_mod
import result_logic as rl
import session_card as card_mod
from version import APP_EDITION, APP_VERSION


def _setup_isolated_db(tmpdir: Path) -> Path:
    db_path = tmpdir / "test_tracker.db"
    cfg_path = tmpdir / "config.yaml"
    log_path = tmpdir / "listener.log"
    status_path = tmpdir / "listener_status.json"

    cfg_path.write_text(
        "app:\n  name: RL Tracker\n  port: 3010\nplayer:\n  name: MagnificoLV\n  friends:\n    - DuoPartner\n",
        encoding="utf-8",
    )

    listener_mod.DB_PATH = db_path
    listener_mod.CONFIG_PATH = cfg_path
    listener_mod.LOG_PATH = log_path
    listener_mod.STATUS_PATH = status_path
    listener_mod._coach = coach_mod.CoachEngine(str(db_path))

    app_mod.DB_PATH = db_path
    app_mod.CONFIG_PATH = cfg_path
    app_mod.LOG_PATH = log_path
    app_mod.coach = coach_mod.CoachEngine(str(db_path))

    app_mod.init_db()
    return db_path


def _tick_payload(
    guid="GUID-1",
    playlist_id=11,
    arena="Stadium_P",
    time_sec=250,
    overtime=False,
    replay=False,
    has_winner=False,
    winner="",
    teams=None,
    players=None,
):
    return {
        "MatchGuid": guid,
        "Game": {
            "PlaylistId": playlist_id,
            "Arena": arena,
            "TimeSeconds": time_sec,
            "bOvertime": overtime,
            "bReplay": replay,
            "bHasWinner": has_winner,
            "Winner": winner,
            "Teams": teams
            if teams is not None
            else [
                {"TeamNum": 0, "Name": "Blue", "Score": 0},
                {"TeamNum": 1, "Name": "Orange", "Score": 0},
            ],
        },
        "Players": players or [],
    }


def _player(
    name,
    team_num,
    *,
    spec=False,
    goals=0,
    score=100,
    shots=1,
    saves=0,
    assists=0,
    touches=5,
    demos=0,
    boost=50,
    speed=1500.0,
    b_boosting=False,
    b_ground=True,
    b_wall=False,
    b_super=False,
    b_powerslide=False,
    b_demolished=False,
    primary_id=None,
):
    d = {
        "Name": name,
        "TeamNum": team_num,
        "Goals": goals,
        "Score": score,
        "Shots": shots,
        "Saves": saves,
        "Assists": assists,
        "Touches": touches,
        "CarTouches": touches,
        "Demos": demos,
    }
    if primary_id:
        d["PrimaryId"] = primary_id
    if spec:
        d.update(
            {
                "bHasCar": True,
                "Boost": boost,
                "Speed": speed,
                "bBoosting": b_boosting,
                "bOnGround": b_ground,
                "bOnWall": b_wall,
                "bSupersonic": b_super,
                "bPowersliding": b_powerslide,
                "bDemolished": b_demolished,
            }
        )
    return d


class TestResultLogic(unittest.TestCase):
    def test_version_constants(self):
        self.assertEqual(APP_VERSION, "4.0.2")
        self.assertEqual(APP_EDITION, "Overdrive")

    def test_classify_match_competitive_vs_practice_vs_casual(self):
        for pid in (10, 11, 13, 27, 28, 29, 30, 34, 61):
            c = rl.classify_match(pid, "ABC123", max_opponents=1, is_spectator_or_replay=False)
            self.assertTrue(c["should_record"], f"Expected pid={pid} allowed")
            self.assertEqual(c["category"], "competitive")

        # Casual rejected under default competitive filter
        for pid in (0, 1, 2, 3, 4, 17, 18, 38):
            c = rl.classify_match(pid, "ABC123", max_opponents=2, is_spectator_or_replay=False)
            self.assertFalse(c["should_record"], f"Expected casual pid={pid} rejected")
            self.assertEqual(c["category"], "casual")

        # Casual allowed under all_online
        c_all = rl.classify_match(2, "ABC123", max_opponents=2, is_spectator_or_replay=False, tracking_cfg={"scope": "all_online"})
        self.assertTrue(c_all["should_record"])

        # Empty MatchGuid (Freeplay/Offline) ALWAYS rejected even under all_online
        c_fp = rl.classify_match(11, "", max_opponents=1, is_spectator_or_replay=False, tracking_cfg={"scope": "all_online"})
        self.assertFalse(c_fp["should_record"])
        self.assertEqual(c_fp["category"], "practice")

        # Zero opponents ALWAYS rejected
        c_zero = rl.classify_match(11, "ABC123", max_opponents=0, is_spectator_or_replay=False, tracking_cfg={"scope": "all_online"})
        self.assertFalse(c_zero["should_record"])

        # Spectator/replay ALWAYS rejected
        c_rep = rl.classify_match(11, "ABC123", max_opponents=2, is_spectator_or_replay=True, tracking_cfg={"scope": "all_online"})
        self.assertFalse(c_rep["should_record"])
        self.assertEqual(c_rep["category"], "replay")

        # Practice playlists ALWAYS rejected
        for pid in (7, 8, 9, 19, 20, 21, 24):
            c_pr = rl.classify_match(pid, "ABC123", max_opponents=1, is_spectator_or_replay=False, tracking_cfg={"scope": "all_online"})
            self.assertFalse(c_pr["should_record"])

    def test_decide_result_authority_and_edge_cases(self):
        # Unknown winner string must NEVER default to Orange
        res, ff = rl.decide_result(0, match_ended_winner=None, game_winner="WeirdClanName", scores=(2, 1), time_remaining=0)
        self.assertEqual(res, "win")
        self.assertFalse(ff)

        # OT counting up (> 5s) must NOT mark forfeit
        res, ff = rl.decide_result(0, match_ended_winner=0, game_winner="Blue", scores=(3, 2), is_overtime=True, time_remaining=145)
        self.assertEqual(res, "win")
        self.assertFalse(ff)

        # Early forfeit (clock > 5s, not OT)
        res, ff = rl.decide_result(0, match_ended_winner=1, game_winner="", scores=(0, 1), is_overtime=False, time_remaining=190)
        self.assertEqual(res, "loss")
        self.assertTrue(ff)

        # No contest (-1)
        res, ff = rl.decide_result(0, match_ended_winner=-1, scores=(0, 0), time_remaining=280)
        self.assertEqual(res, "no_contest")
        self.assertFalse(ff)

    def test_reconcile_scores_and_bogus_goals_and_arena(self):
        # Cumulative carry-over base subtracted -> delta 0-1 (own goal!)
        self.assertEqual(rl.reconcile_scores([1, 0], [1, 1], [1, 0]), (1, 1))
        self.assertTrue(rl.is_bogus_goal_scored({"GoalSpeed": 0, "GoalTime": 0, "Scorer": {"Name": "", "Shortcut": 0}}))
        self.assertFalse(rl.is_bogus_goal_scored({"GoalSpeed": 95.4, "GoalTime": 120.0, "Scorer": {"Name": "MagnificoLV", "Shortcut": 1}}))
        self.assertEqual(rl.arena_label("Stadium_P"), "DFH Stadium")
        self.assertEqual(rl.arena_label("cs_p"), "Champions Field")


class TestListenerAndEndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rl_v4_test_"))
        self.db_path = _setup_isolated_db(self.tmp)

    def tearDown(self):
        for p in self.tmp.rglob("*"):
            try:
                os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
            except Exception:
                pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_3_lock_ticks(self, st, guid="G-1", pid=11, friend=False, team0_base=0, team1_base=0):
        players = [
            _player("MagnificoLV", 0, spec=True, goals=1, score=450, shots=4, saves=2, assists=1, demos=2, boost=60, b_boosting=True, b_wall=True, b_super=True, b_powerslide=True, primary_id="Epic|111|0"),
            _player("DuoPartner" if friend else "RandomMate", 0, spec=True, goals=1, score=320, shots=2, saves=1, demos=1, boost=40),
            _player("OppOne", 1, spec=False, goals=1, score=280),
            _player("OppTwo", 1, spec=False, goals=0, score=150),
        ]
        teams = [
            {"TeamNum": 0, "Name": "Blue", "Score": team0_base},
            {"TeamNum": 1, "Name": "Orange", "Score": team1_base},
        ]
        for _ in range(4):
            st.handle_update_state(_tick_payload(guid=guid, playlist_id=pid, time_sec=240, teams=teams, players=players))
        return players

    def test_ranked_2v2_win_and_personal_goals_and_ot(self):
        st = listener_mod.MatchState("MagnificoLV", ["DuoPartner"])
        st.match_guid = "RANKED-OT-1"
        players = self._run_3_lock_ticks(st, guid="RANKED-OT-1", pid=11, friend=True)
        self.assertEqual(st.user_team_num, 0)
        self.assertEqual(st.mode, "duo")
        self.assertEqual(st.friend_name, "DuoPartner")

        # Simulate 2 team goals + 1 opponent goal + bogus replay duplicate
        st.handle_goal_scored({"Scorer": {"Name": "MagnificoLV", "TeamNum": 0}, "GoalSpeed": 102.4})
        st.handle_goal_scored({"Scorer": {"Name": "DuoPartner", "TeamNum": 0}, "Assister": {"Name": "MagnificoLV"}, "GoalSpeed": 88.0})
        st.handle_goal_scored({"Scorer": {"Name": "OppOne", "TeamNum": 1}, "GoalSpeed": 75.0})
        # Replay ghost ignored
        st.in_replay = True
        st.handle_goal_scored({"Scorer": {"Name": "MagnificoLV", "TeamNum": 0}, "GoalSpeed": 102.4})
        st.in_replay = False
        st.handle_goal_scored({"Scorer": {"Name": "", "Shortcut": 0}, "GoalSpeed": 0, "GoalTime": 0})

        # OT bHasWinner arrives first, then MatchEnded(0)
        st.is_overtime = True
        st.time_remaining = 95
        st.handle_update_state(_tick_payload(guid="RANKED-OT-1", playlist_id=11, time_sec=95, overtime=True, has_winner=True, winner="Team Blue", players=players))
        mid = st.finalize_match(match_ended_winner=0, source="MatchEnded")
        self.assertIsNotNone(mid)

        conn = listener_mod.get_db()
        m = dict(conn.execute("SELECT * FROM matches WHERE id=?", (mid,)).fetchone())
        md = dict(conn.execute("SELECT * FROM match_details WHERE match_id=?", (mid,)).fetchone())
        sm = dict(conn.execute("SELECT * FROM matches_summary WHERE match_id=?", (mid,)).fetchone())
        goals = conn.execute("SELECT * FROM goals WHERE match_id=?", (mid,)).fetchall()
        conn.close()

        self.assertEqual(m["result"], "win")
        self.assertEqual(m["user_score"], 2)
        self.assertEqual(m["opponent_score"], 1)
        self.assertEqual(m["playlist"], "Ranked 2v2")
        self.assertEqual(md["player_goals"], 1)  # Personal goals = 1, NOT team 2!
        self.assertEqual(md["is_mvp"], 1)
        self.assertEqual(md["overtime"], 1)
        self.assertEqual(md["forfeit"], 0)
        self.assertEqual(md["teammate_goals"], 1)
        self.assertEqual(md["teammate_boost_avg"], 40.0)
        self.assertEqual(sm["goals"], 1)
        self.assertEqual(len(goals), 3)

    def test_freeplay_casual_replay_nocontest_rejected(self):
        st = listener_mod.MatchState("MagnificoLV", [])

        # 1) Freeplay (empty guid, 0 opponents)
        st.match_guid = ""
        for _ in range(4):
            st.handle_update_state(_tick_payload(guid="", playlist_id=0, players=[_player("MagnificoLV", 0, spec=True)]))
        self.assertIsNone(st.finalize_match(match_ended_winner=0, source="MatchDestroyed"))

        # 2) Casual 2v2 rejected in competitive mode
        st._match_recorded = False
        self._run_3_lock_ticks(st, guid="CASUAL-1", pid=2)
        self.assertIsNone(st.finalize_match(match_ended_winner=0, source="MatchEnded"))

        # 3) Spectator / Replay (bHasCar on BOTH teams 0 and 1)
        st._match_recorded = False
        both_spec = [_player("P1", 0, spec=True), _player("P2", 1, spec=True)]
        for _ in range(listener_mod.SPECTATOR_CONFIRM_TICKS + 2):
            st.handle_update_state(_tick_payload(guid="REPLAY-1", playlist_id=11, players=both_spec))
        self.assertTrue(st.is_spectator_or_replay)
        self.assertIsNone(st.finalize_match(match_ended_winner=0, source="MatchEnded"))

        # 4) No contest (-1)
        st._match_recorded = False
        self._run_3_lock_ticks(st, guid="NC-1", pid=11)
        self.assertIsNone(st.finalize_match(match_ended_winner=-1, source="MatchEnded"))

        conn = listener_mod.get_db()
        cnt = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
        conn.close()
        self.assertEqual(cnt, 0)

    def test_own_goal_and_cumulative_score_baseline(self):
        st = listener_mod.MatchState("MagnificoLV", [])
        # RL sends stale cumulative 5-3 at start, then own goal makes it 5-4
        self._run_3_lock_ticks(st, guid="OG-1", pid=11, team0_base=5, team1_base=3)
        st.handle_update_state(_tick_payload(
            guid="OG-1", playlist_id=11, time_sec=10,
            teams=[{"TeamNum": 0, "Score": 5}, {"TeamNum": 1, "Score": 4}],
            players=[
                _player("MagnificoLV", 0, spec=True, goals=0),
                _player("OppOne", 1, spec=False, goals=0),
            ],
        ))
        mid = st.finalize_match(match_ended_winner=1, source="MatchEnded")
        conn = listener_mod.get_db()
        m = dict(conn.execute("SELECT * FROM matches WHERE id=?", (mid,)).fetchone())
        conn.close()
        self.assertEqual((m["user_score"], m["opponent_score"], m["result"]), (0, 1, "loss"))

    def test_goal_replay_telemetry_does_not_skip_ranked_match_and_no_phantom(self):
        """Regression (v4.0.2): real Ranked 3v3 5-2 WIN was skipped as 'replay' and re-appeared as 5-0 phantom."""
        st = listener_mod.MatchState("Magnificox", ["Deglisthedk", "InsulinLV._"], aliases=["MagnificoLV"])
        guid = "RANKED3-REAL"

        def roster(blue_goals, orange_goals, all_spec, blue_scorer_left=False):
            blue = [_player("HVK_Mat80", 0, spec=all_spec, goals=0)]
            if not blue_scorer_left:
                blue.append(_player("BlueScorer", 0, spec=all_spec, goals=blue_goals))
            blue.append(_player("BsM-HQZ", 0, spec=all_spec, goals=0))
            orange = [
                _player("MagnificoX", 1, spec=True, goals=3, score=543, shots=4, assists=1),
                _player("Insulin", 1, spec=True, goals=max(0, orange_goals - 3)),
                _player("Deglisthedk", 1, spec=True, goals=0),
            ]
            return blue + orange

        def teams(b, o):
            return [{"TeamNum": 0, "Name": "Blue", "Score": b}, {"TeamNum": 1, "Name": "Orange", "Score": o}]

        # Kickoff: only own (orange) team carries SPECTATOR fields -> lock Orange
        for _ in range(4):
            st.handle_update_state(_tick_payload(guid=guid, playlist_id=13, time_sec=300, teams=teams(0, 0), players=roster(0, 0, False)))
        self.assertEqual(st.user_team_num, 1)

        # Goal replays: RL sends telemetry for BOTH teams for many seconds -> must NOT flag spectator
        score_b, score_o = 0, 0
        for scorer_team in (1, 0, 1, 1, 0, 1, 1):
            if scorer_team == 1:
                score_o += 1
                st.handle_goal_scored({"Scorer": {"Name": "MagnificoX" if score_o <= 3 else "Insulin", "TeamNum": 1}, "GoalSpeed": 90.0 + score_o})
            else:
                score_b += 1
                st.handle_goal_scored({"Scorer": {"Name": "BlueScorer", "TeamNum": 0}, "GoalSpeed": 80.0 + score_b})
            for _ in range(listener_mod.SPECTATOR_CONFIRM_TICKS * 3):
                st.handle_update_state(_tick_payload(guid=guid, playlist_id=13, time_sec=200, replay=True, teams=teams(score_b, score_o), players=roster(score_b, score_o, True)))
            for _ in range(10):
                st.handle_update_state(_tick_payload(guid=guid, playlist_id=13, time_sec=150, teams=teams(score_b, score_o), players=roster(score_b, score_o, False)))
        self.assertFalse(st.is_spectator_or_replay)

        # Even live both-team telemetry while the user is on the pitch is never "spectating"
        for _ in range(listener_mod.SPECTATOR_CONFIRM_TICKS * 2):
            st.handle_update_state(_tick_payload(guid=guid, playlist_id=13, time_sec=20, teams=teams(score_b, score_o), players=roster(score_b, score_o, True)))
        self.assertFalse(st.is_spectator_or_replay)

        # Blue scorer leaves before the end; podium shows both teams' telemetry
        st.handle_update_state(_tick_payload(guid=guid, playlist_id=13, time_sec=0, has_winner=True, winner="Orange", teams=teams(2, 5), players=roster(2, 5, True, blue_scorer_left=True)))
        mid = st.finalize_match(match_ended_winner=1, source="MatchEnded")
        self.assertIsNotNone(mid)

        conn = listener_mod.get_db()
        m = dict(conn.execute("SELECT * FROM matches WHERE id=?", (mid,)).fetchone())
        conn.close()
        self.assertEqual((m["user_score"], m["opponent_score"], m["result"], m["playlist"]), (5, 2, "win", "Ranked 3v3"))

        # Trailing podium/scoreboard ticks of the SAME match must not start a phantom live match
        for _ in range(20):
            st.handle_update_state(_tick_payload(guid=guid, playlist_id=13, time_sec=0, replay=True, teams=teams(2, 5), players=roster(2, 5, True, blue_scorer_left=True)))
        self.assertIsNone(st.user_team_num)
        self.assertEqual(st.tick_count, 0)

    def test_skipped_match_trailing_ticks_do_not_create_phantom(self):
        st = listener_mod.MatchState("MagnificoLV", [])
        self._run_3_lock_ticks(st, guid="CASUAL-PH", pid=2)
        self.assertIsNone(st.finalize_match(match_ended_winner=0, source="MatchEnded"))
        players = [_player("MagnificoLV", 0, spec=True, goals=3), _player("OppOne", 1, spec=False, goals=0)]
        for _ in range(10):
            st.handle_update_state(_tick_payload(guid="CASUAL-PH", playlist_id=2, teams=[{"TeamNum": 0, "Score": 3}, {"TeamNum": 1, "Score": 0}], players=players))
        self.assertIsNone(st.user_team_num)
        self.assertEqual(st.tick_count, 0)
        # A NEW match guid starts tracking again
        for _ in range(4):
            st.handle_update_state(_tick_payload(guid="NEXT-1", playlist_id=11, players=players))
        self.assertEqual(st.user_team_num, 0)

    def test_alt_account_spectator_lock(self):
        st = listener_mod.MatchState("WrongConfigName", [])
        for _ in range(4):
            st.handle_update_state(_tick_payload(
                guid="ALT-1", playlist_id=10,
                players=[
                    _player("Magnificox", 1, spec=True, goals=3),
                    _player("Opponent", 0, spec=False, goals=1),
                ],
            ))
        self.assertEqual(st.user_team_num, 1)
        self.assertEqual(st.player_name, "magnificox")

    def test_ensure_tastatsapi_ini_repairs_broken_section_and_sets_readonly(self):
        cfg_dir = self.tmp / "RLConfig"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        ini_path = cfg_dir / "TAStatsAPI.ini"
        ini_path.write_text("[System]\nPacketSendRate=30\n", encoding="utf-8")
        os.chmod(ini_path, stat.S_IREAD)  # Already Read-Only broken file!
        orig_find = listener_mod.find_rl_config_dirs
        try:
            listener_mod.find_rl_config_dirs = lambda: [cfg_dir]
            self.assertTrue(listener_mod.ensure_tastatsapi_ini())
            txt = ini_path.read_text(encoding="utf-8")
            self.assertIn("[TAGame.MatchStatsExporter_TA]", txt)
            self.assertIn("Port=49123", txt)
            self.assertIn("WebPort=49124", txt)
            self.assertIn("PacketSendRate=30", txt)
            self.assertNotIn("[System]", txt)
            self.assertFalse(os.access(ini_path, os.W_OK))
        finally:
            listener_mod.find_rl_config_dirs = orig_find

    def test_steam_libraryfolders_vdf_and_acf_parsing(self):
        steam_root = self.tmp / "SteamRoot"
        lib_e = self.tmp / "DriveE" / "SteamLibrary"
        (steam_root / "steamapps").mkdir(parents=True, exist_ok=True)
        rl_common = lib_e / "steamapps" / "common" / "rocketleague"
        rl_common.mkdir(parents=True, exist_ok=True)
        escaped_e = str(lib_e).replace("\\", "\\\\")
        (steam_root / "steamapps" / "libraryfolders.vdf").write_text(
            f'"libraryfolders"\n{{\n\t"0"\n\t{{\n\t\t"path"\t\t"{escaped_e}"\n\t}}\n}}\n',
            encoding="utf-8",
        )
        (lib_e / "steamapps" / "appmanifest_252950.acf").write_text(
            '"AppState"\n{\n\t"appid"\t\t"252950"\n\t"installdir"\t\t"rocketleague"\n}\n',
            encoding="utf-8",
        )
        found = listener_mod._find_steam_rl_dirs(extra_steam_roots=[steam_root])
        self.assertIn(rl_common.resolve(), [p.resolve() for p in found])

    def test_ensure_default_statsapi_ini_replaces_zero_variants(self):
        rl_dir = self.tmp / "SteamRL"
        cfg = rl_dir / "TAGame" / "Config"
        cfg.mkdir(parents=True, exist_ok=True)
        ini = cfg / "DefaultStatsAPI.ini"
        ini.write_text(
            "[TAGame.MatchStatsExporter_TA]\nPort=49123\nWebPort=49124\nPacketSendRate = 0.0\n",
            encoding="utf-8",
        )
        orig = listener_mod.find_rl_install_dirs
        try:
            listener_mod.find_rl_install_dirs = lambda: [rl_dir]
            self.assertTrue(listener_mod.ensure_default_statsapi_ini())
            txt = ini.read_text(encoding="utf-8")
            self.assertIn("PacketSendRate = 30", txt)
            self.assertNotIn("0.0", txt)
        finally:
            listener_mod.find_rl_install_dirs = orig

    def test_parse_launch_log_steam_and_epic(self):
        cfg_dir = self.tmp / "MyGames" / "Rocket League" / "TAGame" / "Config"
        logs_dir = cfg_dir.parent / "Logs"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        logs_dir.mkdir(parents=True, exist_ok=True)
        (logs_dir / "Launch.log").write_text(
            "Init: Base directory: E:\\SteamLibrary\\steamapps\\common\\rocketleague\\Binaries\\Win64\\\n"
            "[0022.10] StatsAPI: PacketSendRate=(30.0000) Port=(49123) WebPort=(49124)\n",
            encoding="utf-8",
        )
        parsed = listener_mod._parse_launch_log([cfg_dir])
        self.assertEqual(parsed["last_launch_client"], "Steam")
        self.assertEqual(parsed["last_launch_base_dir"], r"E:\SteamLibrary\steamapps\common\rocketleague")
        self.assertEqual(parsed["last_launch_rate"], 30.0)
        self.assertEqual(parsed["last_launch_port"], 49123)

    def test_flask_api_and_maintenance_and_card(self):
        # Seed a competitive match + a legacy casual match
        st = listener_mod.MatchState("MagnificoLV", ["DuoPartner"])
        self._run_3_lock_ticks(st, guid="API-1", pid=11, friend=True)
        st.handle_goal_scored({"Scorer": {"Name": "MagnificoLV", "TeamNum": 0}, "GoalSpeed": 115.2})
        mid1 = st.finalize_match(match_ended_winner=0, source="MatchEnded")

        conn = app_mod.get_db()
        conn.execute(
            "INSERT INTO matches (session_id, played_at, user_score, opponent_score, result, mode, playlist, playlist_id) "
            "VALUES (1, '2026-08-01T12:00:00+00:00', 1, 2, 'loss', 'solo', 'Unknown', 2)"
        )
        conn.commit()
        conn.close()

        client = app_mod.app.test_client()
        self.assertEqual(client.get("/api/status").get_json()["version"], "4.0.2")
        self.assertIn("in_match", client.get("/api/live").get_json())

        # Analytics & Coach
        ana = client.get("/api/stats/analytics").get_json()
        self.assertIn("timeline", ana)
        self.assertIn("win_vs_loss", ana)
        rep = client.get("/api/coach/session/1/report").get_json()
        self.assertIn("radar", rep)
        self.assertEqual(len(rep["players"]), 2)

        # Match PATCH
        patch_r = client.patch(f"/api/matches/{mid1}", json={"tags": "CustomTag"}).get_json()
        self.assertTrue(patch_r["updated"])

        # Maintenance dry run + cleanup
        dry = client.post("/api/maintenance/cleanup-non-competitive", json={"dry_run": True}).get_json()
        self.assertEqual(dry["count"], 1)
        clean = client.post("/api/maintenance/cleanup-non-competitive", json={"dry_run": False}).get_json()
        self.assertEqual(clean["deleted_matches"], 1)

        # PNG session card
        card_resp = client.get("/api/sessions/1/card.png")
        self.assertEqual(card_resp.status_code, 200)
        im = Image.open(io.BytesIO(card_resp.data))
        self.assertEqual(im.size, (1200, 675))

        preview_dir = ROOT / "exports"
        preview_dir.mkdir(exist_ok=True)
        (preview_dir / "session-v4-preview.png").write_bytes(card_resp.data)

    def test_real_db_copy_migration(self):
        real_db = ROOT / "data-v2.db"
        if not real_db.exists():
            self.skipTest("No local data-v2.db")
        copy_db = self.tmp / "real_copy.db"
        shutil.copy2(real_db, copy_db)
        old_db = app_mod.DB_PATH
        try:
            app_mod.DB_PATH = copy_db
            app_mod.init_db()
            conn = sqlite3.connect(str(copy_db))
            cnt = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
            cols = {r[1] for r in conn.execute("PRAGMA table_info(match_details)").fetchall()}
            conn.close()
            self.assertGreaterEqual(cnt, 1)
            self.assertIn("players_json", cols)
            self.assertIn("player_goals", cols)
        finally:
            app_mod.DB_PATH = old_db


if __name__ == "__main__":
    unittest.main()
