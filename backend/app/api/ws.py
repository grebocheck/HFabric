"""WebSocket endpoint: streams every event from the bus to the browser.

On connect we push the current GPU status so a freshly opened tab is in sync.
"""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from ..core.enums import EventType
from ..core.events import Event
from ..util import security

router = APIRouter(tags=["ws"])


@router.websocket("/ws")
async def ws_events(ws: WebSocket) -> None:
    if not security.websocket_is_authorized(ws):
        await ws.send_denial_response(JSONResponse({"detail": "authentication required"}, status_code=401))
        return
    await ws.accept()
    bus = ws.app.state.bus
    arbiter = ws.app.state.arbiter
    await ws.send_json(Event(EventType.GPU_STATUS, **arbiter.status()))
    async with bus.subscribe() as queue:
        try:
            while True:
                event = await queue.get()
                await ws.send_json(event)
        except WebSocketDisconnect:
            return
        except Exception:
            return
