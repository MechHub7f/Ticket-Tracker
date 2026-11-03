#!/usr/bin/env python3
"""One command to run Ticket Tracker.

    python3 run.py                 # http://127.0.0.1:8765
    python3 run.py --seed          # add demo data on first run
    python3 run.py --desktop       # open in a desktop app window
    python3 run.py --host 0.0.0.0  # share on the local network

Zero dependencies. Data lives in data/ticket_tracker.db (SQLite).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from server.app import serve  # noqa: E402
from server.db import Database  # noqa: E402

CHROMIUM_BINARIES = [
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
    "microsoft-edge",
    "brave-browser",
]


def open_browser(url: str, desktop: bool) -> None:
    time.sleep(0.7)
    if desktop:
        for name in CHROMIUM_BINARIES:
            binary = shutil.which(name)
            if binary:
                subprocess.Popen(
                    [
                        binary,
                        f"--app={url}",
                        "--window-size=1400,950",
                        "--user-data-dir=" + str(Path.home() / ".ticket-tracker-app"),
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return
    webbrowser.open(url)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Ticket Tracker server")
    parser.add_argument("--host", default=os.environ.get("TT_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("TT_PORT", "8765")))
    parser.add_argument("--seed", action="store_true", help="add demo data if empty")
    parser.add_argument("--desktop", action="store_true", help="open a desktop window")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    db = Database()
    db.init_schema()
    db.migrate()

    if args.seed:
        from server.seed import seed_demo

        result = seed_demo(db)
        if result["created"]:
            print(f"Demo data added: {result['residents']} residents, {result['items']} menu items.")
        else:
            print("Demo data skipped (database already has residents).")

    shown_host = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
    url = f"http://{shown_host}:{args.port}"

    httpd = serve(db, args.host, args.port)
    print(f"Open {url} in your browser. Press Ctrl+C to stop.")
    if not args.no_browser:
        threading.Thread(target=open_browser, args=(url, args.desktop), daemon=True).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
