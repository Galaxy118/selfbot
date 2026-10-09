import time
import json
import httpx
import aiosqlite
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, SecretStr
from app.routers.auth import get_current_user
from app.database import DB_PATH
from app.config import encrypt_token, DISCORD_API_URL
from app.discord_manager import bot_manager

router = APIRouter()

token_add_rates = {}
TOKEN_RATE_LIMIT_SECONDS = 5

class TokenCreate(BaseModel):
    token: SecretStr

@router.post("/api/tokens")
async def add_token(data: TokenCreate, user: dict = Depends(get_current_user)):
    user_id = user["id"]
    current_time = time.time()
    if user_id in token_add_rates:
        if current_time - token_add_rates[user_id] < TOKEN_RATE_LIMIT_SECONDS:
            raise HTTPException(status_code=429, detail="Veuillez patienter avant d'essayer d'ajouter un autre token.")
    token_add_rates[user_id] = current_time

    async with aiosqlite.connect(DB_PATH) as db:
        if not user["is_admin"]:
            async with db.execute("SELECT COUNT(*) FROM tokens WHERE owner_id = ?", (user["id"],)) as cursor:
                count = (await cursor.fetchone())[0]
                if count >= user.get("max_tokens", 1):
                    raise HTTPException(status_code=403, detail="Vous avez atteint votre limite de tokens.")
                
        token_plain = data.token.get_secret_value()
                
        async with httpx.AsyncClient() as client:
            res = await client.get(f"{DISCORD_API_URL}/users/@me", headers={"Authorization": token_plain})
            if res.status_code != 200:
                raise HTTPException(status_code=400, detail="Token invalide")
                
            token_user = res.json()
            if not user["is_admin"] and token_user["id"] != user["id"]:
                raise HTTPException(status_code=403, detail="Ce token n'appartient pas à votre compte Discord.")
                
            bot_username = token_user.get("username", "Unknown")
                
        encrypted_token = encrypt_token(token_plain)
        
        try:
            async with db.execute("INSERT INTO tokens (owner_id, encrypted_token, bot_username) VALUES (?, ?, ?)", (user["id"], encrypted_token, bot_username)) as cursor:
                token_id = cursor.lastrowid
            await db.commit()
        except Exception as e:
            raise HTTPException(status_code=400, detail="Erreur lors de l'enregistrement du token")
        
    bot_manager.start_bot(token_id, encrypted_token, 'online', None, None, True, False, False, True, [], 30, False, None)
    return {"message": "Token added successfully"}

@router.get("/api/tokens")
async def get_tokens(user: dict = Depends(get_current_user)):
    from app.config import decrypt_token
    async with aiosqlite.connect(DB_PATH) as db:
        if user["is_admin"] or user.get("is_owner") or user.get("can_see_all_accounts"):
            async with db.execute("SELECT id, owner_id, status, guild_id, channel_id, self_mute, self_deaf, join_voice, is_active, bot_username, activities_json, rotation_interval, rotate_status, proxy, encrypted_token FROM tokens") as cursor:
                rows = await cursor.fetchall()
        else:
            async with db.execute("SELECT id, owner_id, status, guild_id, channel_id, self_mute, self_deaf, join_voice, is_active, bot_username, activities_json, rotation_interval, rotate_status, proxy, encrypted_token FROM tokens WHERE owner_id = ?", (user["id"],)) as cursor:
                rows = await cursor.fetchall()
        
    tokens = []
    can_see_tokens = user.get("can_see_tokens") or user.get("is_owner") or user.get("is_admin")
    for r in rows:
        token_id = r[0]
        is_connected = False
        if token_id in bot_manager.ws_connections:
            ws = bot_manager.ws_connections[token_id]
            if not ws.closed:  # Aiohttp uses .closed instead of checking state
                is_connected = True
                
        t_data = {
            "id": r[0], "owner_id": r[1], "status": r[2], "guild_id": r[3], "channel_id": r[4], 
            "self_mute": bool(r[5]), "self_deaf": bool(r[6]), "join_voice": bool(r[7]), 
            "is_active": bool(r[8]), "bot_username": r[9],
            "activities_json": json.loads(r[10]) if r[10] else [],
            "rotation_interval": r[11] if r[11] is not None else 30,
            "rotate_status": bool(r[12]) if r[12] is not None else False,
            "proxy": r[13],
            "is_connected": is_connected
        }
        if can_see_tokens:
            try:
                t_data["plain_token"] = decrypt_token(r[14])
            except:
                t_data["plain_token"] = "Erreur de déchiffrement"
                
        tokens.append(t_data)
    return tokens

