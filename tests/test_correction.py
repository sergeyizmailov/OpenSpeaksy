"""
Dictation correction pass: model/temperature routing, the length gate, the
switch, sanitizing of model output, and fallback to the raw transcript.
"""
import io
import json
import struct
from unittest.mock import patch
from urllib.error import HTTPError

import pytest


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
    monkeypatch.setenv("MISTRAL_API_KEY", "mistral-test-key")
    # Shipped default is off; these tests exercise the pass itself.
    monkeypatch.setenv("OPENSPEAKSY_CORRECT_DICTATION", "1")
    monkeypatch.delenv("OPENSPEAKSY_GLOSSARY", raising=False)
    import importlib
    import transcriber as t
    importlib.reload(t)
    monkeypatch.setattr(t, "RETRY_DELAYS_SEC", (0, 0))
    yield t
    importlib.reload(t)


def _write_loud_wav(tmp_path):
    """Non-silent WAV: the empty-transcript guard treats silence differently."""
    p = tmp_path / "loud.wav"
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
        f.write(b"\x10\x20" * num_samples)
    return p


LONG = "Надо переписать раскрытие ключей, потому что оно падает на четыресто двадцать девять."
FIXED = "Надо переписать ротацию ключей, потому что оно падает на 429."


def test_long_transcript_is_corrected(transcriber_module, tmp_path):
    t = transcriber_module
    wav = _write_loud_wav(tmp_path)
    with patch.object(t, "urlopen", side_effect=[_ok_transcribe(LONG), _ok_chat(FIXED)]):
        assert t.Transcriber().transcribe_and_correct_sync(wav) == FIXED + " "


def test_correction_uses_its_own_model_and_temperature(transcriber_module, tmp_path):
    t = transcriber_module
    wav = _write_loud_wav(tmp_path)
    with patch.object(
        t, "urlopen", side_effect=[_ok_transcribe(LONG), _ok_chat(FIXED)]
    ) as mock:
        t.Transcriber().transcribe_and_correct_sync(wav)
    payload = json.loads(mock.call_args_list[1].args[0].data.decode())
    assert payload["model"] == t.MISTRAL_CORRECTION_MODEL
    assert payload["temperature"] == t.CORRECTION_TEMPERATURE
    assert payload["messages"][1]["content"] == LONG


def test_shipped_default_is_off(monkeypatch, tmp_path):
    """Dictation pastes the raw transcript unless the switch is set explicitly."""
    monkeypatch.setenv("MISTRAL_API_KEY", "mistral-test-key")
    monkeypatch.delenv("OPENSPEAKSY_CORRECT_DICTATION", raising=False)
    import importlib
    import transcriber as t
    importlib.reload(t)
    assert t.CORRECT_DICTATION is False
    wav = _write_loud_wav(tmp_path)
    with patch.object(t, "urlopen", side_effect=[_ok_transcribe(LONG)]) as mock:
        assert t.Transcriber().transcribe_and_correct_sync(wav) == LONG + " "
    assert mock.call_count == 1


def test_short_transcript_skips_the_round_trip(transcriber_module, tmp_path):
    t = transcriber_module
    wav = _write_loud_wav(tmp_path)
    with patch.object(t, "urlopen", side_effect=[_ok_transcribe("Привет")]) as mock:
        assert t.Transcriber().transcribe_and_correct_sync(wav) == "Привет "
    assert mock.call_count == 1


def test_switch_off_skips_the_round_trip(transcriber_module, tmp_path, monkeypatch):
    t = transcriber_module
    monkeypatch.setattr(t, "CORRECT_DICTATION", False)
    wav = _write_loud_wav(tmp_path)
    with patch.object(t, "urlopen", side_effect=[_ok_transcribe(LONG)]) as mock:
        assert t.Transcriber().transcribe_and_correct_sync(wav) == LONG + " "
    assert mock.call_count == 1


def test_failed_correction_falls_back_to_raw_transcript(transcriber_module, tmp_path):
    t = transcriber_module
    wav = _write_loud_wav(tmp_path)
    error = HTTPError("https://api.mistral.ai/", 500, "boom", {}, io.BytesIO(b""))
    with patch.object(
        t, "urlopen", side_effect=[_ok_transcribe(LONG), error, error, error]
    ):
        assert t.Transcriber().transcribe_and_correct_sync(wav) == LONG + " "


def test_language_is_passed_through_to_transcription(transcriber_module, tmp_path):
    t = transcriber_module
    wav = _write_loud_wav(tmp_path)
    with patch.object(
        t, "urlopen", side_effect=[_ok_transcribe(LONG), _ok_chat(FIXED)]
    ) as mock:
        t.Transcriber().transcribe_and_correct_sync(wav, language="ru")
    assert b'name="language"\r\n\r\nru' in mock.call_args_list[0].args[0].data


