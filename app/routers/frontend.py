import asyncio
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse
from app.routers.auth import get_current_user
from app.discord_manager import bot_manager

router = APIRouter()

@router.get("/")
async def serve_frontend(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/auth/login")
    with open("static/dashboard.html", "r") as f:
        html = f.read()
    return HTMLResponse(content=html)

@router.get("/api/stream")
async def stream_status(request: Request, user: dict = Depends(get_current_user)):
    """ Server-Sent Events endpoint to push updates to the UI """
    async def event_generator():
        q = asyncio.Queue()
        bot_manager.subscribers.append(q)
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    yield f"data: ping\n\n"
        finally:
            if q in bot_manager.subscribers:
                bot_manager.subscribers.remove(q)
                
    return StreamingResponse(event_generator(), media_type="text/event-stream")
