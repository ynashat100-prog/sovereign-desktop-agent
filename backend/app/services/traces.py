"""WebSocket trace hub used by every runtime component."""

from __future__ import annotations

from collections import defaultdict

from fastapi import WebSocket

from app.models.schemas import TraceEvent


class TraceHub:
    def __init__(self) -> None:
        self._connections: defaultdict[str, set[WebSocket]] = defaultdict(set)

    async def connect(
        self, session_id: str, websocket: WebSocket, subprotocol: str | None = None
    ) -> None:
        await websocket.accept(subprotocol=subprotocol)
        self._connections[session_id].add(websocket)

    def disconnect(self, session_id: str, websocket: WebSocket) -> None:
        self._connections[session_id].discard(websocket)

    async def publish(self, session_id: str, event: TraceEvent) -> None:
        stale: list[WebSocket] = []
        for websocket in self._connections[session_id]:
            try:
                await websocket.send_json(event.model_dump(mode="json"))
            except Exception:
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(session_id, websocket)

    async def wait_for_disconnect(self, websocket: WebSocket) -> None:
        try:
            while True:
                await websocket.receive_text()
        except Exception:
            return


trace_hub = TraceHub()
