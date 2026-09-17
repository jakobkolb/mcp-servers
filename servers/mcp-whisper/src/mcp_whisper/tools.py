"""MCP tool surface.

Three tools, deliberately: submit work, collect work, and ask what the server
is doing. Everything returns JSON text so the client can quote exact numbers
back to the user.
"""

import json
import logging
from typing import Any

from mcp.types import TextContent, Tool

from .audio import AudioNotFound, AudioSpool, AudioTooLarge
from .config import Config
from .jobs import JobQueue, QueueFull
from .transcriber import ModelManager

logger = logging.getLogger("mcp-whisper.tools")

MAX_WAIT_SECONDS = 120.0


def tool_definitions(max_audio_mib: int) -> list[Tool]:
    return [
        Tool(
            name="transcribe_audio",
            description=(
                "Transcribe a voice memo or any audio file with Whisper. Returns a job_id "
                "immediately — transcription runs in the background, so call "
                "get_transcription with that job_id to collect the text. Supply the audio "
                "exactly one of three ways: audio_id (from a prior POST to /mcp/upload, the "
                "only route that is practical for files of more than a few hundred KB), "
                "audio_url (the server downloads it), or audio_base64 (inline, and only "
                f"sensible for short clips). Hard limit {max_audio_mib} MiB."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "audio_id": {
                        "type": "string",
                        "description": "Id returned by POST /mcp/upload.",
                    },
                    "audio_url": {
                        "type": "string",
                        "description": "http(s) URL the server should download the audio from.",
                    },
                    "audio_base64": {
                        "type": "string",
                        "description": (
                            "Base64-encoded audio. Inline transport costs roughly 1.4 tokens "
                            "per audio byte, so prefer audio_id or audio_url above ~500 KB."
                        ),
                    },
                    "filename": {
                        "type": "string",
                        "description": (
                            "Original filename, e.g. memo.wav. Only used as a container-format "
                            "hint; ffmpeg sniffs the actual format."
                        ),
                    },
                    "language": {
                        "type": "string",
                        "description": (
                            "ISO 639-1 code such as 'de' or 'en'. Omit to auto-detect, but "
                            "setting it is faster and more accurate on short clips."
                        ),
                    },
                    "task": {
                        "type": "string",
                        "enum": ["transcribe", "translate"],
                        "description": "'translate' renders the audio into English.",
                        "default": "transcribe",
                    },
                    "initial_prompt": {
                        "type": "string",
                        "description": (
                            "Vocabulary hint — names, jargon and spellings the model should prefer."
                        ),
                    },
                },
                "additionalProperties": False,
            },
        ),
        Tool(
            name="get_transcription",
            description=(
                "Fetch the state and, once finished, the text of a transcription job. "
                "Pass wait_seconds to block server-side until the job finishes instead of "
                "polling in a loop."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "Id from transcribe_audio."},
                    "wait_seconds": {
                        "type": "number",
                        "description": (
                            f"Block up to this many seconds (max {int(MAX_WAIT_SECONDS)}) "
                            "waiting for the job to finish. 0 returns the current state."
                        ),
                        "default": 0,
                    },
                    "include_segments": {
                        "type": "boolean",
                        "description": "Include per-segment timestamps alongside the full text.",
                        "default": False,
                    },
                },
                "required": ["job_id"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="whisper_status",
            description=(
                "Report which model is loaded (or still downloading), the device it runs on, "
                "and the current job backlog. Use this when a job stays queued to find out "
                "whether the model is still being fetched."
            ),
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        ),
    ]


