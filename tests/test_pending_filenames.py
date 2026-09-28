"""
Pending-recording filenames carry the cycle's mode so a crash between save
and worker spawn doesn't lose translate intent. parse_pending_mode reads it
back, falling back to dictate for legacy files (pre-upgrade) without a mode
segment.
"""
from pathlib import Path

import main


def test_dictate_filename_parses():
    p = Path(".pending/20260523-150000-deadbeef.dictate.wav")
    assert main.parse_pending_mode(p) == main.MODE_DICTATE


def test_translate_filename_parses():
    p = Path(".pending/20260523-150000-deadbeef.translate.wav")
    assert main.parse_pending_mode(p) == main.MODE_TRANSLATE


def test_legacy_filename_falls_back_to_dictate():
    """Pre-upgrade WAVs (no mode segment) must still be transcribable."""
    p = Path(".pending/20260523-150000-deadbeef.wav")
    assert main.parse_pending_mode(p) == main.MODE_DICTATE


def test_save_pending_recording_writes_mode_in_filename(tmp_path, monkeypatch):
    import numpy as np

    monkeypatch.setattr(main, "PENDING_DIR", tmp_path / ".pending")
    audio = np.zeros(16000, dtype=np.float32)

    p = main.save_pending_recording(audio, main.MODE_TRANSLATE)

    assert p.name.endswith(".translate.wav")
    assert main.parse_pending_mode(p) == main.MODE_TRANSLATE
