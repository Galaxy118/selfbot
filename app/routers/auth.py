import httpx
import sqlite3
from fastapi import APIRouter, Request, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from app.config import CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, DISCORD_API_URL, OWNER_IDS, DB_PATH
import aiosqlite

router = APIRouter()

@router.get("/auth/login")
async def login():
    url = f"https://discord.com/oauth2/authorize?client_id={CLIENT_ID}&response_type=code&redirect_uri={REDIRECT_URI}&scope=identify"
    return RedirectResponse(url)

@router.get("/auth/callback")
async def auth_callback(request: Request, code: str):
    async with httpx.AsyncClient() as client:
        data = {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        token_res = await client.post("https://discord.com/api/oauth2/token", data=data, headers=headers)
        
        if token_res.status_code != 200:
            return HTMLResponse("Failed to authenticate with Discord", status_code=400)
            
        token_data = token_res.json()
        access_token = token_data.get("access_token")
        
        user_res = await client.get(f"{DISCORD_API_URL}/users/@me", headers={"Authorization": f"Bearer {access_token}"})
        if user_res.status_code != 200:
            return HTMLResponse("Failed to fetch user info", status_code=400)
            
        user_data = user_res.json()
        
        is_owner = user_data["id"] in OWNER_IDS
        is_admin = is_owner
        max_tokens = 1
        can_use_proxies = False
        can_see_all_accounts = False
        can_see_tokens = False
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT OR IGNORE INTO users (discord_id, username, avatar) VALUES (?, ?, ?)", 
                      (user_data["id"], user_data["username"], user_data.get("avatar", "")))
            # Update username and avatar in case they changed
            await db.execute("UPDATE users SET username = ?, avatar = ? WHERE discord_id = ?",
                      (user_data["username"], user_data.get("avatar", ""), user_data["id"]))
            
            async with db.execute("SELECT is_admin, max_tokens, can_use_proxies, can_see_all_accounts, can_see_tokens FROM users WHERE discord_id = ?", (user_data["id"],)) as cursor:
                row = await cursor.fetchone()
                if row:
                    if not is_owner:
                        is_admin = bool(row[0])
                    max_tokens = row[1]
                    can_use_proxies = bool(row[2])
                    can_see_all_accounts = bool(row[3])
                    can_see_tokens = bool(row[4])
            await db.commit()
        
        request.session["user_id"] = user_data["id"]
        request.session["username"] = user_data["username"]
        request.session["is_admin"] = is_admin
        request.session["is_owner"] = is_owner
        request.session["max_tokens"] = max_tokens
        request.session["can_use_proxies"] = can_use_proxies
        request.session["can_see_all_accounts"] = can_see_all_accounts
        request.session["can_see_tokens"] = can_see_tokens
        
        return RedirectResponse("/")

@router.get("/auth/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")

def get_current_user(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
        
    is_owner = user_id in OWNER_IDS
    is_admin = request.session.get("is_admin") or is_owner
    
    return {
        "id": user_id,
        "username": request.session.get("username"),
        "is_admin": is_admin,
        "is_owner": is_owner,
        "max_tokens": request.session.get("max_tokens", 1),
        "can_use_proxies": request.session.get("can_use_proxies", False) or is_owner or is_admin,
        "can_see_all_accounts": request.session.get("can_see_all_accounts", False) or is_owner or is_admin,
        "can_see_tokens": request.session.get("can_see_tokens", False) or is_owner or is_admin
    }
