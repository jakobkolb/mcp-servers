"""faster-whisper model management and decoding.

The model is loaded in the background at startup so `/health` answers straight
away and jobs can be accepted while the weights are still downloading — they
simply sit in the queue until `ready` flips.
"""

import asyncio
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from .config import Config
from .jobs import Job, Runner, TranscriptionResult

logger = logging.getLogger("mcp-whisper.transcriber")

ModelState = Literal["loading", "ready", "failed"]


class ModelManager:
    """Owns the single WhisperModel instance and its load state."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._model: Any | None = None
        self._state: ModelState = "loading"
        self._error: str | None = None
        self._loaded_at: float | None = None
        self._ready = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def state(self) -> ModelState:
        return self._state

    @property
    def error(self) -> str | None:
        return self._error

    def status(self) -> dict[str, Any]:
        return {
            "model": self._config.model,
            "device": self._config.device,
            "compute_type": self._config.compute_type,
            "model_state": self._state,
            "model_dir": str(self._config.model_dir),
            "loaded_at": self._loaded_at,
            "error": self._error,
        }

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._load(), name="mcp-whisper-model-load")

    async def stop(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = None

    async def wait_ready(self) -> Any:
        """Block until the model is usable, or raise if loading failed."""
        await self._ready.wait()
        if self._state != "ready" or self._model is None:
            raise RuntimeError(f"whisper model failed to load: {self._error}")
        return self._model

    async def _load(self) -> None:
        try:
            self._model = await asyncio.to_thread(_build_model, self._config)
            self._state = "ready"
            self._loaded_at = time.time()
            logger.info("whisper model %s ready", self._config.model)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._state = "failed"
            self._error = f"{type(exc).__name__}: {exc}"
            logger.exception("loading whisper model %s failed", self._config.model)
        finally:
            # Woken either way — waiters need to see the failure, not hang.
            self._ready.set()


def _build_model(config: Config) -> Any:
    # Imported lazily: it pulls in CTranslate2 and (for VAD) onnxruntime, which
    # we do not want in the import path of the tests or the health endpoint.
    from faster_whisper import WhisperModel

    config.model_dir.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, Any] = {
        "device": config.device,
        "compute_type": config.compute_type,
        "download_root": str(config.model_dir),
    }
    if config.cpu_threads > 0:
        kwargs["cpu_threads"] = config.cpu_threads
    return WhisperModel(config.model, **kwargs)


def _decode(
    model: Any, path: Path, options: dict[str, Any], vad_filter: bool
) -> TranscriptionResult:
    segments, info = model.transcribe(
        str(path),
        language=options.get("language"),
        task=options.get("task", "transcribe"),
        initial_prompt=options.get("initial_prompt"),
        beam_size=options.get("beam_size", 5),
        vad_filter=vad_filter,
    )
    # `segments` is a generator — decoding happens as it is consumed.
    collected: list[dict[str, Any]] = [
        {"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
        for s in segments
    ]
    return TranscriptionResult(
        text=" ".join(s["text"] for s in collected).strip(),
        language=getattr(info, "language", None),
        language_probability=getattr(info, "language_probability", None),
        duration=getattr(info, "duration", None),
        segments=collected,
    )


def make_runner(
    manager: ModelManager,
    resolve_path: Callable[[str], Path],
    vad_filter: bool,
) -> Runner:
    """Build the JobQueue runner that ties the queue to the model."""

    async def run(job: Job) -> TranscriptionResult:
        model = await manager.wait_ready()
        path = resolve_path(job.audio_id)
        # to_thread keeps the event loop responsive; decoding is CPU-bound and
        # releases the GIL inside CTranslate2 anyway.
        return await asyncio.to_thread(_decode, model, path, job.options, vad_filter)

    return run
