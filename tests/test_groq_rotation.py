"""
Multi-key rotation: a 401/403/429 response with another key available must
advance the index and retry the same request. Other HTTP errors propagate.
"""
import io
import os
from unittest.mock import patch
from urllib.error import HTTPError

import pytest


def _http_error(code):
    return HTTPError("https://api.groq.com/", code, "test", {}, io.BytesIO(b""))


def _ok_response(text="hello"):
    class _Resp:
        def read(self):
            return f'{{"text": "{text}"}}'.encode()

    return _Resp()


@pytest.fixture
def transcriber_module(monkeypatch):
    # Reload module under fixed env so module-level GROQ_API_KEYS is deterministic.
    monkeypatch.setenv("GROQ_API_KEYS", "k1,k2,k3")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    import importlib
    import transcriber as t
    importlib.reload(t)
    yield t


def _write_silent_wav(tmp_path):
    import struct
    p = tmp_path / "silent.wav"
    samplerate = 16000
    num_samples = samplerate  # 1 s of zeros
    data_size = num_samples * 2
    with open(p, "wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<IHHIIHH", 16, 1, 1, samplerate, samplerate * 2, 2, 16))
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        f.write(b"\x00" * data_size)
    return p


def test_rotation_on_429(transcriber_module, tmp_path):
    t = transcriber_module
    wav = _write_silent_wav(tmp_path)
    calls = []

    def fake_urlopen(req, timeout):
        calls.append(req.headers.get("Authorization"))
        if len(calls) < 3:
            raise _http_error(429)
        return _ok_response("ok")

    with patch.object(t, "urlopen", side_effect=fake_urlopen):
        result = t.Transcriber()._transcribe_groq(wav)

    assert result == "ok"
    assert calls == ["Bearer k1", "Bearer k2", "Bearer k3"]


def test_500_propagates_without_rotation(transcriber_module, tmp_path):
    t = transcriber_module
    wav = _write_silent_wav(tmp_path)
    calls = []

    def fake_urlopen(req, timeout):
        calls.append(req.headers.get("Authorization"))
        raise _http_error(500)

    with patch.object(t, "urlopen", side_effect=fake_urlopen):
        with pytest.raises(t.TranscriptionError):
            t.Transcriber()._transcribe_groq(wav)

    assert len(calls) == 1


def test_all_keys_exhausted_raises(transcriber_module, tmp_path):
    t = transcriber_module
    wav = _write_silent_wav(tmp_path)

    def fake_urlopen(req, timeout):
        raise _http_error(401)

    with patch.object(t, "urlopen", side_effect=fake_urlopen):
        with pytest.raises(t.TranscriptionError, match="exhausted"):
            t.Transcriber()._transcribe_groq(wav)


def test_user_agent_override(transcriber_module, tmp_path):
    t = transcriber_module
    wav = _write_silent_wav(tmp_path)
    captured = {}

    def fake_urlopen(req, timeout):
        captured["ua"] = req.headers.get("User-agent")
        return _ok_response("hi")

    with patch.object(t, "urlopen", side_effect=fake_urlopen):
        t.Transcriber()._transcribe_groq(wav)

    # Default urllib UA is "Python-urllib/X.Y" and gets 403'd by Groq's WAF —
    # we must override.
    assert captured["ua"] is not None
    assert "Python-urllib" not in captured["ua"]
