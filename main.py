from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import SESSION_SECRET
from app.database import init_db
from app.discord_manager import bot_manager
from app.routers import auth, tokens, settings, frontend
import asyncio

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    asyncio.create_task(bot_manager.start_all())
    yield
    for task in list(bot_manager.tasks.values()):
        task.cancel()

app = FastAPI(title="Selfbot Manager", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, max_age=86400 * 30)

app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(auth.router)
app.include_router(tokens.router)
app.include_router(settings.router)
app.include_router(frontend.router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)
