import asyncio
import json
import logging
from typing import Dict, List
import aiohttp

from app.config import decrypt_token
from app.database import DB_PATH, is_global_active
import aiosqlite

logger = logging.getLogger(__name__)

class DiscordManager:
    def __init__(self):
        self.tasks: Dict[int, asyncio.Task] = {}
        self.ws_connections: Dict[int, aiohttp.ClientWebSocketResponse] = {}
        self.bot_configs: Dict[int, dict] = {}
        self.rotator_tasks: Dict[int, asyncio.Task] = {}
        self.subscribers: List[asyncio.Queue] = []
        self.session = None

    async def _get_session(self):
        if not self.session:
            self.session = aiohttp.ClientSession()
        return self.session

    async def broadcast_status(self):
        msg = "update"
        for sub in self.subscribers:
            try:
                sub.put_nowait(msg)
            except asyncio.QueueFull:
                pass

    async def start_all(self):
        if not await is_global_active():
            return
            
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT id, encrypted_token, status, guild_id, channel_id, self_mute, self_deaf, join_voice, is_active, activities_json, rotation_interval, rotate_status, proxy FROM tokens") as cursor:
                rows = await cursor.fetchall()
                
        for row in rows:
            activities = json.loads(row[9]) if row[9] else []
            rot_int = row[10] if row[10] else 30
            rot_status = bool(row[11]) if row[11] is not None else False
            self.start_bot(row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8], activities, rot_int, rot_status, row[12])

    def start_bot(self, token_id, encrypted_token, status, guild_id, channel_id, self_mute, self_deaf, join_voice, is_active, activities, rotation_interval, rotate_status, proxy):
        self.stop_bot(token_id)
        if not is_active:
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
            "rotation_interval": max(15, rotation_interval),
            "rotate_status": bool(rotate_status),
            "proxy": proxy
        }
        task = asyncio.create_task(self.run_bot(token_id))
        self.tasks[token_id] = task

    def stop_bot(self, token_id):
        if token_id in self.tasks:
            self.tasks[token_id].cancel()
            del self.tasks[token_id]
        if token_id in self.bot_configs:
            del self.bot_configs[token_id]
        if token_id in self.rotator_tasks:
            self.rotator_tasks[token_id].cancel()
            del self.rotator_tasks[token_id]
        asyncio.create_task(self.broadcast_status())

    async def update_bot(self, token_id, encrypted_token, status, guild_id, channel_id, self_mute, self_deaf, join_voice, is_active, activities, rotation_interval, rotate_status, proxy):
        old_config = self.bot_configs.get(token_id)
        token = decrypt_token(encrypted_token)
        needs_restart = True
        
        if old_config and old_config["is_active"] and is_active and await is_global_active():
            if old_config["token"] == token and old_config["proxy"] == proxy:
                needs_restart = False
                
        if needs_restart:
            self.stop_bot(token_id)
            if is_active and await is_global_active():
                self.start_bot(token_id, encrypted_token, status, guild_id, channel_id, self_mute, self_deaf, join_voice, is_active, activities, rotation_interval, rotate_status, proxy)
        else:
            self.bot_configs[token_id].update({
                "status": status,
                "guild_id": guild_id,
                "channel_id": channel_id,
                "self_mute": bool(self_mute),
                "self_deaf": bool(self_deaf),
                "join_voice": bool(join_voice),
                "activities": activities,
                "rotation_interval": max(15, rotation_interval),
                "rotate_status": bool(rotate_status)
            })
            
            ws = self.ws_connections.get(token_id)
            if ws and not ws.closed:
                if join_voice and guild_id and channel_id:
                    asyncio.create_task(ws.send_json({
                        "op": 4,
                        "d": {
                            "guild_id": guild_id,
                            "channel_id": channel_id,
                            "self_mute": bool(self_mute),
                            "self_deaf": bool(self_deaf)
                        }
                    }))
                elif guild_id:
                    asyncio.create_task(ws.send_json({
                        "op": 4,
                        "d": {
                            "guild_id": guild_id,
                            "channel_id": None,
                            "self_mute": False,
                            "self_deaf": False
                        }
                    }))
                
                if token_id in self.rotator_tasks:
                    self.rotator_tasks[token_id].cancel()
                    del self.rotator_tasks[token_id]
                
                if rotate_status and activities and len(activities) > 1:
                    self.rotator_tasks[token_id] = asyncio.create_task(self.activity_rotator(ws, max(15, rotation_interval), activities, status))
                else:
                    act = activities[0] if activities else None
                    asyncio.create_task(ws.send_json({
                        "op": 3,
                        "d": {
                            "status": status,
                            "since": 0,
                            "activities": [act] if act else [],
                            "afk": False
                        }
                    }))

    async def activity_rotator(self, ws, interval, activities, status):
        try:
            idx = 0
            while True:
                await asyncio.sleep(interval)
                idx = (idx + 1) % len(activities)
                await ws.send_json({
                    "op": 3,
                    "d": {
                        "status": status,
                        "since": 0,
                        "activities": [activities[idx]],
                        "afk": False
                    }
                })
        except asyncio.CancelledError:
            pass

    async def run_bot(self, token_id):
        API_VERSION = 10
        uri = f"wss://gateway.discord.gg/?v={API_VERSION}&encoding=json"
        
        async def heartbeat(ws, interval):
            try:
                while True:
                    await asyncio.sleep(interval / 1000)
                    await ws.send_json({"op": 1, "d": None})
            except asyncio.CancelledError:
                pass

        session = await self._get_session()
        
        while True:
            try:
                config = self.bot_configs.get(token_id)
                if not config:
                    break
                    
                proxy = config.get("proxy")
                if proxy and not proxy.startswith("http"):
                    proxy = f"http://{proxy}"
                    
                # aiohttp proxy setup
                async with session.ws_connect(uri, proxy=proxy, timeout=30.0) as ws:
                    self.ws_connections[token_id] = ws
                    asyncio.create_task(self.broadcast_status())
                    
                    hello_msg = await ws.receive_json()
                    heartbeat_interval = hello_msg["d"]["heartbeat_interval"]
                    
                    hb_task = asyncio.create_task(heartbeat(ws, heartbeat_interval))
                    
                    initial_activities = []
                    if config.get("rotate_status") and config.get("activities") and len(config["activities"]) > 0:
                        initial_activities = [config["activities"][0]]

                    # Anti-detect Discord PC IDENTIFY Payload
                    identify_payload = {
                        "op": 2,
                        "d": {
                            "token": config["token"],
                            "capabilities": 16381,
                            "properties": {
                                "os": "Windows",
                                "browser": "Discord Client",
                                "release_channel": "stable",
                                "client_version": "1.0.9024",
                                "os_version": "10.0.19045",
                                "os_arch": "x64",
                                "system_locale": "fr-FR",
                                "client_build_number": 248065,
                                "native_build_number": 41819
                            },
                            "presence": {
                                "status": config["status"],
                                "since": 0,
                                "activities": initial_activities,
                                "afk": False
                            },
                            "compress": False,
                            "client_state": {
                                "guild_versions": {},
                                "highest_last_message_id": "0",
                                "read_state_version": 0,
                                "user_guild_settings_version": -1,
                                "user_settings_version": -1,
                                "private_channels_version": "0",
                                "api_code_version": 0
                            }
                        }
                    }

                    await ws.send_json(identify_payload)
                    
                    if config.get("rotate_status") and config.get("activities") and len(config["activities"]) > 1:
                        self.rotator_tasks[token_id] = asyncio.create_task(self.activity_rotator(
                            ws, 
                            config["rotation_interval"], 
                            config["activities"], 
                            config["status"]
                        ))

                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            event = json.loads(msg.data)
                            if event.get("t") == "READY":
                                logger.info(f"[Bot {token_id}] READY")
                                
                                config = self.bot_configs.get(token_id)
                                if config and config["join_voice"] and config["guild_id"] and config["channel_id"]:
                                    await ws.send_json({
                                        "op": 4,
                                        "d": {
                                            "guild_id": config["guild_id"],
                                            "channel_id": config["channel_id"],
                                            "self_mute": config["self_mute"],
                                            "self_deaf": config["self_deaf"]
                                        }
                                    })
                                    logger.info(f"[Bot {token_id}] Joined Voice Channel")
                                elif config and not config["join_voice"] and config["guild_id"]:
                                    await ws.send_json({
                                        "op": 4,
                                        "d": {
                                            "guild_id": config["guild_id"],
                                            "channel_id": None,
                                            "self_mute": False,
                                            "self_deaf": False
                                        }
                                    })

            except asyncio.CancelledError:
                if 'hb_task' in locals():
                    hb_task.cancel()
                if token_id in self.rotator_tasks:
                    self.rotator_tasks[token_id].cancel()
                    del self.rotator_tasks[token_id]
                logger.info(f"[Bot {token_id}] Task cancelled, stopping...")
                if token_id in self.ws_connections:
                    del self.ws_connections[token_id]
                asyncio.create_task(self.broadcast_status())
                break
            except Exception as e:
                logger.error(f"[Bot {token_id}] Disconnected: {e}. Reconnecting in 5s...")
                if token_id in self.ws_connections:
                    del self.ws_connections[token_id]
                asyncio.create_task(self.broadcast_status())
                if token_id in self.rotator_tasks:
                    self.rotator_tasks[token_id].cancel()
                    del self.rotator_tasks[token_id]
                await asyncio.sleep(5)

bot_manager = DiscordManager()
