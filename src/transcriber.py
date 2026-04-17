"""
Real-time transcription module using FunASR + SenseVoice Small.

Model: FunAudioLLM/SenseVoiceSmall
  - Non-autoregressive: ~70 ms for 10 s audio on CPU
  - Supports ASR + language ID + emotion + sound events
  - 50+ languages auto-detected

The Transcriber runs in its own thread, pulling audio chunks from a queue
and emitting transcription results via a callback.
"""

import queue
import threading
import time
import numpy as np
from pathlib import Path
from typing import Callable, Optional
from src.utils import get_models_dir


MODEL_ID = "FunAudioLLM/SenseVoiceSmall"
SAMPLE_RATE = 16000


class Transcriber:
    """
    Loads SenseVoice model and transcribes audio chunks from a queue.

    Usage:
        q = queue.Queue()
        t = Transcriber(q, on_result=my_callback)
        t.load_model()        # blocking, call in background thread
        t.start()             # starts consumer thread
        # ... push audio chunks into q ...
        t.stop()
    """

    def __init__(
        self,
        audio_queue: "queue.Queue[np.ndarray]",
        on_result: Callable[[float, str], None],
        on_status: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ):
        self.audio_queue = audio_queue
        self.on_result = on_result        # callback(timestamp_seconds, text)
        self.on_status = on_status        # callback(status_message)
        self.on_error = on_error

        self._model = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._start_time: float = 0.0
        self._elapsed: float = 0.0       # seconds of audio processed

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_model(self) -> bool:
        """
        Load the SenseVoice model. Blocking. Returns True on success.
        First run downloads ~300 MB model to models/ directory.
        """
        self._notify_status("正在加载 SenseVoice 模型...")
        try:
            from funasr import AutoModel

            model_dir = str(get_models_dir())
            self._model = AutoModel(
                model=MODEL_ID,
                model_revision="v2.0.4",
                trust_remote_code=True,
                remote_code="./model.py",
                vad_model="fsmn-vad",
                vad_kwargs={"max_single_segment_time": 30000},
                disable_update=True,
                hub="hf",
            )
            self._notify_status("模型加载完成")
            return True
        except Exception as e:
            self._report_error(f"模型加载失败: {e}")
            return False

    def start(self) -> None:
        """Start the transcription consumer thread."""
        if self._model is None:
            self._report_error("模型未加载,无法启动转录")
            return
        self._running = True
        self._start_time = time.time()
        self._elapsed = 0.0
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Signal the consumer thread to stop."""
        self._running = False
        # Unblock queue.get()
        try:
            self.audio_queue.put_nowait(None)
        except queue.Full:
            pass
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run(self) -> None:
        while self._running:
            try:
                chunk = self.audio_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            if chunk is None:
                break  # stop signal

            timestamp = self._elapsed
            self._elapsed += len(chunk) / SAMPLE_RATE

            try:
                text = self._transcribe_chunk(chunk)
                if text:
                    self.on_result(timestamp, text)
            except Exception as e:
                self._report_error(f"转录错误: {e}")

    def _transcribe_chunk(self, audio: np.ndarray) -> str:
        """Run SenseVoice inference on a single audio chunk."""
        if self._model is None:
            return ""

        # funasr expects list of arrays or file paths
        results = self._model.generate(
            input=audio,
            cache={},
            language="auto",
            use_itn=True,
            batch_size_s=60,
            merge_vad=True,
            merge_length_s=15,
        )

        if not results:
            return ""

        texts = []
        for res in results:
            raw = res.get("text", "")
            # SenseVoice prepends emotion/event tags like <|HAPPY|><|Speech|>
            # Strip angle-bracket tags
            import re
            clean = re.sub(r"<\|[^|]+\|>", "", raw).strip()
            if clean:
                texts.append(clean)

        return " ".join(texts)

    def _notify_status(self, msg: str) -> None:
        if self.on_status:
            self.on_status(msg)

    def _report_error(self, msg: str) -> None:
        if self.on_error:
            self.on_error(msg)
