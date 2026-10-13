from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app import models  # noqa: F401
from app.config import get_settings
from app.database import initialize_database
from app.routers import auth
from app.routers import sessions
from app.routers import demo
from app.routers import monitoring
from app.routers import browser_activity
from app.routers import session_inventory

settings = get_settings()
app = FastAPI(title=settings.app_name)
initialize_database()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["chrome-extension://bcndehhdcfcohhigpcbamkpipbgdopla"],
    allow_credentials=False,
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
app.include_router(auth.router)
app.include_router(sessions.router)
app.include_router(demo.router)
app.include_router(monitoring.router)
app.include_router(browser_activity.router)
app.include_router(session_inventory.router)


@app.get("/")
def dashboard() -> FileResponse:
    return FileResponse(
        Path(__file__).parent / "templates" / "dashboard.html",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