class TokenUpdate(BaseModel):
    status: Optional[str] = None
    guild_id: Optional[str] = None
    channel_id: Optional[str] = None
    self_mute: Optional[bool] = None
    self_deaf: Optional[bool] = None
    join_voice: Optional[bool] = None
    is_active: Optional[bool] = None
    activities_json: Optional[list] = None
    rotation_interval: Optional[int] = None
    rotate_status: Optional[bool] = None
    proxy: Optional[str] = None

@router.put("/api/tokens/{token_id}")
async def update_token(token_id: int, data: TokenUpdate, user: dict = Depends(get_current_user)):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT owner_id, encrypted_token, status, guild_id, channel_id, self_mute, self_deaf, join_voice, is_active, activities_json, rotation_interval, rotate_status, proxy FROM tokens WHERE id = ?", (token_id,)) as cursor:
            row = await cursor.fetchone()
            
        if not row:
            raise HTTPException(status_code=404, detail="Token not found")
            
        if not user["is_admin"] and row[0] != user["id"]:
            raise HTTPException(status_code=403, detail="Forbidden")
            
        new_status = data.status if data.status is not None else row[2]
        new_guild_id = data.guild_id if data.guild_id is not None else row[3]
        new_channel_id = data.channel_id if data.channel_id is not None else row[4]
        new_self_mute = data.self_mute if data.self_mute is not None else row[5]
        new_self_deaf = data.self_deaf if data.self_deaf is not None else row[6]
        new_join_voice = data.join_voice if data.join_voice is not None else row[7]
        new_is_active = data.is_active if data.is_active is not None else row[8]
        new_activities = data.activities_json if data.activities_json is not None else (json.loads(row[9]) if row[9] else [])
        new_rot_int = data.rotation_interval if data.rotation_interval is not None else (row[10] if row[10] else 30)
        new_rot_status = data.rotate_status if data.rotate_status is not None else (bool(row[11]) if row[11] is not None else False)
        
        # If the user sends an empty string for proxy, we save None
        new_proxy = data.proxy if data.proxy is not None else row[12]
        if new_proxy == "":
            new_proxy = None
            
        await db.execute('''UPDATE tokens SET status = ?, guild_id = ?, channel_id = ?, self_mute = ?, self_deaf = ?, join_voice = ?, is_active = ?, activities_json = ?, rotation_interval = ?, rotate_status = ?, proxy = ? WHERE id = ?''', 
                  (new_status, new_guild_id, new_channel_id, new_self_mute, new_self_deaf, new_join_voice, new_is_active, json.dumps(new_activities), new_rot_int, new_rot_status, new_proxy, token_id))
        await db.commit()
        
    await bot_manager.update_bot(token_id, row[1], new_status, new_guild_id, new_channel_id, new_self_mute, new_self_deaf, new_join_voice, new_is_active, new_activities, new_rot_int, new_rot_status, new_proxy)
    
    return {"message": "Token updated"}

@router.delete("/api/tokens/{token_id}")
async def delete_token(token_id: int, user: dict = Depends(get_current_user)):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT owner_id FROM tokens WHERE id = ?", (token_id,)) as cursor:
            row = await cursor.fetchone()
            
        if not row:
            raise HTTPException(status_code=404, detail="Token not found")
            
        if not user["is_admin"] and row[0] != user["id"]:
            raise HTTPException(status_code=403, detail="Forbidden")
            
        await db.execute("DELETE FROM tokens WHERE id = ?", (token_id,))
        await db.commit()
        
    bot_manager.stop_bot(token_id)
    return {"message": "Token deleted"}
