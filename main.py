"""
Rocket League Tracker v4.0 Overdrive - Portable Windows Edition
================================================================
Single entry point. Double-click to run.
Starts non-blocking TCP Stats API listener + Waitress WSGI dashboard.
"""
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

try:
    from waitress import serve as _wsgi_serve
    _HAS_WAITRESS = True
except ImportError:
    _wsgi_serve = None
    _HAS_WAITRESS = False

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent

os.chdir(str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR))

from version import APP_EDITION, APP_VERSION
from app import app, init_db
from listener import ensure_default_statsapi_ini, ensure_tastatsapi_ini, run_listener


def main():
    print("=" * 56)
    print(f"  Rocket League Tracker v{APP_VERSION} ({APP_EDITION})")
    print(f"  Dir: {BASE_DIR}")
    print("=" * 56)

    init_db()
    ensure_tastatsapi_ini()
    ensure_default_statsapi_ini()

    try:
        import yaml

        config_path = BASE_DIR / "config.yaml"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
        else:
            config = {}
        player_name = (config.get("player") or {}).get("name", "")
        friends = (config.get("player") or {}).get("friends", [])
    except Exception:
        player_name = ""
        friends = []
        config = {}

    stop_event = threading.Event()
    listener_thread = threading.Thread(
        target=run_listener,
        args=(player_name, friends, stop_event),
        daemon=True,
        name="rl-listener",
    )
    listener_thread.start()
    print(f"  Listener thread started (player: {player_name or 'not set'})")
    app.config["listener_thread"] = listener_thread
    app.config["listener_stop_event"] = stop_event

    port = int((config.get("app") or {}).get("port", 3010))
    if "--no-browser" not in sys.argv[1:]:
        def open_browser():
            time.sleep(1.5)
            webbrowser.open(f"http://localhost:{port}")

        threading.Thread(target=open_browser, daemon=True).start()

    print(f"  Dashboard -> http://localhost:{port}")
    print("=" * 56)
    print("  Press Ctrl+C to exit (or use Exit tracker button in UI)")
    if _wsgi_serve is not None:
        print("  Waitress WSGI server (6 threads)")
        _wsgi_serve(app, host="127.0.0.1", port=port, threads=6)
    else:
        print("  Waitress not installed — falling back to Flask dev server")
        app.run(host="127.0.0.1", port=port, debug=False)

    if app.config.get("_should_exit"):
        print("Shutting down via /api/quit...")
        os._exit(0)
    stop_event.set()
    print("Shutting down...")


if __name__ == "__main__":
    main()
