"""
Startup configuration gate. main() only logs whatever configuration_error()
returns and exits, so these rules are the whole contract: a bad config must be
refused with an actionable message rather than failing later on a live hotkey.
"""
from unittest.mock import patch

import main


def _error(**overrides):
    """Evaluate the gate against one config, without booting anything."""
    defaults = {"MISTRAL_API_KEY": "m"}
    defaults.update(overrides)
    with patch.multiple(main, **defaults):
        return main.configuration_error()


def test_shipped_configuration_is_accepted():
    assert _error() is None


def test_mistral_key_is_required_for_stt():
    msg = _error(MISTRAL_API_KEY="")
    assert msg is not None
    assert "MISTRAL_API_KEY" in msg


def test_missing_key_points_at_the_plist():
    """A fatal exit is only useful if it says where to fix the setting."""
    assert "com.openspeaksy.plist" in _error(MISTRAL_API_KEY="")
