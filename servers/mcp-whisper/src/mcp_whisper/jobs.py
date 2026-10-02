"""Async job queue.

Transcription on a Pi takes minutes, far longer than an MCP client will hold a
request open, so `transcribe_audio` only enqueues and hands back a job id. A
single worker drains the queue serially — the box has one set of cores and
parallel decoding would only make every job slower.
"""

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

logger = logging.getLogger("mcp-whisper.jobs")

JobStatus = Literal["queued", "running", "completed", "failed"]


@dataclass
class TranscriptionResult:
    text: str
    language: str | None
    language_probability: float | None
    duration: float | None
    segments: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Job:
    id: str
    audio_id: str
    filename: str | None
    options: dict[str, Any]
    status: JobStatus = "queued"
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    result: TranscriptionResult | None = None
    error: str | None = None
    # Set the moment the job leaves "queued"/"running"; lets get_transcription
    # long-poll instead of forcing the client into a tight polling loop.
    done: asyncio.Event = field(default_factory=asyncio.Event)

    def summary(self, include_segments: bool = False) -> dict[str, Any]:
        out: dict[str, Any] = {
            "job_id": self.id,
            "status": self.status,
            "filename": self.filename,
            "created_at": self.created_at,
        }
        if self.started_at is not None:
            out["started_at"] = self.started_at
        if self.finished_at is not None:
            out["finished_at"] = self.finished_at
            out["processing_seconds"] = round(self.finished_at - (self.started_at or 0.0), 1)
        if self.result is not None:
            out["text"] = self.result.text
            out["language"] = self.result.language
            out["language_probability"] = self.result.language_probability
            out["audio_duration_seconds"] = self.result.duration
            if include_segments:
                out["segments"] = self.result.segments
        if self.error is not None:
            out["error"] = self.error
        return out


class QueueFull(RuntimeError):
    """Raised when more jobs are submitted than the queue is configured to hold."""


Runner = Callable[[Job], Awaitable[TranscriptionResult]]
Cleanup = Callable[[str], None]


class JobQueue:
    """Holds jobs, runs them one at a time, and expires old ones."""

    def __init__(
        self,
        runner: Runner,
        *,
        max_queued: int = 16,
        ttl_seconds: int = 24 * 60 * 60,
        max_retained: int = 200,
        cleanup: Cleanup | None = None,
    ) -> None:
        self._runner = runner
        self._jobs: dict[str, Job] = {}
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._max_queued = max_queued
        self._ttl = ttl_seconds
        self._max_retained = max_retained
        self._cleanup = cleanup
        self._worker: asyncio.Task[None] | None = None

    # ── lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._loop(), name="mcp-whisper-worker")

    async def stop(self) -> None:
        if self._worker is None:
            return
        self._worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._worker
        self._worker = None

    # ── submission / lookup ──────────────────────────────────────────────────

    def submit(self, audio_id: str, filename: str | None, options: dict[str, Any]) -> Job:
        self._expire()
        if self._queue.qsize() >= self._max_queued:
            raise QueueFull(
                f"{self._queue.qsize()} jobs already queued (limit {self._max_queued}); "
                "wait for the backlog to drain"
            )
        job = Job(id=uuid.uuid4().hex, audio_id=audio_id, filename=filename, options=options)
        self._jobs[job.id] = job
        self._queue.put_nowait(job.id)
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)

    @property
    def queued(self) -> int:
        return self._queue.qsize()

    def position(self, job_id: str) -> int | None:
        """1-based position in the backlog, or None once it is no longer queued."""
        job = self._jobs.get(job_id)
        if job is None or job.status != "queued":
            return None
        ahead = [
            j for j in self._jobs.values() if j.status == "queued" and j.created_at < job.created_at
        ]
        return len(ahead) + 1

    async def wait(self, job_id: str, timeout: float) -> Job | None:
        job = self._jobs.get(job_id)
        if job is None:
            return None
        if timeout > 0 and not job.done.is_set():
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(job.done.wait(), timeout=timeout)
        return job

    # ── internals ────────────────────────────────────────────────────────────

    async def _loop(self) -> None:
        while True:
            job_id = await self._queue.get()
            job = self._jobs.get(job_id)
            if job is None:  # expired before it ran
                self._queue.task_done()
                continue
            job.status = "running"
            job.started_at = time.time()
            try:
                job.result = await self._runner(job)
                job.status = "completed"
            except asyncio.CancelledError:
                job.status = "failed"
                job.error = "server shutting down"
                job.finished_at = time.time()
                job.done.set()
                raise
            except Exception as exc:
                logger.exception("job %s failed", job.id)
                job.status = "failed"
                job.error = f"{type(exc).__name__}: {exc}"
            finally:
                if job.status in ("completed", "failed"):
                    job.finished_at = time.time()
                    job.done.set()
                    if self._cleanup is not None:
                        self._cleanup(job.audio_id)
                self._queue.task_done()

    def _expire(self, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        finished = [
            j
            for j in self._jobs.values()
            if j.status in ("completed", "failed") and j.finished_at is not None
        ]
        stale = {j.id for j in finished if now - (j.finished_at or now) > self._ttl}
        # Beyond the TTL, keep only the newest `max_retained` finished jobs.
        if len(finished) - len(stale) > self._max_retained:
            survivors = sorted(
                (j for j in finished if j.id not in stale),
                key=lambda j: j.finished_at or 0.0,
                reverse=True,
            )
            stale.update(j.id for j in survivors[self._max_retained :])
        for job_id in stale:
            job = self._jobs.pop(job_id, None)
            if job is not None and self._cleanup is not None:
                self._cleanup(job.audio_id)
