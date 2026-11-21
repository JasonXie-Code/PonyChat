"""Compatibility proxy: Drive storage and file operations live on Server-USA."""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.background import BackgroundTask
import httpx

router = APIRouter(prefix="/api/drive", tags=["Drive compatibility"])
_HOP_HEADERS = {"host", "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
                "te", "trailer", "transfer-encoding", "upgrade", "content-length"}


@router.api_route("/{path:path}", methods=["GET", "POST", "HEAD", "OPTIONS"])
async def drive_compatibility_proxy(path: str, request: Request):
    client = httpx.AsyncClient(timeout=httpx.Timeout(300, connect=5), trust_env=False)
    target = httpx.URL("https://drive.ponychat.org" + request.url.path,
                       query=request.url.query.encode("utf-8"))
    headers = {key: value for key, value in request.headers.items() if key.lower() not in _HOP_HEADERS}
    try:
        outgoing = client.build_request(request.method, target, headers=headers, content=request.stream())
        response = await client.send(outgoing, stream=True)
    except httpx.HTTPError:
        await client.aclose()
        return JSONResponse(status_code=503, content={"detail": "Server-USA 网盘暂时不可用，请稍后重试"})

    async def close_upstream():
        await response.aclose()
        await client.aclose()

    return StreamingResponse(response.aiter_raw(), status_code=response.status_code,
        headers={key: value for key, value in response.headers.items() if key.lower() not in _HOP_HEADERS},
        background=BackgroundTask(close_upstream))
