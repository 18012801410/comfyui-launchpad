"""SSE 事件流（API-020）：领域事件总线 → text/event-stream。"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.api.deps import require_token
from app.core.config import PanelSettings
from app.core.events import EventBus, Subscription

router = APIRouter(prefix="/api")

VALID_TOPICS = {"process", "logs", "downloads", "versions", "panel"}
DEFAULT_HEARTBEAT_S = 15.0

SettingsDep = Annotated[PanelSettings, Depends(require_token)]


@router.get("/events")
async def events(
    request: Request,
    _s: SettingsDep,
    topics: str = "",
) -> StreamingResponse:
    bus: EventBus = request.app.state.events
    heartbeat: float = getattr(request.app.state, "sse_heartbeat", DEFAULT_HEARTBEAT_S)
    wanted = {t for t in topics.split(",") if t} & VALID_TOPICS
    if not wanted:
        wanted = set(VALID_TOPICS)
    sub: Subscription = bus.subscribe(wanted)

    async def stream() -> AsyncIterator[str]:
        try:
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    topic, payload = await asyncio.wait_for(
                        sub.queue.get(), timeout=heartbeat
                    )
                    yield f"event: {topic}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            with contextlib.suppress(KeyError, ValueError):
                bus.unsubscribe(sub)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
