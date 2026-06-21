<div align="center">
  <img src="icon.png" width="120" alt="RocketTracker logo"><br>
  <h1>🚀 RocketTracker</h1>
  <p><strong>Auto-track every Rocket League match — no install, no Python, no WSL.</strong></p>
</div>

<p align="center">
  <a href="https://github.com/magnificolv/RocketTracker/releases/latest"><img src="https://img.shields.io/github/v/release/magnificolv/RocketTracker?style=flat-square&label=version&color=blue" alt="Version"></a>
  &nbsp;
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="License"></a>
  &nbsp;
  <a href="https://github.com/magnificolv/RocketTracker/stargazers"><img src="https://img.shields.io/github/stars/magnificolv/RocketTracker?style=flat-square&color=yellow" alt="Stars"></a>
  &nbsp;
  <a href="https://github.com/magnificolv/RocketTracker/releases"><img src="https://img.shields.io/github/downloads/magnificolv/RocketTracker/total?style=flat-square&color=orange&label=downloads" alt="Downloads"></a>
  &nbsp;
  <a href="https://github.com/magnificolv/RocketTracker/commits/main"><img src="https://img.shields.io/github/last-commit/magnificolv/RocketTracker?style=flat-square&label=last%20commit" alt="Last commit"></a>
</p>

---

<div align="center">

### 🎯 Track shots, boost, demos, assists & more — automatically, every match.

<br>

<a href="https://github.com/magnificolv/RocketTracker/releases/latest">
  <img src="https://img.shields.io/badge/⬇️%20DOWNLOAD-v1.0.5%20ZIP-brightgreen?style=for-the-badge&logo=windows&logoColor=white" alt="Download v1.0.5 ZIP" height="62">
</a>

<br><br>

<a href="https://github.com/magnificolv/RocketTracker/releases">
  <img src="https://img.shields.io/badge/All%20Releases-Releases-9cf?style=for-the-badge" alt="All Releases" height="32">
</a>

<br>

<sub>📦 Download · Extract to Desktop · Double-click the .exe · Play</sub>

</div>

---

## 📸 Screenshots

<table>
<tr>
  <td width="50%" align="center"><b>🎮 Active Session</b><br><sub>Live match scores & per-match deep stats</sub></td>
  <td width="50%" align="center"><b>📋 History</b><br><sub>Browse past sessions, click to expand</sub></td>
</tr>
<tr>
  <td><img src="screenshots/01-active-session.png" alt="Active Session"></td>
  <td><img src="screenshots/03-history-sessions.png" alt="History"></td>
</tr>
<tr>
  <td width="50%" align="center"><b>📊 Stats Overview</b><br><sub>All-time analytics with deep breakdowns</sub></td>
  <td width="50%" align="center"><b>🔍 Session Deep Stats</b><br><sub>Aggregate stats per completed session</sub></td>
</tr>
<tr>
  <td><img src="screenshots/02-stats-overview.png" alt="Stats Overview"></td>
  <td><img src="screenshots/04-session-deep-stats.png" alt="Session Deep Stats"></td>
</tr>
</table>

---

## ✨ Features

| Category | What it tracks |
|:--------:|----------------|
| 🎯 **Shot Power** | Fastest goal (km/h), avg shot power, shot accuracy %, total shots |
| ⛽ **Movement** | Avg boost %, time boosting %, supersonic %, air time % |
| 💥 **Combat** | Demos given, demos taken, saves, overtime matches |
| 🎮 **Ball Control** | Total touches, car touches, assists, your goals |
| 👥 **Duo Mode** | Auto-detects when your friend is on your team |
| 📋 **Sessions** | Auto-creates sessions, keeps full history |

---

## 🚀 Quick Start

