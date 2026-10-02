"""Environment-driven configuration.

Every knob is an env var so the Helm chart can set it through `env:` without a
config file — unlike mcp-calendar there is nothing secret to mount here.
"""

import os
from dataclasses import dataclass
from pathlib import Path


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Config:
    # Whisper model. On a Raspberry Pi anything above "small" is slower than
    # real time; "base" with int8 is the practical sweet spot.
    model: str = "base"
    device: str = "cpu"
    compute_type: str = "int8"
    # 0 lets CTranslate2 pick, which is one thread per core — too greedy when
    # the pod shares a node, so the chart pins this to the CPU limit.
    cpu_threads: int = 0
    # Persisted across restarts by a PVC; re-downloading the model on every
    # pod restart is minutes of Pi-speed I/O.
    model_dir: Path = Path("/models")
    # Audio is spooled to disk rather than held in memory so a queue of
    # multi-MB uploads cannot OOM a 4 GB Pi.
    spool_dir: Path = Path("/tmp/mcp-whisper")
    max_audio_bytes: int = 64 * 1024 * 1024
    max_queued_jobs: int = 16
    job_ttl_seconds: int = 24 * 60 * 60
    max_jobs_retained: int = 200
    # Silero VAD trims silence before decoding — a large win on voice memos.
    vad_filter: bool = True
    # Empty means any host; set to a comma-separated allowlist to restrict
    # which hosts `audio_url` may fetch from.
    allowed_url_hosts: tuple[str, ...] = ()


def load_config() -> Config:
    hosts = tuple(
        h.strip() for h in os.getenv("WHISPER_ALLOWED_URL_HOSTS", "").split(",") if h.strip()
    )
    return Config(
        model=os.getenv("WHISPER_MODEL", "base"),
        device=os.getenv("WHISPER_DEVICE", "cpu"),
        compute_type=os.getenv("WHISPER_COMPUTE_TYPE", "int8"),
        cpu_threads=_int_env("WHISPER_CPU_THREADS", 0),
        model_dir=Path(os.getenv("WHISPER_MODEL_DIR", "/models")),
        spool_dir=Path(os.getenv("WHISPER_SPOOL_DIR", "/tmp/mcp-whisper")),
        max_audio_bytes=_int_env("WHISPER_MAX_AUDIO_BYTES", 64 * 1024 * 1024),
        max_queued_jobs=_int_env("WHISPER_MAX_QUEUED_JOBS", 16),
        job_ttl_seconds=_int_env("WHISPER_JOB_TTL_SECONDS", 24 * 60 * 60),
        max_jobs_retained=_int_env("WHISPER_MAX_JOBS_RETAINED", 200),
        vad_filter=_bool_env("WHISPER_VAD_FILTER", True),
        allowed_url_hosts=hosts,
    )
