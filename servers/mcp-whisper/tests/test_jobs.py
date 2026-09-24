import asyncio
import time

import pytest
from mcp_whisper.jobs import JobQueue, QueueFull, TranscriptionResult


def _result(text="hello"):
    return TranscriptionResult(text=text, language="en", language_probability=0.9, duration=1.0)


async def _ok_runner(job):
    return _result(f"text for {job.audio_id}")


async def _failing_runner(job):
    raise RuntimeError("model exploded")


@pytest.fixture
async def queue():
    q = JobQueue(_ok_runner)
    q.start()
    yield q
    await q.stop()


async def test_submit_returns_queued_job(queue):
    job = queue.submit("audio-1", "memo.wav", {})
    assert job.status == "queued"
    assert queue.get(job.id) is job


async def test_job_runs_and_completes(queue):
    job = queue.submit("audio-1", "memo.wav", {})
    finished = await queue.wait(job.id, timeout=2)
    assert finished is not None
    assert finished.status == "completed"
    assert finished.result is not None
    assert finished.result.text == "text for audio-1"
    assert finished.finished_at is not None


async def test_failure_is_recorded_not_raised():
    q = JobQueue(_failing_runner)
    q.start()
    try:
        job = q.submit("audio-1", None, {})
        finished = await q.wait(job.id, timeout=2)
        assert finished is not None
        assert finished.status == "failed"
        assert "model exploded" in (finished.error or "")
    finally:
        await q.stop()


async def test_worker_survives_a_failed_job():
    calls = []

    async def flaky(job):
        calls.append(job.audio_id)
        if job.audio_id == "bad":
            raise RuntimeError("nope")
        return _result()

    q = JobQueue(flaky)
    q.start()
    try:
        bad = q.submit("bad", None, {})
        good = q.submit("good", None, {})
        assert (await q.wait(bad.id, timeout=2)).status == "failed"
        assert (await q.wait(good.id, timeout=2)).status == "completed"
    finally:
        await q.stop()


async def test_queue_full_is_rejected():
    blocked = asyncio.Event()

    async def slow(job):
        await blocked.wait()
        return _result()

    q = JobQueue(slow, max_queued=2)
    q.start()
    try:
        for i in range(3):
            q.submit(f"audio-{i}", None, {})
            await asyncio.sleep(0)
        with pytest.raises(QueueFull):
            for i in range(5):
                q.submit(f"overflow-{i}", None, {})
    finally:
        blocked.set()
        await q.stop()


async def test_wait_with_zero_timeout_returns_immediately(queue):
    job = queue.submit("audio-1", None, {})
    seen = await queue.wait(job.id, timeout=0)
    assert seen is not None
    assert seen.status in ("queued", "running", "completed")


async def test_wait_unknown_job_is_none(queue):
    assert await queue.wait("nope", timeout=0) is None


async def test_cleanup_runs_after_completion():
    discarded = []
    q = JobQueue(_ok_runner, cleanup=discarded.append)
    q.start()
    try:
        job = q.submit("audio-1", None, {})
        await q.wait(job.id, timeout=2)
        assert discarded == ["audio-1"]
    finally:
        await q.stop()


async def test_expired_jobs_are_dropped_and_cleaned():
    discarded = []
    q = JobQueue(_ok_runner, ttl_seconds=1, cleanup=discarded.append)
    q.start()
    try:
        job = q.submit("audio-1", None, {})
        await q.wait(job.id, timeout=2)
        job.finished_at = time.time() - 3600
        q.submit("audio-2", None, {})  # submit sweeps first
        assert q.get(job.id) is None
        assert "audio-1" in discarded
    finally:
        await q.stop()


async def test_retention_cap_keeps_newest():
    q = JobQueue(_ok_runner, max_retained=1)
    q.start()
    try:
        first = q.submit("audio-1", None, {})
        await q.wait(first.id, timeout=2)
        second = q.submit("audio-2", None, {})
        await q.wait(second.id, timeout=2)
        q.submit("audio-3", None, {})  # triggers the sweep
        assert q.get(first.id) is None
        assert q.get(second.id) is not None
    finally:
        await q.stop()


async def test_summary_hides_segments_unless_asked(queue):
    job = queue.submit("audio-1", "memo.wav", {})
    finished = await queue.wait(job.id, timeout=2)
    assert "segments" not in finished.summary()
    assert "segments" in finished.summary(include_segments=True)
