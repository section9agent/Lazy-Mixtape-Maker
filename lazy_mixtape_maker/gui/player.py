"""Preview playback: streams a rendered WAV through miniaudio (prebuilt for Windows,
macOS and Linux, no system libraries needed)."""
from __future__ import annotations

import os
import threading

import soundfile as sf

SR = 44100


class AudioPlayer:
    def __init__(self):
        self._file: sf.SoundFile | None = None
        self._lock = threading.Lock()
        self._dev = None
        self._pos = 0
        self.paused = True
        self.ended = False
        self.error = ""

    # ------------------------------------------------------------------ device
    def _ensure_device(self) -> bool:
        if self._dev is not None:
            return True
        try:
            import miniaudio

            kw = {}
            if os.environ.get("LMM_AUDIO_BACKEND", "").lower() == "null":   # for tests
                kw["backends"] = [miniaudio.Backend.Null]
            dev = miniaudio.PlaybackDevice(output_format=miniaudio.SampleFormat.SIGNED16, nchannels=2,
                                           sample_rate=SR, buffersize_msec=80, **kw)
            gen = self._stream()
            next(gen)
            dev.start(gen)
            self._dev = dev
            self.error = ""
            return True
        except Exception as e:  # noqa: BLE001 - no sound card, no backend...
            self.error = str(e) or "No audio output device is available."
            self._dev = None
            return False

    def _stream(self):
        required = yield b""
        while True:
            n = int(required)
            data = None
            if not self.paused:
                with self._lock:
                    f = self._file
                    if f is not None:
                        arr = f.read(n, dtype="int16", always_2d=True)
                        got = len(arr)
                        self._pos += got
                        if got < n:
                            self.paused, self.ended = True, True
                            import numpy as np

                            arr = np.pad(arr, ((0, n - got), (0, 0)))
                        data = arr.tobytes()
            required = yield (data if data is not None else bytes(n * 4))

    # --------------------------------------------------------------------- api
    @property
    def playing(self) -> bool:
        return self._dev is not None and not self.paused and self._file is not None

    @property
    def loaded(self) -> bool:
        return self._file is not None

    def position(self) -> float:
        return self._pos / SR

    def load(self, path, at: float = 0.0) -> bool:
        with self._lock:
            if self._file is not None:
                self._file.close()
                self._file = None
            self.paused, self.ended = True, False
            f = sf.SoundFile(str(path))
            if f.samplerate != SR or f.channels != 2:
                f.close()
                raise ValueError("Preview must be 44.1 kHz stereo")
            f.seek(max(0, min(int(at * SR), f.frames)))
            self._pos = f.tell()
            self._file = f
        return self._ensure_device()

    def play(self) -> bool:
        if not self._ensure_device() or self._file is None:
            return False
        self.ended = False
        self.paused = False
        return True

    def pause(self):
        self.paused = True

    def seek(self, seconds: float):
        with self._lock:
            if self._file is not None:
                self._file.seek(max(0, min(int(seconds * SR), self._file.frames)))
                self._pos = self._file.tell()
                self.ended = False

    def stop(self):
        self.paused = True
        self.seek(0.0)

    def close(self):
        self.paused = True
        if self._dev is not None:
            try:
                self._dev.close()
            except Exception:  # noqa: BLE001
                pass
            self._dev = None
        with self._lock:
            if self._file is not None:
                self._file.close()
                self._file = None
