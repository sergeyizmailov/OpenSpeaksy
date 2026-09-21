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
        "STT_BACKEND": "mistral",
        "POLISH_STT_BACKEND": "mistral",
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
    assert "mistral" in msg


def test_unknown_polish_backend_is_refused():
    msg = _error(POLISH_STT_BACKEND="whisper")
    assert msg is not None
    assert "Polish" in msg


def test_mistral_key_is_required_for_stt():
    msg = _error(MISTRAL_API_KEY="")
    assert msg is not None
    assert "MISTRAL_API_KEY" in msg


def test_mistral_key_is_required_even_when_only_polish_uses_it():
    """Right Shift alone still needs the key — Mistral is the only backend."""
    msg = _error(STT_BACKEND="mistral", POLISH_STT_BACKEND="mistral", MISTRAL_API_KEY="")
    assert msg is not None
    assert "MISTRAL_API_KEY" in msg


@pytest.mark.parametrize(
    "overrides",
    [
        {"STT_BACKEND": "whisper"},
        {"MISTRAL_API_KEY": ""},
    ],
)
def test_every_refusal_points_at_the_plist(overrides):
    """A fatal exit is only useful if it says where to fix the setting."""
    msg = _error(**overrides)
    assert msg is not None
    assert "expected one of" in msg or "com.openspeaksy.plist" in msg
