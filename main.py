import asyncio
import json
import sqlite3
import os
import secrets
import logging
from typing import Optional, List, Dict
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException, Depends, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from cryptography.fernet import Fernet
from dotenv import load_dotenv
import httpx
import websockets
from starlette.middleware.sessions import SessionMiddleware

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

CLIENT_ID = os.environ.get("CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET", "")
REDIRECT_URI = os.environ.get("REDIRECT_URI", "http://localhost:8000/auth/callback")
ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY")
SESSION_SECRET = os.environ.get("SESSION_SECRET", secrets.token_hex(32))
ADMIN_IDS = [uid.strip() for uid in os.environ.get("ADMIN_IDS", "").split(",") if uid.strip()]

if not ENCRYPTION_KEY:
    ENCRYPTION_KEY = Fernet.generate_key().decode()
    logger.warning("ENCRYPTION_KEY not found in .env. A temporary one was generated. Tokens will be lost on restart if not saved.")

fernet = Fernet(ENCRYPTION_KEY.encode())

def encrypt_token(token: str) -> str:
    return fernet.encrypt(token.encode()).decode()

def decrypt_token(encrypted_token: str) -> str:
    return fernet.decrypt(encrypted_token.encode()).decode()

# --- DB SETUP ---
def init_db():
    conn = sqlite3.connect("data.db")
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            discord_id TEXT PRIMARY KEY,
            username TEXT,
            avatar TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id TEXT NOT NULL,
            encrypted_token TEXT NOT NULL,
            status TEXT DEFAULT 'online',
            guild_id TEXT,
            channel_id TEXT,
            self_mute BOOLEAN DEFAULT 1,
            self_deaf BOOLEAN DEFAULT 0,
            FOREIGN KEY (owner_id) REFERENCES users(discord_id)
        )
    ''')
    conn.commit()
    conn.close()

# --- DISCORD MANAGER ---
class DiscordManager:
    def __init__(self):
        self.tasks: Dict[int, asyncio.Task] = {} # token_id -> Task
        self.ws_connections: Dict[int, websockets.WebSocketClientProtocol] = {}

    async def start_all(self):
        conn = sqlite3.connect("data.db")
        c = conn.cursor()
        c.execute("SELECT id, encrypted_token, status, guild_id, channel_id, self_mute, self_deaf FROM tokens")
        rows = c.fetchall()
        conn.close()

        for row in rows:
            self.start_bot(row[0], row[1], row[2], row[3], row[4], row[5], row[6])

    def start_bot(self, token_id, encrypted_token, status, guild_id, channel_id, self_mute, self_deaf):
        self.stop_bot(token_id)
        token = decrypt_token(encrypted_token)
        task = asyncio.create_task(self.run_bot(token_id, token, status, guild_id, channel_id, bool(self_mute), bool(self_deaf)))
        self.tasks[token_id] = task

    def stop_bot(self, token_id):
        if token_id in self.tasks:
            self.tasks[token_id].cancel()
            del self.tasks[token_id]

    async def run_bot(self, token_id, token, status, guild_id, channel_id, self_mute, self_deaf):
        API_VERSION = 10
        uri = f"wss://gateway.discord.gg/?v={API_VERSION}&encoding=json"
        
        async def heartbeat(ws, interval):
            try:
                while True:
                    await asyncio.sleep(interval / 1000)
                    await ws.send(json.dumps({"op": 1, "d": None}))
            except asyncio.CancelledError:
                pass

        while True:
            try:
                async with websockets.connect(uri, max_size=10 * 1024 * 1024) as ws:
                    self.ws_connections[token_id] = ws
                    
                    hello_msg = await ws.recv()
                    hello = json.loads(hello_msg)
                    heartbeat_interval = hello["d"]["heartbeat_interval"]
                    
                    hb_task = asyncio.create_task(heartbeat(ws, heartbeat_interval))
                    
                    await ws.send(json.dumps({
                        "op": 2,
                        "d": {
                            "token": token,
                            "properties": {
                                "$os": "windows",
                                "$browser": "chrome",
                                "$device": "pc"
                            },
                            "presence": {
                                "status": status,
                                "afk": False
                            }
                        }
                    }))

                    while True:
                        msg = await ws.recv()
                        event = json.loads(msg)
                        if event.get("t") == "READY":
                            logger.info(f"[Bot {token_id}] READY")
                            
                            if guild_id and channel_id:
                                await ws.send(json.dumps({
                                    "op": 4,
                                    "d": {
                                        "guild_id": guild_id,
                                        "channel_id": channel_id,
                                        "self_mute": self_mute,
                                        "self_deaf": self_deaf
                                    }
                                }))
                                logger.info(f"[Bot {token_id}] Joined Voice Channel")
                            break

                    # Keep listening
                    while True:
                        await ws.recv()

            except asyncio.CancelledError:
                if 'hb_task' in locals():
                    hb_task.cancel()
                logger.info(f"[Bot {token_id}] Task cancelled, stopping...")
                break
            except Exception as e:
                logger.error(f"[Bot {token_id}] Disconnected: {e}. Reconnecting in 5s...")
                await asyncio.sleep(5)

bot_manager = DiscordManager()

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    asyncio.create_task(bot_manager.start_all())
    yield
    # Shutdown
    for task in bot_manager.tasks.values():
        task.cancel()

app = FastAPI(lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)

os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- AUTH ---
DISCORD_API_URL = "https://discord.com/api/v10"

@app.get("/auth/login")
async def login():
    url = f"https://discord.com/oauth2/authorize?client_id={CLIENT_ID}&response_type=code&redirect_uri={REDIRECT_URI}&scope=identify"
    return RedirectResponse(url)

@app.get("/auth/callback")
async def auth_callback(request: Request, code: str):
    async with httpx.AsyncClient() as client:
        # Get access token
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
        
        # Get user info
        user_res = await client.get(f"{DISCORD_API_URL}/users/@me", headers={"Authorization": f"Bearer {access_token}"})
        if user_res.status_code != 200:
            return HTMLResponse("Failed to fetch user info", status_code=400)
            
        user_data = user_res.json()
        
        # Save user to DB
        conn = sqlite3.connect("data.db")
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO users (discord_id, username, avatar) VALUES (?, ?, ?)", 
                  (user_data["id"], user_data["username"], user_data.get("avatar", "")))
        conn.commit()
        conn.close()
        
        request.session["user_id"] = user_data["id"]
        request.session["username"] = user_data["username"]
        request.session["is_admin"] = user_data["id"] in ADMIN_IDS
        
        return RedirectResponse("/")

@app.get("/auth/logout")
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

# --- API ROUTES ---
@app.get("/api/me")
async def get_me(user: dict = Depends(get_current_user)):
    return user

class TokenCreate(BaseModel):
    token: str

@app.post("/api/tokens")
async def add_token(data: TokenCreate, user: dict = Depends(get_current_user)):
    # VERIFY TOKEN OWNERSHIP
    async with httpx.AsyncClient() as client:
        res = await client.get(f"{DISCORD_API_URL}/users/@me", headers={"Authorization": data.token})
        if res.status_code != 200:
            raise HTTPException(status_code=400, detail="Invalid token")
            
        token_user = res.json()
        if token_user["id"] != user["id"]:
            raise HTTPException(status_code=403, detail="This token does not belong to your Discord account.")
            
    encrypted_token = encrypt_token(data.token)
    
    conn = sqlite3.connect("data.db")
    c = conn.cursor()
    try:
        c.execute("INSERT INTO tokens (owner_id, encrypted_token) VALUES (?, ?)", (user["id"], encrypted_token))
        token_id = c.lastrowid
        conn.commit()
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=400, detail="Error saving token")
        
    conn.close()
    
    # Start bot
    bot_manager.start_bot(token_id, encrypted_token, 'online', None, None, True, False)
    return {"message": "Token added successfully"}

@app.get("/api/tokens")
async def get_tokens(user: dict = Depends(get_current_user)):
    conn = sqlite3.connect("data.db")
    c = conn.cursor()
    if user["is_admin"]:
        c.execute("SELECT id, owner_id, status, guild_id, channel_id FROM tokens")
    else:
        c.execute("SELECT id, owner_id, status, guild_id, channel_id FROM tokens WHERE owner_id = ?", (user["id"],))
    rows = c.fetchall()
    conn.close()
    
    tokens = [{"id": r[0], "owner_id": r[1], "status": r[2], "guild_id": r[3], "channel_id": r[4]} for r in rows]
    return tokens

class TokenUpdate(BaseModel):
    status: Optional[str] = None
    guild_id: Optional[str] = None
    channel_id: Optional[str] = None
    self_mute: Optional[bool] = None
    self_deaf: Optional[bool] = None

@app.put("/api/tokens/{token_id}")
async def update_token(token_id: int, data: TokenUpdate, user: dict = Depends(get_current_user)):
    conn = sqlite3.connect("data.db")
    c = conn.cursor()
    c.execute("SELECT owner_id, encrypted_token, status, guild_id, channel_id, self_mute, self_deaf FROM tokens WHERE id = ?", (token_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Token not found")
        
    if not user["is_admin"] and row[0] != user["id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="Forbidden")
        
    # Update DB
    new_status = data.status if data.status is not None else row[2]
    new_guild_id = data.guild_id if data.guild_id is not None else row[3]
    new_channel_id = data.channel_id if data.channel_id is not None else row[4]
    new_self_mute = data.self_mute if data.self_mute is not None else row[5]
    new_self_deaf = data.self_deaf if data.self_deaf is not None else row[6]
    
    c.execute('''UPDATE tokens SET status = ?, guild_id = ?, channel_id = ?, self_mute = ?, self_deaf = ? WHERE id = ?''', 
              (new_status, new_guild_id, new_channel_id, new_self_mute, new_self_deaf, token_id))
    conn.commit()
    conn.close()
    
    # Restart bot with new config
    bot_manager.start_bot(token_id, row[1], new_status, new_guild_id, new_channel_id, new_self_mute, new_self_deaf)
    
    return {"message": "Token updated"}

@app.delete("/api/tokens/{token_id}")
async def delete_token(token_id: int, user: dict = Depends(get_current_user)):
    conn = sqlite3.connect("data.db")
    c = conn.cursor()
    c.execute("SELECT owner_id FROM tokens WHERE id = ?", (token_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Token not found")
        
    if not user["is_admin"] and row[0] != user["id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="Forbidden")
        
    c.execute("DELETE FROM tokens WHERE id = ?", (token_id,))
    conn.commit()
    conn.close()
    
    bot_manager.stop_bot(token_id)
    return {"message": "Token deleted"}

# --- FRONTEND ROUTES ---
@app.get("/")
async def serve_frontend(request: Request):
    if not request.session.get("user_id"):
        return FileResponse("static/index.html")
    return FileResponse("static/dashboard.html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
