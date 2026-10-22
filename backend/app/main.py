from fastapi import FastAPI

from app.api import health

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    app = FastAPI(title="FareWatch API")
    app.include_router(health.router, prefix=API_PREFIX)
    return app


app = create_app()
