import os
from fastapi import Header, HTTPException

_API_KEY = os.environ.get("GRAPHIFY_SERVICE_API_KEY", "")


async def check_api_key(x_api_key: str = Header(default="")) -> None:
    if _API_KEY and x_api_key != _API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key header")
