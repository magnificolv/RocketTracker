# 🚀 Rocket League Match Tracker v2.0.3

<p align="center">
  <a href="https://github.com/magnificolv/RocketTracker/releases/latest"><img src="https://img.shields.io/github/v/release/magnificolv/RocketTracker?style=flat-square&label=version&color=blue" alt="Version"></a>
  &nbsp;
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="License"></a>
  &nbsp;
  <a href="https://github.com/magnificolv/RocketTracker/stargazers"><img src="https://img.shields.io/github/stars/magnificolv/RocketTracker?style=flat-square&color=yellow" alt="Stars"></a>
  &nbsp;
  <a href="https://github.com/magnificolv/RocketTracker/releases"><img src="https://img.shields.io/github/downloads/magnificolv/RocketTracker/total?style=flat-square&color=orange&label=downloads" alt="Downloads"></a>
</p>

---

<div align="center">

<a href="https://github.com/magnificolv/RocketTracker/releases/latest">
  <img src="https://img.shields.io/badge/⬇️%20DOWNLOAD%20v1.3.2-brightgreen?style=for-the-badge&logo=windows&logoColor=white" alt="Download v1.3.2" height="56">
</a>

<br><sub>📦 Download ZIP → Extract to Desktop → Double-click → Play</sub>

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

## ✨ What It Tracks

### 1. Download
Get the latest `RL-Tracker-v2.0.3` from [Releases](https://github.com/magnificolv/RocketTracker/releases).

### 2. Run
Double-click `RL-Tracker-v2.0.3`. A console window opens — **keep it running**.

### 3. Open Dashboard
Your browser opens automatically at `http://localhost:3010`.

### 4. Set Your Player Name
Click ⚙️ **Settings** → enter your Rocket League display name → **Save**.

### 5. Launch Rocket League
The tracker auto-connects. Status dot turns 🟢 green when tracking is live. Play a match — stats appear automatically!

> **⚠️ First time?** After entering your name, restart Rocket League so the Stats API activates.

---

## 🚀 Quick Start

1. **Download** the [latest ZIP](https://github.com/magnificolv/RocketTracker/releases/latest) (~13 MB)
2. **Extract** to your Desktop — keep the `RL-Tracker\` folder together, don't move the .exe out
3. **Double-click** `RL-Tracker-v1.3.2.exe` — a console window opens, your browser opens the dashboard at `http://localhost:3010`
4. **Enter your name** in ⚙️ Settings → click **Auto-Create** → restart Rocket League → play!

> 💡 First time? Auto-Create sets up everything automatically. Just restart RL once.

---

## 🔧 Troubleshooting

**Tracker shows "RL not running" but RL IS running?**  
Click ⚙️ Settings → **🔍 Diagnose**. It checks your config, port, and running processes, then tells you exactly what to fix.

**Using WSL2 / Docker Desktop?**  
WSL2 can silently intercept port 49123. Quick fix: run `wsl --shutdown` in PowerShell. Permanent fix: add `ignoredPorts=49123` to `%USERPROFILE%\.wslconfig` under `[wsl2]`.

**Windows Defender flags the .exe?**  
False positive — the file is unsigned. Click `Keep anyway` in your browser, or restore from Windows Security → Protection history.

---

## 🔄 Auto-Update

| Problem | Fix |
|---------|-----|
| Status stays ⚫ grey | Make sure Rocket League is running AND you're in a match (not main menu) |
| No stats appear | Check your player name matches exactly in Settings |
| Port 3010 already in use | Close other instances of the tracker first |
| .exe crashes immediately | Try running as Administrator (RL config folder may need permissions) |

---

## 🛠️ For Friends

1. Download `RL-Tracker-v2.0.3`
2. Double-click to run
3. Enter YOUR Rocket League display name in Settings
4. Play!

Each player needs their own `config.yaml` with their name. The tracker auto-creates the Stats API config in your RL folder.

---

## 📝 Version History

| Version | Date | Changes |
|---------|------|---------|
| **v2.0.3** | Jun 28, 2026 | Bugfix: SPECTATOR skip invalid TeamNum, Avg Shot Power rounding, saves tracking |
| v9g | Jun 16, 2026 | Custom icon, all features stable |
| v1-v8 | Jun 10-15, 2026 | Internal development (dedup, demolish tracking, deep stats, PyInstaller builds) |

---

<div align="center">

Built with ❤️ by **Magnifico** & **Hermes AI Collective**

[🐛 Report Bug](https://github.com/magnificolv/RocketTracker/issues) · [📦 All Releases](https://github.com/magnificolv/RocketTracker/releases) · [⭐ Star the repo](https://github.com/magnificolv/RocketTracker/stargazers)

</div>
