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
