"""meta-ads-mcp — server Agent24 pattern (FastAPI + FastMCP streamable_http + identity broker).
Alternativo a server.py originale (Pipeboard/OAuth). Usa questo per deploy su Nomad.
"""
from __future__ import annotations
import json as _json, os
from contextlib import asynccontextmanager
import uvicorn
from fastapi import FastAPI
from mcp.server.transport_security import TransportSecuritySettings
from meta_ads_mcp.identity import resolve_credentials, _request_creds
from meta_ads_mcp.session import AlertMiddleware, SessionMiddleware

# Importa il mcp_server originale (già registra tutti i tool via @mcp_server.tool())
from meta_ads_mcp.core.server import mcp_server as mcp

# Aggiorna transport_security sull'istanza esistente
mcp._transport_security = TransportSecuritySettings(allowed_hosts=["mcp.agent24.it"])

async def _asgi_json(send, body: dict, status: int) -> None:
    data = _json.dumps(body).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(data)).encode())]})
    await send({"type": "http.response.body", "body": data})

class _IdentityMiddleware:
    def __init__(self, app): self._app = app
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self._app(scope, receive, send); return
        if scope.get("path", "") == "/health":
            await self._app(scope, receive, send); return
        headers = dict(scope.get("headers", []))
        api_key = headers.get(b"x-api-key", b"").decode()
        if not api_key:
            await _asgi_json(send, {"error": "Unauthorized"}, 401); return
        creds = await resolve_credentials(api_key, mcp_name="mcp-marketing-meta-ads")
        _st = creds.pop("_status", None)
        if _st == 403: await _asgi_json(send, {"error": "Forbidden"}, 403); return
        if _st == 401: await _asgi_json(send, {"error": "Unauthorized"}, 401); return
        token = _request_creds.set(creds)
        try:
            await self._app(scope, receive, send)
        finally:
            _request_creds.reset(token)

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp.session_manager.run():
        yield

app = FastAPI(lifespan=lifespan)
app.add_middleware(AlertMiddleware)
app.add_middleware(SessionMiddleware)

@app.get("/health")
async def health():
    return {"status": "ok"}

app.mount("/", mcp.streamable_http_app())
app = _IdentityMiddleware(app)

def main():
    uvicorn.run("meta_ads_mcp.core.server_agent24:app", host="0.0.0.0",
                port=int(os.environ.get("PORT", "8124")))

if __name__ == "__main__":
    main()
