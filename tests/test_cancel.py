"""
Caps Lock calls off a transcription that is taking too long, and a second tap
puts it back in the queue.

The rule the whole feature rests on: cancelling stops the retries, never the
audio. A user who gives up waiting must still be able to get the words back.
"""

import struct

import pytest

import main


class _Overlay:
    def __init__(self):
        self.events = []

    def hide(self, token=None):
        self.events.append(("hide", token))

    def show(self, mode, label=None, token=None):
        self.events.append((mode, label))

    def flash_error(self, message=None, duration=None, token=None):
        self.events.append(("error", message))

    def flash_notice(self, message, duration=None, sound=True):
        self.events.append(("notice", message))


def _wav(path):
    sr = 16000
    with open(path, "wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + sr * 2))
        f.write(b"WAVEfmt ")
        f.write(struct.pack("<IHHIIHH", 16, 1, 1, sr, sr * 2, 2, 16))
        f.write(b"data")
        f.write(struct.pack("<I", sr * 2))
        f.write(b"\x10\x20" * sr)
    return path


@pytest.fixture
def app(monkeypatch, tmp_path):
    overlay = _Overlay()
    monkeypatch.setattr(main, "overlay", overlay)
    monkeypatch.setattr(main, "PENDING_DIR", tmp_path)
    monkeypatch.setattr(main, "FALLBACK_PENDING_DIR", tmp_path / "fallback")
    monkeypatch.setattr(main, "QUARANTINE_DIR", tmp_path / "quarantine")
    monkeypatch.setattr(main, "state", "idle")
    monkeypatch.setattr(main, "current_wav_path", None)
    monkeypatch.setattr(main, "copy_to_clipboard", lambda text: None)
    monkeypatch.setattr(main, "_last_cancel_tap", 0.0)
    return overlay


def test_cancelling_keeps_the_audio(app, tmp_path):
    """The point of the feature: stop waiting, do not lose what was said."""
    wav = _wav(tmp_path / "20260922-030000-a.dictate.wav")

    stopped, held = main.cancel_everything()

    assert wav.exists()
    assert held == 1
    assert wav.name in main._pending_cancelled


def test_a_cancelled_recording_is_not_retried(app, monkeypatch, tmp_path):
    wav = _wav(tmp_path / "20260922-030001-a.dictate.wav")
    calls = []
    monkeypatch.setattr(
        main.transcriber,
        "transcribe_and_correct_sync",
        lambda p, language=None: calls.append(p) or "text ",
    )

    main.cancel_everything()
    main._pending_next_attempt.clear()  # even once the wait has elapsed
    main.recover_pending_recordings()

    assert calls == []
    assert wav.exists()


def test_a_second_tap_puts_it_back_in_the_queue(app, monkeypatch, tmp_path):
    wav = _wav(tmp_path / "20260922-030002-a.dictate.wav")
    calls = []
    monkeypatch.setattr(
        main.transcriber,
        "transcribe_and_correct_sync",
        lambda p, language=None: calls.append(p) or "text ",
    )

    main.cancel_everything()
    released = main.resume_everything()
    main.recover_pending_recordings()

    assert released == 1
    assert calls == [wav]
    assert not main._pending_cancelled


def test_cancelling_a_live_job_makes_its_worker_abort(app, monkeypatch, tmp_path):
    """
    A worker that finishes after the cancel must not paste into whatever the
    user is doing by then — the same rule the watchdog reset relies on.
    """
    wav = _wav(tmp_path / "20260922-030003-a.dictate.wav")
    monkeypatch.setattr(main, "state", "processing")
    monkeypatch.setattr(main, "current_job_id", 7)
    monkeypatch.setattr(main, "current_wav_path", wav)
    pasted = []
    monkeypatch.setattr(
        main.transcriber, "transcribe_and_correct_sync", lambda *a, **k: "late text "
    )
    monkeypatch.setattr(main, "paste_text", lambda t: pasted.append(t) or True)

    stopped, _ = main.cancel_everything()
    # The worker was already running with the old generation.
    main.process_pending_recording(wav, 7, main.MODE_DICTATE)

    assert stopped == "processing"
    assert pasted == []
    assert wav.exists()


def test_two_quick_taps_resume_instead_of_cancelling_twice(app, monkeypatch, tmp_path):
    _wav(tmp_path / "20260922-030004-a.dictate.wav")
    monkeypatch.setattr(main.time, "monotonic", lambda: 100.0)

    main.on_cancel_tap()
    assert main._pending_cancelled

    # Same instant, so well inside CANCEL_DOUBLE_TAP_SEC.
    main.on_cancel_tap()
    assert not main._pending_cancelled

    kinds = [m for k, m in app.events if k == "notice"]
    assert "Cancelled" in kinds[0]
    assert "Retrying" in kinds[1]


def test_two_slow_taps_are_two_cancels(app, monkeypatch, tmp_path):
    _wav(tmp_path / "20260922-030005-a.dictate.wav")
    clock = {"t": 100.0}
    monkeypatch.setattr(main.time, "monotonic", lambda: clock["t"])

    main.on_cancel_tap()
    clock["t"] += main.CANCEL_DOUBLE_TAP_SEC + 1
    main.on_cancel_tap()

    # Still held: a slow second tap must not be read as "retry now".
    assert main._pending_cancelled


def test_cancelling_with_nothing_running_says_so(app):
    main.on_cancel_tap()

    assert ("notice", "Nothing to cancel") in app.events


def test_every_caps_lock_press_counts_as_one_tap(app, monkeypatch, tmp_path):
    """
    Caps Lock is a toggle: one press emits one event whose flag is SET when it
    turns capitals on and CLEAR when it turns them off. Gating the handler on
    the flag being set would act on every second press only, and the double
    tap could never happen at all.
    """
    _wav(tmp_path / "20260922-030006-a.dictate.wav")
    taps = []
    monkeypatch.setattr(main, "on_cancel_tap", lambda: taps.append(1))

    class _Event:
        def __init__(self, flags):
            self.flags = flags

    def _fake_flags(event):
        return event.flags

    def _fake_keycode(event, field):
        return main.CANCEL_KEYCODE

    monkeypatch.setattr(main, "CGEventGetFlags", _fake_flags)
    monkeypatch.setattr(main, "CGEventGetIntegerValueField", _fake_keycode)

    # Press on (flag set), press off (flag clear): two presses, two taps.
    main.tap_callback(None, main.kCGEventFlagsChanged, _Event(main.CANCEL_FLAG), None)
    main.tap_callback(None, main.kCGEventFlagsChanged, _Event(0), None)

    assert len(taps) == 2
