"""Known silence hallucinations must be filtered without eating real speech."""
from unittest.mock import patch

import numpy as np

import transcriber as transcriber_module
from transcriber import Transcriber, write_wav


def test_russian_hallucination_filtered():
    t = Transcriber()
    assert t._is_hallucination("Спасибо за просмотр")
    assert t._is_hallucination("спасибо за просмотр.")
    assert t._is_hallucination("Подписывайтесь!")


def test_english_hallucination_filtered():
    t = Transcriber()
    assert t._is_hallucination("Thanks for watching")
    assert t._is_hallucination("Subscribe!")
    assert t._is_hallucination("Bye.")


def test_real_text_passes():
    t = Transcriber()
    assert not t._is_hallucination("This is an actual dictation")
    assert not t._is_hallucination("Привет, как дела?")
    assert not t._is_hallucination("subscribe to my newsletter please")  # substring, not exact match


def test_empty_string_not_hallucination():
    t = Transcriber()
    assert not t._is_hallucination("")


def test_known_phrase_is_filtered_for_silent_audio(tmp_path, monkeypatch):
    wav = tmp_path / "silent.wav"
    write_wav(np.zeros(16000, dtype=np.float32), wav)
    monkeypatch.setattr(transcriber_module, "STT_BACKEND", "mistral")

    with patch.object(
        Transcriber,
        "_transcribe_mistral",
        return_value="Спасибо за просмотр",
    ):
        assert Transcriber().transcribe_wav_sync(wav) == ""


def test_legitimate_phrase_is_kept_when_spoken(tmp_path, monkeypatch):
    wav = tmp_path / "speech.wav"
    write_wav(np.full(16000, 0.1, dtype=np.float32), wav)
    monkeypatch.setattr(transcriber_module, "STT_BACKEND", "mistral")

    with patch.object(
        Transcriber,
        "_transcribe_mistral",
        return_value="Thank you",
    ):
        assert Transcriber().transcribe_wav_sync(wav) == "Thank you "
