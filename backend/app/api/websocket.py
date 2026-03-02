"""
WebSocket endpoints for real-time agent communication and status streaming.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()
logger = logging.getLogger(__name__)

# Active WebSocket connections
_connections: dict[str, list[WebSocket]] = {}


class ConnectionManager:
    """Manages WebSocket connections for real-time streaming."""

    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, session_id: str) -> None:
        await websocket.accept()
        if session_id not in self._connections:
            self._connections[session_id] = []
        self._connections[session_id].append(websocket)
        logger.info("WebSocket connected: session=%s", session_id)

    def disconnect(self, websocket: WebSocket, session_id: str) -> None:
        if session_id in self._connections:
            self._connections[session_id] = [
                ws for ws in self._connections[session_id] if ws != websocket
            ]
            if not self._connections[session_id]:
                del self._connections[session_id]
        logger.info("WebSocket disconnected: session=%s", session_id)

    async def broadcast(self, session_id: str, data: dict[str, Any]) -> None:
        """Broadcast a message to all connections watching a session."""
        if session_id not in self._connections:
            return

        payload = json.dumps(data, ensure_ascii=False)
        dead = []
        for ws in self._connections[session_id]:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)

        # Clean up dead connections
        for ws in dead:
            self.disconnect(ws, session_id)

    async def send_to(
        self, websocket: WebSocket, data: dict[str, Any]
    ) -> None:
        """Send a message to a specific connection."""
        await websocket.send_text(json.dumps(data, ensure_ascii=False))


manager = ConnectionManager()


@router.websocket("/ws/{session_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    session_id: str,
) -> None:
    """WebSocket endpoint for real-time agent events.

    Clients connect to watch a session's progress.
    Server sends: agent state changes, draft updates, status events.
    Client can send: commands (HALT, RESUME, FORCE_UPDATE).
    """
    await manager.connect(websocket, session_id)

    try:
        # Send initial connection confirmation
        await manager.send_to(websocket, {
            "type": "connected",
            "session_id": session_id,
            "message": "Connected to PD-MAWS session stream",
        })

        while True:
            # Listen for client commands
            data = await websocket.receive_text()
            try:
                command = json.loads(data)
                await _handle_ws_command(websocket, session_id, command)
            except json.JSONDecodeError:
                await manager.send_to(websocket, {
                    "type": "error",
                    "message": "Invalid JSON",
                })

    except WebSocketDisconnect:
        manager.disconnect(websocket, session_id)
    except Exception as e:
        logger.error("WebSocket error: %s", e)
        manager.disconnect(websocket, session_id)


async def _handle_ws_command(
    websocket: WebSocket,
    session_id: str,
    command: dict[str, Any],
) -> None:
    """Handle a command from a WebSocket client."""
    cmd_type = command.get("type", "")

    if cmd_type == "ping":
        await manager.send_to(websocket, {"type": "pong"})

    elif cmd_type == "get_status":
        from app.main import get_registry
        registry = get_registry()
        entry = await registry.get_session(session_id)
        if entry:
            await manager.send_to(websocket, {
                "type": "session_status",
                "data": entry.model_dump(),
            })
        else:
            await manager.send_to(websocket, {
                "type": "error",
                "message": f"Session {session_id} not found",
            })

    elif cmd_type == "halt":
        from app.main import get_registry
        from app.models.session import SessionState
        registry = get_registry()
        entry = await registry.transition_state(session_id, SessionState.HALTED)
        await manager.broadcast(session_id, {
            "type": "session_halted",
            "data": entry.model_dump(),
        })

    else:
        await manager.send_to(websocket, {
            "type": "error",
            "message": f"Unknown command: {cmd_type}",
        })
