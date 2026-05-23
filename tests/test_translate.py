"""
Russian→English translate path: language passthrough on transcription,
LLM call shape, key rotation on chat-completions, empty-transcript
short-circuit.
"""
import io
import json
import struct
from unittest.mock import patch
from urllib.error import HTTPError

import pytest


def _http_error(code):
    return HTTPError("https://api.groq.com/", code, "test", {}, io.BytesIO(b""))


def _ok_transcribe(text):
    class _Resp:
        def read(self):
            return json.dumps({"text": text}).encode()
    return _Resp()


def _ok_chat(content):
    class _Resp:
        def read(self):
            return json.dumps({"choices": [{"message": {"content": content}}]}).encode()
    return _Resp()


@pytest.fixture
def transcriber_module(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEYS", "k1,k2,k3")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    import importlib
    import transcriber as t
    importlib.reload(t)
    yield t


def _write_silent_wav(tmp_path):
    p = tmp_path / "silent.wav"
    samplerate = 16000
    num_samples = samplerate
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


def test_language_field_in_multipart(transcriber_module, tmp_path):
    t = transcriber_module
    wav = _write_silent_wav(tmp_path)
    captured = {}

    def fake_urlopen(req, timeout):
        captured["body"] = req.data
        return _ok_transcribe("привет")

    with patch.object(t, "urlopen", side_effect=fake_urlopen):
        t.Transcriber()._transcribe_groq(wav, language="ru")

    assert b'name="language"' in captured["body"]
    assert b"\r\nru\r\n" in captured["body"]


def test_language_omitted_by_default(transcriber_module, tmp_path):
    t = transcriber_module
    wav = _write_silent_wav(tmp_path)
    captured = {}

    def fake_urlopen(req, timeout):
        captured["body"] = req.data
        return _ok_transcribe("hello")

    with patch.object(t, "urlopen", side_effect=fake_urlopen):
        t.Transcriber()._transcribe_groq(wav)

    assert b'name="language"' not in captured["body"]


def test_translate_groq_posts_chat_completions(transcriber_module):
    t = transcriber_module
    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode())
        captured["ct"] = req.headers.get("Content-type")
        return _ok_chat("Hello world")

    with patch.object(t, "urlopen", side_effect=fake_urlopen):
        result = t.Transcriber()._translate_groq("Привет мир")

    assert result == "Hello world"
    assert captured["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert captured["ct"] == "application/json"
    assert captured["body"]["model"] == "llama-3.3-70b-versatile"
    # Bumped from 0.0 for more natural phrasing on conversational speech.
    assert captured["body"]["temperature"] == 0.2
    msgs = captured["body"]["messages"]
    assert msgs[0]["role"] == "system"
    assert "Russian" in msgs[0]["content"] and "English" in msgs[0]["content"]
    assert msgs[1] == {"role": "user", "content": "Привет мир"}


def test_translate_rotates_on_429(transcriber_module):
    t = transcriber_module
    calls = []

    def fake_urlopen(req, timeout):
        calls.append(req.headers.get("Authorization"))
        if len(calls) < 3:
            raise _http_error(429)
        return _ok_chat("ok")

    with patch.object(t, "urlopen", side_effect=fake_urlopen):
        result = t.Transcriber()._translate_groq("текст")

    assert result == "ok"
    assert calls == ["Bearer k1", "Bearer k2", "Bearer k3"]


def test_translate_500_propagates(transcriber_module):
    t = transcriber_module

    def fake_urlopen(req, timeout):
        raise _http_error(500)

    with patch.object(t, "urlopen", side_effect=fake_urlopen):
        with pytest.raises(t.TranscriptionError):
            t.Transcriber()._translate_groq("текст")


def test_transcribe_and_translate_skips_llm_on_empty(transcriber_module, tmp_path):
    """If the Russian transcript is empty (hallucination/silence), the LLM
    must NOT be called — both to save quota and to avoid the LLM inventing
    output from an empty input."""
    t = transcriber_module
    wav = _write_silent_wav(tmp_path)
    chat_calls = []

    def fake_urlopen(req, timeout):
        if "audio/transcriptions" in req.full_url:
            return _ok_transcribe("Спасибо за просмотр")  # known hallucination
        chat_calls.append(True)
        return _ok_chat("should not happen")

    with patch.object(t, "urlopen", side_effect=fake_urlopen):
        result = t.Transcriber().transcribe_and_translate_sync(wav)

    assert result == ""
    assert chat_calls == []


def test_transcribe_and_translate_happy_path(transcriber_module, tmp_path):
    t = transcriber_module
    wav = _write_silent_wav(tmp_path)
    captured_msgs = {}

    def fake_urlopen(req, timeout):
        if "audio/transcriptions" in req.full_url:
            return _ok_transcribe("Как дела?")
        body = json.loads(req.data.decode())
        captured_msgs["user"] = body["messages"][1]["content"]
        return _ok_chat("How are you?")

    with patch.object(t, "urlopen", side_effect=fake_urlopen):
        result = t.Transcriber().transcribe_and_translate_sync(wav)

    # Translator must see the clean Russian (no trailing space from transcribe_wav_sync)
    assert captured_msgs["user"] == "Как дела?"
    # Final output has the trailing space matching dictate-path convention
    # ("How are you?" is below REFINE_MIN_CHARS so refinement is skipped)
    assert result == "How are you? "


def test_whisper_prompt_sent_in_translate_mode(transcriber_module, tmp_path):
    """Translate mode passes a Russian-context prompt to bias Whisper toward
    well-formed Russian sentences. Dictate mode (no language) must NOT send a
    prompt — that would bias against other languages."""
    t = transcriber_module
    wav = _write_silent_wav(tmp_path)
    captured_bodies = []

    def fake_urlopen(req, timeout):
        if "audio/transcriptions" in req.full_url:
            captured_bodies.append(req.data)
            return _ok_transcribe("")  # empty -> skips LLM
        return _ok_chat("")

    with patch.object(t, "urlopen", side_effect=fake_urlopen):
        t.Transcriber().transcribe_and_translate_sync(wav)
        t.Transcriber().transcribe_wav_sync(wav)  # dictate path

    assert b'name="prompt"' in captured_bodies[0], "translate mode must send Whisper prompt"
    assert b'name="prompt"' not in captured_bodies[1], "dictate mode must NOT send Whisper prompt"


def test_refinement_runs_for_long_translations(transcriber_module, tmp_path):
    """Translations >= REFINE_MIN_CHARS get a second LLM pass to polish phrasing."""
    t = transcriber_module
    wav = _write_silent_wav(tmp_path)
    chat_payloads = []
    long_first_pass = "I was just thinking that maybe we could meet up tomorrow afternoon."
    assert len(long_first_pass) >= t.REFINE_MIN_CHARS

    def fake_urlopen(req, timeout):
        if "audio/transcriptions" in req.full_url:
            return _ok_transcribe("Я подумал, может встретимся завтра днём.")
        body = json.loads(req.data.decode())
        chat_payloads.append(body)
        # First call = translate, second = refine
        if len(chat_payloads) == 1:
            return _ok_chat(long_first_pass)
        return _ok_chat("I was thinking — maybe we could meet up tomorrow afternoon?")

    with patch.object(t, "urlopen", side_effect=fake_urlopen):
        result = t.Transcriber().transcribe_and_translate_sync(wav)

    assert len(chat_payloads) == 2, "refinement must trigger for long translations"
    # Refinement receives the first-pass English, not the Russian
    assert chat_payloads[1]["messages"][1]["content"] == long_first_pass
    assert "editor" in chat_payloads[1]["messages"][0]["content"].lower()
    assert result == "I was thinking — maybe we could meet up tomorrow afternoon? "


def test_refinement_failure_falls_back_to_first_pass(transcriber_module, tmp_path):
    """If the refinement call errors, the first-pass translation is still returned —
    a stiff translation is better than no translation."""
    t = transcriber_module
    wav = _write_silent_wav(tmp_path)
    chat_count = {"n": 0}
    long_first_pass = "I was just thinking that maybe we could meet up tomorrow afternoon."

    def fake_urlopen(req, timeout):
        if "audio/transcriptions" in req.full_url:
            return _ok_transcribe("Я подумал, может встретимся завтра днём.")
        chat_count["n"] += 1
        if chat_count["n"] == 1:
            return _ok_chat(long_first_pass)
        raise _http_error(500)  # refinement fails

    with patch.object(t, "urlopen", side_effect=fake_urlopen):
        result = t.Transcriber().transcribe_and_translate_sync(wav)

    assert result == long_first_pass + " "
