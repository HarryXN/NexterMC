#!/usr/bin/env python3
"""Root-owned local RPC for a fixed set of NexterMC systemd actions."""
from __future__ import annotations

import json
import os
import socket
import socketserver
import stat
import subprocess
import urllib.error
import urllib.request
import re

SOCKET_PATH = "/run/nextermc-control.sock"
UNIT = "nextermc-bot.service"
SYSTEMCTL = "/usr/bin/systemctl"
ALLOWED_ACTIONS = {"start", "stop", "restart"}
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9._-]{20,200}$")


def send_interaction_result(application_id: str, token: str, message: str) -> None:
    """Post a fixed-content followup to Discord; never log the interaction token."""
    if not application_id.isdigit() or len(application_id) > 24 or not TOKEN_PATTERN.fullmatch(token):
        raise ValueError("Invalid interaction webhook credentials")
    url = f"https://discord.com/api/v10/webhooks/{application_id}/{token}"
    body = json.dumps({"content": message, "flags": 64}).encode("utf-8")
    request = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json", "User-Agent": "NexterMC-Controller/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        response.read(1024)


class Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        raw = self.rfile.readline(2049)
        try:
            if len(raw) > 2048 or not raw.endswith(b"\n"):
                raise ValueError("Invalid request size")
            request = json.loads(raw.decode("utf-8"))
            action = request.get("action") if isinstance(request, dict) else None
            if action == "status":
                result = subprocess.run(
                    [SYSTEMCTL, "show", UNIT, "--property=ActiveState", "--property=SubState", "--value"],
                    check=False, capture_output=True, text=True, timeout=5,
                )
                values = result.stdout.splitlines()
                if result.returncode != 0 or not values:
                    response = {"ok": False, "message": "Could not read service status."}
                else:
                    response = {
                        "ok": True,
                        "state": values[0] if values else "unknown",
                        "substate": values[1] if len(values) > 1 else "",
                    }
            elif action in ALLOWED_ACTIONS:
                # The action and unit are allowlisted constants; no user input reaches a shell.
                result = subprocess.run(
                    [SYSTEMCTL, action, UNIT], check=False,
                    capture_output=True, text=True, timeout=20,
                )
                response = {
                    "ok": result.returncode == 0,
                    "message": (
                        f"`{UNIT}` {action} completed."
                        if result.returncode == 0
                        else f"systemd could not {action} `{UNIT}` (exit {result.returncode})."
                    ),
                }
                application_id = request.get("application_id")
                interaction_token = request.get("interaction_token")
                if action in {"stop", "restart"} and application_id and interaction_token:
                    result_message = (
                        f"✅ {action.title()} successful. `nextermc-bot.service` "
                        + ("is stopped." if action == "stop" else "is running again.")
                        if result.returncode == 0
                        else f"❌ {action.title()} failed. Check the VPS systemd journal."
                    )
                    try:
                        send_interaction_result(str(application_id), str(interaction_token), result_message)
                    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
                        # Do not include the request URL: it contains the secret interaction token.
                        print(f"Discord action-result delivery failed ({type(exc).__name__})", flush=True)
            else:
                response = {"ok": False, "message": "Unsupported action."}
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError, subprocess.TimeoutExpired):
            response = {"ok": False, "message": "Invalid request or systemd timed out."}
        except Exception:
            response = {"ok": False, "message": "Controller error."}
        self.wfile.write((json.dumps(response) + "\n").encode("utf-8"))


class LocalController(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True


def main() -> None:
    if os.path.lexists(SOCKET_PATH):
        info = os.lstat(SOCKET_PATH)
        if not stat.S_ISSOCK(info.st_mode):
            raise RuntimeError(f"Refusing to replace non-socket path: {SOCKET_PATH}")
        os.unlink(SOCKET_PATH)
    with LocalController(SOCKET_PATH, Handler) as server:
        os.chmod(SOCKET_PATH, 0o600)
        server.serve_forever(poll_interval=1)


if __name__ == "__main__":
    main()
