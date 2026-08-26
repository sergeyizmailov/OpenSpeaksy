"""
Gemini 3.5 Transcribe backend: request shape for the Interactions API, the
nested-response parser, and the guards around both.
"""
import io
import json
import struct
from unittest.mock import patch

import pytest


def _write_loud_wav(tmp_path):
    p = tmp_path / "loud.wav"
    samplerate = 16000
    data_size = samplerate * 2
    with open(p, "wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))
        f.write(b"WAVEfmt ")
        f.write(struct.pack("<IHHIIHH", 16, 1, 1, samplerate, samplerate * 2, 2, 16))
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        f.write(b"\x10\x20" * samplerate)
    return p


def _ok(text):
    class _Resp:
        def read(self):
            return json.dumps({
                "status": "completed",
                "steps": [{
                    "type": "model_output",
                    "content": [{"type": "text", "text": text}],
                }],
            }).encode()
    return _Resp()


@pytest.fixture
def gemini(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "mistral-test-key")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEYS", "key-one, key-two, key-three")
    monkeypatch.setenv("OPENSPEAKSY_STT_BACKEND", "gemini")
    import importlib
    import transcriber as t
    importlib.reload(t)
    monkeypatch.setattr(t, "RETRY_DELAYS_SEC", (0, 0))
    yield t
    importlib.reload(t)


def test_gemini_is_a_selectable_backend(gemini):
    assert gemini.STT_BACKEND == "gemini"
    assert "gemini" in gemini.SUPPORTED_STT_BACKENDS


def test_transcript_comes_from_the_nested_model_output_step(gemini, tmp_path):
    wav = _write_loud_wav(tmp_path)
    with patch.object(gemini, "urlopen", side_effect=[_ok("Привет мир")]):
        assert gemini.Transcriber().transcribe_wav_sync(wav) == "Привет мир "


def test_request_targets_the_interactions_api_with_inline_audio(gemini, tmp_path):
    """generateContent returns an empty part for this model; the endpoint matters."""
    import base64
    wav = _write_loud_wav(tmp_path)
    with patch.object(gemini, "urlopen", side_effect=[_ok("текст")]) as mock:
        gemini.Transcriber().transcribe_wav_sync(wav, language="ru")
    req = mock.call_args_list[0].args[0]
    assert req.full_url == gemini.GEMINI_ENDPOINT
    assert req.get_header("X-goog-api-key") == "key-one"
    body = json.loads(req.data.decode())
    assert body["model"] == gemini.GEMINI_MODEL
    # Audio alone: this model only transcribes, so no instruction is sent.
    assert len(body["input"]) == 1
    audio_part = body["input"][0]
    assert audio_part["type"] == "audio"
    assert audio_part["mime_type"] == "audio/wav"
    assert base64.b64decode(audio_part["data"]) == wav.read_bytes()


def test_no_text_part_is_sent_with_the_audio(gemini, tmp_path):
    """
    Regression guard: an instruction was measured to change nothing for this
    transcription-only model, so the request carries audio and nothing else.
    """
    wav = _write_loud_wav(tmp_path)
    with patch.object(gemini, "urlopen", side_effect=[_ok("текст")]) as mock:
        gemini.Transcriber().transcribe_wav_sync(wav, language="ru")
    body = json.loads(mock.call_args_list[0].args[0].data.decode())
    assert [part["type"] for part in body["input"]] == ["audio"]
    assert "text" not in json.dumps(body["input"])



def test_missing_key_is_reported_not_silently_skipped(monkeypatch, tmp_path):
    monkeypatch.setenv("MISTRAL_API_KEY", "m")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    monkeypatch.setenv("OPENSPEAKSY_STT_BACKEND", "gemini")
    import importlib
    import transcriber as t
    importlib.reload(t)
    with pytest.raises(t.TranscriptionError, match="Gemini API key"):
        t.Transcriber()._transcribe_gemini(_write_loud_wav(tmp_path))
    importlib.reload(t)


def test_oversized_recording_fails_before_the_upload(gemini, tmp_path):
    wav = _write_loud_wav(tmp_path)
    with patch.object(gemini, "GEMINI_MAX_INLINE_BYTES", 10):
        with patch.object(gemini, "urlopen") as mock:
            with pytest.raises(gemini.TranscriptionError, match="too large"):
                gemini.Transcriber()._transcribe_gemini(wav)
    assert mock.call_count == 0


def test_empty_transcript_on_loud_audio_is_retried_then_reported(gemini, tmp_path):
    """A completed response with no text means the model declined the audio."""
    wav = _write_loud_wav(tmp_path)
    with patch.object(gemini, "urlopen", side_effect=[_ok(""), _ok(""), _ok("")]) as mock:
        with pytest.raises(gemini.TranscriptionError):
            gemini.Transcriber()._transcribe_gemini(wav)
    assert mock.call_count == 3



def test_completed_response_with_no_steps_is_silence_not_a_failure(gemini, tmp_path):
    """
    The model omits `steps` entirely when it hears no speech. Retrying that
    three times would spend the whole free-tier per-minute quota on silence.
    """
    class _Silent:
        def read(self):
            return json.dumps({"status": "completed", "usage": {}}).encode()

    wav = tmp_path / "quiet.wav"
    samplerate = 16000
    data_size = samplerate * 2
    with open(wav, "wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))
        f.write(b"WAVEfmt ")
        f.write(struct.pack("<IHHIIHH", 16, 1, 1, samplerate, samplerate * 2, 2, 16))
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        f.write(b"\x00\x00" * samplerate)

    with patch.object(gemini, "urlopen", side_effect=[_Silent()]) as mock:
        assert gemini.Transcriber()._transcribe_gemini(wav) == ""
    assert mock.call_count == 1


def test_malformed_steps_are_still_retried(gemini, tmp_path):
    class _Bad:
        def read(self):
            return json.dumps({"status": "completed", "steps": "nonsense"}).encode()

    wav = _write_loud_wav(tmp_path)
    with patch.object(gemini, "urlopen", side_effect=[_Bad(), _Bad(), _Bad()]) as mock:
        with pytest.raises(gemini.TranscriptionError):
            gemini.Transcriber()._transcribe_gemini(wav)
    assert mock.call_count == 3


def _keys_used(mock):
    return [c.args[0].get_header("X-goog-api-key") for c in mock.call_args_list]


def test_each_key_gets_its_own_quota_before_the_next_is_touched(gemini, tmp_path):
    """
    The per-minute limit is metered per project, so three keys at 3/min give
    nine transcriptions per minute — spent one key at a time.
    """
    wav = _write_loud_wav(tmp_path)
    tr = gemini.Transcriber()
    with patch.object(gemini, "urlopen", side_effect=[_ok("t")] * 9) as mock:
        for _ in range(9):
            assert tr.transcribe_wav_sync(wav) == "t "
    assert _keys_used(mock) == ["key-one"] * 3 + ["key-two"] * 3 + ["key-three"] * 3


def test_exhausting_every_key_fails_rather_than_pasting_nothing(gemini, tmp_path):
    """
    With all quota spent the recording must surface an error so main.py leaves
    it in .pending for recovery.
    """
    wav = _write_loud_wav(tmp_path)
    tr = gemini.Transcriber()
    with patch.object(gemini, "urlopen", side_effect=[_ok("t")] * 9):
        for _ in range(9):
            tr.transcribe_wav_sync(wav)
    with patch.object(gemini, "urlopen") as mock:
        with pytest.raises(gemini.TranscriptionError, match="rate-limited"):
            tr.transcribe_wav_sync(wav)
    assert mock.call_count == 0


def test_a_throttled_key_is_skipped_and_the_next_one_serves(gemini, tmp_path):
    """A 429 on key one must not cost the dictation — key two takes it."""
    from urllib.error import HTTPError
    wav = _write_loud_wav(tmp_path)
    throttled = HTTPError("https://x/", 429, "rate", {}, io.BytesIO(b""))
    with patch.object(gemini, "urlopen", side_effect=[throttled, _ok("t")]) as mock:
        assert gemini.Transcriber().transcribe_wav_sync(wav) == "t "
    assert _keys_used(mock) == ["key-one", "key-two"]


def test_a_429_burns_that_keys_whole_window(gemini, tmp_path):
    """Google's accounting wins: after a 429 stop retrying that key this minute."""
    from urllib.error import HTTPError
    wav = _write_loud_wav(tmp_path)
    throttled = HTTPError("https://x/", 429, "rate", {}, io.BytesIO(b""))
    tr = gemini.Transcriber()
    with patch.object(gemini, "urlopen", side_effect=[throttled, _ok("t")]):
        tr.transcribe_wav_sync(wav)
    # Key one is now considered spent, so the next call starts at key two.
    with patch.object(gemini, "urlopen", side_effect=[_ok("t")]) as mock:
        tr.transcribe_wav_sync(wav)
    assert _keys_used(mock) == ["key-two"]


def test_an_unreachable_key_keeps_its_quota(gemini, tmp_path):
    """A dead network must not spend an entire key's minute."""
    wav = _write_loud_wav(tmp_path)
    calls = []

    def _fail_first(self, wav_path, language=None, api_key=None):
        calls.append(api_key)
        if api_key == "key-one":
            raise gemini.ProviderUnavailableError("no route")
        return "served"

    with patch.object(gemini.Transcriber, "_transcribe_gemini", _fail_first):
        assert gemini.Transcriber().transcribe_wav_sync(wav) == "served "
    assert calls == ["key-one", "key-two"]
    # key-one was never actually charged.
    assert gemini._gemini_quotas[0].try_acquire() is not None


def test_quota_frees_up_once_the_window_slides(gemini, tmp_path):
    wav = _write_loud_wav(tmp_path)
    tr = gemini.Transcriber()
    with patch.object(gemini, "urlopen", side_effect=[_ok("t")] * 9):
        for _ in range(9):
            tr.transcribe_wav_sync(wav)
    # Age every reservation past the window instead of sleeping 60 s.
    for quota in gemini._gemini_quotas:
        with quota._lock:
            quota._hits = [
                (at - gemini.GEMINI_WINDOW_SEC - 1, token)
                for at, token in quota._hits
            ]
    with patch.object(gemini, "urlopen", side_effect=[_ok("t")]) as mock:
        assert tr.transcribe_wav_sync(wav) == "t "
    assert _keys_used(mock) == ["key-one"]


def test_duplicate_keys_do_not_get_double_quota(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "m")
    monkeypatch.setenv("GEMINI_API_KEYS", "dup, other, dup")
    monkeypatch.setenv("GEMINI_API_KEY", "other")
    import importlib
    import transcriber as t
    importlib.reload(t)
    assert t.GEMINI_API_KEYS == ["dup", "other"]
    assert len(t._gemini_quotas) == 2
    importlib.reload(t)


def test_single_key_env_var_still_works(monkeypatch):
    """GEMINI_API_KEY alone must keep configuring the backend."""
    monkeypatch.setenv("MISTRAL_API_KEY", "m")
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "solo")
    import importlib
    import transcriber as t
    importlib.reload(t)
    assert t.GEMINI_API_KEYS == ["solo"]
    importlib.reload(t)


def test_translation_still_goes_to_mistral_when_stt_is_gemini(gemini, tmp_path):
    """Switching STT to Gemini must not move the translation path."""
    wav = _write_loud_wav(tmp_path)

    class _Chat:
        def read(self):
            return json.dumps(
                {"choices": [{"message": {"content": "Hello world"}}]}
            ).encode()

    with patch.object(gemini, "urlopen", side_effect=[_ok("Привет мир"), _Chat()]) as mock:
        assert gemini.Transcriber().transcribe_and_translate_sync(wav) == "Hello world "
    assert mock.call_args_list[0].args[0].full_url == gemini.GEMINI_ENDPOINT
    assert mock.call_args_list[1].args[0].full_url == gemini.MISTRAL_CHAT_ENDPOINT


def test_polish_path_uses_gemini_stt_and_mistral_translation(monkeypatch, tmp_path):
    monkeypatch.setenv("MISTRAL_API_KEY", "m")
    monkeypatch.setenv("GEMINI_API_KEYS", "key-one")
    monkeypatch.setenv("OPENSPEAKSY_STT_BACKEND", "gemini")
    monkeypatch.setenv("OPENSPEAKSY_POLISH_STT_BACKEND", "gemini")
    import importlib
    import transcriber as t
    importlib.reload(t)

    class _Chat:
        def read(self):
            return json.dumps(
                {"choices": [{"message": {"content": "Dzień dobry"}}]}
            ).encode()

    wav = _write_loud_wav(tmp_path)
    with patch.object(t, "urlopen", side_effect=[_ok("Привет"), _Chat()]) as mock:
        assert t.Transcriber().transcribe_to_polish_sync(wav) == "Dzień dobry "
    assert mock.call_args_list[0].args[0].full_url == t.GEMINI_ENDPOINT
    assert mock.call_args_list[1].args[0].full_url == t.MISTRAL_CHAT_ENDPOINT
    importlib.reload(t)


def test_a_throttled_key_is_abandoned_without_retrying_it(gemini, tmp_path):
    """
    Retrying a key we already know is throttled just delays the paste. One
    attempt per key, then rotate.
    """
    from urllib.error import HTTPError
    wav = _write_loud_wav(tmp_path)
    throttled = HTTPError("https://x/", 429, "rate", {}, io.BytesIO(b""))
    with patch.object(gemini, "urlopen", side_effect=[throttled, _ok("t")]) as mock:
        assert gemini.Transcriber().transcribe_wav_sync(wav) == "t "
    assert _keys_used(mock) == ["key-one", "key-two"]


def test_server_errors_are_still_retried_on_the_same_key(gemini, tmp_path):
    """Only throttling short-circuits; a 500 may well succeed on retry."""
    from urllib.error import HTTPError
    wav = _write_loud_wav(tmp_path)
    boom = HTTPError("https://x/", 500, "boom", {}, io.BytesIO(b""))
    with patch.object(gemini, "urlopen", side_effect=[boom, _ok("t")]) as mock:
        assert gemini.Transcriber().transcribe_wav_sync(wav) == "t "
    assert _keys_used(mock) == ["key-one", "key-one"]


def test_release_frees_only_the_callers_own_reservation(gemini):
    """
    Regression: release() used to pop the newest reservation. A worker whose
    request died unreachable would then free a slot that a concurrent worker
    (the pending-retry loop, or recovery) was still using, drifting the
    accounting and overshooting the provider's real limit.
    """
    quota = gemini._SlidingWindowQuota(3, 60.0)
    first = quota.try_acquire()
    second = quota.try_acquire()
    assert first is not None and second is not None
    quota.release(first)
    # The other worker's reservation must survive.
    assert [token for _, token in quota._hits] == [second]


def test_a_stale_token_cannot_free_a_slot_twice(gemini):
    quota = gemini._SlidingWindowQuota(1, 60.0)
    token = quota.try_acquire()
    quota.release(token)
    quota.release(token)  # double release must not create phantom capacity
    assert quota.try_acquire() is not None
    assert quota.try_acquire() is None


def test_a_bad_request_does_not_walk_the_whole_key_list(gemini, tmp_path):
    """
    A 400 is about the payload, so every key would reproduce it. Trying them
    all spends three keys' quota to collect the same error three times.
    """
    from urllib.error import HTTPError
    wav = _write_loud_wav(tmp_path)
    bad = HTTPError("https://x/", 400, "bad", {}, io.BytesIO(b""))
    with patch.object(gemini, "urlopen", side_effect=[bad, bad, bad]) as mock:
        with pytest.raises(gemini.TranscriptionError):
            gemini.Transcriber().transcribe_wav_sync(wav)
    assert _keys_used(mock) == ["key-one"]
    assert [len(q._hits) for q in gemini._gemini_quotas] == [1, 0, 0]


def test_a_server_error_still_tries_the_other_keys(gemini, tmp_path):
    """A 500 may be one project's bad luck, so the next key is worth trying."""
    from urllib.error import HTTPError
    wav = _write_loud_wav(tmp_path)
    boom = HTTPError("https://x/", 500, "boom", {}, io.BytesIO(b""))
    with patch.object(
        gemini, "urlopen", side_effect=[boom, boom, boom, _ok("t")]
    ) as mock:
        assert gemini.Transcriber().transcribe_wav_sync(wav) == "t "
    # Three attempts burn key one's retries, then key two serves it.
    assert _keys_used(mock) == ["key-one"] * 3 + ["key-two"]


def test_shipped_default_backend_matches_the_plist_template(monkeypatch):
    """The code default and launchd/*.template must not disagree."""
    monkeypatch.delenv("OPENSPEAKSY_STT_BACKEND", raising=False)
    monkeypatch.setenv("MISTRAL_API_KEY", "m")
    monkeypatch.setenv("GEMINI_API_KEYS", "k")
    import importlib
    import transcriber as t
    importlib.reload(t)
    assert t.STT_BACKEND == "gemini"
    importlib.reload(t)


def _oversized_wav(tmp_path, gemini):
    p = tmp_path / "big.wav"
    n = gemini.GEMINI_MAX_INLINE_BYTES + 1000
    with open(p, "wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + n))
        f.write(b"WAVEfmt ")
        f.write(struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16))
        f.write(b"data")
        f.write(struct.pack("<I", n))
        f.write(b"\x10\x20" * (n // 2))
    return p


def test_an_oversized_recording_stops_at_the_first_key(gemini, tmp_path):
    """
    Regression: the local size guard raised a plain TranscriptionError, whose
    message never matched the "HTTP Error 413" text test, so an oversized file
    walked every key and spent a slot of each. The pending-retry loop reruns
    every 5 minutes, so one stuck file could starve live dictation of quota.
    """
    wav = _oversized_wav(tmp_path, gemini)
    with patch.object(gemini, "urlopen") as mock:
        with pytest.raises(gemini.RequestRejectedError, match="too large"):
            gemini.Transcriber().transcribe_wav_sync(wav)
    assert mock.call_count == 0  # never reached the network
    assert [len(q._hits) for q in gemini._gemini_quotas] == [1, 0, 0]


def test_request_rejected_is_a_transcription_error(gemini):
    """Callers in main.py catch TranscriptionError; this must not escape it."""
    assert issubclass(gemini.RequestRejectedError, gemini.TranscriptionError)


def test_a_real_defect_is_not_masked_by_a_routine_429(gemini, tmp_path):
    """
    Only the raised exception reaches main.py and the overlay. When key one hits
    a genuine failure and key two is merely throttled, the caller must see the
    genuine one.
    """
    from urllib.error import HTTPError
    wav = _write_loud_wav(tmp_path)
    real = HTTPError("https://x/", 403, "key disabled", {}, io.BytesIO(b""))
    throttled = HTTPError("https://x/", 429, "rate", {}, io.BytesIO(b""))
    with patch.object(
        gemini, "urlopen", side_effect=[real, throttled, throttled]
    ):
        with pytest.raises(gemini.TranscriptionError) as caught:
            gemini.Transcriber().transcribe_wav_sync(wav)
    assert "403" in str(caught.value)


def test_all_keys_throttled_still_reports_throttling(gemini, tmp_path):
    """With nothing but 429s, the 429 is the honest answer."""
    from urllib.error import HTTPError
    wav = _write_loud_wav(tmp_path)
    throttled = HTTPError("https://x/", 429, "rate", {}, io.BytesIO(b""))
    with patch.object(gemini, "urlopen", side_effect=[throttled] * 3):
        with pytest.raises(gemini.TranscriptionError) as caught:
            gemini.Transcriber().transcribe_wav_sync(wav)
    assert "429" in str(caught.value)


def test_a_bad_request_on_a_later_key_also_stops_the_rotation(gemini, tmp_path):
    """
    The short-circuit must hold mid-rotation, not just on the first key: key one
    throttled, key two rejects the payload, key three must not be tried.
    """
    from urllib.error import HTTPError
    wav = _write_loud_wav(tmp_path)
    throttled = HTTPError("https://x/", 429, "rate", {}, io.BytesIO(b""))
    bad = HTTPError("https://x/", 400, "bad", {}, io.BytesIO(b""))
    with patch.object(gemini, "urlopen", side_effect=[throttled, bad, _ok("t")]) as mock:
        with pytest.raises(gemini.TranscriptionError):
            gemini.Transcriber().transcribe_wav_sync(wav)
    assert _keys_used(mock) == ["key-one", "key-two"]
