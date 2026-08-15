#!/usr/bin/env python3
"""
One-time helper to mint a Google OAuth2 refresh token for ALEX (used by the
google_calendar and google_tasks plugins).

Run this on a machine WITH A BROWSER (your laptop/desktop) - not on the
headless Raspberry Pi. It opens a browser tab for you to log in and
consent, catches the redirect on a local port, exchanges the code for
tokens, and prints the refresh token to paste into the Pi's .env.

Uses only the Python standard library - no extra pip install needed.

Prerequisites (Google Cloud Console, https://console.cloud.google.com):
  1. Create a project (or use an existing one).
  2. Enable the API(s) you need: "Google Calendar API" and/or "Tasks API".
  3. Create OAuth2 credentials of type "Desktop app".
  4. Note the Client ID and Client Secret.

Usage:
    # Calendar only (default):
    python3 google_oauth_auth.py --client-id ... --client-secret ...

    # Tasks only:
    python3 google_oauth_auth.py --client-id ... --client-secret ... --scopes tasks

    # Both at once with a single consent (reuse the same refresh token for
    # both plugins' config instead of authorizing twice):
    python3 google_oauth_auth.py --client-id ... --client-secret ... --scopes calendar,tasks
"""
from __future__ import annotations

import argparse
import http.server
import json
import threading
import urllib.parse
import urllib.request
import webbrowser

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REDIRECT_PORT = 8765
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}"

SCOPE_URLS = {
    "calendar": "https://www.googleapis.com/auth/calendar",
    "tasks": "https://www.googleapis.com/auth/tasks",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--client-secret", required=True)
    parser.add_argument(
        "--scopes", default="calendar",
        help="Comma-separated: 'calendar', 'tasks', or 'calendar,tasks' (default: calendar).",
    )
    args = parser.parse_args()

    requested = [s.strip() for s in args.scopes.split(",") if s.strip()]
    unknown = [s for s in requested if s not in SCOPE_URLS]
    if unknown:
        raise SystemExit(f"Unknown scope(s): {unknown}. Valid: {list(SCOPE_URLS)}")
    scope = " ".join(SCOPE_URLS[s] for s in requested)

    auth_url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": args.client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": scope,
        "access_type": "offline",
        "prompt": "consent",
    })

    code_holder: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            query = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(query)
            code_holder["code"] = params.get("code", [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<html><body>Listo, puedes cerrar esta pestana y volver a la terminal.</body></html>")

        def log_message(self, *_args):
            pass  # keep stdout clean

    server = http.server.HTTPServer(("localhost", REDIRECT_PORT), Handler)
    threading.Thread(target=server.handle_request, daemon=True).start()

    print(f"Abriendo el navegador para autorizar ({', '.join(requested)})...\n{auth_url}\n")
    webbrowser.open(auth_url)

    print("Esperando la autorizacion en el navegador...")
    while "code" not in code_holder:
        pass
    server.server_close()

    code = code_holder["code"]
    if not code:
        print("No se recibio un codigo de autorizacion. Cancelado o rechazado.")
        raise SystemExit(1)

    token_request = urllib.request.Request(
        TOKEN_URL,
        data=urllib.parse.urlencode({
            "client_id": args.client_id,
            "client_secret": args.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
        }).encode(),
        method="POST",
    )
    with urllib.request.urlopen(token_request) as resp:
        tokens = json.loads(resp.read())

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        print("Google no devolvio un refresh_token. Si ya habias autorizado esta app antes,")
        print("revoca el acceso en https://myaccount.google.com/permissions y vuelve a intentarlo")
        print("(Google solo entrega refresh_token la primera vez que autorizas una app).")
        raise SystemExit(1)

    print("\nListo. Copia esto en el .env de la Raspberry Pi:\n")
    if "calendar" in requested:
        print(f"ALEX_GOOGLE_CALENDAR_CLIENT_ID={args.client_id}")
        print(f"ALEX_GOOGLE_CALENDAR_CLIENT_SECRET={args.client_secret}")
        print(f"ALEX_GOOGLE_CALENDAR_REFRESH_TOKEN={refresh_token}")
    if "tasks" in requested:
        print(f"ALEX_GOOGLE_TASKS_CLIENT_ID={args.client_id}")
        print(f"ALEX_GOOGLE_TASKS_CLIENT_SECRET={args.client_secret}")
        print(f"ALEX_GOOGLE_TASKS_REFRESH_TOKEN={refresh_token}")


if __name__ == "__main__":
    main()
