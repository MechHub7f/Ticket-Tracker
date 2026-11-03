#!/usr/bin/env python3
"""One command to run Ticket Tracker:  python3 run.py

Serves the API and the web app from a single Python process, no build step.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "server"))

from app import create_app  # noqa: E402

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8787"))
    app = create_app()
    print(f"\n  Ticket Tracker is running:  http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
