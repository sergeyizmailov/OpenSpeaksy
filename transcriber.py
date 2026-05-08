import logging
import os
import tempfile
import struct
import json
import wave
from urllib.request import urlopen, Request
from urllib.error import URLError

import numpy as np

logger = logging.getLogger("openspeaksy")

WHISPER_SERVER = "http://127.0.0.1:8178"
REQUEST_TIMEOUT_SEC = 120

# Below this duration use a smaller audio context for ~2x speedup;
# above it use the full context to preserve quality on long dictations.
SHORT_AUDIO_THRESHOLD_SEC = 15.0
SHORT_AUDIO_CTX = "512"


class TranscriptionError(Exception):
    pass


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

    def _wav_duration_sec(self, wav_path):
        try:
            with wave.open(wav_path, "rb") as w:
                return w.getnframes() / float(w.getframerate())
        except Exception:
            return 0.0

    def transcribe_wav_sync(self, wav_path):
        try:
            with open(wav_path, "rb") as f:
                wav_data = f.read()

            duration = self._wav_duration_sec(wav_path)
            use_short_ctx = duration > 0 and duration < SHORT_AUDIO_THRESHOLD_SEC

            boundary = b"----WhisperBoundary"
            body = b""
            body += b"--" + boundary + b"\r\n"
            body += b'Content-Disposition: form-data; name="file"; filename="audio.wav"\r\n'
            body += b"Content-Type: audio/wav\r\n\r\n"
            body += wav_data + b"\r\n"
            body += b"--" + boundary + b"\r\n"
            body += b'Content-Disposition: form-data; name="response_format"\r\n\r\n'
            body += b"json\r\n"
            body += b"--" + boundary + b"\r\n"
            body += b'Content-Disposition: form-data; name="temperature"\r\n\r\n'
            body += b"0.0\r\n"
            if use_short_ctx:
                body += b"--" + boundary + b"\r\n"
                body += b'Content-Disposition: form-data; name="audio_ctx"\r\n\r\n'
                body += SHORT_AUDIO_CTX.encode() + b"\r\n"
            body += b"--" + boundary + b"--\r\n"

            req = Request(
                f"{WHISPER_SERVER}/inference",
                data=body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary.decode()}"},
            )
            resp = urlopen(req, timeout=REQUEST_TIMEOUT_SEC)
            result = json.loads(resp.read().decode())
            text = result.get("text", "").strip()

            if self._is_hallucination(text):
                return ""
            if text:
                text += " "
            return text
        except URLError as e:
            logger.error(f"whisper-server error: {e}")
            raise TranscriptionError(str(e)) from e
        except Exception as e:
            logger.error(f"transcribe error: {e}")
            raise TranscriptionError(str(e)) from e

    def transcribe_sync(self, audio):
        wav_path = audio_to_wav(audio)
        try:
            return self.transcribe_wav_sync(wav_path)
        except TranscriptionError:
            return ""
        finally:
            os.unlink(wav_path)
