import base64
import time

import pytest
from mcp_whisper.audio import AudioNotFound, AudioSpool, AudioTooLarge


@pytest.fixture
def spool(tmp_path):
    return AudioSpool(tmp_path / "spool", max_bytes=1024, ttl_seconds=60)


def test_store_and_read_back(spool):
    audio_id = spool.store(b"RIFFfake", "memo.wav")
    assert spool.path(audio_id).suffix == ".wav"
    assert spool.path(audio_id).read_bytes() == b"RIFFfake"


def test_unknown_extension_falls_back(spool):
    audio_id = spool.store(b"x", "memo.exe")
    assert spool.path(audio_id).suffix == ".audio"


def test_missing_filename_falls_back(spool):
    audio_id = spool.store(b"x")
    assert spool.path(audio_id).suffix == ".audio"


def test_store_rejects_oversized(spool):
    with pytest.raises(AudioTooLarge):
        spool.store(b"x" * 1025, "memo.wav")


def test_store_rejects_empty(spool):
    with pytest.raises(ValueError):
        spool.store(b"", "memo.wav")


def test_discard_removes_file(spool):
    audio_id = spool.store(b"x", "memo.wav")
    spool.discard(audio_id)
    with pytest.raises(AudioNotFound):
        spool.path(audio_id)


def test_discard_is_idempotent(spool):
    spool.discard("deadbeef")  # never existed — must not raise


def test_path_rejects_traversal(spool):
    with pytest.raises(AudioNotFound):
        spool.path("../../etc/passwd")


def test_store_base64_roundtrip(spool):
    audio_id = spool.store_base64(base64.b64encode(b"hello").decode(), "memo.wav")
    assert spool.path(audio_id).read_bytes() == b"hello"


def test_store_base64_rejects_garbage(spool):
    with pytest.raises(ValueError, match="not valid base64"):
        spool.store_base64("not base64 !!!", "memo.wav")


def test_store_base64_rejects_oversized_before_decoding(spool):
    # 4/3 inflation means we can refuse without materialising the bytes.
    with pytest.raises(AudioTooLarge):
        spool.store_base64("A" * 4096, "memo.wav")


def test_sweep_removes_expired_only(spool, tmp_path):
    old = spool.store(b"old", "a.wav")
    fresh = spool.store(b"new", "b.wav")
    stale_path = spool.path(old)
    past = time.time() - 3600
    import os

    os.utime(stale_path, (past, past))

    assert spool.sweep() == 1
    with pytest.raises(AudioNotFound):
        spool.path(old)
    assert spool.path(fresh).read_bytes() == b"new"


async def test_store_url_rejects_non_http(spool):
    with pytest.raises(ValueError, match="http"):
        await spool.store_url("file:///etc/passwd")


async def test_store_url_enforces_allowlist(spool):
    with pytest.raises(ValueError, match="not in WHISPER_ALLOWED_URL_HOSTS"):
        await spool.store_url("https://evil.example/x.wav", allowed_hosts=("cloud.example",))


def test_original_name_is_remembered_and_forgotten(spool):
    audio_id = spool.store(b"x", "voice-memo.wav")
    assert spool.original_name(audio_id) == "voice-memo.wav"
    spool.discard(audio_id)
    assert spool.original_name(audio_id) is None


def test_original_name_is_none_when_not_supplied(spool):
    assert spool.original_name(spool.store(b"x")) is None
