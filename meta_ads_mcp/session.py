"""Session middleware: log tool calls to Redis + alert su errori 5xx."""
import asyncio, json as _json, logging, os, time
from datetime import datetime, timezone
import httpx
import redis.asyncio as aioredis
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)
_MACRO_API_URL = os.environ.get("MACRO_API_URL", "http://macro-api.service.consul:8100")
_REDIS_URL = os.environ.get("REDIS_URL", "")
_REDIS_KEY = "mcp:logs"
_REDIS_MAXLEN = 10000
_SERVICE_NAME = os.environ.get("SERVICE_NAME", "mcp-marketing-meta-ads")
_redis_pool: aioredis.Redis | None = None

def _get_redis():
    global _redis_pool
    if not _REDIS_URL: return None
    if _redis_pool is None:
        _redis_pool = aioredis.from_url(_REDIS_URL, decode_responses=True)
    return _redis_pool

async def _push_log(entry: dict) -> None:
    r = _get_redis()
    if r is None: return
    try:
        pipe = r.pipeline()
        pipe.lpush(_REDIS_KEY, _json.dumps(entry, ensure_ascii=False))
        pipe.ltrim(_REDIS_KEY, 0, _REDIS_MAXLEN - 1)
        await pipe.execute()
    except Exception:
        logger.exception("redis_push_failed")

async def _send_alert(path: str, detail: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{_MACRO_API_URL}/macros/internal-notify",
                json={"text": f"[{_SERVICE_NAME}]\nPath: {path}\nErrore: {detail}"},
            )
    except Exception:
        logger.exception("alert_send_failed")

class AlertMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path == "/health": return await call_next(request)
        try:
            response = await call_next(request)
            if response.status_code >= 500:
                asyncio.create_task(_send_alert(request.url.path, f"HTTP {response.status_code}"))
            return response
        except Exception as exc:
            asyncio.create_task(_send_alert(request.url.path, repr(exc))); raise

class SessionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        start = time.monotonic()
        tool_name = tool_arguments = jsonrpc_method = None
        if request.method == "POST":
            try:
                body = await request.body()
                payload = _json.loads(body)
                jsonrpc_method = payload.get("method", "")
                if jsonrpc_method == "tools/call":
                    tool_name = payload.get("params", {}).get("name")
                    tool_arguments = payload.get("params", {}).get("arguments")
            except Exception: pass
        response = await call_next(request)
        if request.url.path == "/mcp" and jsonrpc_method == "tools/call":
            entry = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "method": request.method, "path": request.url.path,
                "jsonrpc_method": jsonrpc_method, "tool": tool_name,
                "tool_arguments": tool_arguments, "status": response.status_code,
                "duration_ms": int((time.monotonic() - start) * 1000),
                "company_id": 0, "agent_id": 0, "phone": "", "partner_id": None,
                "server_id": _SERVICE_NAME, "server_name": _SERVICE_NAME,
            }
            asyncio.create_task(_push_log(entry))
        return response
