import logging
import os
import re
import tempfile
import struct
import threading
import json
import wave
from difflib import SequenceMatcher
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

import numpy as np

logger = logging.getLogger("openspeaksy")

REQUEST_TIMEOUT_SEC = 120

# Comma-separated list — multiple keys are rotated on HTTP 401/403/429.
# Single GROQ_API_KEY is also accepted for convenience.
GROQ_API_KEYS = [k.strip() for k in os.environ.get("GROQ_API_KEYS", "").split(",") if k.strip()]
if not GROQ_API_KEYS:
    _single = os.environ.get("GROQ_API_KEY", "").strip()
    if _single:
        GROQ_API_KEYS = [_single]
GROQ_ENDPOINT = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_MODEL = os.environ.get("GROQ_MODEL", "whisper-large-v3")

_groq_key_index = 0
_groq_key_lock = threading.Lock()


def _current_groq_key():
    with _groq_key_lock:
        return GROQ_API_KEYS[_groq_key_index]


def _rotate_groq_key():
    global _groq_key_index
    with _groq_key_lock:
        _groq_key_index = (_groq_key_index + 1) % len(GROQ_API_KEYS)
        return GROQ_API_KEYS[_groq_key_index]


class TranscriptionError(Exception):
    pass


def _normalize_for_repeat_check(text):
    return " ".join(re.findall(r"\w+", text.lower()))


def _is_same_text(left, right):
    left_norm = _normalize_for_repeat_check(left)
    right_norm = _normalize_for_repeat_check(right)
    if not left_norm or not right_norm:
        return False

    ratio = len(left_norm) / len(right_norm)
    if ratio < 0.7 or ratio > 1.3:
        return False

    return SequenceMatcher(None, left_norm, right_norm).ratio() >= 0.80


def collapse_repeated_transcript(text):
    """
    Whisper can occasionally emit the same short dictation twice with tiny wording
    differences. Collapse only full adjacent repeats; partial repeats are left alone.
    """
    if len(text) < 40:
        return text

    sentences = [s.strip() for s in re.findall(r"[^.!?]+[.!?]*", text) if s.strip()]
    if len(sentences) >= 2:
        deduped = []
        for sentence in sentences:
            if deduped and _is_same_text(deduped[-1], sentence):
                continue
            deduped.append(sentence)
        if len(deduped) < len(sentences):
            text = " ".join(deduped).strip()
            sentences = deduped

        for split in range(1, len(sentences)):
            left = " ".join(sentences[:split]).strip()
            right = " ".join(sentences[split:]).strip()
            if _is_same_text(left, right):
                return left

    words = text.split()
    if len(words) >= 8:
        for split in range(max(4, len(words) // 3), min(len(words) - 3, (len(words) * 2) // 3) + 1):
            left = " ".join(words[:split]).strip()
            right = " ".join(words[split:]).strip()
            if _is_same_text(left, right):
                return left

    return text


def write_wav(audio, wav_path, samplerate=16000):
    pcm = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
    num_samples = len(pcm)
    data_size = num_samples * 2
    with open(wav_path, "wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<IHHIIHH", 16, 1, 1, samplerate, samplerate * 2, 2, 16))
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        f.write(pcm.tobytes())


def audio_to_wav(audio, samplerate=16000):
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    write_wav(audio, tmp.name, samplerate)
    return tmp.name


HALLUCINATIONS = {
    # Russian
    "продолжение следует",
    "субтитры",
    "редактор субтитров",
    "субтитры сделал",
    "подписывайтесь",
    "спасибо за просмотр",
    "до свидания",
    "субтитры подогнал",
    "корректор",
    # English
    "thanks for watching",
    "thank you for watching",
    "thank you",
    "thanks",
    "please subscribe",
    "subscribe",
    "you",
    "bye",
    "goodbye",
}


class Transcriber:
    def _is_hallucination(self, text):
        lower = text.lower().strip().rstrip(" .!?")
        return lower in HALLUCINATIONS

    def transcribe_wav_sync(self, wav_path):
        text = self._transcribe_groq(wav_path)

        collapsed = collapse_repeated_transcript(text)
        if len(collapsed) < len(text):
            logger.info(f"collapsed repeated transcript: {len(text)} -> {len(collapsed)} chars")
            text = collapsed

        if self._is_hallucination(text):
            return ""
        if text:
            text += " "
        return text

    def _transcribe_groq(self, wav_path):
        with open(wav_path, "rb") as f:
            wav_data = f.read()

        boundary = b"----GroqBoundary"
        body = b""
        body += b"--" + boundary + b"\r\n"
        body += b'Content-Disposition: form-data; name="file"; filename="audio.wav"\r\n'
        body += b"Content-Type: audio/wav\r\n\r\n"
        body += wav_data + b"\r\n"
        body += b"--" + boundary + b"\r\n"
        body += b'Content-Disposition: form-data; name="model"\r\n\r\n'
        body += GROQ_MODEL.encode() + b"\r\n"
        body += b"--" + boundary + b"\r\n"
        body += b'Content-Disposition: form-data; name="response_format"\r\n\r\n'
        body += b"json\r\n"
        body += b"--" + boundary + b"\r\n"
        body += b'Content-Disposition: form-data; name="temperature"\r\n\r\n'
        body += b"0.0\r\n"
        body += b"--" + boundary + b"--\r\n"

        # Try each key in turn. Rotate on auth/rate-limit; other errors propagate.
        last_error = None
        key = _current_groq_key()
        for attempt in range(len(GROQ_API_KEYS)):
            try:
                req = Request(
                    GROQ_ENDPOINT,
                    data=body,
                    headers={
                        "Content-Type": f"multipart/form-data; boundary={boundary.decode()}",
                        "Authorization": f"Bearer {key}",
                        # Default Python-urllib UA gets 403'd by Groq's WAF.
                        "User-Agent": "openspeaksy/1.0",
                    },
                )
                resp = urlopen(req, timeout=REQUEST_TIMEOUT_SEC)
                result = json.loads(resp.read().decode())
                return result.get("text", "").strip()
            except HTTPError as e:
                if e.code in (401, 403, 429) and len(GROQ_API_KEYS) > 1:
                    logger.warning(
                        f"groq key {attempt + 1}/{len(GROQ_API_KEYS)} got HTTP {e.code}, rotating"
                    )
                    last_error = e
                    key = _rotate_groq_key()
                    continue
                logger.error(f"groq HTTP {e.code}: {e}")
                raise TranscriptionError(str(e)) from e
            except URLError as e:
                logger.error(f"groq error: {e}")
                raise TranscriptionError(str(e)) from e
            except Exception as e:
                logger.error(f"groq transcribe error: {e}")
                raise TranscriptionError(str(e)) from e

        logger.error(f"all {len(GROQ_API_KEYS)} groq keys exhausted: {last_error}")
        raise TranscriptionError(f"all keys exhausted: {last_error}")

    def transcribe_sync(self, audio):
        wav_path = audio_to_wav(audio)
        try:
            return self.transcribe_wav_sync(wav_path)
        except TranscriptionError:
            return ""
        finally:
            os.unlink(wav_path)
