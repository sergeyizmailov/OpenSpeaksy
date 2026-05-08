import logging
import threading

import numpy as np
import sounddevice as sd

logger = logging.getLogger("openspeaksy")


class Recorder:
    def __init__(self, samplerate=16000):
        self.samplerate = samplerate
        self._stream = None
        self._chunks = []
        self._lock = threading.Lock()
        self._recording = False

    def _callback(self, indata, frames, time, status):
        try:
            if status:
                logger.info(f"audio status: {status}")
            with self._lock:
                self._chunks.append(indata.copy())
        except Exception as e:
            logger.error(f"audio callback error: {e}")

    def start(self):
        # Defensive: clean up orphan stream if previous recording was abandoned
        # (watchdog reset, lost key-up event)
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as e:
                logger.error(f"orphan stream cleanup error: {e}")
            self._stream = None

        with self._lock:
            self._chunks = []
        self._recording = True
        self._stream = sd.InputStream(
            samplerate=self.samplerate,
            channels=1,
            dtype="float32",
            callback=self._callback,
        )
        self._stream.start()

    def stop(self):
        self._recording = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        with self._lock:
            if self._chunks:
                audio = np.concatenate(self._chunks, axis=0).flatten()
            else:
                audio = np.array([], dtype="float32")
            self._chunks = []
        return audio

    @property
    def is_recording(self):
        return self._recording
