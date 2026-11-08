"""Pushes scored transactions to connected dashboards over WebSockets."""

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
router = APIRouter()


class ConnectionManager:
    """Keeps track of open dashboard connections.

    Note: connections live in this process's memory, so run the API with a
    single worker (or swap this for Redis pub/sub to scale out).
    """

    def __init__(self) -> None:
        self.active: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self.active.discard(websocket)

    async def broadcast(self, message: dict) -> None:
        dead = []
        for websocket in list(self.active):
            try:
                await websocket.send_json(message)
            except Exception:  # client went away mid-send
                dead.append(websocket)
        for websocket in dead:
            self.disconnect(websocket)


@router.websocket("/ws/transactions")
async def transactions_feed(websocket: WebSocket) -> None:
    manager: ConnectionManager = websocket.app.state.ws_manager
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()  # we ignore client messages (keep-alive pings)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
