"""The speech-to-text service with a fake Whisper model: no model file, no audio decoding."""
from types import SimpleNamespace

from fastapi.testclient import TestClient

from bot import stt_service
from bot.stt_service import MAX_BYTES, SttError, WhisperEngine, create_app


class FakeModel:
    """Stands in for faster_whisper.WhisperModel: `transcribe` returns (segments, info)."""

    def __init__(self, text="twenty litres of oat drink for Monday", language="en", duration=6.0,
                 probs=None, fail=False):
        self.text, self.language, self.duration, self.probs, self.fail = text, language, duration, probs, fail
        self.calls = []
        self.segments_read = 0

    def transcribe(self, audio, language=None, **options):
        self.calls.append({"language": language, **options})
        if self.fail:
            raise ValueError("decoder said: <the raw bytes of the file>")

        def segments():
            for part in self.text.split(" | "):
                self.segments_read += 1
                yield SimpleNamespace(text=f" {part} ")

        info = SimpleNamespace(language=language or self.language, language_probability=0.97314,
                               duration=self.duration, all_language_probs=self.probs)
        return segments(), info


def client(model: FakeModel) -> TestClient:
    return TestClient(create_app(WhisperEngine("small", model=model), preload=False))


def test_health_says_the_model_and_if_it_is_loaded():
    assert client(FakeModel()).get("/health").json() == {"status": "ok", "model": "small", "ready": True}
    unloaded = TestClient(create_app(WhisperEngine("small"), preload=False))
    assert unloaded.get("/health").json()["ready"] is False


def test_a_voice_message_becomes_text():
    model = FakeModel(text="twenty litres | of oat drink for Monday")
    body = client(model).post("/transcribe", content=b"OggS-audio").json()
    assert body["text"] == "twenty litres of oat drink for Monday"
    assert body["language"] == "en"
    assert body["language_probability"] == 0.973
    assert body["audio_seconds"] == 6.0
    assert body["model"] == "small"
    assert isinstance(body["duration_ms"], int)
    assert model.calls == [{"language": None, "beam_size": 5, "vad_filter": True}]


def test_the_caller_can_name_the_language():
    model = FakeModel(language="fi")
    body = client(model).post("/transcribe?language=fi", content=b"x").json()
    assert body["language"] == "fi"
    assert model.calls[0]["language"] == "fi"


def test_a_language_we_do_not_serve_is_refused():
    response = client(FakeModel()).post("/transcribe?language=de", content=b"x")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_a_clip_heard_as_another_language_is_read_again_in_the_most_likely_of_ours():
    model = FakeModel(language="nn", probs=[("nn", 0.5), ("sv", 0.2), ("fi", 0.25), ("de", 0.05)])
    body = client(model).post("/transcribe", content=b"x").json()
    assert [call["language"] for call in model.calls] == [None, "fi"]
    assert body["language"] == "fi"


def test_silence_gives_empty_text_not_an_error():
    response = client(FakeModel(text="")).post("/transcribe", content=b"x")
    assert response.status_code == 200
    assert response.json()["text"] == ""


def test_no_audio_is_refused():
    response = client(FakeModel()).post("/transcribe", content=b"")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "EMPTY_AUDIO"


def test_a_file_over_the_size_limit_is_refused_before_the_model_runs():
    model = FakeModel()
    response = client(model).post("/transcribe", content=b"x" * (MAX_BYTES + 1))
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "AUDIO_TOO_LARGE"
    assert model.calls == []


def test_a_message_over_30_seconds_is_refused_and_not_transcribed():
    model = FakeModel(duration=31.0)
    response = client(model).post("/transcribe", content=b"x")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "AUDIO_TOO_LONG"
    assert model.segments_read == 0


def test_audio_that_cannot_be_read_gives_a_fixed_sentence_without_the_decoder_text():
    response = client(FakeModel(fail=True)).post("/transcribe", content=b"not audio")
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "CANNOT_READ_AUDIO"
    assert "raw bytes" not in error["message"]


def test_check_command_prints_the_result(tmp_path, capsys, monkeypatch):
    clip = tmp_path / "clip.ogg"
    clip.write_bytes(b"x")
    monkeypatch.setattr(stt_service, "WhisperEngine", lambda: WhisperEngine("small", model=FakeModel(text="moi")))
    assert stt_service.main(["--check", str(clip)]) == 0
    assert '"text": "moi"' in capsys.readouterr().out


def test_check_command_reports_an_error_with_exit_code_1(tmp_path, capsys, monkeypatch):
    clip = tmp_path / "clip.ogg"
    clip.write_bytes(b"x")
    monkeypatch.setattr(stt_service, "WhisperEngine", lambda: WhisperEngine("small", model=FakeModel(duration=99)))
    assert stt_service.main(["--check", str(clip)]) == 1
    assert "AUDIO_TOO_LONG" in capsys.readouterr().out


def test_stt_error_keeps_its_parts():
    error = SttError(422, "X", "y")
    assert (error.status, error.code, error.message) == (422, "X", "y")


def test_a_model_that_cannot_load_is_503_not_a_fault_of_the_audio(monkeypatch):
    engine = WhisperEngine("small")
    monkeypatch.setattr(engine, "load", lambda: (_ for _ in ()).throw(RuntimeError("no memory")))
    response = TestClient(create_app(engine, preload=False)).post("/transcribe", content=b"x")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "STT_UNAVAILABLE"
