"""
Whisper has known hallucination phrases that appear on silence or
near-silent input. They must never reach the user's clipboard.
"""
from transcriber import Transcriber


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
