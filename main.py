import asyncio
import json
import sqlite3
import os
import secrets
import logging
import time
from typing import Optional, List, Dict
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException, Depends, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, SecretStr
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware
import httpx
import websockets
from starlette.middleware.sessions import SessionMiddleware

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ENV_PATH = os.environ.get("ENV_PATH", ".env")
load_dotenv(ENV_PATH)

DB_PATH = os.environ.get("DB_PATH", "data.db")

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
    conn = sqlite3.connect(DB_PATH)
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
            join_voice BOOLEAN DEFAULT 0,
            is_active BOOLEAN DEFAULT 1,
            bot_username TEXT,
            FOREIGN KEY (owner_id) REFERENCES users(discord_id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS system_settings (
            id INTEGER PRIMARY KEY,
            global_active BOOLEAN DEFAULT 1
        )
    ''')
    c.execute("INSERT OR IGNORE INTO system_settings (id, global_active) VALUES (1, 1)")
    try:
        c.execute("ALTER TABLE tokens ADD COLUMN join_voice BOOLEAN DEFAULT 0")
    except sqlite3.OperationalError:
        pass # Column exists
    try:
        c.execute("ALTER TABLE tokens ADD COLUMN is_active BOOLEAN DEFAULT 1")
    except sqlite3.OperationalError:
        pass # Column exists
    try:
        c.execute("ALTER TABLE tokens ADD COLUMN bot_username TEXT")
    except sqlite3.OperationalError:
    try:
        c.execute("ALTER TABLE tokens ADD COLUMN activities_json TEXT DEFAULT '[]'")
    except sqlite3.OperationalError:
        pass # Column exists
    try:
        c.execute("ALTER TABLE tokens ADD COLUMN rotation_interval INTEGER DEFAULT 30")
    except sqlite3.OperationalError:
        pass # Column exists
    conn.commit()
    conn.close()

def is_global_active():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT global_active FROM system_settings WHERE id = 1")
    res = c.fetchone()
    conn.close()
    return bool(res[0]) if res else True

# --- DISCORD MANAGER ---
class DiscordManager:
    def __init__(self):
        self.tasks: Dict[int, asyncio.Task] = {} # token_id -> Task
        self.ws_connections: Dict[int, websockets.WebSocketClientProtocol] = {}
        self.bot_configs: Dict[int, dict] = {}

    async def start_all(self):
        if not is_global_active():
            return
            
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id, encrypted_token, status, guild_id, channel_id, self_mute, self_deaf, join_voice, is_active, activities_json, rotation_interval FROM tokens")
        rows = c.fetchall()
        conn.close()

        for row in rows:
            activities = json.loads(row[9]) if row[9] else []
            rot_int = row[10] if row[10] else 30
            self.start_bot(row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8], activities, rot_int)

    def start_bot(self, token_id, encrypted_token, status, guild_id, channel_id, self_mute, self_deaf, join_voice, is_active, activities, rotation_interval):
        self.stop_bot(token_id)
        if not is_active or not is_global_active():
            return
            
        self.bot_configs[token_id] = {
            "token": decrypt_token(encrypted_token),
            "status": status,
            "guild_id": guild_id,
            "channel_id": channel_id,
            "self_mute": bool(self_mute),
            "self_deaf": bool(self_deaf),
            "join_voice": bool(join_voice),
            "is_active": bool(is_active),
            "activities": activities,
            "rotation_interval": max(15, rotation_interval) # minimum 15 seconds
        }
        task = asyncio.create_task(self.run_bot(token_id))
        self.tasks[token_id] = task

    def stop_bot(self, token_id):
        if token_id in self.tasks:
            self.tasks[token_id].cancel()
            del self.tasks[token_id]
        if token_id in self.bot_configs:
            del self.bot_configs[token_id]

    async def update_bot(self, token_id, encrypted_token, status, guild_id, channel_id, self_mute, self_deaf, join_voice, is_active, activities, rotation_interval):
        # Stop and restart completely if activities or interval changes to refresh the loop properly
        old_config = self.bot_configs.get(token_id, {})
        activities_changed = old_config.get("activities") != activities or old_config.get("rotation_interval") != rotation_interval
        
        if not is_active or not is_global_active() or activities_changed:
            self.stop_bot(token_id)
            if is_active and is_global_active():
                self.start_bot(token_id, encrypted_token, status, guild_id, channel_id, self_mute, self_deaf, join_voice, is_active, activities, rotation_interval)
            return

        if token_id not in self.tasks:
            self.start_bot(token_id, encrypted_token, status, guild_id, channel_id, self_mute, self_deaf, join_voice, is_active, activities, rotation_interval)
            return

        self.bot_configs[token_id] = {
            "token": decrypt_token(encrypted_token),
            "status": status,
            "guild_id": guild_id,
            "channel_id": channel_id,
            "self_mute": bool(self_mute),
            "self_deaf": bool(self_deaf),
            "join_voice": bool(join_voice),
            "is_active": bool(is_active),
            "activities": old_config.get("activities", []),
            "rotation_interval": old_config.get("rotation_interval", 30)
        }

        ws = self.ws_connections.get(token_id)
        if ws and ws.state.name == "OPEN":
            # Update presence if changed
            if old_config.get("status") != status:
                await ws.send(json.dumps({
                    "op": 3,
                    "d": {
                        "status": status,
                        "since": 0,
                        "activities": old_config.get("activities", [])[:1],
                        "afk": False
                    }
                }))
            
            # Update voice if changed
            voice_changed = (
                old_config.get("join_voice") != join_voice or
                old_config.get("guild_id") != guild_id or
                old_config.get("channel_id") != channel_id or
                old_config.get("self_mute") != self_mute or
                old_config.get("self_deaf") != self_deaf
            )
            
            if voice_changed:
                if join_voice and guild_id and channel_id:
                    await ws.send(json.dumps({
                        "op": 4,
                        "d": {
                            "guild_id": guild_id,
                            "channel_id": channel_id,
                            "self_mute": bool(self_mute),
                            "self_deaf": bool(self_deaf)
                        }
                    }))
                elif not join_voice and old_config.get("guild_id"):
                    await ws.send(json.dumps({
                        "op": 4,
                        "d": {
                            "guild_id": old_config.get("guild_id"),
                            "channel_id": None,
                            "self_mute": False,
                            "self_deaf": False
                        }
                    }))

    async def run_bot(self, token_id):
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
                config = self.bot_configs.get(token_id)
                if not config:
                    break
                    
                async with websockets.connect(uri, max_size=None) as ws:
                    self.ws_connections[token_id] = ws
                    
                    hello_msg = await ws.recv()
                    hello = json.loads(hello_msg)
                    heartbeat_interval = hello["d"]["heartbeat_interval"]
                    
                    hb_task = asyncio.create_task(heartbeat(ws, heartbeat_interval))
                    
                    # Prepare first activity
                    initial_activities = []
                    if config.get("activities") and len(config["activities"]) > 0:
                        initial_activities = [config["activities"][0]]

                    await ws.send(json.dumps({
                        "op": 2,
                        "d": {
                            "token": config["token"],
                            "properties": {
                                "$os": "windows",
                                "$browser": "chrome",
                                "$device": "pc"
                            },
                            "presence": {
                                "status": config["status"],
                                "afk": False,
                                "activities": initial_activities
                            }
                        }
                    }))
                    
                    rotator_task = None
                    if config.get("activities") and len(config["activities"]) > 1:
                        async def activity_rotator(ws, interval, activities, status):
                            try:
                                idx = 0
                                while True:
                                    await asyncio.sleep(interval)
                                    idx = (idx + 1) % len(activities)
                                    await ws.send(json.dumps({
                                        "op": 3,
                                        "d": {
                                            "status": status,
                                            "since": 0,
                                            "activities": [activities[idx]],
                                            "afk": False
                                        }
                                    }))
                            except asyncio.CancelledError:
                                pass
                                
                        rotator_task = asyncio.create_task(activity_rotator(
                            ws, 
                            config["rotation_interval"], 
                            config["activities"], 
                            config["status"]
                        ))

                    while True:
                        msg = await ws.recv()
                        event = json.loads(msg)
                        if event.get("t") == "READY":
                            logger.info(f"[Bot {token_id}] READY")
                            
                            config = self.bot_configs.get(token_id)
                            if config and config["join_voice"] and config["guild_id"] and config["channel_id"]:
                                await ws.send(json.dumps({
                                    "op": 4,
                                    "d": {
                                        "guild_id": config["guild_id"],
                                        "channel_id": config["channel_id"],
                                        "self_mute": config["self_mute"],
                                        "self_deaf": config["self_deaf"]
                                    }
                                }))
                                logger.info(f"[Bot {token_id}] Joined Voice Channel")
                            elif config and not config["join_voice"] and config["guild_id"]:
                                # Send disconnect op if disabled
                                await ws.send(json.dumps({
                                    "op": 4,
                                    "d": {
                                        "guild_id": config["guild_id"],
                                        "channel_id": None,
                                        "self_mute": False,
                                        "self_deaf": False
                                    }
                                }))
                            break

                    # Keep listening
                    while True:
                        await ws.recv()

            except asyncio.CancelledError:
                if 'hb_task' in locals():
                    hb_task.cancel()
                if 'rotator_task' in locals() and rotator_task:
                    rotator_task.cancel()
                logger.info(f"[Bot {token_id}] Task cancelled, stopping...")
                break
            except Exception as e:
                logger.error(f"[Bot {token_id}] Disconnected: {e}. Reconnecting in 5s...")
                if 'rotator_task' in locals() and rotator_task:
                    rotator_task.cancel()
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
        conn = sqlite3.connect(DB_PATH)
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

@app.get("/api/settings")
async def get_settings(user: dict = Depends(get_current_user)):
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Admin only")
    return {"global_active": is_global_active()}

@app.put("/api/settings/global_active")
async def update_global_active(data: dict, user: dict = Depends(get_current_user)):
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Admin only")
        
    active = data.get("global_active", True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE system_settings SET global_active = ? WHERE id = 1", (active,))
    conn.commit()
    conn.close()
    
    if active:
        asyncio.create_task(bot_manager.start_all())
    else:
        for tid in list(bot_manager.tasks.keys()):
            bot_manager.stop_bot(tid)
            
    return {"message": "Global status updated"}

# Rate Limiter pour l'ajout de tokens
token_add_rates = {}
TOKEN_RATE_LIMIT_SECONDS = 5

class TokenCreate(BaseModel):
    token: SecretStr

@app.post("/api/tokens")
async def add_token(data: TokenCreate, user: dict = Depends(get_current_user)):
    # Rate limiting
    user_id = user["id"]
    current_time = time.time()
    if user_id in token_add_rates:
        if current_time - token_add_rates[user_id] < TOKEN_RATE_LIMIT_SECONDS:
            raise HTTPException(status_code=429, detail="Veuillez patienter avant d'essayer d'ajouter un autre token.")
    token_add_rates[user_id] = current_time

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    if not user["is_admin"]:
        # Check if user already has a token
        c.execute("SELECT COUNT(*) FROM tokens WHERE owner_id = ?", (user["id"],))
        if c.fetchone()[0] >= 1:
            conn.close()
            raise HTTPException(status_code=403, detail="Vous ne pouvez ajouter qu'un seul token.")
            
    token_plain = data.token.get_secret_value()
            
    # VERIFY TOKEN (Fetch username regardless, check ownership only if not admin)
    async with httpx.AsyncClient() as client:
        res = await client.get(f"{DISCORD_API_URL}/users/@me", headers={"Authorization": token_plain})
        if res.status_code != 200:
            conn.close()
            raise HTTPException(status_code=400, detail="Token invalide")
            
        token_user = res.json()
        if not user["is_admin"] and token_user["id"] != user["id"]:
            conn.close()
            raise HTTPException(status_code=403, detail="Ce token n'appartient pas à votre compte Discord.")
            
        bot_username = token_user.get("username", "Unknown")
            
    encrypted_token = encrypt_token(token_plain)
    
    try:
        c.execute("INSERT INTO tokens (owner_id, encrypted_token, bot_username) VALUES (?, ?, ?)", (user["id"], encrypted_token, bot_username))
        token_id = c.lastrowid
        conn.commit()
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=400, detail="Erreur lors de l'enregistrement du token")
        
    conn.close()
    
    # Start bot
    bot_manager.start_bot(token_id, encrypted_token, 'online', None, None, True, False, False, True)
    return {"message": "Token added successfully"}

@app.get("/api/tokens")
async def get_tokens(user: dict = Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if user["is_admin"]:
        c.execute("SELECT id, owner_id, status, guild_id, channel_id, self_mute, self_deaf, join_voice, is_active, bot_username, activities_json, rotation_interval FROM tokens")
    else:
        c.execute("SELECT id, owner_id, status, guild_id, channel_id, self_mute, self_deaf, join_voice, is_active, bot_username, activities_json, rotation_interval FROM tokens WHERE owner_id = ?", (user["id"],))
    rows = c.fetchall()
    conn.close()
    
    tokens = []
    for r in rows:
        token_id = r[0]
        is_connected = False
        if token_id in bot_manager.ws_connections:
            ws = bot_manager.ws_connections[token_id]
            if ws.state.name == "OPEN":
                is_connected = True
                
        tokens.append({
            "id": r[0], "owner_id": r[1], "status": r[2], "guild_id": r[3], "channel_id": r[4], 
            "self_mute": bool(r[5]), "self_deaf": bool(r[6]), "join_voice": bool(r[7]), 
            "is_active": bool(r[8]), "bot_username": r[9],
            "activities_json": json.loads(r[10]) if r[10] else [],
            "rotation_interval": r[11] if r[11] is not None else 30,
            "is_connected": is_connected
        })
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

@app.put("/api/tokens/{token_id}")
async def update_token(token_id: int, data: TokenUpdate, user: dict = Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT owner_id, encrypted_token, status, guild_id, channel_id, self_mute, self_deaf, join_voice, is_active, activities_json, rotation_interval FROM tokens WHERE id = ?", (token_id,))
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
    new_join_voice = data.join_voice if data.join_voice is not None else row[7]
    new_is_active = data.is_active if data.is_active is not None else row[8]
    new_activities = data.activities_json if data.activities_json is not None else (json.loads(row[9]) if row[9] else [])
    new_rot_int = data.rotation_interval if data.rotation_interval is not None else (row[10] if row[10] else 30)
    
    c.execute('''UPDATE tokens SET status = ?, guild_id = ?, channel_id = ?, self_mute = ?, self_deaf = ?, join_voice = ?, is_active = ?, activities_json = ?, rotation_interval = ? WHERE id = ?''', 
              (new_status, new_guild_id, new_channel_id, new_self_mute, new_self_deaf, new_join_voice, new_is_active, json.dumps(new_activities), new_rot_int, token_id))
    conn.commit()
    conn.close()
    
    # Update bot dynamically
    await bot_manager.update_bot(token_id, row[1], new_status, new_guild_id, new_channel_id, new_self_mute, new_self_deaf, new_join_voice, new_is_active, new_activities, new_rot_int)
    
    return {"message": "Token updated"}

@app.delete("/api/tokens/{token_id}")
async def delete_token(token_id: int, user: dict = Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
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
