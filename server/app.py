"""Zero-dependency HTTP server for Ticket Tracker."""

from __future__ import annotations

import json
import mimetypes
import os
import sys
import traceback
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import api
from .auth import COOKIE_NAME, SESSION_HOURS
from .db import BASE_DIR, Database

WEB_DIR = BASE_DIR / "web"
MAX_BODY = 4 * 1024 * 1024

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self'; "
        "connect-src 'self'; manifest-src 'self'; worker-src 'self'"
    ),
}


class TicketTrackerHandler(BaseHTTPRequestHandler):
    server_version = "TicketTracker/1.0"
    protocol_version = "HTTP/1.1"

    # -------------------------------------------------------------- helpers
    @property
    def db(self) -> Database:
        return self.server.db  # type: ignore[attr-defined]

    def do_GET(self):
        self._handle("GET")

    def do_HEAD(self):
        self._handle("HEAD")

    def do_POST(self):
        self._handle("POST")

    def do_PATCH(self):
        self._handle("PATCH")

    def do_DELETE(self):
        self._handle("DELETE")

    def do_OPTIONS(self):
        self._handle("OPTIONS")

    def log_message(self, fmt, *args):
        if os.environ.get("TT_QUIET") != "1":
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # -------------------------------------------------------------- handler
    def _handle(self, method: str):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}

        if path.startswith("/api/"):
            self._handle_api(method, path, query)
        elif method in ("GET", "HEAD"):
            self._serve_static(path)
        else:
            self._json(405, {"error": "Method not allowed"})

    def _handle_api(self, method: str, path: str, query: dict):
        try:
            body = self._read_body()
            if method not in ("GET", "HEAD", "OPTIONS"):
                self._check_origin()

            token = self._session_token()
            user = api.auth.get_session_user(self.db, token)

            status, payload, headers, ctx = api.dispatch(
                self.db, method, path, query, body, user, token, self.client_address[0]
            )

            extra = list(headers)
            if isinstance(payload, dict) and "token" in payload:
                extra.append(
                    (
                        "Set-Cookie",
                        f"{COOKIE_NAME}={payload['token']}; Path=/; HttpOnly; "
                        f"SameSite=Lax; Max-Age={SESSION_HOURS * 3600}",
                    )
                )
            if path == "/api/auth/logout":
                extra.append(
                    ("Set-Cookie", f"{COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0")
                )

            if isinstance(payload, dict) and "_raw" in payload:
                self._raw(
                    payload.get("_content_type", "application/octet-stream"),
                    payload["_raw"],
                    download=payload.get("_download"),
                    headers=extra,
                )
            else:
                self._json(status if status >= 400 else 200, payload, headers=extra)
        except api.ApiError as exc:
            self._json(exc.status, {"error": exc.message})
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
        except BrokenPipeError:
            pass
        except Exception:
            traceback.print_exc()
            self._json(500, {"error": "Something went wrong on the server"})

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise api.ApiError("Request is too large", 413)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise api.ApiError("Invalid JSON body", 400)
        if not isinstance(data, dict):
            raise api.ApiError("JSON body must be an object", 400)
        return data

    def _session_token(self) -> str | None:
        header = self.headers.get("Cookie")
        if not header:
            return None
        cookie = SimpleCookie()
        try:
            cookie.load(header)
        except Exception:
            return None
        morsel = cookie.get(COOKIE_NAME)
        return morsel.value if morsel else None

    def _check_origin(self):
        origin = self.headers.get("Origin")
        host = self.headers.get("Host")
        if not origin or not host:
            return
        parsed = urlparse(origin)
        if parsed.netloc and parsed.netloc != host:
            raise api.ApiError("Cross-site request blocked", 403)

    # -------------------------------------------------------------- static
    def _serve_static(self, path: str):
        if path in ("", "/"):
            path = "/index.html"

        candidate = (WEB_DIR / path.lstrip("/")).resolve()
        try:
            candidate.relative_to(WEB_DIR.resolve())
        except ValueError:
            self._json(403, {"error": "Forbidden"})
            return

        if not candidate.is_file():
            # Single-page app fallback for client-side routes.
            if "." not in Path(path).name:
                candidate = WEB_DIR / "index.html"
            else:
                self._json(404, {"error": "Not found"})
                return

        content = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        if candidate.suffix == ".webmanifest":
            content_type = "application/manifest+json"
        if candidate.suffix == ".js":
            content_type = "text/javascript; charset=utf-8"
        if candidate.suffix == ".svg":
            content_type = "image/svg+xml"

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        no_cache = candidate.name in ("sw.js", "index.html", "manifest.webmanifest")
        self.send_header(
            "Cache-Control", "no-store" if no_cache else "no-cache"
        )
        for key, value in SECURITY_HEADERS.items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(content)

    # -------------------------------------------------------------- output
    def _json(self, status: int, payload, headers: list[tuple[str, str]] | None = None):
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for key, value in SECURITY_HEADERS.items():
            self.send_header(key, value)
        for key, value in headers or []:
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _raw(self, content_type: str, body: bytes, download: str | None = None,
             headers: list[tuple[str, str]] | None = None):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{download}"')
        for key, value in SECURITY_HEADERS.items():
            self.send_header(key, value)
        for key, value in headers or []:
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)


class TicketServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, db: Database):
        super().__init__(address, TicketTrackerHandler)
        self.db = db


def serve(db: Database, host: str = "127.0.0.1", port: int = 8765) -> TicketServer:
    server = TicketServer((host, port), db)
    print(f"Ticket Tracker running at http://{host}:{port}")
    return server


if __name__ == "__main__":
    database = Database()
    database.init_schema()
    httpd = serve(database)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
