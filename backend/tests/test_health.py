from httpx import ASGITransport, AsyncClient

from app.main import create_app


async def test_health_ok() -> None:
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as c:
        r = await c.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_health_not_mounted_at_root() -> None:
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as c:
        r = await c.get("/health")
    assert r.status_code == 404
