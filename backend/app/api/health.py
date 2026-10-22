from fastapi import APIRouter

router = APIRouter()


# 不查 DB：正式環境每次健康檢查都連 Neon 會把休眠的 DB 叫醒
@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
