"""
Startup configuration gate. main() only logs whatever configuration_error()
returns and exits, so these rules are the whole contract: a bad config must be
refused with an actionable message rather than failing later on a live hotkey.
"""
from unittest.mock import patch

import pytest

import main


def _error(**overrides):
    """Evaluate the gate against one config, without booting anything."""
    defaults = {
        "STT_BACKEND": "gemini",
        "POLISH_STT_BACKEND": "gemini",
        "GEMINI_API_KEYS": ["k"],
        "MISTRAL_API_KEY": "m",
    }
    defaults.update(overrides)
    with patch.multiple(main, **defaults):
        return main.configuration_error()


def test_shipped_configuration_is_accepted():
    assert _error() is None


def test_unknown_stt_backend_is_refused():
    msg = _error(STT_BACKEND="whisper")
    assert msg is not None
    assert "whisper" in msg
    # The message must list what IS valid, or the user cannot act on it.
    assert "gemini" in msg and "mistral" in msg


def test_unknown_polish_backend_is_refused():
    msg = _error(POLISH_STT_BACKEND="whisper")
    assert msg is not None
    assert "Polish" in msg


def test_gemini_backend_without_a_key_is_refused():
    msg = _error(GEMINI_API_KEYS=[])
    assert msg is not None
    assert "GEMINI_API_KEYS" in msg


def test_gemini_key_is_required_even_when_only_polish_uses_it():
    """Right Shift alone on Gemini still needs the key."""
    msg = _error(STT_BACKEND="mistral", POLISH_STT_BACKEND="gemini", GEMINI_API_KEYS=[])
    assert msg is not None
    assert "Gemini" in msg


def test_gemini_key_is_not_required_when_no_path_uses_gemini():
    assert _error(
        STT_BACKEND="mistral", POLISH_STT_BACKEND="mistral", GEMINI_API_KEYS=[]
    ) is None


def test_mistral_key_is_required_even_on_gemini_stt():
    """Translation always goes to Mistral, so its key is never optional."""
    msg = _error(MISTRAL_API_KEY="")
    assert msg is not None
    assert "MISTRAL_API_KEY" in msg


def test_mistral_stt_without_its_key_names_the_stt_problem():
    """
    The generic 'translate hotkeys require it' message would be misleading when
    the missing key also breaks transcription itself.
    """
    msg = _error(STT_BACKEND="mistral", POLISH_STT_BACKEND="mistral", MISTRAL_API_KEY="")
    assert msg is not None
    assert "STT backend is Mistral" in msg


@pytest.mark.parametrize(
    "overrides",
    [
        {"STT_BACKEND": "whisper"},
        {"GEMINI_API_KEYS": []},
        {"MISTRAL_API_KEY": ""},
    ],
)
def test_every_refusal_points_at_the_plist(overrides):
    """A fatal exit is only useful if it says where to fix the setting."""
    msg = _error(**overrides)
    assert msg is not None
    assert "expected one of" in msg or "com.openspeaksy.plist" in msg
