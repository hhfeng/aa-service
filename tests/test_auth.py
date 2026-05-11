import pytest
import os
from unittest.mock import patch
from fastapi import HTTPException
from auth import check_api_key

@pytest.mark.asyncio
async def test_check_api_key_no_env():
    with patch.dict(os.environ, {"GRAPHIFY_SERVICE_API_KEY": ""}):
        # Reloading auth is hard because it's already imported.
        # But we can patch the _API_KEY directly if needed, 
        # or just rely on the fact that if it's empty, it passes.
        import auth
        with patch("auth._API_KEY", ""):
            await check_api_key("")  # Should not raise

@pytest.mark.asyncio
async def test_check_api_key_valid():
    import auth
    with patch("auth._API_KEY", "secret"):
        await check_api_key("secret")  # Should not raise

@pytest.mark.asyncio
async def test_check_api_key_invalid():
    import auth
    with patch("auth._API_KEY", "secret"):
        with pytest.raises(HTTPException) as excinfo:
            await check_api_key("wrong")
        assert excinfo.value.status_code == 401
