"""Internal speech-to-text service (#1331): Whisper on our own server.

It turns one short voice message into text and does nothing else. Nemotron stays the agent
that reads the text and decides. The audio and the text are never stored and never logged
here; the caller (the Telegram bot) shows the text to the person before anything is ordered.

Reached only inside the compose network (no published port, no Caddy route), like the Buyer
worker. It holds no key.
"""
from __future__ import annotations

import io
import json
import os
import sys
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

# A kitchen in Finland: Finnish, Swedish and English; Polish because the team speaks it.
LANGUAGES = ("fi", "en", "sv", "pl")
MAX_BYTES = 2 * 1024 * 1024      # a 30 s Telegram voice message is about 0.2 MB
MAX_SECONDS = 30.0


class SttError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


@dataclass(frozen=True)
class Transcript:
    text: str
    language: str
    language_probability: float
    audio_seconds: float


class WhisperEngine:
    """One Whisper model, loaded once, one transcription at a time (it uses every core it gets)."""

    def __init__(self, model_name: str | None = None, model=None):
        self.model_name = model_name or os.environ.get("WHISPER_MODEL", "small")
        self._model = model
        self._load_lock = threading.Lock()
        self._run_lock = threading.Lock()

    @property
    def ready(self) -> bool:
        return self._model is not None

    def load(self):
        with self._load_lock:
            if self._model is None:
                from faster_whisper import WhisperModel     # heavy: only this container has it
                self._model = WhisperModel(
                    self.model_name, device="cpu", compute_type="int8",
                    cpu_threads=int(os.environ.get("WHISPER_THREADS", "2")),
                )
        return self._model

    def _run(self, audio: bytes, language: str | None):
        try:
            model = self.load()
        except Exception:
            # No model (the first download failed, or no memory): not the caller's audio.
            raise SttError(503, "STT_UNAVAILABLE", "Speech to text is not ready. Type the request instead.") from None
        try:
            # vad_filter drops silence, so a silent message gives no text instead of invented words.
            return model.transcribe(io.BytesIO(audio), language=language, beam_size=5, vad_filter=True)
        except Exception:
            # The decoder's own message can quote the input: say only that it could not be read.
            raise SttError(422, "CANNOT_READ_AUDIO", "The audio could not be read. Send a voice message again.") from None

    def transcribe(self, audio: bytes, language: str | None = None) -> Transcript:
        with self._run_lock:
            segments, info = self._run(audio, language)
            if info.duration > MAX_SECONDS:
                # `segments` is lazy: nothing was transcribed yet, so a long file costs only its decoding.
                raise SttError(422, "AUDIO_TOO_LONG", f"The message is longer than {int(MAX_SECONDS)} seconds. Send a shorter one.")
            if language is None and info.language not in LANGUAGES:
                # A short clip is sometimes heard as a language no kitchen here speaks: take the most
                # likely of ours and read it again in that one.
                ours = [(lang, p) for lang, p in (info.all_language_probs or []) if lang in LANGUAGES]
                best = max(ours, key=lambda row: row[1])[0] if ours else "en"
                segments, info = self._run(audio, best)
            text = " ".join(part.text.strip() for part in segments).strip()
            return Transcript(text, info.language, round(float(info.language_probability), 3), round(float(info.duration), 2))


def _error(exc: SttError) -> JSONResponse:
    return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status)


def create_app(engine: WhisperEngine | None = None, preload: bool | None = None) -> FastAPI:
    engine = engine or WhisperEngine()
    if preload is None:
        preload = os.environ.get("STT_PRELOAD", "true").lower() != "false"

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if preload:
            # In the background: the first start downloads the model, and /health must answer meanwhile.
            threading.Thread(target=engine.load, daemon=True).start()
        yield

    app = FastAPI(title="Kitchen Buyer speech to text", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "model": engine.model_name, "ready": engine.ready}

    @app.post("/transcribe")
    async def transcribe(request: Request):
        """Body: the audio file itself (OGG/Opus from Telegram; any format the decoder knows).
        `?language=fi|en|sv|pl` is optional; without it the language is detected."""
        language = request.query_params.get("language") or None
        try:
            if language is not None and language not in LANGUAGES:
                raise SttError(422, "INVALID_REQUEST", f"language must be one of {', '.join(LANGUAGES)}.")
            declared = request.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > MAX_BYTES:
                raise SttError(413, "AUDIO_TOO_LARGE", "The audio file is too large.")
            audio = await request.body()
            if not audio:
                raise SttError(422, "EMPTY_AUDIO", "The request has no audio.")
            if len(audio) > MAX_BYTES:
                raise SttError(413, "AUDIO_TOO_LARGE", "The audio file is too large.")
            started = time.monotonic()
            result = await run_in_threadpool(engine.transcribe, audio, language)
        except SttError as exc:
            return _error(exc)
        return {
            "text": result.text,            # "" when nothing was said: the caller asks the person again
            "language": result.language,
            "language_probability": result.language_probability,
            "audio_seconds": result.audio_seconds,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "model": engine.model_name,
        }

    return app


def main(argv: list[str] | None = None) -> int:
    """No argument: serve on port 8002. `--check <file>`: transcribe one file and print the result
    (a check on the server: `docker compose exec stt python -m bot.stt_service --check <file>`)."""
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--check"] and len(argv) == 2:
        engine = WhisperEngine()
        started = time.monotonic()
        with open(argv[1], "rb") as handle:
            try:
                result = engine.transcribe(handle.read())
            except SttError as exc:
                print(json.dumps({"error": {"code": exc.code, "message": exc.message}}))
                return 1
        print(json.dumps({**result.__dict__, "duration_ms": int((time.monotonic() - started) * 1000),
                          "model": engine.model_name}, ensure_ascii=False))
        return 0
    import uvicorn
    uvicorn.run(create_app(), host="0.0.0.0", port=int(os.environ.get("STT_PORT", "8002")), access_log=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
