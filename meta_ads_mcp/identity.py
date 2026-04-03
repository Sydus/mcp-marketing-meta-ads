"""Integrazione con il broker credenziali (seas-identity-api /identity/resolve)."""
from __future__ import annotations
from contextvars import ContextVar
import logging, os
import httpx

logger = logging.getLogger(__name__)
_IDENTITY_URL = os.environ.get("IDENTITY_URL", "http://seas-identity-api.service.consul:15104")
_IDENTITY_INTERNAL_KEY = os.environ.get("IDENTITY_INTERNAL_KEY", "")
_request_creds: ContextVar[dict] = ContextVar("request_creds", default={})

def get_creds() -> dict:
    return _request_creds.get()

async def resolve_credentials(api_key: str, mcp_name: str = "") -> dict:
    if not api_key or not _IDENTITY_INTERNAL_KEY:
        return {"_status": 401}
    payload: dict = {"api_key": api_key}
    if mcp_name:
        payload["mcp_name"] = mcp_name
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{_IDENTITY_URL}/identity/resolve",
                json=payload,
                headers={"X-Internal-Key": _IDENTITY_INTERNAL_KEY},
            )
            if resp.status_code == 200:
                return resp.json().get("credentials", {})
            if resp.status_code == 403:
                return {"_status": 403}
            logger.warning("identity_resolve failed: HTTP %s", resp.status_code)
            return {"_status": 401}
    except Exception:
        logger.exception("identity_resolve error")
    return {}
