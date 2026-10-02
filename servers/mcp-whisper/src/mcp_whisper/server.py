"""HTTP entrypoint: Streamable-HTTP MCP endpoint, upload sink and health probe."""

import asyncio
import contextlib
import logging
import os
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from mcp.server import Server
from mcp.server.context import ServerRequestContext
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from .audio import AudioSpool, AudioTooLarge
from .config import load_config
from .jobs import JobQueue
from .tools import WhisperTools
from .transcriber import ModelManager, make_runner

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("mcp-whisper")

_config = load_config()
_spool = AudioSpool(_config.spool_dir, _config.max_audio_bytes, _config.job_ttl_seconds)
_manager = ModelManager(_config)
_queue = JobQueue(
    make_runner(_manager, _spool.path, _config.vad_filter),
    max_queued=_config.max_queued_jobs,
    ttl_seconds=_config.job_ttl_seconds,
    max_retained=_config.max_jobs_retained,
    cleanup=_spool.discard,
)
_tools = WhisperTools(_config, _spool, _queue, _manager)

SWEEP_INTERVAL_SECONDS = 3600


async def list_tools() -> list[Tool]:
    return _tools.list_tools()


async def call_tool(name: str, arguments: Any) -> Sequence[TextContent]:
    if not isinstance(arguments, dict):
        raise RuntimeError("arguments must be a dictionary")
    return await _tools.call(name, arguments)


async def _on_list_tools(
    ctx: ServerRequestContext[Any, Any], params: PaginatedRequestParams | None
) -> ListToolsResult:
    return ListToolsResult(tools=await list_tools())


async def _on_call_tool(
    ctx: ServerRequestContext[Any, Any], params: CallToolRequestParams
) -> CallToolResult:
    try:
        content = await call_tool(params.name, params.arguments or {})
        return CallToolResult(content=list(content))
    except Exception as e:
        logger.error("tool %s failed: %s", params.name, e)
        return CallToolResult(is_error=True, content=[TextContent(type="text", text=str(e))])


app: Server[Any] = Server(
    "mcp-whisper",
    on_list_tools=_on_list_tools,
    on_call_tool=_on_call_tool,
)

_session_manager = StreamableHTTPSessionManager(
    app=app,
    event_store=None,
    json_response=False,
    stateless=True,
)


async def _health(_: Request) -> JSONResponse:
    # Deliberately "ok" while the model is still downloading — the pod is
    # serving, it just cannot decode yet, and failing the probe here would
    # restart the pod and throw away the partial download.
    return JSONResponse({"status": "ok", "model_state": _manager.state})


async def _upload(request: Request) -> JSONResponse:
    """Raw-body audio sink.

    Sits under /mcp so it inherits the gateway's OAuth ingress rule without a
    second ingress path:

        curl --data-binary @memo.wav -H 'Authorization: Bearer $TOKEN' \
             'https://whisper.<baseDomain>/mcp/upload?filename=memo.wav'
    """
    filename = request.query_params.get("filename") or request.headers.get("x-filename")
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > _config.max_audio_bytes:
            return JSONResponse(
                {"error": f"audio exceeds {_config.max_audio_bytes} bytes"}, status_code=413
            )
        chunks.append(chunk)
    try:
        audio_id = _spool.store(b"".join(chunks), filename)
    except AudioTooLarge as exc:
        return JSONResponse({"error": str(exc)}, status_code=413)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"audio_id": audio_id, "bytes": total, "filename": filename})


async def _sweep_loop() -> None:
    while True:
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
        removed = await asyncio.to_thread(_spool.sweep)
        if removed:
            logger.info("swept %d expired audio files", removed)


@asynccontextmanager
async def _lifespan(_: Starlette) -> AsyncIterator[None]:
    # Kicked off before the first request: the weights download in the
    # background while the server already accepts and queues jobs.
    _manager.start()
    _queue.start()
    sweeper = asyncio.create_task(_sweep_loop(), name="mcp-whisper-sweeper")
    try:
        async with _session_manager.run():
            yield
    finally:
        sweeper.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sweeper
        await _queue.stop()
        await _manager.stop()


http_app = Starlette(
    routes=[
        Route("/health", _health),
        # Must precede the /mcp mount — Starlette matches in declaration order.
        Route("/mcp/upload", _upload, methods=["POST"]),
        Mount("/mcp", app=_session_manager.handle_request),
    ],
    lifespan=_lifespan,
)


def main() -> None:
    uvicorn.run(http_app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
