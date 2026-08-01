from __future__ import annotations

import asyncio
from contextlib import suppress

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.market_fund_stream import get_market_fund_stream


router = APIRouter(prefix="/api/market", tags=["market-fund"])

_MAX_CONNECTIONS = 10
_MAX_CODES = 500
_IDLE_TIMEOUT_SECONDS = 300
_active_connections = 0


@router.websocket("/fund-stream")
async def market_fund_stream(websocket: WebSocket) -> None:
    global _active_connections
    if _active_connections >= _MAX_CONNECTIONS:
        await websocket.close(code=1013, reason="too many connections")
        return
    _active_connections += 1
    await websocket.accept()
    stream = get_market_fund_stream()
    queue = None
    try:
        initial = await asyncio.wait_for(websocket.receive_json(), timeout=10)
        codes = initial.get("codes") if isinstance(initial, dict) else []
        codes = (codes if isinstance(codes, list) else [])[:_MAX_CODES]
        queue = await stream.subscribe(codes)
        await websocket.send_json(queue.get_nowait())
        while True:
            client_task = asyncio.create_task(websocket.receive_json())
            patch_task = asyncio.create_task(queue.get())
            done, pending = await asyncio.wait(
                {client_task, patch_task},
                return_when=asyncio.FIRST_COMPLETED,
                timeout=_IDLE_TIMEOUT_SECONDS,
            )
            if not done:
                break
            for task in pending:
                task.cancel()
            if client_task in done:
                message = client_task.result()
                updated = message.get("codes") if isinstance(message, dict) else []
                if isinstance(updated, list):
                    updated = updated[:_MAX_CODES]
                    await stream.update(queue, updated)
                    await websocket.send_json(await stream.snapshot(updated))
            if patch_task in done:
                await websocket.send_json(patch_task.result())
    except (WebSocketDisconnect, asyncio.TimeoutError):
        pass
    finally:
        _active_connections -= 1
        if queue is not None:
            stream.unsubscribe(queue)
        for task_name in ("client_task", "patch_task"):
            task = locals().get(task_name)
            if isinstance(task, asyncio.Task) and not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
