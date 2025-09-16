from __future__ import annotations

from fastapi import APIRouter, Request, Response
import os
import httpx

router = APIRouter(prefix="/graph", tags=["graph-proxy"])


def _target_base() -> str | None:
    # Remote LangGraph server base URL, e.g. https://graph.example.com
    url = (os.getenv("LANGGRAPH_REMOTE_URL") or "").strip()
    return url or None


def _auth_headers() -> dict[str, str]:
    # Inject server-held credentials so the UI can remain cookie-only.
    # Supports LangGraph Studio style X-Api-Key and/or Authorization.
    h: dict[str, str] = {}
    api_key = (os.getenv("LANGSMITH_API_KEY") or "").strip()
    if api_key:
        h["X-Api-Key"] = api_key
    bearer = (os.getenv("LANGGRAPH_BEARER_TOKEN") or "").strip()
    if bearer:
        h["Authorization"] = f"Bearer {bearer}"
    return h


async def _forward(request: Request, method: str, path: str) -> Response:
    base = _target_base()
    if not base:
        return Response(status_code=501, content=b"Graph proxy not configured")
    # Build target URL preserving path and query string
    target = base.rstrip("/") + "/" + path.lstrip("/")
    # Compose headers: server auth + selected pass-throughs
    headers: dict[str, str] = {}
    headers.update(_auth_headers())
    client_headers = request.headers
    for name in ("content-type", "x-tenant-id", "cookie"):
        v = client_headers.get(name)
        if v:
            headers[name] = v
    # Send request
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        body = await request.body() if method.upper() not in ("GET", "HEAD") else None
        resp = await client.request(method=method.upper(), url=target, headers=headers, content=body)
        return Response(content=resp.content, status_code=resp.status_code, headers=resp.headers)


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def proxy_all(path: str, request: Request):
    return await _forward(request, request.method, path)

