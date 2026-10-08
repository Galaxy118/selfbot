import httpx
import sqlite3
from fastapi import APIRouter, Request, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from app.config import CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, DISCORD_API_URL, ADMIN_IDS, DB_PATH
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
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT OR REPLACE INTO users (discord_id, username, avatar) VALUES (?, ?, ?)", 
                      (user_data["id"], user_data["username"], user_data.get("avatar", "")))
            await db.commit()
        
        request.session["user_id"] = user_data["id"]
        request.session["username"] = user_data["username"]
        request.session["is_admin"] = user_data["id"] in ADMIN_IDS
        
        return RedirectResponse("/")

@router.get("/auth/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")

def get_current_user(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return {
        "id": user_id,
        "username": request.session.get("username"),
        "is_admin": request.session.get("is_admin")
    }
