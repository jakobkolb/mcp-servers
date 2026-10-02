import asyncio
import base64
import json

import pytest
from mcp_whisper.audio import AudioSpool
from mcp_whisper.config import Config
from mcp_whisper.jobs import JobQueue, TranscriptionResult
from mcp_whisper.tools import WhisperTools
from mcp_whisper.transcriber import ModelManager

WAV = base64.b64encode(b"RIFFfake-wav-bytes").decode()


@pytest.fixture
def config(tmp_path):
    return Config(model_dir=tmp_path / "models", spool_dir=tmp_path / "spool", max_audio_bytes=1024)


@pytest.fixture
async def harness(config):
    spool = AudioSpool(config.spool_dir, config.max_audio_bytes, config.job_ttl_seconds)

    async def runner(job):
        return TranscriptionResult(
            text="Guten Morgen",
            language="de",
            language_probability=0.98,
            duration=2.5,
            segments=[{"start": 0.0, "end": 2.5, "text": "Guten Morgen"}],
        )

    queue = JobQueue(runner, cleanup=spool.discard)
    queue.start()
    manager = ModelManager(config)
    yield WhisperTools(config, spool, queue, manager), spool, queue
    await queue.stop()


async def _call(tools, name, args):
    content = await tools.call(name, args)
    return json.loads(content[0].text)


async def test_list_tools_exposes_three(harness):
    tools, _, _ = harness
    names = {t.name for t in tools.list_tools()}
    assert names == {"transcribe_audio", "get_transcription", "whisper_status"}


async def test_tool_description_carries_the_size_limit(harness):
    tools, _, _ = harness
    describe = next(t for t in tools.list_tools() if t.name == "transcribe_audio")
    assert "MiB" in (describe.description or "")


async def test_transcribe_returns_a_job_id_immediately(harness):
    tools, _, _ = harness
    out = await _call(tools, "transcribe_audio", {"audio_base64": WAV, "filename": "memo.wav"})
    assert out["status"] in ("queued", "running")
    assert out["job_id"]
    # The model has not been started in this harness, so the hint must say so
    # rather than telling the client to poll for a result that cannot come yet.
    assert out["model_state"] == "loading"


async def test_transcribe_then_collect(harness):
    tools, _, _ = harness
    submitted = await _call(tools, "transcribe_audio", {"audio_base64": WAV})
    out = await _call(
        tools,
        "get_transcription",
        {"job_id": submitted["job_id"], "wait_seconds": 2},
    )
    assert out["status"] == "completed"
    assert out["text"] == "Guten Morgen"
    assert out["language"] == "de"
    assert "segments" not in out


async def test_collect_can_include_segments(harness):
    tools, _, _ = harness
    submitted = await _call(tools, "transcribe_audio", {"audio_base64": WAV})
    out = await _call(
        tools,
        "get_transcription",
        {"job_id": submitted["job_id"], "wait_seconds": 2, "include_segments": True},
    )
    assert out["segments"][0]["text"] == "Guten Morgen"


async def test_audio_id_from_upload_is_accepted(harness):
    tools, spool, queue = harness
    audio_id = spool.store(b"RIFFfake", "memo.wav")
    out = await _call(tools, "transcribe_audio", {"audio_id": audio_id})
    assert out["job_id"]
    # The name the uploader gave survives into the job listing without the
    # client having to repeat it.
    assert queue.get(out["job_id"]).filename == "memo.wav"


async def test_failed_model_does_not_tell_the_client_to_wait(harness):
    tools, _, _ = harness
    tools._manager._state = "failed"
    tools._manager._error = "OSError: no space left on device"
    out = await _call(tools, "transcribe_audio", {"audio_base64": WAV})
    assert "could not be loaded" in out["next_step"]
    assert "no space left" in out["next_step"]


async def test_ready_model_points_at_get_transcription(harness):
    tools, _, _ = harness
    tools._manager._state = "ready"
    out = await _call(tools, "transcribe_audio", {"audio_base64": WAV})
    assert "get_transcription" in out["next_step"]


async def test_unknown_audio_id_is_rejected(harness):
    tools, _, _ = harness
    with pytest.raises(ValueError, match="unknown or has expired"):
        await tools.call("transcribe_audio", {"audio_id": "0" * 32})


async def test_exactly_one_audio_source_required(harness):
    tools, _, _ = harness
    with pytest.raises(ValueError, match="exactly one"):
        await tools.call("transcribe_audio", {})
    with pytest.raises(ValueError, match="exactly one"):
        await tools.call("transcribe_audio", {"audio_base64": WAV, "audio_url": "https://x/y.wav"})


async def test_oversized_base64_is_rejected(harness):
    tools, _, _ = harness
    with pytest.raises(ValueError, match="decodes to more than"):
        await tools.call("transcribe_audio", {"audio_base64": "A" * 8192})


async def test_unknown_job_id_is_rejected(harness):
    tools, _, _ = harness
    with pytest.raises(ValueError, match="unknown job_id"):
        await tools.call("get_transcription", {"job_id": "nope"})


async def test_wait_seconds_is_capped(harness):
    tools, _, _ = harness
    submitted = await _call(tools, "transcribe_audio", {"audio_base64": WAV})
    # 10_000 must not become a 10_000-second await; the job finishes at once.
    out = await asyncio.wait_for(
        _call(tools, "get_transcription", {"job_id": submitted["job_id"], "wait_seconds": 10_000}),
        timeout=5,
    )
    assert out["status"] == "completed"


async def test_status_reports_model_and_backlog(harness):
    tools, _, _ = harness
    out = await _call(tools, "whisper_status", {})
    assert out["model"] == "base"
    assert out["device"] == "cpu"
    assert out["model_state"] == "loading"
    assert out["upload_endpoint"] == "POST /mcp/upload"
    assert out["max_audio_bytes"] == 1024


async def test_unknown_tool_raises(harness):
    tools, _, _ = harness
    with pytest.raises(ValueError, match="Unknown tool"):
        await tools.call("nope", {})


async def test_spooled_audio_is_cleaned_up_after_the_job(harness):
    tools, spool, queue = harness
    submitted = await _call(tools, "transcribe_audio", {"audio_base64": WAV})
    await queue.wait(submitted["job_id"], timeout=2)
    job = queue.get(submitted["job_id"])
    assert not list(spool._dir.glob(f"{job.audio_id}.*"))
