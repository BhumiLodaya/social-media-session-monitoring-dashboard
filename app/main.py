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
from app.routers import social
from app.routers import login_activity
from app.routers import users

settings = get_settings()
app = FastAPI(title=settings.app_name)
initialize_database(initial_admin_username=settings.initial_admin_username)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^chrome-extension://[a-p]{32}$",
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
app.include_router(social.router)
app.include_router(login_activity.router)
app.include_router(users.router)


def _dashboard_page() -> FileResponse:
    return FileResponse(
        Path(__file__).parent / "templates" / "dashboard.html",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/")
def dashboard() -> FileResponse:
    return _dashboard_page()


@app.get("/login")
@app.get("/register")
def authentication_page() -> FileResponse:
    return _dashboard_page()


# SPA routes: same dashboard shell, client-side view switching
@app.get("/user-directory")
@app.get("/users/{user_id:int}")
@app.get("/login-activity")
@app.get("/dashboard-sessions")
@app.get("/monitoring")
@app.get("/panels")
@app.get("/connected-accounts")
@app.get("/organic-ids")
@app.get("/diagnosis")
def dashboard_routes() -> FileResponse:
    return _dashboard_page()


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
