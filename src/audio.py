"""
Audio capture module for Meeting Notes.

Supports:
  - Microphone input via sounddevice
  - Windows system audio loopback via WASAPI (sounddevice wasapi loopback)
  - Mixed capture (both simultaneously)

Audio is pushed into a thread-safe queue in fixed-length chunks
for the transcriber to consume.
"""

import queue
import threading
import time
import numpy as np
from typing import Callable, Optional
from dataclasses import dataclass, field


SAMPLE_RATE = 16000      # SenseVoice expects 16 kHz
CHANNELS = 1             # Mono
CHUNK_SECONDS = 6        # How many seconds per transcription segment
CHUNK_SAMPLES = SAMPLE_RATE * CHUNK_SECONDS
DTYPE = "float32"


@dataclass
class AudioDevice:
    index: int
    name: str
    max_input_channels: int
    default_samplerate: float
    is_wasapi_loopback: bool = False

    def __str__(self) -> str:
        tag = " [系统音频]" if self.is_wasapi_loopback else ""
        return f"{self.name}{tag}"


def list_input_devices() -> list[AudioDevice]:
    """
    Return all usable input devices, including WASAPI loopback devices.
    Works on Windows; on other OS loopback devices are skipped gracefully.
    """
    try:
        import sounddevice as sd
    except ImportError:
        return []

    devices: list[AudioDevice] = []
    try:
        all_devs = sd.query_devices()
        hostapis = sd.query_hostapis()
    except Exception:
        return devices

    # Find WASAPI host API index (Windows only)
    wasapi_idx = None
    for i, api in enumerate(hostapis):
        if "WASAPI" in api.get("name", ""):
            wasapi_idx = i
            break

    for i, dev in enumerate(all_devs):
        if dev["max_input_channels"] < 1:
            continue
        is_loopback = (
            wasapi_idx is not None
            and dev.get("hostapi") == wasapi_idx
            and "loopback" in dev["name"].lower()
        )
        devices.append(
            AudioDevice(
                index=i,
                name=dev["name"],
                max_input_channels=dev["max_input_channels"],
                default_samplerate=dev["default_samplerate"],
                is_wasapi_loopback=is_loopback,
            )
        )
    return devices


def get_wasapi_loopback_devices() -> list[AudioDevice]:
    """Return only WASAPI loopback (system audio) devices."""
    return [d for d in list_input_devices() if d.is_wasapi_loopback]


class AudioCapture:
    """
    Captures audio from one or two devices simultaneously and pushes
    numpy float32 chunks (16 kHz mono, CHUNK_SECONDS long) into a queue.
    """

    def __init__(
        self,
        audio_queue: "queue.Queue[np.ndarray]",
        mic_device_index: Optional[int] = None,
        loopback_device_index: Optional[int] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ):
        self.audio_queue = audio_queue
        self.mic_device_index = mic_device_index
        self.loopback_device_index = loopback_device_index
        self.on_error = on_error

        self._running = False
        self._streams: list = []
        self._lock = threading.Lock()

        # Accumulation buffers per source
        self._mic_buffer: list[np.ndarray] = []
        self._loop_buffer: list[np.ndarray] = []
        self._mic_samples = 0
        self._loop_samples = 0

        # If mixing two sources we keep separate buffers and merge at chunk boundary
        self._use_mix = (
            mic_device_index is not None and loopback_device_index is not None
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start audio capture streams."""
        try:
            import sounddevice as sd
        except ImportError as e:
            self._report_error(f"sounddevice 未安装: {e}")
            return

        self._running = True
        self._streams = []

        try:
            if self.mic_device_index is not None:
                stream = sd.InputStream(
                    device=self.mic_device_index,
                    channels=CHANNELS,
                    samplerate=SAMPLE_RATE,
                    dtype=DTYPE,
                    blocksize=1024,
                    callback=self._mic_callback,
                )
                stream.start()
                self._streams.append(stream)

            if self.loopback_device_index is not None:
                stream = sd.InputStream(
                    device=self.loopback_device_index,
                    channels=CHANNELS,
                    samplerate=SAMPLE_RATE,
                    dtype=DTYPE,
                    blocksize=1024,
                    callback=self._loop_callback,
                    extra_settings=self._wasapi_loopback_settings(),
                )
                stream.start()
                self._streams.append(stream)

        except Exception as e:
            self._report_error(f"音频流启动失败: {e}")
            self.stop()

    def stop(self) -> None:
        """Stop all audio capture streams."""
        self._running = False
        for stream in self._streams:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        self._streams = []
        # Flush remaining buffers
        self._flush_mic()
        self._flush_loop()

    # ------------------------------------------------------------------
    # Internal callbacks
    # ------------------------------------------------------------------

    def _mic_callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        if not self._running:
            return
        mono = indata[:, 0].copy()
        with self._lock:
            self._mic_buffer.append(mono)
            self._mic_samples += len(mono)
            if self._mic_samples >= CHUNK_SAMPLES:
                self._flush_mic()

    def _loop_callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        if not self._running:
            return
        mono = indata[:, 0].copy()
        with self._lock:
            self._loop_buffer.append(mono)
            self._loop_samples += len(mono)
            if self._loop_samples >= CHUNK_SAMPLES:
                self._flush_loop()

    def _flush_mic(self) -> None:
        """Flush mic buffer; caller must hold _lock."""
        if not self._mic_buffer:
            return
        chunk = np.concatenate(self._mic_buffer)
        self._mic_buffer = []
        self._mic_samples = 0
        if self._use_mix:
            # Store until loopback chunk is ready — just queue mic-only for now
            # (simple approach: queue each source independently)
            pass
        self._enqueue(chunk)

    def _flush_loop(self) -> None:
        """Flush loopback buffer; caller must hold _lock."""
        if not self._loop_buffer:
            return
        chunk = np.concatenate(self._loop_buffer)
        self._loop_buffer = []
        self._loop_samples = 0
        self._enqueue(chunk)

    def _enqueue(self, chunk: np.ndarray) -> None:
        """Trim/pad chunk to CHUNK_SAMPLES and push to queue."""
        if len(chunk) > CHUNK_SAMPLES:
            chunk = chunk[:CHUNK_SAMPLES]
        elif len(chunk) < CHUNK_SAMPLES // 2:
            return  # Too short, discard
        try:
            self.audio_queue.put_nowait(chunk)
        except queue.Full:
            pass  # Drop if consumer is slow

    @staticmethod
    def _wasapi_loopback_settings():
        """Return WASAPI loopback extra_settings if on Windows, else None."""
        try:
            import sounddevice as sd
            return sd.WasapiSettings(loopback=True)
        except Exception:
            return None

    def _report_error(self, msg: str) -> None:
        if self.on_error:
            self.on_error(msg)
