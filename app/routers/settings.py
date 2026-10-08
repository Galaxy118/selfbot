import asyncio
import aiosqlite
from fastapi import APIRouter, Depends, HTTPException
from app.routers.auth import get_current_user
from app.database import DB_PATH, is_global_active
from app.discord_manager import bot_manager

router = APIRouter()

@router.get("/api/me")
async def get_me(user: dict = Depends(get_current_user)):
    return user

@router.get("/api/settings")
async def get_settings(user: dict = Depends(get_current_user)):
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Admin only")
    return {"global_active": await is_global_active()}

@router.put("/api/settings/global_active")
async def update_global_active(data: dict, user: dict = Depends(get_current_user)):
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Admin only")
        
    active = data.get("global_active", True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE system_settings SET global_active = ? WHERE id = 1", (active,))
        await db.commit()
    
    if active:
        asyncio.create_task(bot_manager.start_all())
    else:
        for tid in list(bot_manager.tasks.keys()):
            bot_manager.stop_bot(tid)
            
    return {"message": "Global status updated"}
