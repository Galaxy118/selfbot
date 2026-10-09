import aiosqlite
from app.config import DB_PATH

async def _add_col(conn, table, col_name, definition):
    try:
        await conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {definition}")
    except aiosqlite.OperationalError:
        pass

async def init_db():
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA synchronous=NORMAL")
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                discord_id TEXT PRIMARY KEY,
                username TEXT,
                avatar TEXT,
                is_admin BOOLEAN DEFAULT 0,
                max_tokens INTEGER DEFAULT 1,
                can_use_proxies BOOLEAN DEFAULT 0,
                can_see_all_accounts BOOLEAN DEFAULT 0,
                can_see_tokens BOOLEAN DEFAULT 0
            )
        ''')
        await conn.execute('''
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
                activities_json TEXT DEFAULT '[]',
                rotation_interval INTEGER DEFAULT 30,
                rotate_status BOOLEAN DEFAULT 0,
                proxy TEXT,
                FOREIGN KEY (owner_id) REFERENCES users(discord_id)
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS system_settings (
                id INTEGER PRIMARY KEY,
                global_active BOOLEAN DEFAULT 1
            )
        ''')
        await conn.execute("INSERT OR IGNORE INTO system_settings (id, global_active) VALUES (1, 1)")
        
        # Migrations
        await _add_col(conn, "tokens", "join_voice", "BOOLEAN DEFAULT 0")
        await _add_col(conn, "tokens", "is_active", "BOOLEAN DEFAULT 1")
        await _add_col(conn, "tokens", "bot_username", "TEXT")
        await _add_col(conn, "tokens", "activities_json", "TEXT DEFAULT '[]'")
        await _add_col(conn, "tokens", "rotation_interval", "INTEGER DEFAULT 30")
        await _add_col(conn, "tokens", "rotate_status", "BOOLEAN DEFAULT 0")
        await _add_col(conn, "tokens", "proxy", "TEXT")
        
        await _add_col(conn, "users", "is_admin", "BOOLEAN DEFAULT 0")
        await _add_col(conn, "users", "max_tokens", "INTEGER DEFAULT 1")
        await _add_col(conn, "users", "can_use_proxies", "BOOLEAN DEFAULT 0")
        await _add_col(conn, "users", "can_see_all_accounts", "BOOLEAN DEFAULT 0")
        await _add_col(conn, "users", "can_see_tokens", "BOOLEAN DEFAULT 0")
        
        await conn.commit()

async def get_db():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db

async def is_global_active():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT global_active FROM system_settings WHERE id = 1") as cursor:
            res = await cursor.fetchone()
            return bool(res[0]) if res else True
