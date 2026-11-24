"""Hermes Stats as a dashboard tab: the stats client and its API under /api/plugins/stats/.

The tab (dist/index.js) frames `/api/plugins/stats/?profile=<p>`. The client's requests are relative
(`api/...`), so they land here too and pass the dashboard's own auth gate: the session cookie of a
dashboard with a login, which a framed page sends. The API is the one `hermes stats serve` answers,
through `stats_server.get_api` / `post_api`.
"""
from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
import sys
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, Response

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = "hermes_stats_dashboard"
SSE_RETRY_MS = 5000


def _server() -> Any:
    """`stats_server`, imported as part of this plugin's package (it uses relative imports). The
    dashboard loads this file alone, outside the package Hermes's plugin loader imports."""
    if PACKAGE not in sys.modules:
        spec = importlib.util.spec_from_file_location(PACKAGE, ROOT / "__init__.py",
                                                      submodule_search_locations=[str(ROOT)])
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[PACKAGE] = module
        spec.loader.exec_module(module)
    return importlib.import_module(f"{PACKAGE}.stats_server")


def _llm(narrate: Any) -> Any:
    """The user's auxiliary model for `stats_insights`, as `ctx.llm` would reach it; None outside Hermes."""
    try:
        from agent.plugin_llm import PluginLlm  # type: ignore
    except ImportError:
        return None
    return narrate.hermes_llm(PluginLlm(plugin_id="stats"))


server = _server()
app = server.App(server.Source(server.stats_hermes.root_of(server.hermes_home()), server.default_voice_root()),
                 _llm(server.stats_narrate), server.default_cache())

router = APIRouter()


def _json(result: tuple[int, Any]) -> Response:
    status, payload = result
    return Response(server._dumps(payload), status_code=status, media_type="application/json",
                    headers={"Cache-Control": "no-store"})


@router.get("/api/events")
def events() -> Response:
    """One status event, then the stream ends and the browser reconnects after `retry`. The
    dashboard buffers a plugin's answer, so a stream that never ends would never arrive."""
    body = b"retry: %d\ndata: " % SSE_RETRY_MS + server._dumps(app.source.status()) + b"\n\n"
    return Response(body, media_type="text/event-stream", headers={"Cache-Control": "no-store"})


@router.get("/api/{path:path}")
def get(path: str, request: Request) -> Response:
    return _json(server.get_api(app, f"/api/{path}", request.url.query))


@router.post("/api/{path:path}")
async def post(path: str, request: Request) -> Response:
    """Only JSON is accepted, so a cross-site form cannot post here without a CORS preflight."""
    raw = await request.body()
    content_type = request.headers.get("content-type") or ""
    return _json(await _to_thread(server.post_api, app, f"/api/{path}", request.url.query, content_type, raw))


async def _to_thread(fn: Any, *args: Any) -> Any:
    import asyncio

    return await asyncio.to_thread(fn, *args)


@router.get("/")
@router.get("/{name}")
def asset(name: str = "index.html") -> Response:
    found = server.ASSETS.get(f"/{name}")
    if found is None:
        return JSONResponse({"error": "Not found."}, status_code=404)
    file, media_type = found
    return FileResponse(server.DIST / file, media_type=media_type, headers={"Cache-Control": "no-cache"})
