import main


class StubTranscriber:
    def __init__(self, *, text=None, error=None):
        self.text = text
        self.error = error

    def transcribe_wav_sync(self, path):
        if self.error:
            raise self.error
        return self.text


def _valid_wav(path):
    path.write_bytes(
        b"RIFF\x26\x00\x00\x00WAVEfmt \x10\x00\x00\x00"
        b"\x01\x00\x01\x00\x80\x3e\x00\x00\x00\x7d\x00\x00"
        b"\x02\x00\x10\x00data\x02\x00\x00\x00\x00\x00"
    )


def test_recovery_copies_then_deletes_pending_audio(tmp_path, monkeypatch):
    pending = tmp_path / ".pending"
    pending.mkdir()
    wav = pending / "20260721-000000-a.dictate.wav"
    _valid_wav(wav)
    clipboard = []

    monkeypatch.setattr(main, "PENDING_DIR", pending)
    monkeypatch.setattr(main, "QUARANTINE_DIR", pending / "quarantine")
    monkeypatch.setattr(main, "transcriber", StubTranscriber(text="recovered "))
    monkeypatch.setattr(main, "copy_to_clipboard", clipboard.append)

    main.recover_pending_recordings()

    assert clipboard == ["recovered "]
    assert not wav.exists()


def test_recovery_keeps_audio_when_transcription_fails(tmp_path, monkeypatch):
    pending = tmp_path / ".pending"
    pending.mkdir()
    wav = pending / "20260721-000000-a.dictate.wav"
    _valid_wav(wav)

    monkeypatch.setattr(main, "PENDING_DIR", pending)
    monkeypatch.setattr(main, "QUARANTINE_DIR", pending / "quarantine")
    monkeypatch.setattr(
        main,
        "transcriber",
        StubTranscriber(error=main.TranscriptionError("provider unavailable")),
    )

    main.recover_pending_recordings()

    assert wav.exists()