def test_glossary_is_appended_to_the_system_prompt(transcriber_module, tmp_path, monkeypatch):
    t = transcriber_module
    monkeypatch.setattr(t, "CORRECTION_GLOSSARY", "Voxtral, nginx")
    wav = _write_loud_wav(tmp_path)
    with patch.object(
        t, "urlopen", side_effect=[_ok_transcribe(LONG), _ok_chat(FIXED)]
    ) as mock:
        t.Transcriber().transcribe_and_correct_sync(wav)
    system = json.loads(mock.call_args_list[1].args[0].data.decode())["messages"][0]
    assert "Voxtral, nginx" in system["content"]


def test_context_bias_terms_are_sent_with_the_audio(monkeypatch, tmp_path):
    """One repeated form field per term, in the transcription request itself."""
    monkeypatch.setenv("MISTRAL_API_KEY", "mistral-test-key")
    monkeypatch.setenv("OPENSPEAKSY_GLOSSARY", "Binom, Facebook, лид")
    import importlib
    import transcriber as t
    importlib.reload(t)
    wav = _write_loud_wav(tmp_path)
    with patch.object(t, "urlopen", side_effect=[_ok_transcribe(LONG)]) as mock:
        t.Transcriber().transcribe_wav_sync(wav)
    body = mock.call_args_list[0].args[0].data
    assert body.count(b'name="context_bias"') == 3
    for term in ("Binom", "Facebook", "лид"):
        assert term.encode() in body
    importlib.reload(t)


def test_multi_word_glossary_entries_are_dropped_from_context_bias(monkeypatch):
    """The provider rejects terms with whitespace, so they never reach it."""
    monkeypatch.setenv("MISTRAL_API_KEY", "mistral-test-key")
    monkeypatch.setenv("OPENSPEAKSY_GLOSSARY", "Binom, Claude Skills, , Kimi")
    import importlib
    import transcriber as t
    importlib.reload(t)
    assert t.CONTEXT_BIAS_TERMS == ["Binom", "Kimi"]
    # The correction pass still gets the full glossary, phrases included.
    assert "Claude Skills" in t.CORRECTION_GLOSSARY
    importlib.reload(t)


def test_context_bias_is_capped_at_the_provider_limit(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "mistral-test-key")
    monkeypatch.setenv("OPENSPEAKSY_GLOSSARY", ",".join(f"term{i}" for i in range(150)))
    import importlib
    import transcriber as t
    importlib.reload(t)
    assert len(t.CONTEXT_BIAS_TERMS) == 100
    importlib.reload(t)


def test_no_glossary_sends_no_context_bias(transcriber_module, tmp_path):
    t = transcriber_module
    wav = _write_loud_wav(tmp_path)
    with patch.object(t, "urlopen", side_effect=[_ok_transcribe(LONG)]) as mock:
        t.Transcriber().transcribe_wav_sync(wav)
    assert b"context_bias" not in mock.call_args_list[0].args[0].data


def test_translate_mode_does_not_run_the_correction_pass(transcriber_module, tmp_path):
    t = transcriber_module
    wav = _write_loud_wav(tmp_path)
    with patch.object(
        t, "urlopen", side_effect=[_ok_transcribe(LONG), _ok_chat("Short one.")]
    ) as mock:
        assert t.Transcriber().transcribe_and_translate_sync(wav) == "Short one. "
    assert mock.call_count == 2  # transcription + translation only


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("**Ротация** ключей", "Ротация ключей"),
        ("__Ротация__ ключей", "Ротация ключей"),
        ('"Ротация ключей"', "Ротация ключей"),
        ("«Ротация ключей»", "Ротация ключей"),
        ("```\nРотация ключей\n```", "Ротация ключей"),
    ],
)
def test_markup_is_stripped(transcriber_module, raw, expected):
    original = "Ротация ключей"
    assert transcriber_module._accepted_correction(original, raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        # Summarized instead of cleaned up.
        "Ключи.",
        # Answered the dictation instead of cleaning it up.
        "Конечно! Вот как настроить ротацию ключей: сначала откройте консоль, "
        "затем создайте новый ключ, потом обновите его в конфигурации сервиса, "
        "удалите старый и перезапустите агент.",
    ],
)
def test_non_corrections_are_rejected(transcriber_module, raw):
    original = "Надо переписать ротацию ключей, потому что оно падает на 429."
    assert transcriber_module._accepted_correction(original, raw) is None


def test_restored_words_are_accepted_even_though_they_lengthen_the_text():
    """Completing dropped words and cut-off phrases must survive the guard."""
    import transcriber as t
    original = "Я вчера отправил ему письмо, но он так и не, в общем я не знаю что делать."
    restored = "Я вчера отправил ему письмо, но он так и не ответил. В общем, я не знаю, что делать."
    assert t._accepted_correction(original, restored) == restored


def test_length_guard_only_catches_wholesale_rewrites():
    """
    Legitimate cleanups move the length a lot: restoring dropped words grows the
    text, collapsing spelled-out numbers shrinks it. Only an answer or a summary
    should trip the guard.
    """
    import transcriber as t
    original = "x" * 100
    assert t._accepted_correction(original, "x" * 155) == "x" * 155
    assert t._accepted_correction(original, "x" * 180) is None
    assert t._accepted_correction(original, "x" * 55) == "x" * 55
    assert t._accepted_correction(original, "x" * 30) is None
