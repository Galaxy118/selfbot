import asyncio
import aiosqlite
from fastapi import APIRouter, Depends, HTTPException
from app.routers.auth import get_current_user
from app.database import DB_PATH, is_global_active
from app.discord_manager import bot_manager
from pydantic import BaseModel

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

@router.get("/api/proxies")
async def get_proxies(user: dict = Depends(get_current_user)):
    if not user.get("is_admin") and not user.get("is_owner") and not user.get("can_use_proxies"):
        return []
    import os
    proxies = []
    proxy_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'proxies.txt')
    if os.path.exists(proxy_file):
        with open(proxy_file, 'r') as f:
            proxies = [line.strip() for line in f if line.strip()]
    return proxies

@router.get("/api/users")
async def get_users(user: dict = Depends(get_current_user)):
    if not user.get("is_owner") and not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin or Owner only")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT discord_id, username, avatar, is_admin, max_tokens, can_use_proxies, can_see_all_accounts, can_see_tokens FROM users") as cursor:
            rows = await cursor.fetchall()
            
    users_list = []
    from app.config import OWNER_IDS
    for r in rows:
        if r[0] in OWNER_IDS:
            continue
        users_list.append({
            "discord_id": r[0],
            "username": r[1],
            "avatar": r[2],
            "is_admin": bool(r[3]),
            "max_tokens": r[4],
            "can_use_proxies": bool(r[5]),
            "can_see_all_accounts": bool(r[6]),
            "can_see_tokens": bool(r[7]),
            "is_owner": False  # They are not owner since we skip owners
        })
    return users_list


class UserUpdate(BaseModel):
    is_admin: bool
    max_tokens: int
    can_use_proxies: bool
    can_see_all_accounts: bool
    can_see_tokens: bool

@router.put("/api/users/{discord_id}")
async def update_user(discord_id: str, data: UserUpdate, user: dict = Depends(get_current_user)):
    if not user.get("is_owner") and not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin or Owner only")
        
    from app.config import OWNER_IDS
    if discord_id in OWNER_IDS and not user.get("is_owner"):
        raise HTTPException(status_code=403, detail="Cannot modify an owner")
        
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_admin = ?, max_tokens = ?, can_use_proxies = ?, can_see_all_accounts = ?, can_see_tokens = ? WHERE discord_id = ?", 
                  (data.is_admin, data.max_tokens, data.can_use_proxies, data.can_see_all_accounts, data.can_see_tokens, discord_id))
        await db.commit()
    
    return {"message": "User updated"}
