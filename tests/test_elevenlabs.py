import json
import struct
from unittest.mock import patch

import pytest


def _write_silent_wav(tmp_path):
    path = tmp_path / "silent.wav"
    sample_rate = 16000
    data_size = sample_rate * 2
    with open(path, "wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))
        f.write(b"WAVEfmt ")
        f.write(struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16))
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        f.write(b"\x00" * data_size)
    return path


def test_scribe_v2_is_primary_transcriber(monkeypatch, tmp_path):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "eleven-test-key")
    import importlib
    import transcriber as module

    importlib.reload(module)
    wav = _write_silent_wav(tmp_path)
    captured = {}

    class Response:
        def read(self):
            return json.dumps({"text": "hello"}).encode()

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["key"] = request.headers.get("Xi-api-key")
        captured["body"] = request.data
        return Response()

    with patch.object(module, "urlopen", side_effect=fake_urlopen):
        result = module.Transcriber().transcribe_wav_sync(wav)

    assert result == "hello "
    assert captured["url"] == "https://api.elevenlabs.io/v1/speech-to-text"
    assert captured["key"] == "eleven-test-key"
    assert b'name="model_id"' in captured["body"]
    assert b"\r\nscribe_v2\r\n" in captured["body"]
    assert b'name="tag_audio_events"' in captured["body"]
    assert b"\r\nfalse\r\n" in captured["body"]


def test_groq_stt_backend_is_a_real_fallback(monkeypatch, tmp_path):
    import transcriber as module

    wav = _write_silent_wav(tmp_path)
    monkeypatch.setattr(module, "STT_BACKEND", "groq")
    with patch.object(module.Transcriber, "_transcribe_groq", return_value="fallback") as groq:
        result = module.Transcriber().transcribe_wav_sync(wav, language="ru")

    assert result == "fallback "
    groq.assert_called_once_with(wav, language="ru")


def test_unknown_stt_backend_fails_clearly(monkeypatch, tmp_path):
    import transcriber as module

    wav = _write_silent_wav(tmp_path)
    monkeypatch.setattr(module, "STT_BACKEND", "unknown")

    with pytest.raises(module.TranscriptionError, match="unsupported STT backend"):
        module.Transcriber().transcribe_wav_sync(wav)


def test_missing_groq_key_fails_clearly(monkeypatch):
    import transcriber as module

    monkeypatch.setattr(module, "GROQ_API_KEYS", [])
    with pytest.raises(module.TranscriptionError, match="Groq API key"):
        module.Transcriber()._translate_groq("text")


def test_multipart_boundary_is_unique_per_request(monkeypatch, tmp_path):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "eleven-test-key")
    import importlib
    import transcriber as module

    importlib.reload(module)
    wav = _write_silent_wav(tmp_path)
    content_types = []

    class Response:
        def read(self):
            return b'{"text": ""}'

    def fake_urlopen(request, timeout):
        content_types.append(request.headers["Content-type"])
        return Response()

    with patch.object(module, "urlopen", side_effect=fake_urlopen):
        module.Transcriber()._transcribe_elevenlabs(wav)
        module.Transcriber()._transcribe_elevenlabs(wav)

    assert content_types[0] != content_types[1]
