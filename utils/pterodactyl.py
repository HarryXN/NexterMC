"""Small async client for the Pterodactyl client API used by the staff panel."""
from __future__ import annotations

import re
import asyncio
import json
import logging
import time

import aiohttp

from config import PANEL_API_KEY, PANEL_URL

log = logging.getLogger("nextermc.panel_api")


class PanelAPIError(RuntimeError):
    """A safe, user-facing panel API error without response secrets."""


def _headers() -> dict[str, str]:
    if not PANEL_API_KEY:
        raise PanelAPIError("Panel API key is missing from the bot VPS .env file.")
    return {
        "Authorization": f"Bearer {PANEL_API_KEY}",
        "Accept": "Application/vnd.pterodactyl.v1+json",
        "Content-Type": "application/json",
    }


async def _request(method: str, path: str, *, payload: dict | None = None):
    url = f"{PANEL_URL}/api/client{path}"
    timeout = aiohttp.ClientTimeout(total=12, connect=6)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.request(method, url, headers=_headers(), json=payload) as response:
                if response.status == 204:
                    return None
                if response.status >= 400:
                    # Log the endpoint and status so logs.py can forward useful
                    # diagnostics. Never log request headers or the API key.
                    body = (await response.text())[:400].replace("\n", " ").replace("\r", " ")
                    if PANEL_API_KEY:
                        body = body.replace(PANEL_API_KEY, "[REDACTED]")
                    log.error(
                        "Panel API request failed: method=%s path=%s status=%s response=%r",
                        method,
                        path,
                        response.status,
                        body,
                    )
                if response.status == 401:
                    raise PanelAPIError(
                        "Panel returned HTTP 401: the Client API key is invalid, expired, or not accepted by this panel."
                    )
                if response.status == 403:
                    raise PanelAPIError(
                        "Panel returned HTTP 403: the key was recognized, but this account or hosting provider denied access."
                    )
                if response.status == 404:
                    raise PanelAPIError(
                        "Panel returned HTTP 404: check the server identifier and whether NexterCloud exposes this API endpoint."
                    )
                if response.status >= 400:
                    raise PanelAPIError(f"Panel request failed (HTTP {response.status}).")
                try:
                    return await response.json(content_type=None)
                except (ValueError, aiohttp.ContentTypeError) as exc:
                    raise PanelAPIError("Panel returned an unreadable response.") from exc
    except PanelAPIError:
        raise
    except (aiohttp.ClientError, TimeoutError) as exc:
        log.exception("Panel API transport error: method=%s path=%s", method, path)
        raise PanelAPIError("Could not connect to the NexterCloud panel.") from exc


async def get_server_resources(identifier: str) -> dict:
    data = await _request("GET", f"/servers/{identifier}/resources")
    try:
        attributes = data["attributes"]
        return {
            "state": str(attributes.get("current_state", "unknown")),
            "suspended": bool(attributes.get("is_suspended", False)),
            "resources": attributes.get("resources") or {},
        }
    except (TypeError, KeyError) as exc:
        raise PanelAPIError("Panel returned an unexpected server status response.") from exc


async def send_server_command(identifier: str, command: str) -> None:
    # Commands are single-line only. Callers constrain player names and verbs.
    clean = re.sub(r"[\x00-\x1f\x7f]", " ", command).strip()
    if not clean or len(clean) > 500:
        raise PanelAPIError("Command is empty or too long.")
    await _request(
        "POST",
        f"/servers/{identifier}/command",
        payload={"command": clean},
    )


async def run_server_command(
    identifier: str,
    command: str,
    *,
    timeout: float = 4.0,
    expected_output: str | None = None,
) -> str:
    """Run a command over the Pterodactyl console websocket and collect output.

    The ordinary Client API command endpoint only acknowledges submission; this
    websocket path is needed for commands such as `data get` whose output matters.
    """
    clean = re.sub(r"[\x00-\x1f\x7f]", " ", command).strip()
    if not clean or len(clean) > 500:
        raise PanelAPIError("Command is empty or too long.")

    response = await _request("GET", f"/servers/{identifier}/websocket")
    try:
        credentials = response["data"]
        socket_url = credentials["socket"]
        token = credentials["token"]
    except (TypeError, KeyError) as exc:
        raise PanelAPIError("Panel returned incomplete console websocket credentials.") from exc

    client_timeout = aiohttp.ClientTimeout(total=timeout + 10, connect=6)
    try:
        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            async with session.ws_connect(socket_url, heartbeat=20) as websocket:
                await websocket.send_json({"event": "auth", "args": [token]})
                auth_deadline = time.monotonic() + 6
                authenticated = False
                while time.monotonic() < auth_deadline:
                    message = await websocket.receive(timeout=max(0.1, auth_deadline - time.monotonic()))
                    if message.type != aiohttp.WSMsgType.TEXT:
                        continue
                    event = json.loads(message.data)
                    if event.get("event") == "auth success":
                        authenticated = True
                        break
                    if event.get("event") in {"jwt error", "daemon error"}:
                        log.error("Panel console websocket auth failed for server %s: %s", identifier, event.get("args"))
                        raise PanelAPIError("Panel denied console websocket access for this server.")
                if not authenticated:
                    raise PanelAPIError("Panel console websocket authentication timed out.")

                await websocket.send_json({"event": "send command", "args": [clean]})
                deadline = time.monotonic() + timeout
                output: list[str] = []
                while time.monotonic() < deadline:
                    try:
                        message = await websocket.receive(timeout=max(0.1, deadline - time.monotonic()))
                    except asyncio.TimeoutError:
                        break
                    if message.type != aiohttp.WSMsgType.TEXT:
                        continue
                    event = json.loads(message.data)
                    if event.get("event") == "console output":
                        args = event.get("args") or []
                        if args:
                            line = str(args[0])
                            if expected_output and expected_output.casefold() not in line.casefold():
                                if "no entity was found" not in line.casefold():
                                    continue
                            output.append(line)
                            # Console command replies normally arrive as one line.
                            if len(output) >= 1:
                                break
                    if event.get("event") in {"jwt error", "daemon error"}:
                        log.error("Panel console websocket command failed for server %s: %s", identifier, event.get("args"))
                        raise PanelAPIError("Panel console websocket failed while running the command.")
                return "\n".join(output)
    except PanelAPIError:
        raise
    except (aiohttp.ClientError, asyncio.TimeoutError, TimeoutError) as exc:
        log.exception("Panel console websocket error for server %s", identifier)
        raise PanelAPIError("Could not read command output from the panel console websocket.") from exc


async def set_server_power(identifier: str, signal: str) -> None:
    if signal not in {"start", "stop", "restart"}:
        raise PanelAPIError("Unsupported power action.")
    await _request(
        "POST",
        f"/servers/{identifier}/power",
        payload={"signal": signal},
    )
