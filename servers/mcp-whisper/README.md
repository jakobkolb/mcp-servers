# mcp-whisper

Speech-to-text over MCP, backed by [faster-whisper](https://github.com/SYSTRAN/faster-whisper).
Claude has no native transcription, so this gives it a tool for turning voice memos into text.

Transcription is **asynchronous**: `transcribe_audio` returns a `job_id` straight away and a
single background worker drains the queue. On a Raspberry Pi a few minutes of audio take
longer than any MCP client will hold a request open, so there is no synchronous variant.

## Tools

| Tool | Description |
|------|-------------|
| `transcribe_audio` | Queue an audio file for transcription; returns a `job_id` immediately |
| `get_transcription` | Fetch a job's state and, once finished, its text (optionally with timestamps) |
| `whisper_status` | Which model is loaded or still downloading, on which device, and the current backlog |

## Getting audio to the server

`transcribe_audio` takes exactly one of three inputs:

| Input | When to use it |
|-------|----------------|
| `audio_id` | **The practical route for anything above a few hundred KB.** Upload the bytes first (below), then pass the id. |
| `audio_url` | The server downloads the file itself. Good for a Nextcloud/S3 share link. |
| `audio_base64` | Inline. Costs roughly 1.4 tokens per audio byte in the client's context, so only sensible for very short clips. |

The upload sink is mounted at `/mcp/upload` rather than `/upload` on purpose: the OAuth gateway
routes `/mcp(/|$)(.*)` to this service, so the endpoint inherits the same Bearer-token
protection as the MCP endpoint without a second ingress rule.

```bash
curl --data-binary @memo.wav \
     -H 'Authorization: Bearer <token>' \
     'https://whisper.<baseDomain>/mcp/upload?filename=memo.wav'
# → {"audio_id":"4f6243…","bytes":32044,"filename":"memo.wav"}
```

Audio is spooled to disk (never held in memory), deleted as soon as its job finishes, and swept
hourly for anything left unused past the TTL.

## Configuration

| Environment variable | Default | Description |
|---------------------|---------|-------------|
| `WHISPER_MODEL` | `base` | `tiny`, `base`, `small`, `medium`, `large-v3`, … |
| `WHISPER_DEVICE` | `cpu` | `cpu` or `cuda` |
| `WHISPER_COMPUTE_TYPE` | `int8` | `int8`, `int8_float16`, `float16`, `float32` |
| `WHISPER_CPU_THREADS` | `0` (auto) | Pin to the pod's CPU limit so CTranslate2 does not grab every core |
| `WHISPER_MODEL_DIR` | `/models` | Where weights are downloaded. **Back this with a volume** or every restart re-downloads. |
| `WHISPER_SPOOL_DIR` | `/spool` | Where uploaded audio waits for its job |
| `WHISPER_MAX_AUDIO_BYTES` | `67108864` (64 MiB) | Upload ceiling; keep the ingress `proxy-body-size` at or above this |
| `WHISPER_MAX_QUEUED_JOBS` | `16` | Backlog limit before `transcribe_audio` refuses new work |
| `WHISPER_JOB_TTL_SECONDS` | `86400` | How long finished jobs and unused audio are kept |
| `WHISPER_MAX_JOBS_RETAINED` | `200` | Cap on retained finished jobs |
| `WHISPER_VAD_FILTER` | `true` | Silero VAD trims silence before decoding — a large win on voice memos |
| `WHISPER_ALLOWED_URL_HOSTS` | *(empty = any)* | Comma-separated allowlist restricting which hosts `audio_url` may fetch from |
| `PORT` | `8000` | HTTP listen port |
| `LOG_LEVEL` | `INFO` | |

## Model sizing on a Raspberry Pi

Weights are downloaded on first start and the pod serves `/health` throughout, so it never
fails its probe while fetching. Jobs submitted meanwhile stay queued until the model is ready.

| Model | Download | Rough speed on a Pi 5 (CPU, int8) |
|-------|----------|-----------------------------------|
| `tiny` | ~75 MB | several times faster than real time |
| `base` | ~145 MB | around real time — the practical default |
| `small` | ~480 MB | a few times slower than real time |
| `medium` and up | 1.5 GB+ | not worth it on ARM CPU |

## Usage

```bash
# Run directly
WHISPER_MODEL_DIR=./models WHISPER_SPOOL_DIR=./spool uv run mcp-whisper

# Run via Docker
docker build -t mcp-whisper:latest .
docker run --rm -p 8000:8000 -v whisper-models:/models mcp-whisper:latest
```

## ARM / Raspberry Pi notes

Every native dependency ships an `aarch64` manylinux wheel and vendors what it links
against — `ctranslate2` carries its own `libgomp`, `av` carries ffmpeg — so the image
needs no apt layer and the emulated arm64 CI build installs wheels rather than
compiling.

## Limitations

- Jobs live in memory. A pod restart loses queued and finished jobs; the downloaded model
  survives if `WHISPER_MODEL_DIR` is on a PVC.
- One job at a time, by design — parallel decoding on a shared-core box only makes every job
  slower.
