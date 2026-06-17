from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

router = APIRouter()

@router.get("/healthz", status_code=status.HTTP_200_OK)
async def health_check():
    """Liveness probe – returns 200 if the API is running."""
    return {"status": "ok", "service": "template-builder-api"}
