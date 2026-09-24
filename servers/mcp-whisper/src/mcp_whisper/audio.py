"""Getting audio bytes onto local disk, whatever route they arrive by."""

import base64
import binascii
import logging
import os
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("mcp-whisper.audio")

# Extensions we hand to PyAV as a demuxer hint. Anything ffmpeg can open works;
# the suffix only helps it pick a demuxer faster.
_SAFE_SUFFIXES = frozenset(
    {".wav", ".mp3", ".m4a", ".mp4", ".aac", ".flac", ".ogg", ".oga", ".opus", ".webm", ".wma"}
)


class AudioTooLarge(ValueError):
    """Raised when an upload exceeds the configured byte budget."""


class AudioNotFound(KeyError):
    """Raised when an audio_id has expired or never existed."""


def _suffix_for(filename: str | None) -> str:
    if not filename:
        return ".audio"
    suffix = Path(filename).suffix.lower()
    return suffix if suffix in _SAFE_SUFFIXES else ".audio"


class AudioSpool:
    """Stores audio on disk under an opaque id.

    Both the upload endpoint and the inline base64/url inputs funnel through
    here, so the queue only ever carries an id and jobs survive without holding
    megabytes of audio in memory.
    """

    def __init__(self, spool_dir: Path, max_bytes: int, ttl_seconds: int) -> None:
        self._dir = spool_dir
        self._max_bytes = max_bytes
        self._ttl = ttl_seconds
        # Original filenames, purely cosmetic: the spooled file is named after
        # the opaque id, so this is the only place the uploader's name lives.
        # In-memory like the jobs themselves, and lost on restart just as they are.
        self._names: dict[str, str] = {}
        self._dir.mkdir(parents=True, exist_ok=True)

    @property
    def max_bytes(self) -> int:
        return self._max_bytes

    def store(self, data: bytes, filename: str | None = None) -> str:
        if len(data) > self._max_bytes:
            raise AudioTooLarge(
                f"audio is {len(data)} bytes, limit is {self._max_bytes} bytes "
                f"({self._max_bytes // (1024 * 1024)} MiB)"
            )
        if not data:
            raise ValueError("audio is empty")
        audio_id = uuid.uuid4().hex
        path = self._dir / f"{audio_id}{_suffix_for(filename)}"
        # Write to a temp name first so a crash mid-write cannot leave a
        # truncated file that later looks like a valid id.
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(data)
        tmp.rename(path)
        if filename:
            self._names[audio_id] = filename
        return audio_id

    def path(self, audio_id: str) -> Path:
        # audio_id is used to build a filename, so reject anything that could
        # escape the spool directory.
        if not audio_id or not audio_id.isalnum():
            raise AudioNotFound(audio_id)
        for candidate in self._dir.glob(f"{audio_id}.*"):
            if candidate.suffix != ".part":
                return candidate
        raise AudioNotFound(audio_id)

    def original_name(self, audio_id: str) -> str | None:
        """The filename the uploader supplied, if any."""
        return self._names.get(audio_id)

    def discard(self, audio_id: str) -> None:
        self._names.pop(audio_id, None)
        try:
            self.path(audio_id).unlink(missing_ok=True)
        except AudioNotFound:
            pass

    def sweep(self, now: float | None = None) -> int:
        """Delete spooled audio older than the TTL. Returns how many went."""
        cutoff = (now if now is not None else time.time()) - self._ttl
        removed = 0
        for candidate in self._dir.iterdir():
            try:
                if candidate.is_file() and candidate.stat().st_mtime < cutoff:
                    candidate.unlink(missing_ok=True)
                    self._names.pop(candidate.stem, None)
                    removed += 1
            except OSError:  # pragma: no cover — racing sweeps
                logger.debug("could not sweep %s", candidate, exc_info=True)
        return removed

    def store_base64(self, payload: str, filename: str | None = None) -> str:
        # Reject before decoding: base64 inflates by 4/3, so the encoded length
        # already tells us whether the result blows the budget.
        if len(payload) // 4 * 3 > self._max_bytes:
            raise AudioTooLarge(
                f"base64 payload decodes to more than {self._max_bytes} bytes "
                f"({self._max_bytes // (1024 * 1024)} MiB)"
            )
        try:
            data = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError(f"audio_base64 is not valid base64: {exc}") from exc
        return self.store(data, filename)

    async def store_url(
        self,
        url: str,
        filename: str | None = None,
        allowed_hosts: tuple[str, ...] = (),
    ) -> str:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("audio_url must be an http(s) URL")
        if allowed_hosts and parsed.hostname not in allowed_hosts:
            raise ValueError(
                f"audio_url host {parsed.hostname!r} is not in WHISPER_ALLOWED_URL_HOSTS"
            )

        chunks: list[bytes] = []
        total = 0
        async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    # Abort mid-stream rather than buffering a hostile response.
                    if total > self._max_bytes:
                        raise AudioTooLarge(
                            f"audio_url exceeds {self._max_bytes} bytes "
                            f"({self._max_bytes // (1024 * 1024)} MiB)"
                        )
                    chunks.append(chunk)
        return self.store(b"".join(chunks), filename or os.path.basename(parsed.path) or None)
