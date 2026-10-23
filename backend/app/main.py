from fastapi import FastAPI

from app.api import health
from app.modules.auth import router as auth_router
from app.modules.reference import router as reference_router
from app.modules.users import router as users_router

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    app = FastAPI(title="FareWatch API")
    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(auth_router.router, prefix=f"{API_PREFIX}/auth")
    app.include_router(users_router.router, prefix=API_PREFIX)
    app.include_router(reference_router.router, prefix=API_PREFIX)
    return app


app = create_app()
