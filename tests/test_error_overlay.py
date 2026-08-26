"""
Error pill: turning a provider error into a readable notice, and sizing the
pill to whatever text it has to carry.
"""
import pytest

import main
import overlay as o
from transcriber import ProviderUnavailableError, TranscriptionError


@pytest.fixture(autouse=True)
def colors():
    # ERROR_ATTRS is built lazily on the AppKit side; measurement needs it.
    o._init_colors()


# --- turning an error into a notice ----------------------------------------

def test_a_wait_hint_becomes_the_headline():
    """The seconds left is the single most actionable thing to show."""
    notice = main.error_notice(
        TranscriptionError(
            "all 3 Gemini key(s) are rate-limited; next one frees up in 39s"
        )
    )
    assert notice == "Rate limited, try again in 39s"


def test_a_retry_in_hint_is_also_read():
    notice = main.error_notice(TranscriptionError("Please retry in 12.4s"))
    assert notice == "Rate limited, try again in 12s"


def test_throttling_without_a_hint_still_reads_as_throttling():
    assert main.error_notice(
        TranscriptionError("HTTP Error 429: Too Many Requests")
    ) == "Rate limited, try again shortly"


def test_a_dead_network_says_so():
    assert "connection" in main.error_notice(
        ProviderUnavailableError("[Errno 8] nodename nor servname provided")
    )


@pytest.mark.parametrize(
    "raw, expected_fragment",
    [
        ("recording is too large for inline Gemini upload: 99 bytes", "too long"),
        ("Gemini API key is not configured", "API key"),
        ("Microphone permission is denied", "Microphone"),
    ],
)
def test_known_failures_get_plain_language(raw, expected_fragment):
    assert expected_fragment in main.error_notice(TranscriptionError(raw))


def test_an_unrecognized_error_is_shown_verbatim_not_swallowed():
    """Hiding an unknown failure behind 'something went wrong' loses the clue."""
    assert main.error_notice(
        TranscriptionError("weird provider explosion")
    ) == "weird provider explosion"


def test_an_empty_error_still_says_something():
    assert main.error_notice(TranscriptionError("")) == "Transcription failed"


# --- shaping the message ----------------------------------------------------

def test_log_style_whitespace_is_collapsed():
    assert o._clean_message("line one\n  line   two\t") == "line one line two"


def test_a_runaway_message_is_truncated_with_an_ellipsis():
    msg = o._clean_message("x" * 500)
    assert len(msg) <= o.ERROR_MAX_CHARS
    assert msg.endswith("…")


def test_no_message_stays_the_bare_flash():
    assert o._clean_message(None) is None
    assert o._clean_message("   ") is None


# --- sizing -----------------------------------------------------------------

def test_the_pill_widens_with_the_text():
    short = o._error_frame("Rate limited")
    longer = o._error_frame("No connection to the transcription service")
    assert longer.size.width > short.size.width


def test_the_pill_wraps_and_grows_taller_instead_of_running_off_screen():
    frame = o._error_frame(o._clean_message("A very long provider message " * 6))
    assert frame.size.width <= o.ERROR_MAX_W
    assert frame.size.height > o.ERROR_MIN_H


def test_the_pill_never_exceeds_the_panel():
    """The panel is built once at a fixed size; the pill must fit inside it."""
    for text in ("short", "x" * o.ERROR_MAX_CHARS, "слово " * 40):
        frame = o._error_frame(o._clean_message(text))
        assert frame.size.width <= o.PANEL_W - 2 * o.PAD
        assert frame.origin.x >= 0
        assert frame.origin.y + frame.size.height <= o.PANEL_H


def test_a_short_message_keeps_the_pill_height():
    assert o._error_frame("Rate limited").size.height == o.ERROR_MIN_H


def test_the_pill_stays_centered_in_the_panel():
    for text in ("short", "a much longer error message than that one"):
        frame = o._error_frame(text)
        center = frame.origin.x + frame.size.width / 2.0
        assert abs(center - o.PANEL_W / 2.0) < 0.51


# --- how long it stays up ---------------------------------------------------

def test_longer_text_stays_up_longer():
    assert o._read_time("x" * 100) > o._read_time("x" * 10)


def test_read_time_is_bounded():
    assert o._read_time("x") >= o.ERROR_FLASH_SEC
    assert o._read_time("x" * o.ERROR_MAX_CHARS) <= o.ERROR_MESSAGE_MAX_SEC
