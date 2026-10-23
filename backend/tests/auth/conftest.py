from http.cookies import SimpleCookie

from httpx import AsyncClient, Response

REFRESH_URL = "/api/v1/auth/refresh"


async def refresh_with(client: AsyncClient, token: str) -> Response:
    # 清掉 client 自動保存的 cookie，只送指定的 token，模擬不同瀏覽器
    client.cookies.clear()
    return await client.post(REFRESH_URL, headers={"Cookie": f"refresh_token={token}"})


def cookie_token(resp: Response) -> str:
    cookie: SimpleCookie = SimpleCookie()
    cookie.load(resp.headers["set-cookie"])
    return cookie["refresh_token"].value
