"""
Meeting Notes - Main entry point and GUI.

Clean modern tkinter GUI using ttk themes.
"""

import queue
import threading
import time
import datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from typing import Optional

from src.audio import AudioCapture, AudioDevice, list_input_devices, get_wasapi_loopback_devices
from src.transcriber import Transcriber
from src.summarizer import summarize, check_ollama_available, list_ollama_models, DEFAULT_MODEL
from src.utils import save_meeting_notes, format_timestamp, format_duration
from src.setup_wizard import run_if_needed


# ──────────────────────────────────────────────
# Color palette (dark-accent modern theme)
# ──────────────────────────────────────────────
COLORS = {
    "bg": "#1e1e2e",
    "surface": "#2a2a3e",
    "surface2": "#313149",
    "accent": "#7c6ff7",
    "accent_hover": "#9d98f5",
    "text": "#cdd6f4",
    "text_dim": "#a6adc8",
    "success": "#a6e3a1",
    "warning": "#f9e2af",
    "error": "#f38ba8",
    "border": "#45475a",
}

FONT_NORMAL = ("Segoe UI", 10)
FONT_SMALL = ("Segoe UI", 9)
FONT_MONO = ("Consolas", 10)
FONT_TITLE = ("Segoe UI", 16, "bold")
FONT_BUTTON = ("Segoe UI", 10, "bold")


class MeetingNotesApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("会议纪要")
        self.geometry("900x700")
        self.minsize(720, 540)
        self.configure(bg=COLORS["bg"])

        # State
        self._recording = False
        self._start_time: Optional[datetime.datetime] = None
        self._end_time: Optional[datetime.datetime] = None
        self._transcript_lines: list[tuple[float, str]] = []   # (ts_seconds, text)
        self._summary: str = ""
        self._audio_queue: queue.Queue = queue.Queue(maxsize=50)
        self._audio_capture: Optional[AudioCapture] = None
        self._transcriber: Optional[Transcriber] = None
        self._model_loaded = False
        self._model_loading = False

        # Timer
        self._timer_id: Optional[str] = None
        self._elapsed_seconds: int = 0

        self._build_ui()
        self._populate_devices()
        self._check_ollama()

        # Start model load in background
        self._load_model_async()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ──────────────────────────────────────────
    # UI construction
    # ──────────────────────────────────────────

    def _build_ui(self):
        self._apply_style()

        # ── Header ──────────────────────────────
        header = tk.Frame(self, bg=COLORS["bg"], pady=12)
        header.pack(fill="x", padx=20)

        tk.Label(
            header, text="会议纪要", font=FONT_TITLE,
            bg=COLORS["bg"], fg=COLORS["accent"]
        ).pack(side="left")

        self._status_var = tk.StringVar(value="就绪")
        tk.Label(
            header, textvariable=self._status_var, font=FONT_SMALL,
            bg=COLORS["bg"], fg=COLORS["text_dim"]
        ).pack(side="right", pady=4)

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=20)

        # ── Device panel ─────────────────────────
        dev_frame = tk.LabelFrame(
            self, text=" 音频设备 ", font=FONT_SMALL,
            bg=COLORS["bg"], fg=COLORS["text_dim"],
            bd=1, relief="flat",
        )
        dev_frame.pack(fill="x", padx=20, pady=(12, 4))

        # Mic row
        mic_row = tk.Frame(dev_frame, bg=COLORS["bg"])
        mic_row.pack(fill="x", padx=8, pady=4)
        tk.Label(mic_row, text="麦克风:", font=FONT_SMALL,
                 bg=COLORS["bg"], fg=COLORS["text"], width=10, anchor="w").pack(side="left")
        self._mic_var = tk.StringVar()
        self._mic_cb = ttk.Combobox(
            mic_row, textvariable=self._mic_var, state="readonly",
            font=FONT_SMALL, width=50
        )
        self._mic_cb.pack(side="left", padx=4, fill="x", expand=True)

        # Loopback row
        loop_row = tk.Frame(dev_frame, bg=COLORS["bg"])
        loop_row.pack(fill="x", padx=8, pady=(0, 4))
        tk.Label(loop_row, text="系统音频:", font=FONT_SMALL,
                 bg=COLORS["bg"], fg=COLORS["text"], width=10, anchor="w").pack(side="left")
        self._loop_var = tk.StringVar()
        self._loop_cb = ttk.Combobox(
            loop_row, textvariable=self._loop_var, state="readonly",
            font=FONT_SMALL, width=50
        )
        self._loop_cb.pack(side="left", padx=4, fill="x", expand=True)

        # Model selector row
        model_row = tk.Frame(dev_frame, bg=COLORS["bg"])
        model_row.pack(fill="x", padx=8, pady=(0, 6))
        tk.Label(model_row, text="LLM 模型:", font=FONT_SMALL,
                 bg=COLORS["bg"], fg=COLORS["text"], width=10, anchor="w").pack(side="left")
        self._model_var = tk.StringVar(value=DEFAULT_MODEL)
        self._model_cb = ttk.Combobox(
            model_row, textvariable=self._model_var, font=FONT_SMALL, width=30
        )
        self._model_cb.pack(side="left", padx=4)
        self._ollama_status_lbl = tk.Label(
            model_row, text="检查 Ollama...", font=FONT_SMALL,
            bg=COLORS["bg"], fg=COLORS["text_dim"]
        )
        self._ollama_status_lbl.pack(side="left", padx=8)

        # ── Notebook: Transcript / Summary ──────
        self._notebook = ttk.Notebook(self)
        self._notebook.pack(fill="both", expand=True, padx=20, pady=8)

        # Transcript tab
        trans_frame = tk.Frame(self._notebook, bg=COLORS["surface"])
        self._notebook.add(trans_frame, text="  实时转录  ")

        self._transcript_text = tk.Text(
            trans_frame, font=FONT_MONO, wrap="word",
            bg=COLORS["surface"], fg=COLORS["text"],
            insertbackground=COLORS["accent"],
            selectbackground=COLORS["accent"],
            bd=0, padx=8, pady=8,
            state="disabled",
        )
        scroll_t = ttk.Scrollbar(trans_frame, command=self._transcript_text.yview)
        self._transcript_text.configure(yscrollcommand=scroll_t.set)
        scroll_t.pack(side="right", fill="y")
        self._transcript_text.pack(fill="both", expand=True)

        # Summary tab
        summary_frame = tk.Frame(self._notebook, bg=COLORS["surface"])
        self._notebook.add(summary_frame, text="  会议纪要  ")

        self._summary_text = tk.Text(
            summary_frame, font=FONT_NORMAL, wrap="word",
            bg=COLORS["surface"], fg=COLORS["text"],
            insertbackground=COLORS["accent"],
            selectbackground=COLORS["accent"],
            bd=0, padx=10, pady=10,
            state="disabled",
        )
        scroll_s = ttk.Scrollbar(summary_frame, command=self._summary_text.yview)
        self._summary_text.configure(yscrollcommand=scroll_s.set)
        scroll_s.pack(side="right", fill="y")
        self._summary_text.pack(fill="both", expand=True)

        # ── Bottom toolbar ───────────────────────
        toolbar = tk.Frame(self, bg=COLORS["bg"], pady=10)
        toolbar.pack(fill="x", padx=20)

        # Timer
        self._timer_var = tk.StringVar(value="00:00:00")
        timer_lbl = tk.Label(
            toolbar, textvariable=self._timer_var, font=("Consolas", 13, "bold"),
            bg=COLORS["bg"], fg=COLORS["accent"], width=10
        )
        timer_lbl.pack(side="left")

        # Buttons (right-aligned)
        btn_frame = tk.Frame(toolbar, bg=COLORS["bg"])
        btn_frame.pack(side="right")

        self._save_btn = self._make_button(
            btn_frame, "保存", self._on_save, state="disabled", secondary=True
        )
        self._save_btn.pack(side="right", padx=(6, 0))

        self._gen_btn = self._make_button(
            btn_frame, "生成纪要", self._on_generate, state="disabled", secondary=True
        )
        self._gen_btn.pack(side="right", padx=6)

        self._rec_btn = self._make_button(
            btn_frame, "开始录制", self._on_record_toggle, state="disabled"
        )
        self._rec_btn.pack(side="right")

        # Model load progress
        self._model_lbl = tk.Label(
            toolbar, text="正在加载转录模型...", font=FONT_SMALL,
            bg=COLORS["bg"], fg=COLORS["warning"]
        )
        self._model_lbl.pack(side="left", padx=12)

    def _apply_style(self):
        style = ttk.Style(self)
        # Use clam as base, then override
        style.theme_use("clam")

        style.configure(
            "TCombobox",
            fieldbackground=COLORS["surface2"],
            background=COLORS["surface2"],
            foreground=COLORS["text"],
            arrowcolor=COLORS["accent"],
            bordercolor=COLORS["border"],
            lightcolor=COLORS["surface2"],
            darkcolor=COLORS["surface2"],
        )
        style.map("TCombobox", fieldbackground=[("readonly", COLORS["surface2"])])

        style.configure(
            "TNotebook",
            background=COLORS["bg"],
            borderwidth=0,
        )
        style.configure(
            "TNotebook.Tab",
            background=COLORS["surface"],
            foreground=COLORS["text_dim"],
            padding=[12, 6],
            font=FONT_SMALL,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", COLORS["surface2"])],
            foreground=[("selected", COLORS["text"])],
        )
        style.configure("TSeparator", background=COLORS["border"])
        style.configure("TScrollbar", background=COLORS["surface2"],
                        troughcolor=COLORS["surface"], bordercolor=COLORS["surface"],
                        arrowcolor=COLORS["text_dim"])

    def _make_button(
        self, parent, text: str, command, state: str = "normal", secondary: bool = False
    ) -> tk.Button:
        bg = COLORS["surface2"] if secondary else COLORS["accent"]
        fg = COLORS["text"] if secondary else "#ffffff"
        abg = COLORS["border"] if secondary else COLORS["accent_hover"]
        btn = tk.Button(
            parent, text=text, command=command,
            font=FONT_BUTTON, bg=bg, fg=fg,
            activebackground=abg, activeforeground=fg,
            relief="flat", bd=0, padx=16, pady=7,
            cursor="hand2", state=state,
        )
        btn.bind("<Enter>", lambda e: btn.configure(bg=abg))
        btn.bind("<Leave>", lambda e: btn.configure(bg=bg))
        return btn

    # ──────────────────────────────────────────
    # Device population
    # ──────────────────────────────────────────

    def _populate_devices(self):
        devices = list_input_devices()
        self._devices = devices  # list[AudioDevice]

        none_label = "(不捕获)"
        mic_options = [none_label] + [str(d) for d in devices if not d.is_wasapi_loopback]
        loop_options = [none_label] + [str(d) for d in devices if d.is_wasapi_loopback]

        self._mic_cb["values"] = mic_options
        self._loop_cb["values"] = loop_options

        # Default: first mic, first loopback if available
        self._mic_var.set(mic_options[1] if len(mic_options) > 1 else none_label)
        self._loop_var.set(loop_options[1] if len(loop_options) > 1 else none_label)

    def _get_selected_mic(self) -> Optional[AudioDevice]:
        sel = self._mic_var.get()
        if not sel or "不捕获" in sel:
            return None
        for d in self._devices:
            if str(d) == sel:
                return d
        return None

    def _get_selected_loop(self) -> Optional[AudioDevice]:
        sel = self._loop_var.get()
        if not sel or "不捕获" in sel:
            return None
        for d in self._devices:
            if str(d) == sel:
                return d
        return None

    # ──────────────────────────────────────────
    # Model loading
    # ──────────────────────────────────────────

    def _load_model_async(self):
        self._model_loading = True
        t = threading.Thread(target=self._load_model_thread, daemon=True)
        t.start()

    def _load_model_thread(self):
        transcriber = Transcriber(
            audio_queue=self._audio_queue,
            on_result=self._on_transcription,
            on_status=self._on_model_status,
            on_error=self._on_error,
        )
        ok = transcriber.load_model()
        self._transcriber = transcriber if ok else None
        self._model_loaded = ok
        self._model_loading = False
        self.after(0, self._on_model_ready, ok)

    def _on_model_ready(self, ok: bool):
        if ok:
            self._model_lbl.configure(text="模型就绪", fg=COLORS["success"])
            self._rec_btn.configure(state="normal")
            self._set_status("模型就绪,可开始录制")
        else:
            self._model_lbl.configure(text="模型加载失败", fg=COLORS["error"])
            self._set_status("模型加载失败,请检查依赖")

    def _on_model_status(self, msg: str):
        self.after(0, lambda: self._model_lbl.configure(text=msg, fg=COLORS["warning"]))

    # ──────────────────────────────────────────
    # Ollama check
    # ──────────────────────────────────────────

    def _check_ollama(self):
        def _check():
            ok, msg = check_ollama_available()
            models = list_ollama_models() if ok else []
            self.after(0, self._update_ollama_ui, ok, msg, models)

        threading.Thread(target=_check, daemon=True).start()

    def _update_ollama_ui(self, ok: bool, msg: str, models: list[str]):
        color = COLORS["success"] if ok else COLORS["error"]
        self._ollama_status_lbl.configure(text=msg, fg=color)
        if models:
            self._model_cb["values"] = models
            if DEFAULT_MODEL in models:
                self._model_var.set(DEFAULT_MODEL)
            else:
                self._model_var.set(models[0])

    # ──────────────────────────────────────────
    # Recording control
    # ──────────────────────────────────────────

    def _on_record_toggle(self):
        if self._recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self):
        mic_dev = self._get_selected_mic()
        loop_dev = self._get_selected_loop()

        if mic_dev is None and loop_dev is None:
            messagebox.showwarning("提示", "请至少选择一个音频源(麦克风或系统音频)")
            return

        # Reset state
        self._transcript_lines = []
        self._summary = ""
        self._clear_text(self._transcript_text)
        self._clear_text(self._summary_text)
        self._audio_queue = queue.Queue(maxsize=50)
        self._elapsed_seconds = 0
        self._start_time = datetime.datetime.now()
        self._end_time = None

        # Start audio capture
        self._audio_capture = AudioCapture(
            audio_queue=self._audio_queue,
            mic_device_index=mic_dev.index if mic_dev else None,
            loopback_device_index=loop_dev.index if loop_dev else None,
            on_error=self._on_error,
        )

        # Reuse transcriber, give it the new queue
        if self._transcriber:
            self._transcriber.audio_queue = self._audio_queue
            self._transcriber.start()

        self._audio_capture.start()
        self._recording = True

        # Update UI
        self._rec_btn.configure(
            text="停止录制",
            bg=COLORS["error"],
            activebackground="#c97070",
        )
        self._rec_btn.bind("<Enter>", lambda e: self._rec_btn.configure(bg="#c97070"))
        self._rec_btn.bind("<Leave>", lambda e: self._rec_btn.configure(bg=COLORS["error"]))
        self._gen_btn.configure(state="disabled")
        self._save_btn.configure(state="disabled")
        self._mic_cb.configure(state="disabled")
        self._loop_cb.configure(state="disabled")
        self._set_status("录制中...")
        self._start_timer()

    def _stop_recording(self):
        self._recording = False
        self._end_time = datetime.datetime.now()

        if self._audio_capture:
            self._audio_capture.stop()
            self._audio_capture = None

        if self._transcriber:
            self._transcriber.stop()

        self._stop_timer()

        # Update UI
        acc = COLORS["accent"]
        ahov = COLORS["accent_hover"]
        self._rec_btn.configure(text="开始录制", bg=acc, activebackground=ahov)
        self._rec_btn.bind("<Enter>", lambda e: self._rec_btn.configure(bg=ahov))
        self._rec_btn.bind("<Leave>", lambda e: self._rec_btn.configure(bg=acc))
        self._gen_btn.configure(state="normal" if self._transcript_lines else "disabled")
        self._save_btn.configure(state="normal" if self._transcript_lines else "disabled")
        self._mic_cb.configure(state="readonly")
        self._loop_cb.configure(state="readonly")
        self._set_status(f"录制结束,共 {format_duration(self._elapsed_seconds)}")

    # ──────────────────────────────────────────
    # Timer
    # ──────────────────────────────────────────

    def _start_timer(self):
        self._tick()

    def _tick(self):
        if not self._recording:
            return
        self._elapsed_seconds += 1
        h = self._elapsed_seconds // 3600
        m = (self._elapsed_seconds % 3600) // 60
        s = self._elapsed_seconds % 60
        self._timer_var.set(f"{h:02d}:{m:02d}:{s:02d}")
        self._timer_id = self.after(1000, self._tick)

    def _stop_timer(self):
        if self._timer_id:
            self.after_cancel(self._timer_id)
            self._timer_id = None

    # ──────────────────────────────────────────
    # Transcription callback (from background thread)
    # ──────────────────────────────────────────

    def _on_transcription(self, timestamp: float, text: str):
        self._transcript_lines.append((timestamp, text))
        self.after(0, self._append_transcript, timestamp, text)

    def _append_transcript(self, timestamp: float, text: str):
        ts_str = format_timestamp(timestamp)
        line = f"[{ts_str}] {text}\n"
        self._transcript_text.configure(state="normal")
        self._transcript_text.insert("end", line)
        self._transcript_text.see("end")
        self._transcript_text.configure(state="disabled")

    # ──────────────────────────────────────────
    # Generate summary
    # ──────────────────────────────────────────

    def _on_generate(self):
        if not self._transcript_lines:
            messagebox.showinfo("提示", "没有转录内容,无法生成纪要")
            return

        self._gen_btn.configure(state="disabled", text="生成中...")
        self._set_status("正在生成会议纪要...")
        self._notebook.select(1)  # switch to summary tab
        self._clear_text(self._summary_text)

        transcript_text = "\n".join(
            f"[{format_timestamp(ts)}] {txt}"
            for ts, txt in self._transcript_lines
        )
        model = self._model_var.get() or DEFAULT_MODEL

        def _gen():
            def _token(tok: str):
                self.after(0, self._append_summary, tok)

            result = summarize(transcript_text, model=model, on_token=_token)
            self._summary = result
            self.after(0, self._on_generate_done)

        threading.Thread(target=_gen, daemon=True).start()

    def _append_summary(self, token: str):
        self._summary_text.configure(state="normal")
        self._summary_text.insert("end", token)
        self._summary_text.see("end")
        self._summary_text.configure(state="disabled")

    def _on_generate_done(self):
        self._gen_btn.configure(state="normal", text="生成纪要")
        self._save_btn.configure(state="normal")
        self._set_status("会议纪要生成完成")

    # ──────────────────────────────────────────
    # Save
    # ──────────────────────────────────────────

    def _on_save(self):
        end = self._end_time or datetime.datetime.now()
        start = self._start_time or end

        filepath = save_meeting_notes(
            transcript_lines=self._transcript_lines,
            summary=self._summary,
            start_time=start,
            end_time=end,
        )
        messagebox.showinfo("保存成功", f"文件已保存:\n{filepath}")
        self._set_status(f"已保存: {filepath.name}")

    # ──────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────

    def _set_status(self, msg: str):
        self._status_var.set(msg)

    def _on_error(self, msg: str):
        self.after(0, lambda: self._set_status(f"错误: {msg}"))

    def _clear_text(self, widget: tk.Text):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.configure(state="disabled")

    def _on_close(self):
        if self._recording:
            self._stop_recording()
        self.destroy()


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────

def main():
    # First-run: show setup wizard (downloads SenseVoice, configures Ollama).
    # run_if_needed() is a no-op on subsequent launches.
    run_if_needed()

    app = MeetingNotesApp()
    app.mainloop()


if __name__ == "__main__":
    main()
