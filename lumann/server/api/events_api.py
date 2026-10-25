"""The single SSE stream. One EventSource in the browser, fanned out by type."""
import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ..jobs.events import bus

router = APIRouter(prefix="/api")

KEEPALIVE = 20          # seconds; keeps proxies and idle sockets from timing out


@router.get("/events")
async def stream(request: Request):
    queue = bus.subscribe()

    async def generator():
        try:
            yield _frame({"type": "hello"})
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield _frame(event)
        finally:
            bus.unsubscribe(queue)

    return StreamingResponse(generator(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    })


def _frame(event):
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
