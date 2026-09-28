"""
Hands-free dictation: right Option + right Command records without holding
either key, and one tap of right Command stops it. The rules that keep it from
firing or stopping by accident are the point of these tests: a shortcut typed
with these modifiers must behave exactly as before.
"""
import numpy as np
import pytest

import main


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class _Recorder:
    """Returns as many samples as the key was actually recording for."""

    def __init__(self, clock):
        self.clock = clock
        self.started_at = None
        self.stops = []

    def start(self):
        self.started_at = self.clock.now

    def stop(self):
        seconds = self.clock.now - self.started_at
        self.stops.append(seconds)
        return np.zeros(int(seconds * 16000), dtype=np.float32)


class _Overlay:
    def __init__(self):
        self.shown = []

    def show(self, mode, label=None, token=None):
        self.shown.append((mode, label))

    def hide(self, token=None):
        pass

    def flash_error(self, message=None, duration=None, token=None):
        self.shown.append(("error", message))


class _Thread:
    def __init__(self, *, target, args, daemon):
        pass

    def start(self):
        pass


@pytest.fixture
def rig(monkeypatch, tmp_path):
    clock = _Clock()
    recorder = _Recorder(clock)
    overlay = _Overlay()
    saved = []
    typed = {"at": None}

    monkeypatch.setattr(main.time, "monotonic", clock)
    monkeypatch.setattr(main, "recorder", recorder)
    monkeypatch.setattr(main, "overlay", overlay)
    monkeypatch.setattr(main, "log", lambda message: None)
    monkeypatch.setattr(main, "_microphone_access_is_blocked", lambda: False)
    monkeypatch.setattr(main.threading, "Thread", _Thread)
    monkeypatch.setattr(
        main,
        "save_recording_with_fallback",
        lambda audio, mode: saved.append(len(audio)) or tmp_path / "x.dictate.wav",
    )
    # Stands in for the system idle counters: "a key went down at typed['at']".
    monkeypatch.setattr(
        main,
        "_other_input_since",
        lambda started: typed["at"] is not None and typed["at"] > started,
    )
    for name, value in {
        "state": "idle",
        "state_ts": 0.0,
        "current_hotkey": None,
        "current_mode": None,
        "current_hands_free": False,
        "current_job_id": 0,
        "current_wav_path": None,
        "_hands_free_started_at": None,
        "_hands_free_stop_pressed_at": None,
    }.items():
        monkeypatch.setattr(main, name, value)

    class Rig:
        option_held = False

        def press(self, after=0.0):
            clock.now += after
            main.on_dictate_key(True, self.option_held)

        def release(self, after=0.0):
            clock.now += after
            main.on_dictate_key(False, self.option_held)

        def tap(self, after=0.0, held=0.1):
            self.press(after)
            self.release(held)

        def option(self, pressed, after=0.0):
            clock.now += after
            self.option_held = pressed
            main.on_hands_free_key(pressed)

        def combo(self, after=0.0, held=0.15):
            """Option down, Command down, Command up, Option up."""
            self.option(True, after)
            self.press(0.03)
            self.release(held)
            self.option(False, 0.02)

        def type_key(self, after=0.0):
            clock.now += after
            typed["at"] = clock.now

    rig = Rig()
    rig.saved = saved
    rig.overlay = overlay
    return rig


def test_holding_the_key_still_dictates_as_before(rig):
    rig.press()
    rig.release(after=3.0)

    assert rig.saved == [48000]
    assert main.state == "processing"
    assert ("recording", main.HANDS_FREE_LABEL) not in rig.overlay.shown


def test_option_plus_command_keeps_recording_after_release(rig):
    rig.combo()

    assert main.state == "recording"
    assert main.current_hands_free is True
    assert rig.overlay.shown[-1] == ("recording", main.HANDS_FREE_LABEL)
    assert rig.saved == []


def test_command_first_then_option_also_works_and_keeps_the_audio(rig):
    """Pressing Option mid-dictation latches it; nothing said so far is lost."""
    rig.press()
    rig.option(True, after=4.0)
    rig.release(after=0.1)
    rig.option(False, after=0.05)

    assert main.state == "recording"
    assert rig.overlay.shown[-1] == ("recording", main.HANDS_FREE_LABEL)

    rig.tap(after=10.0)
    assert main.state == "processing"
    assert rig.saved[0] >= 14 * 16000


def test_one_tap_of_command_stops_and_sends_the_recording(rig):
    rig.combo()
    rig.tap(after=30.0)

    assert main.state == "processing"
    assert len(rig.saved) == 1
    assert rig.saved[0] >= 30 * 16000


def test_the_combination_again_also_stops_it(rig):
    rig.combo()
    rig.combo(after=10.0)

    assert main.state == "processing"
    assert len(rig.saved) == 1


def test_option_alone_does_nothing(rig):
    rig.option(True)
    rig.option(False, after=2.0)

    assert main.state == "idle"
    assert rig.overlay.shown == []


def test_an_option_command_shortcut_does_not_start_dictation(rig):
    """Right Option + Command + a letter is a shortcut, not a request."""
    rig.option(True)
    rig.press(after=0.03)
    rig.type_key(after=0.05)
    rig.release(after=0.05)
    rig.option(False, after=0.02)

    assert main.state == "idle"
    assert rig.saved == []


def test_right_command_used_as_a_shortcut_does_not_stop_it(rig):
    rig.combo()

    rig.press(after=5.0)
    rig.type_key(after=0.05)
    rig.release(after=0.05)

    assert main.state == "recording"
    assert rig.saved == []

    rig.tap(after=5.0)
    assert main.state == "processing"
    assert len(rig.saved) == 1


def test_a_plain_hold_after_hands_free_is_not_hands_free(rig):
    rig.combo()
    rig.tap(after=5.0)
    main._claim_job_completion(main.current_job_id)

    rig.press(after=1.0)
    assert main.current_hands_free is False
    rig.release(after=2.0)
    assert main.state == "processing"


@pytest.mark.parametrize("keycode, flags, expected", [
    (0x36, 0x10, ("down", 0x36, "dictate", False)),
    (0x36, 0x10 | 0x40, ("down", 0x36, "dictate", True)),
    (0x3C, 0x04, ("down", 0x3C, "translate", False)),
])
def test_the_keyboard_map(monkeypatch, keycode, flags, expected):
    """Right Shift is English; right Option only means hands-free."""
    calls = []
    monkeypatch.setattr(main, "CGEventGetIntegerValueField", lambda e, f: keycode)
    monkeypatch.setattr(main, "CGEventGetFlags", lambda e: flags)
    monkeypatch.setattr(main, "_hands_free_recording", lambda: False)
    monkeypatch.setattr(
        main,
        "on_key_down",
        lambda k, mode, hands_free=False: calls.append(("down", k, mode, hands_free)),
    )

    main.tap_callback(None, main.kCGEventFlagsChanged, object(), None)

    assert calls == [expected]


def test_right_option_alone_no_longer_translates(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "CGEventGetIntegerValueField", lambda e, f: 0x3D)
    monkeypatch.setattr(main, "CGEventGetFlags", lambda e: 0x40)
    monkeypatch.setattr(main, "on_key_down", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(main, "state", "idle")

    main.tap_callback(None, main.kCGEventFlagsChanged, object(), None)

    assert calls == []
