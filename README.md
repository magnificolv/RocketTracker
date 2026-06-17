# 🚀 Rocket League Match Tracker v1.0

> **Portable Windows App** — no Python, no WSL, no install. Double-click to run.

Track your Rocket League matches automatically. Stats, history, deep analytics — all in a clean dark dashboard. Built for competitive players who want to understand their game.

---

## ✨ Features

- 🎮 **Auto-tracking** — detects matches, goals, demos, boost usage, and more via RL's built-in Stats API
- 📊 **Deep Stats** — shot power (km/h), accuracy %, boost %, air time %, demos, ball control
- 📋 **Session History** — browse past sessions, click any match for detailed breakdown
- 🎯 **Duo Mode** — tracks you + your friend in the same match
- 🌐 **Web Dashboard** — opens in your browser at `http://localhost:3010`
- ⚡ **Fast & Light** — non-blocking TCP listener, won't lag your game

---

## 🖥️ Screenshots

| Dashboard | Stats |
|-----------|-------|
| *Live match tracking with green status dot* | *Deep analytics across all matches* |

---

## 📦 Installation

### 1. Download
Get the latest `RL-Tracker-v1.0.1.exe` from **[Releases](https://github.com/magnificolv/RocketTracker/releases)**.

[![Download v1.0.1](https://img.shields.io/badge/Download-v1.0.1-orange?style=for-the-badge)](https://github.com/magnificolv/RocketTracker/releases/download/v1.0.1/RL-Tracker-v1.0.1.exe)

### 2. Run
Double-click `RL-Tracker-v1.0.1.exe`. A console window opens — **keep it running**.

### 3. Open Dashboard
Your browser opens automatically at `http://localhost:3010`.

### 4. Set Your Player Name
Click ⚙️ **Settings** → enter your Rocket League display name → **Save**.

### 5. Launch Rocket League
The tracker auto-connects. Status dot turns 🟢 green when tracking is live. Play a match — stats appear automatically!

> **⚠️ First time?** After entering your name, restart Rocket League so the Stats API activates.

---

## 🔧 Requirements

- **Windows 10/11** (64-bit)
- **Rocket League** (Steam or Epic Games)
- That's it! The .exe bundles everything else.

---

## 🗂️ Files Created

| File | Location | Purpose |
|------|----------|---------|
| `data.db` | Next to .exe | All your match data (persists between runs) |
| `config.yaml` | Next to .exe | Your player name & friends |
| `listener.log` | Next to .exe | Debug log (grows over time — delete occasionally) |

---

## 🐛 Troubleshooting

| Problem | Fix |
|---------|-----|
| Status stays ⚫ grey | Make sure Rocket League is running AND you're in a match (not main menu) |
| No stats appear | Check your player name matches exactly in Settings |
| Port 3010 already in use | Close other instances of the tracker first |
| .exe crashes immediately | Try running as Administrator (RL config folder may need permissions) |

---

## 🛠️ For Friends

1. Download `RL-Tracker-v1.0.exe`
2. Double-click to run
3. Enter YOUR Rocket League display name in Settings
4. Play!

Each player needs their own `config.yaml` with their name. The tracker auto-creates the Stats API config in your RL folder.

---

## 📝 Version History

| Version | Date | Changes |
|---------|------|---------|
| **v1.0** | Jun 17, 2026 | First public release. Cleaned dependencies, fixed portability, removed dead code. |
| v9g | Jun 16, 2026 | Custom icon, all features stable |
| v1-v8 | Jun 10-15, 2026 | Internal development (dedup, demolish tracking, deep stats, PyInstaller builds) |

---

## 🔗 Links

- [Latest Release](https://github.com/magnificolv/RocketTracker/releases)
- [Report a Bug](https://github.com/magnificolv/RocketTracker/issues)
- Built with ❤️ by Magnifico + Hermes AI Collective