class WhisperTools:
    """Dispatch layer wiring the tools onto the spool, queue and model."""

    def __init__(
        self,
        config: Config,
        spool: AudioSpool,
        queue: JobQueue,
        manager: ModelManager,
    ) -> None:
        self._config = config
        self._spool = spool
        self._queue = queue
        self._manager = manager

    def list_tools(self) -> list[Tool]:
        return tool_definitions(self._config.max_audio_bytes // (1024 * 1024))

    async def call(self, name: str, arguments: dict[str, Any]) -> list[TextContent]:
        if name == "transcribe_audio":
            return _json(await self._transcribe(arguments))
        if name == "get_transcription":
            return _json(await self._get(arguments))
        if name == "whisper_status":
            return _json(self._status())
        raise ValueError(f"Unknown tool: {name}")

    # ── tools ────────────────────────────────────────────────────────────────

    async def _transcribe(self, args: dict[str, Any]) -> dict[str, Any]:
        supplied = [k for k in ("audio_id", "audio_url", "audio_base64") if args.get(k)]
        if len(supplied) != 1:
            raise ValueError(
                "supply exactly one of audio_id, audio_url or audio_base64 "
                f"(got {supplied or 'none'})"
            )
        filename = args.get("filename")
        source = supplied[0]

        try:
            if source == "audio_id":
                audio_id = str(args["audio_id"])
                self._spool.path(audio_id)  # raises if it expired
                # The uploader already named the file; don't make the client
                # repeat it just to get a readable job listing.
                filename = filename or self._spool.original_name(audio_id)
            elif source == "audio_url":
                audio_id = await self._spool.store_url(
                    str(args["audio_url"]), filename, self._config.allowed_url_hosts
                )
            else:
                audio_id = self._spool.store_base64(str(args["audio_base64"]), filename)
        except AudioNotFound as exc:
            raise ValueError(
                f"audio_id {exc.args[0]!r} is unknown or has expired — upload the audio again"
            ) from exc
        except AudioTooLarge as exc:
            raise ValueError(str(exc)) from exc

        options = {
            "language": args.get("language"),
            "task": args.get("task", "transcribe"),
            "initial_prompt": args.get("initial_prompt"),
        }
        try:
            job = self._queue.submit(audio_id, filename, options)
        except QueueFull as exc:
            self._spool.discard(audio_id)
            raise ValueError(str(exc)) from exc

        out: dict[str, Any] = {
            "job_id": job.id,
            "status": job.status,
            "queue_position": self._queue.position(job.id),
            "model_state": self._manager.state,
        }
        out["next_step"] = _next_step(job.id, self._manager.state, self._manager.error)
        return out

    async def _get(self, args: dict[str, Any]) -> dict[str, Any]:
        job_id = str(args["job_id"])
        wait = min(float(args.get("wait_seconds") or 0.0), MAX_WAIT_SECONDS)
        job = await self._queue.wait(job_id, wait)
        if job is None:
            raise ValueError(f"unknown job_id {job_id!r} — it may have expired")
        out = job.summary(include_segments=bool(args.get("include_segments", False)))
        if job.status == "queued":
            out["queue_position"] = self._queue.position(job_id)
            out["model_state"] = self._manager.state
        return out

    def _status(self) -> dict[str, Any]:
        status = self._manager.status()
        status["queued_jobs"] = self._queue.queued
        status["jobs"] = [
            {"job_id": j.id, "status": j.status, "filename": j.filename}
            for j in self._queue.list()[:20]
        ]
        status["max_audio_bytes"] = self._spool.max_bytes
        status["upload_endpoint"] = "POST /mcp/upload"
        return status


def _next_step(job_id: str, model_state: str, model_error: str | None) -> str:
    if model_state == "ready":
        return f"call get_transcription with job_id={job_id!r} and wait_seconds=60"
    if model_state == "failed":
        # Reporting "still downloading" here would send the client into an
        # endless poll against a job that can never start.
        return (
            "the model could not be loaded, so this job will fail immediately "
            f"({model_error}); check the pod logs and the model PVC"
        )
    return "the model is still downloading; the job starts as soon as it is ready"


def _json(payload: dict[str, Any]) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(payload, indent=2, ensure_ascii=False))]
