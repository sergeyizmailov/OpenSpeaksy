import main


def _recording_state(monkeypatch, *, elapsed):
    monkeypatch.setattr(main, "state", "recording")
    monkeypatch.setattr(main, "state_ts", 100.0 - elapsed)
    monkeypatch.setattr(main, "current_hotkey", main.HOTKEY_KEYCODE)
    monkeypatch.setattr(main, "current_mode", main.MODE_DICTATE)
    monkeypatch.setattr(main.time, "monotonic", lambda: 100.0)


def test_watchdog_does_not_interrupt_normal_long_recording(monkeypatch):
    _recording_state(monkeypatch, elapsed=10)
    released = []

    monkeypatch.setattr(main, "on_key_up", released.append)

    main._watchdog_tick()

    assert released == []
    assert main.state == "recording"


def test_hard_recording_limit_finalizes_instead_of_discarding(monkeypatch):
    _recording_state(monkeypatch, elapsed=main.RECORDING_TIMEOUT_SEC + 1)
    released = []

    monkeypatch.setattr(main, "on_key_up", released.append)

    main._watchdog_tick()

    assert released == [main.HOTKEY_KEYCODE]
