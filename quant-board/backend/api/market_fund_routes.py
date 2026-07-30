from __future__ import annotations

import asyncio
from contextlib import suppress

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.market_fund_stream import get_market_fund_stream


router = APIRouter(prefix="/api/market", tags=["market-fund"])


@router.websocket("/fund-stream")
async def market_fund_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    stream = get_market_fund_stream()
    queue = None
    try:
        initial = await websocket.receive_json()
        codes = initial.get("codes") if isinstance(initial, dict) else []
        queue = await stream.subscribe(codes if isinstance(codes, list) else [])
        await websocket.send_json(queue.get_nowait())
        while True:
            client_task = asyncio.create_task(websocket.receive_json())
            patch_task = asyncio.create_task(queue.get())
            done, pending = await asyncio.wait({client_task, patch_task}, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            if client_task in done:
                message = client_task.result()
                updated = message.get("codes") if isinstance(message, dict) else []
                if isinstance(updated, list):
                    await stream.update(queue, updated)
                    await websocket.send_json(await stream.snapshot(updated))
            if patch_task in done:
                await websocket.send_json(patch_task.result())
    except WebSocketDisconnect:
        pass
    finally:
        if queue is not None:
            stream.unsubscribe(queue)
        for task_name in ("client_task", "patch_task"):
            task = locals().get(task_name)
            if isinstance(task, asyncio.Task) and not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
