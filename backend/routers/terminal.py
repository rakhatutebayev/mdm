"""WebSocket relay for PTY terminal sessions.

Flow:
  Agent  ──ws /ws/agent/{device_id}──→  Backend (relay)  ←──ws /ws/terminal/{device_id}──  Browser
  Agent sends PTY output as binary/text frames.
  Browser sends keystrokes as text frames.
  Backend relays between the two.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Dict, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from auth import decode_token

logger = logging.getLogger(__name__)

router = APIRouter(tags=["terminal"])

# device_id → agent WebSocket
_agent_connections: Dict[str, WebSocket] = {}
# device_id → browser WebSocket
_browser_connections: Dict[str, WebSocket] = {}
# device_id → asyncio.Event (signals agent connected)
_agent_ready: Dict[str, asyncio.Event] = {}


@router.websocket("/ws/agent/{device_id}")
async def agent_ws(websocket: WebSocket, device_id: str):
    """Agent connects here on startup and keeps connection alive."""
    await websocket.accept()
    _agent_connections[device_id] = websocket
    if device_id not in _agent_ready:
        _agent_ready[device_id] = asyncio.Event()
    _agent_ready[device_id].set()
    logger.info("Agent WS connected: %s", device_id)

    try:
        while True:
            # Receive output from agent (PTY data) and forward to browser
            try:
                data = await websocket.receive()
            except WebSocketDisconnect:
                break

            browser = _browser_connections.get(device_id)
            if browser:
                try:
                    if "bytes" in data and data["bytes"] is not None:
                        await browser.send_bytes(data["bytes"])
                    elif "text" in data and data["text"] is not None:
                        await browser.send_text(data["text"])
                except Exception:
                    pass
    except WebSocketDisconnect:
        pass
    finally:
        _agent_connections.pop(device_id, None)
        ev = _agent_ready.get(device_id)
        if ev:
            ev.clear()
        logger.info("Agent WS disconnected: %s", device_id)


@router.websocket("/ws/terminal/{device_id}")
async def browser_ws(
    websocket: WebSocket,
    device_id: str,
    t: Optional[str] = Query(None),
):
    """Browser connects here to open a terminal session."""
    await websocket.accept()

    # Auth via JWT query param — must accept first, then close if invalid
    if not t or not decode_token(t):
        await websocket.send_text('{"type":"error","message":"Unauthorized"}')
        await websocket.close(code=4001)
        return
    _browser_connections[device_id] = websocket
    logger.info("Browser terminal connected: %s", device_id)

    # Wait up to 10s for agent to be connected
    ev = _agent_ready.get(device_id)
    if not ev:
        _agent_ready[device_id] = asyncio.Event()
        ev = _agent_ready[device_id]

    agent = _agent_connections.get(device_id)
    if not agent:
        try:
            await asyncio.wait_for(ev.wait(), timeout=10.0)
            agent = _agent_connections.get(device_id)
        except asyncio.TimeoutError:
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": "Agent not connected. Make sure the agent is running on the device."
            }))
            await websocket.close()
            _browser_connections.pop(device_id, None)
            return

    # Tell agent to open a PTY session
    try:
        await agent.send_text(json.dumps({"type": "open_pty", "cols": 220, "rows": 50}))
    except Exception as e:
        await websocket.send_text(json.dumps({"type": "error", "message": str(e)}))
        await websocket.close()
        _browser_connections.pop(device_id, None)
        return

    # Notify browser that agent PTY is ready
    await websocket.send_text(json.dumps({"type": "ready"}))

    try:
        while True:
            try:
                data = await websocket.receive()
            except WebSocketDisconnect:
                break

            agent = _agent_connections.get(device_id)
            if not agent:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": "Agent disconnected."
                }))
                break

            try:
                if "bytes" in data and data["bytes"] is not None:
                    await agent.send_bytes(data["bytes"])
                elif "text" in data and data["text"] is not None:
                    await agent.send_text(data["text"])
            except Exception:
                break
    except WebSocketDisconnect:
        pass
    finally:
        _browser_connections.pop(device_id, None)
        # Tell agent to close PTY
        agent = _agent_connections.get(device_id)
        if agent:
            try:
                await agent.send_text(json.dumps({"type": "close_pty"}))
            except Exception:
                pass
        logger.info("Browser terminal disconnected: %s", device_id)