1. **Download** → [**RL-Tracker-v1.0.5.zip**](https://github.com/magnificolv/RocketTracker/releases/latest) (~13 MB)
2. **Extract** → Right-click the ZIP → **Extract All…** → Choose your **Desktop**
3. **Launch** → Open `RL-Tracker\` → double-click `RL-Tracker-v1.0.5.exe`
4. **Play** → Enter your name in ⚙️ Settings → launch Rocket League → stats appear automatically 🎉

> 💡 **First time?** Click **Auto-Create** in Settings to set up the Stats API config. Restart RL once.
>
> 💡 **Keep the folder together.** All data (`data.db`, `config.yaml`, logs) stays **inside** `RL-Tracker\`. Don't drag the .exe out.

---

## 🛡️ Windows Defender (false positive)

The .exe is unsigned, so Defender may flag it. This is a **false positive** — here's how to bypass it:

| Problem | Fix |
|---------|-----|
| Chrome/Edge blocks download | Click `···` next to the warning → **Keep anyway** |
| Defender deleted the file | Windows Security → Protection history → **Restore** |
| Add a permanent exclusion | Windows Security → Exclusions → Add `C:\Users\%USERNAME%\Desktop\RL-Tracker` |

---

## 👥 For Friends

1. **Download** the [ZIP](https://github.com/magnificolv/RocketTracker/releases/latest) and **extract** it to your Desktop
2. **Double-click** `RL-Tracker-v1.0.5.exe` inside the `RL-Tracker\` folder, then enter YOUR Rocket League name in ⚙️ Settings
3. Click **Auto-Create**, restart Rocket League, and play! 🎉

> ⚠️ **Important:** Run the .exe **from inside the `RL-Tracker\` folder**. Moving it elsewhere scatters your data files.

> 🔍 **Tracker says "RL not running" but RL IS running?** Open ⚙️ Settings → click the **🔍 Diagnose** button. It checks your TAStatsAPI.ini, the port, and whether RL is running — then tells you exactly what to fix.

> 🐧 **Using WSL2 / Docker Desktop / Ubuntu on Windows?** WSL2's localhost forwarder (`wslrelay.exe`) can silently grab port 49123 and intercept the SYNs meant for Rocket League, producing a TIMEOUT error. **Quick fix:** open PowerShell and run `wsl --shutdown`, then restart Rocket League. **Permanent fix:** create or edit `%USERPROFILE%\.wslconfig` and add:
> ```ini
> [wsl2]
> ignoredPorts=49123
> ```
> Then run `wsl --shutdown` once. The Diagnose button (v1.0.7+) detects this automatically.

---

## 🗂️ Files

| File | Purpose |
|------|---------|
| `data.db` | All match data (persists between runs) |
| `config.yaml` | Your player name & friends |
| `listener.log` | Debug log (safe to delete occasionally) |

All files are created **inside the `RL-Tracker\` folder** automatically — nothing ends up on your Desktop or in Downloads.

---

## 📝 Version History

| Version | Date | Changes |
|:-------:|:----:|---------|
| **v1.1.1** | Jun 21 | **Wall Time 0% fix.** The ground/wall/air tick classifier in `listener.py` checked `bOnGround` before `bOnWall`, but Rocket League reports BOTH as `True` simultaneously when driving on the wall (the wall is world geometry, so ≥3 wheels touching it satisfies `bOnGround`). The old `if/elif` therefore swallowed every wall tick into `on_ground_ticks` and `on_wall_ticks` stayed 0 → Wall Time always showed 0%. Fix: check `bOnWall` first, making the three states mutually exclusive in the order wall > ground > air. Confirmed against the official RL Stats API docs (`bOnWall` is a valid SPECTATOR field — the original "field doesn't exist" hypothesis was wrong; it was a precedence bug, not a missing-field bug). |
| **v1.1** | Jun 21 | **Auto-update check.** New `/api/check-update` endpoint queries the GitHub releases API and compares the running version against the latest published release using semver. Settings modal gets a "🔄 Auto-Update" section with a "Check for Updates" button that shows the latest version, release notes, publish date, and a one-click download link to the new `.zip` asset. On page load the dashboard silently checks in the background and surfaces an "● Update available" badge next to the version number if a newer release exists. Uses stdlib `urllib` (no new deps, PyInstaller-safe). |
| **v1.0.9** | Jun 21 | **Flask → Waitress WSGI server.** Replaces Flask's single-threaded dev server (which prints "Do not use in a production environment" and freezes the dashboard during slow `/api/rl-diagnostics` calls) with Waitress — a production-grade pure-Python WSGI server (4 threads). No more silent 500s or UI lockups during diagnostics. Falls back to Flask automatically if Waitress is missing. **Dashboard layout fix:** Ground Time and Wall Time cards in the Movement & Boost section now render inside the 4-column grid as matching square cards (blue / orange) instead of orphan full-width divs. Fixed in both the all-time Stats view and the per-Session Deep Stats view. |
| **v1.0.8** | Jun 21 | Team detection swap bug fix — rewrote `_fast_find` as two-pass (exact match wins across whole player list), added team-locked `_find_user_player` for stats capture, TeamNum validation (rejects anything that isn't 0 or 1). Fixes the score-flip mid-session bug where the tracker would briefly assign the user to the wrong team. |
| **v1.0.7** | Jun 21 | WSL2 port-forwarding interference detection. The Diagnose button now detects `wslrelay.exe` / `wslhost.exe` grabbing 127.0.0.1:49123 (the most likely cause of TIMEOUT errors on machines with WSL2 / Docker Desktop installed, where no VPN/AV is present). Resolves the netstat listener PID to a process name, parses `%UserProfile%\\.wslconfig` (networkingMode, localhostForwarding, hostAddressLoopback, ignoredPorts), checks for the vEthernet (WSL) Hyper-V adapter, and scans Windows excluded port ranges (`netsh int ipv4 show excludedportrange`). Suggests `wsl --shutdown` and `ignoredPorts=49123` as the permanent fix. |
| **v1.0.5** | Jun 21 | Self-serve diagnostics: `/api/rl-diagnostics` endpoint + 🔍 Diagnose button in Settings — checks INI, port 49123, RL process, OneDrive path conflicts, and tells friends exactly what to fix. Listener logs TAStatsAPI.ini path + restart hint on every connection failure. |
| **v1.0.4** | Jun 20 | GLM 5.2 code review: 17 fixes — dedup timestamp, false losses, GoalScored crash, tie validation, float rounding, ground/wall time display |
| **v1.0.3** | Jun 19 | TAStatsAPI.ini section fix, duo re-check, Recent Form order, float rounding |
| **v1.0.1** | Jun 18 | json_module crash fix, session deep stats, DB persistence |
| **v1.0** | Jun 17 | First public release |

---

<div align="center">

Built with ❤️ by **Magnifico** + **Hermes AI Collective**

[🐛 Report Bug](https://github.com/magnificolv/RocketTracker/issues) · [📦 All Releases](https://github.com/magnificolv/RocketTracker/releases) · [⭐ Star the repo](https://github.com/magnificolv/RocketTracker/stargazers)

</div>
