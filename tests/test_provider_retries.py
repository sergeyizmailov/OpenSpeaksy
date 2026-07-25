import io
import json
import ssl
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request

import pytest

import transcriber


class _Response:
    def __init__(self, payload):
        self.payload = payload
        self.closed = False

    def read(self):
        return json.dumps(self.payload).encode()

    def close(self):
        self.closed = True


def _http_error(code):
    return HTTPError("https://api.mistral.ai/", code, "test", {}, io.BytesIO())


@pytest.fixture(autouse=True)
def _no_retry_wait(monkeypatch):
    monkeypatch.setattr(transcriber, "RETRY_DELAYS_SEC", (0, 0))


def test_tls_failure_is_retried_and_response_is_closed():
    response = _Response({"text": "recovered"})
    calls = [ssl.SSLError("bad record mac"), response]

    with patch.object(transcriber, "urlopen", side_effect=calls) as urlopen:
        result = transcriber._request_json(
            Request("https://api.mistral.ai/"), "test request"
        )

    assert result == {"text": "recovered"}
    assert urlopen.call_count == 2
    assert response.closed


@pytest.mark.parametrize("code", [429, 500, 502, 503, 504])
def test_temporary_http_failure_is_retried(code):
    with patch.object(
        transcriber,
        "urlopen",
        side_effect=[_http_error(code), _Response({"ok": True})],
    ) as urlopen:
        result = transcriber._request_json(
            Request("https://api.mistral.ai/"), "test request"
        )

    assert result == {"ok": True}
    assert urlopen.call_count == 2


def test_authentication_failure_is_not_retried():
    with patch.object(
        transcriber, "urlopen", side_effect=_http_error(401)
    ) as urlopen:
        with pytest.raises(transcriber.TranscriptionError):
            transcriber._request_json(
                Request("https://api.mistral.ai/"), "test request"
            )

    assert urlopen.call_count == 1


def test_retry_budget_is_bounded():
    with patch.object(
        transcriber, "urlopen", side_effect=TimeoutError("timed out")
    ) as urlopen:
        with pytest.raises(transcriber.TranscriptionError):
            transcriber._request_json(
                Request("https://api.mistral.ai/"), "test request"
            )

    assert urlopen.call_count == transcriber.REQUEST_MAX_ATTEMPTS


def test_empty_non_silent_transcription_is_retried(monkeypatch, tmp_path):
    wav = tmp_path / "speech.wav"
    wav.write_bytes(b"test wav bytes")
    responses = [_Response({"text": ""}), _Response({"text": "recovered"})]

    monkeypatch.setattr(transcriber, "MISTRAL_API_KEY", "test-key")
    monkeypatch.setattr(transcriber, "wav_rms", lambda path: 0.1)

    with patch.object(transcriber, "urlopen", side_effect=responses) as urlopen:
        result = transcriber.Transcriber()._transcribe_mistral(wav)

    assert result == "recovered"
    assert urlopen.call_count == 2
    assert all(response.closed for response in responses)


def test_empty_chat_completion_is_retried(monkeypatch):
    responses = [
        _Response({"choices": []}),
        _Response({"choices": [{"message": {"content": "translated"}}]}),
    ]
    monkeypatch.setattr(transcriber, "MISTRAL_API_KEY", "test-key")

    with patch.object(transcriber, "urlopen", side_effect=responses) as urlopen:
        result = transcriber.Transcriber()._translate_mistral("текст")

    assert result == "translated"
    assert urlopen.call_count == 2
    assert all(response.closed for response in responses)
