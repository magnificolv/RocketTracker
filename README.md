# 🚀 Rocket League Match Tracker v1.0.4

<p align="center">
  <img src="icon.png" width="96" alt="RL Tracker logo"><br>
  <strong>Auto-track your Rocket League matches. No install, no Python, no WSL.</strong>
</p>

<p align="center">
  <a href="https://github.com/magnificolv/RocketTracker/releases/tag/v1.0.3">
    <img src="https://img.shields.io/badge/⬇️%20Download-v1.0.3%20ZIP-brightgreen?style=for-the-badge&logo=windows&logoColor=white" alt="Download v1.0.3 ZIP" height="40">
  </a>
  &nbsp;
  <a href="https://github.com/magnificolv/RocketTracker/releases">
    <img src="https://img.shields.io/badge/All%20Releases-Releases-blue?style=for-the-badge" alt="All Releases" height="40">
  </a>
</p>

> 📦 **Download the ZIP, extract it to your Desktop, open the folder, and double‑click the .exe.** A console window opens, your browser opens the dashboard, and stats appear as you play. **Everything stays inside the folder — no scattered files.**

---

## 📸 Screenshots

<table>
<tr>
  <td width="50%"><b>🎮 Active Session</b><br><i>Live match scores, per-match deep stats</i></td>
  <td width="50%"><b>📋 History</b><br><i>Browse past sessions, click to expand</i></td>
</tr>
<tr>
  <td><img src="screenshots/01-active-session.png" alt="Active Session"></td>
  <td><img src="screenshots/03-history-sessions.png" alt="History"></td>
</tr>
<tr>
  <td width="50%"><b>📊 Stats Overview</b><br><i>All-time analytics with deep breakdowns</i></td>
  <td width="50%"><b>🔍 Session Deep Stats</b><br><i>Aggregate stats per completed session</i></td>
</tr>
<tr>
  <td><img src="screenshots/02-stats-overview.png" alt="Stats Overview"></td>
  <td><img src="screenshots/04-session-deep-stats.png" alt="Session Deep Stats"></td>
</tr>
</table>

---

## ✨ What It Tracks

| Category | Stats |
|----------|-------|
| 🎯 **Shot Power** | Fastest goal (km/h), avg shot power, shot accuracy %, total shots |
| ⛽ **Movement** | Avg boost %, time boosting %, supersonic %, air time % |
| 💥 **Combat** | Demos given, demos taken, saves, overtime matches |
| 🎮 **Ball Control** | Total touches, car touches, assists, your goals |
| 👥 **Duo Mode** | Auto-detects when your friend is on your team |
| 📋 **Sessions** | Auto-creates sessions, keeps full history |

---

## 🚀 Quick Start

**1. Download** → [**RL-Tracker-v1.0.3.zip**](https://github.com/magnificolv/RocketTracker/releases/tag/v1.0.3) (13 MB)

**2. Extract** → Right‑click the ZIP → **Extract All…** → Choose your **Desktop** (or anywhere convenient)

**3. Open the folder** → `RL-Tracker\` → **double‑click** `RL-Tracker-v1.0.3.exe`

**4. Enter your name** → ⚙️ Settings → type your Rocket League display name → **Save**

**5. Launch Rocket League** → Play a match, stats appear automatically 🎉

> 💡 **First time?** Click **Auto-Create** in Settings to set up the Stats API config. Restart RL once.
>
> 💡 **Keep the folder together.** All data (`data.db`, `config.yaml`, logs) is saved **inside** the `RL-Tracker\` folder. Don't drag the .exe out.

---

## 🛡️ Windows Defender

"Virus detected" ir **false positive** — fails nav parakstīts. Kā salabot:

| Problēma | Risinājums |
|----------|-----------|
| Chrome/Edge bloķē download | Pogas blakus `···` → **Keep anyway** |
| Defender izdzēsa failu | Windows Security → Protection history → Atjaunot |
| Pievienot izņēmumu | Windows Security → Exclusions → Add `C:\Users\%USERNAME%\Desktop\RL-Tracker` |

---

## 🗂️ Files

| File | Purpose |
|------|---------|
| `data.db` | All match data (persists between runs) |
| `config.yaml` | Your player name & friends |
| `listener.log` | Debug log (delete occasionally) |

All files are created **inside the `RL-Tracker\` folder** automatically — nothing ends up on your Desktop or Downloads folder.

---

## 🛠️ For Friends

1. Download [**RL-Tracker-v1.0.3.zip**](https://github.com/magnificolv/RocketTracker/releases/tag/v1.0.3)
2. **Extract the ZIP** to Desktop → you'll get an `RL-Tracker\` folder
3. **Double‑click** `RL-Tracker-v1.0.3.exe` inside the folder
4. Enter YOUR Rocket League name in ⚙️ Settings
5. Click **Auto-Create** to set up the config
6. Restart Rocket League, play!

> ⚠️ **Important:** Run the .exe from **inside the `RL-Tracker\` folder**. If you move the .exe to another location, the data files will be created there instead.

---

## 📝 Version History

| Version | Date | Changes |
|---------|------|---------|
| **v1.0.4** | Jun 20 | GLM 5.2 code review: 17 fixes — dedup timestamp, false losses, GoalScored crash, tie validation, float rounding, ground/wall time display |
| **v1.0.3** | Jun 19 | TAStatsAPI.ini section fix, duo re-check, Recent Form order, float rounding |
| **v1.0.1** | Jun 18 | json_module crash fix, session deep stats, DB persistence |
| **v1.0** | Jun 17 | First public release |

---

<p align="center">
  Built with ❤️ by <b>Magnifico</b> + <b>Hermes AI Collective</b> · 
  <a href="https://github.com/magnificolv/RocketTracker/issues">Report Bug</a> ·
  <a href="https://github.com/magnificolv/RocketTracker/releases">All Releases</a>
</p>
