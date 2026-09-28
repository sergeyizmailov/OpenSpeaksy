"""
Room noise must read as "nothing said": no error pill, no retry, no quarantine.
Speech that comes back empty must still be retried, since that is a provider
failure that would otherwise silently drop what was dictated.
"""
from unittest.mock import patch

import numpy as np

import main
import transcriber
from transcriber import Transcriber, loudest_frame_rms, wav_has_speech, write_wav


class _Response:
    def __init__(self, text):
        self._body = ('{"text": "%s"}' % text).encode()

    def read(self):
        return self._body

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _room_noise(seconds=2.0, level=0.0015, seed=0):
    """Like the empty recordings seen live: average above 0.001, no peak."""
    return np.random.default_rng(seed).normal(0, level, int(16000 * seconds)).astype(
        np.float32
    )


def _speech_like(seconds=2.0):
    """Mostly quiet, with one short loud burst, as a phrase with pauses is."""
    audio = _room_noise(seconds)
    audio[8000:9600] += 0.1 * np.sin(np.linspace(0, 200 * np.pi, 1600))
    return audio


def test_room_noise_is_not_speech(tmp_path):
    wav = tmp_path / "noise.wav"
    write_wav(_room_noise(), wav)
    assert not wav_has_speech(wav)


def test_one_loud_moment_is_speech_even_if_the_average_is_low(tmp_path):
    wav = tmp_path / "speech.wav"
    audio = _speech_like()
    write_wav(audio, wav)
    assert float(np.sqrt(np.mean(audio ** 2))) < 0.02
    assert wav_has_speech(wav)


def test_an_empty_transcript_of_room_noise_is_accepted_once(monkeypatch, tmp_path):
    wav = tmp_path / "noise.wav"
    write_wav(_room_noise(), wav)
    monkeypatch.setattr(transcriber, "MISTRAL_API_KEY", "k")

    with patch.object(transcriber, "urlopen", return_value=_Response("")) as urlopen:
        assert Transcriber().transcribe_and_correct_sync(wav) == ""

    assert urlopen.call_count == 1


def test_an_empty_transcript_of_speech_is_still_retried(monkeypatch, tmp_path):
    wav = tmp_path / "speech.wav"
    write_wav(_speech_like(), wav)
    monkeypatch.setattr(transcriber, "MISTRAL_API_KEY", "k")
    monkeypatch.setattr(transcriber, "RETRY_DELAYS_SEC", (0, 0))
    responses = [_Response(""), _Response("привет")]

    with patch.object(transcriber, "urlopen", side_effect=responses) as urlopen:
        assert Transcriber().transcribe_wav_sync(wav) == "привет "

    assert urlopen.call_count == 2


def test_a_hallucination_over_room_noise_is_dropped(tmp_path):
    wav = tmp_path / "noise.wav"
    write_wav(_room_noise(), wav)
    with patch.object(Transcriber, "_transcribe_mistral", return_value="Спасибо за просмотр"):
        assert Transcriber().transcribe_wav_sync(wav) == ""


def test_loudest_frame_of_nothing_is_zero():
    assert loudest_frame_rms(np.zeros(0, dtype=np.float32)) == 0.0
    assert loudest_frame_rms(np.full(100, 0.5, dtype=np.float32)) == 0.5


def test_the_recording_limit_always_fits_the_upload_limit():
    """A forgotten hands-free recording must still be transcribable."""
    bytes_per_second = 16000 * 2
    assert main.RECORDING_TIMEOUT_SEC * bytes_per_second < transcriber.MAX_UPLOAD_BYTES
