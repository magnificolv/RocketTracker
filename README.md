# Rocket League Match Tracker v4.0.0 · Overdrive

<p align="center">
  <a href="https://github.com/magnificolv/RocketTracker/releases/latest"><img src="https://img.shields.io/github/v/release/magnificolv/RocketTracker?style=flat-square&label=version&color=00e5ff" alt="Version"></a>
  &nbsp;
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="License"></a>
  &nbsp;
  <a href="https://github.com/magnificolv/RocketTracker/stargazers"><img src="https://img.shields.io/github/stars/magnificolv/RocketTracker?style=flat-square&color=yellow" alt="Stars"></a>
  &nbsp;
  <a href="https://github.com/magnificolv/RocketTracker/releases"><img src="https://img.shields.io/github/downloads/magnificolv/RocketTracker/total?style=flat-square&color=orange&label=downloads" alt="Downloads"></a>
</p>

---

## What's New in v4.0.0 ("Overdrive")

A ground-up architectural and visual remake of Rocket League Match Tracker built on the official local Stats API (`127.0.0.1:49123`):

- **Competitive-Only Match Gate (by default):** Automatically ignores Freeplay, Custom Training, Exhibition, Offline Bots, Saved Replays, and Casual matches (optional filter toggle in Settings for All Online or Custom playlists).
- **Zero-Drift Win/Loss & Score Accuracy:**
  - Uses `MatchEnded.WinnerTeamNum` (`-1` No-Contest skips empty/cancelled lobbies), reconciled against `GoalScored` + match-start-baselined `Teams[].Score` + `Players[].Goals` (catches own-goals while eliminating pre-match carry-over).
  - Separates **personal goals** (`Players[].Goals`) from **team score** so 2v2/3v3 stats and Coach accuracy are truly yours.
  - Replay/pause telemetry gating (`bReplay` / `MatchPaused` / post-match podium ticks never dilute boost, air, wall, or supersonic %).
- **Live Match Telemetry HUD:** Real-time Blue vs Orange scoreboard, countdown/OT clock, boost gauge, car speed, and active `RECORDING` vs `IGNORED` status banner.
- **Full Match Inspector:** Expand any match for a full Blue vs Orange scoreboard table, goal timeline with scorer/assister/speed, Coach anomaly insights, plus Edit/Delete controls.
- **Analytics & Coach 4.0:** Rolling 10-game winrate trend SVG chart, surface movement split, winrates by Playlist & human-readable Arena, Win-vs-Loss telemetry diagnostic diff, 5-axis SVG Radar vs your 20-game baseline, Trophy Cabinet records, and full Duo teammate telemetry.
- **Overdrive Discord Share Card (`1200×675` PNG):** Redesigned Pillow renderer with custom pack icons (zero emoji boxes) and clean KPI layout.
- **Settings & DB Maintenance:** In-app `TAStatsAPI.ini` & `DefaultStatsAPI.ini` diagnostics + repair, live log viewer, SQLite backup download, and one-click non-competitive legacy match cleanup.

---

## Quick Start

1. **Download** the [latest ZIP](https://github.com/magnificolv/RocketTracker/releases/latest)
2. **Extract** to your Desktop — keep the `RL-Tracker\` folder together (`data-v2.db` and `config.yaml` live next to the `.exe`)
3. **Double-click** `RL-Tracker-v4.0.0.exe` — browser opens `http://localhost:3010`
4. **Enter your Rocket League nickname** in Settings → **Auto-Create / Repair INI** → restart Rocket League once → queue Competitive!

---

## Troubleshooting

- **Shows "RL not running" while Rocket League is open?**
  Open Settings → **RL API & Logs** → click **Auto-Create / Repair INI** (fixes missing `[TAGame.MatchStatsExporter_TA]` section or `PacketSendRate=0`), then restart Rocket League completely.
- **Using WSL2 / Docker Desktop?**
  WSL2 can hijack port `49123`. Quick fix: `wsl --shutdown`. Permanent fix: add `ignoredPorts=49123` under `[wsl2]` in `%USERPROFILE%\.wslconfig`.
- **Upgrading from v3.x?**
  Your existing `data-v2.db` and `config.yaml` migrate automatically with zero data loss. You can optionally clean old non-competitive/unknown matches from **Settings → DB & Updates → Cleanup Non-Competitive Legacy Matches**.

---

## Version History

| Version | Date | Highlights |
|---|---|---|
| **v4.0.0** | Nov 2026 | Overdrive complete overhaul: Competitive-only filter, Freeplay/Replay rejection, authoritative `MatchEnded` W/L + OT/forfeit fix, Live HUD, Full Scoreboard & Goal Timeline, SVG Radar & Trend Charts, Win-vs-Loss diagnostics, Duo telemetry, Overdrive UI & Discord Card |
| **v3.1.0** | Oct 12, 2026 | Fixed inverted W/L when `Winner` wasn't "Blue", ranked playlist IDs, accolades, replay goal filter |
| **v3.0.0** | Aug 3, 2026 | Starlight UI, PNG session cards, Coach 2.0, playlist filters |
