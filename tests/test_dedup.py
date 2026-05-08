"""
Whisper occasionally double-emits a short dictation with tiny wording
differences. collapse_repeated_transcript must strip the duplicate.
"""
from transcriber import collapse_repeated_transcript, _is_same_text


def test_short_text_is_left_alone():
    text = "Hello there."
    assert collapse_repeated_transcript(text) == text


def test_full_double_collapses():
    half = "Hello there, this is a fairly typical short dictation."
    text = f"{half} {half}"
    assert len(text) > 40  # below this the function intentionally bails
    result = collapse_repeated_transcript(text)
    assert result.strip() == half


def test_double_with_minor_wording_collapses():
    text = (
        "Почему сейчас два раза он вставляется? "
        "Мой текст, который я говорю, он вставляется два раза сейчас почему-то. "
        "Почему сейчас два раза оно вставляется? "
        "Мой текст, который я говорю, он вставляется два раза сейчас почему-то."
    )
    result = collapse_repeated_transcript(text)
    assert "оно вставляется" not in result
    assert len(result) < len(text)
    assert len(result) > 50


def test_distinct_sentences_left_alone():
    text = (
        "I went to the store this morning. "
        "Then I had coffee at the cafe. "
        "Later I read a book about birds. "
        "It was a productive day overall."
    )
    result = collapse_repeated_transcript(text)
    assert result == text


def test_word_split_fallback_collapses_some_repeats():
    """
    No sentence punctuation — falls back to word-split heuristic.
    The fallback picks the first matching split rather than the optimal one,
    so we only assert that the result is meaningfully shorter and roughly
    half the input, not that it's a perfect dedup.
    """
    half = "the quick brown fox jumps over the lazy dog and continues running"
    text = f"{half} {half}"
    result = collapse_repeated_transcript(text)
    assert len(result) < len(text)
    assert len(result) <= len(half) + 5  # allow a couple words of slop


def test_is_same_text_handles_punctuation_and_case():
    assert _is_same_text("Hello, World!", "hello world")
    assert _is_same_text("THE QUICK BROWN FOX", "the quick brown fox.")


def test_is_same_text_rejects_different_lengths():
    assert not _is_same_text("short", "this is a much much longer sentence")


def test_is_same_text_rejects_different_content():
    a = "the quick brown fox jumps over the lazy dog"
    b = "the slow purple snake crawls under the busy cat"
    assert not _is_same_text(a, b)
