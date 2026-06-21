"""
Rocket League Tracker - Portable Windows Edition
=================================================
Single entry point. Double-click to run.
Starts FAST TCP listener (thread) + Flask web server.
"""
import os, sys, threading, webbrowser, time
from pathlib import Path

if sys.platform == "win32":
    try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception: pass

# DB persistence: store next to exe (not in temp)
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent  # PyInstaller: exe location
else:
    BASE_DIR = Path(__file__).parent  # Dev mode
os.chdir(str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR))

from app import app, init_db
from listener import run_listener, ensure_tastatsapi_ini

def main():
    print("=" * 50)
    print("  🚀 Rocket League Tracker v1.0.5")
    print(f"  📁 {BASE_DIR}")
    print("=" * 50)

    init_db()
    ensure_tastatsapi_ini()

    try:
        import yaml
        config_path = BASE_DIR / "config.yaml"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
        else:
            config = {}
        player_name = config.get("player", {}).get("name", "")
        friends = config.get("player", {}).get("friends", [])
    except Exception:
        player_name = ""; friends = []; config = {}

    stop_event = threading.Event()
    listener_thread = threading.Thread(target=run_listener, args=(player_name, friends, stop_event), daemon=True, name="rl-listener")
    listener_thread.start()
    print(f"  🎧 Listener thread started (player: {player_name or 'not set'})")
    app.config["listener_thread"] = listener_thread
    app.config["listener_stop_event"] = stop_event

    def open_browser():
        time.sleep(1.5)
        webbrowser.open(f"http://localhost:{config.get('app', {}).get('port', 3010)}")

    threading.Thread(target=open_browser, daemon=True).start()

    port = config.get("app", {}).get("port", 3010)
    print(f"  🌐 Dashboard -> http://localhost:{port}")
    print("=" * 50)
    print("  Press Ctrl+C to exit (or use ⏻ button in dashboard)")
    app.run(host="127.0.0.1", port=port, debug=False)
    stop_event.set()
    print("👋 Shutting down...")

if __name__ == "__main__":
    main()
