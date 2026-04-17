"""
First-run setup wizard for Meeting Notes.

Shows a modal window that:
  1. Downloads / verifies the SenseVoice ASR model
  2. Detects Ollama installation and starts its service
  3. Pulls a suitable Ollama LLM model (qwen2.5:3b or qwen2.5:7b)

Entry point: run_if_needed()
  - Checks the setup-complete marker.
  - If setup has already been done, returns immediately.
  - Otherwise, creates a Tk root, runs the wizard to completion, then
    destroys it so the caller can create MeetingNotesApp normally.
"""

import datetime
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any, Optional, Tuple
import tkinter as tk
from tkinter import ttk, messagebox

from src.utils import (
    get_models_dir,
    is_first_run,
    mark_setup_complete,
)

# ── Constants ──────────────────────────────────────────────────────────────
OLLAMA_DOWNLOAD_URL = "https://ollama.com/download/windows"
OLLAMA_API_BASE = "http://localhost:11434"
PREFERRED_MODELS = ["qwen2.5:3b", "qwen2.5:7b"]   # smallest first
HF_MODEL_ID = "FunAudioLLM/SenseVoiceSmall"

TIMEOUT_PYTORCH = 180   # seconds
TIMEOUT_FUNASR  = 120   # seconds
TIMEOUT_MODEL   = 600   # seconds

# ── Color palette (matches main.py) ───────────────────────────────────────
C = {
    "bg":           "#1e1e2e",
    "surface":      "#2a2a3e",
    "surface2":     "#313149",
    "accent":       "#7c6ff7",
    "accent_hover": "#9d98f5",
    "text":         "#cdd6f4",
    "text_dim":     "#a6adc8",
    "success":      "#a6e3a1",
    "warning":      "#f9e2af",
    "error":        "#f38ba8",
    "border":       "#45475a",
}

FONT        = ("Segoe UI", 10)
FONT_S      = ("Segoe UI", 9)
FONT_B      = ("Segoe UI", 10, "bold")
FONT_TITLE  = ("Segoe UI", 14, "bold")
FONT_STATUS = ("Segoe UI", 11, "bold")
FONT_MONO   = ("Consolas", 9)

STEP_PENDING = "○"
STEP_RUNNING = "⟳"
STEP_OK      = "✓"
STEP_WARN    = "⚠"
STEP_ERROR   = "✗"


# ── Public entry point ────────────────────────────────────────────────────

def run_if_needed() -> None:
    """
    Run the setup wizard if this is the first launch.
    Blocks until the wizard is closed (completed or skipped by user).
    """
    if not is_first_run():
        return

    root = tk.Tk()
    root.withdraw()
    wizard = SetupWizard(root)
    root.wait_window(wizard)
    root.destroy()


# ── Wizard window ─────────────────────────────────────────────────────────

class SetupWizard(tk.Toplevel):
    def __init__(self, parent: tk.Tk):
        super().__init__(parent)
        self.title("会议纪要 - 首次运行配置")
        self.geometry("580x700")
        self.resizable(False, False)
        self.configure(bg=C["bg"])
        self._center()
        self.protocol("WM_DELETE_WINDOW", self._on_close_request)
        self.grab_set()  # modal

        self._cancelled = False
        self._all_done = False

        # Per-step state: (icon_var, detail_var)
        self._step_states: list = []
        self._step_frames: list = []

        self._build_ui()
        self.after(200, self._run_steps)

    # ── Layout ─────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # Header
        hdr = tk.Frame(self, bg=C["bg"], pady=14)
        hdr.pack(fill="x", padx=24)
        tk.Label(hdr, text="首次运行配置", font=FONT_TITLE,
                 bg=C["bg"], fg=C["accent"]).pack(side="left")

        tk.Label(
            self,
            text="本向导将自动下载并配置所需组件，完成后即可正常使用。",
            font=FONT_S, bg=C["bg"], fg=C["text_dim"],
            wraplength=532, justify="left",
        ).pack(padx=24, anchor="w")

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=24, pady=10)

        # Steps
        steps = [
            ("语音识别模型 (SenseVoice)",
             "下载 FunAudioLLM/SenseVoiceSmall (约 300 MB)，仅首次需要"),
            ("Ollama 本地 LLM 服务",
             "检测 Ollama 安装状态并启动服务"),
            ("会议总结模型 (Qwen 2.5)",
             "拉取 qwen2.5:3b 对话模型 (约 2 GB)，仅首次需要"),
        ]
        for title, subtitle in steps:
            icon_var   = tk.StringVar(value=STEP_PENDING)
            detail_var = tk.StringVar(value=subtitle)
            self._step_states.append((icon_var, detail_var))
            frame = self._make_step_row(title, icon_var, detail_var)
            self._step_frames.append(frame)

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=24, pady=10)

        # ── Big status label ──────────────────────────────────────────
        self._status_label = tk.Label(
            self,
            text="正在初始化...",
            font=FONT_STATUS,
            bg=C["bg"],
            fg=C["warning"],
            wraplength=532,
            justify="left",
        )
        self._status_label.pack(padx=24, anchor="w", pady=(0, 6))

        # ── Determinate progress bar + percentage ─────────────────────
        prog_frame = tk.Frame(self, bg=C["bg"])
        prog_frame.pack(fill="x", padx=24, pady=(0, 6))

        self._progress = ttk.Progressbar(
            prog_frame, mode="determinate", length=440, maximum=100
        )
        self._progress.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self._pct_label = tk.Label(
            prog_frame, text="  0%", font=FONT_S,
            bg=C["bg"], fg=C["text_dim"], width=5, anchor="e",
        )
        self._pct_label.pack(side="right")

        # ── Log area ──────────────────────────────────────────────────
        log_lbl = tk.Label(self, text="详细日志", font=FONT_S,
                           bg=C["bg"], fg=C["text_dim"])
        log_lbl.pack(padx=24, anchor="w")

        log_frame = tk.Frame(self, bg=C["surface"], bd=1, relief="flat")
        log_frame.pack(fill="both", expand=True, padx=24, pady=(2, 8))

        self._log_text = tk.Text(
            log_frame, font=FONT_MONO, bg=C["surface"], fg=C["text_dim"],
            height=10, bd=0, padx=6, pady=4, state="disabled", wrap="word",
        )
        # Color tags for log entries
        self._log_text.tag_configure("ok",   foreground=C["success"])
        self._log_text.tag_configure("warn", foreground=C["warning"])
        self._log_text.tag_configure("err",  foreground=C["error"])
        self._log_text.tag_configure("dim",  foreground=C["text_dim"])

        log_scroll = ttk.Scrollbar(log_frame, command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=log_scroll.set)
        log_scroll.pack(side="right", fill="y")
        self._log_text.pack(fill="both", expand=True)

        # ── Bottom: done button ───────────────────────────────────────
        bottom = tk.Frame(self, bg=C["bg"], pady=8)
        bottom.pack(fill="x", padx=24)

        self._btn = tk.Button(
            bottom, text="请稍候...", font=FONT_B,
            bg=C["surface2"], fg=C["text_dim"],
            activebackground=C["border"], activeforeground=C["text"],
            relief="flat", bd=0, padx=18, pady=7,
            state="disabled", cursor="arrow",
            command=self._on_done,
        )
        self._btn.pack(side="right")

    def _make_step_row(
        self,
        title: str,
        icon_var: tk.StringVar,
        detail_var: tk.StringVar,
    ) -> tk.Frame:
        frame = tk.Frame(self, bg=C["bg"])
        frame.pack(fill="x", padx=24, pady=4)

        icon_lbl = tk.Label(frame, textvariable=icon_var, font=("Segoe UI", 12),
                            bg=C["bg"], fg=C["text_dim"], width=2)
        icon_lbl.pack(side="left")

        text_frame = tk.Frame(frame, bg=C["bg"])
        text_frame.pack(side="left", fill="x", expand=True, padx=(6, 0))

        tk.Label(text_frame, text=title, font=FONT_B,
                 bg=C["bg"], fg=C["text"], anchor="w").pack(anchor="w")
        tk.Label(text_frame, textvariable=detail_var, font=FONT_S,
                 bg=C["bg"], fg=C["text_dim"], anchor="w",
                 wraplength=470, justify="left").pack(anchor="w")

        frame._icon_lbl = icon_lbl  # type: ignore[attr-defined]
        return frame

    # ── Thread-safe UI helpers ──────────────────────────────────────────

    def _center(self) -> None:
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = (sw - 580) // 2
        y = (sh - 700) // 2
        self.geometry(f"580x700+{x}+{y}")

    @staticmethod
    def _ts() -> str:
        return datetime.datetime.now().strftime("[%H:%M:%S]")

    def _log(self, msg: str, tag: str = "dim") -> None:
        """Append a timestamped line to the log. Thread-safe."""
        line = f"{self._ts()} {msg}\n"
        def _do() -> None:
            self._log_text.configure(state="normal")
            self._log_text.insert("end", line, tag)
            self._log_text.see("end")
            self._log_text.configure(state="disabled")
        self.after(0, _do)

    def _set_big_status(self, text: str, color: str) -> None:
        """Update the prominent status label. Thread-safe."""
        def _do() -> None:
            self._status_label.configure(text=text, fg=color)
        self.after(0, _do)

    def _set_step(self, idx: int, icon: str, detail: str,
                  color: Optional[str] = None) -> None:
        icon_var, detail_var = self._step_states[idx]
        def _do() -> None:
            icon_var.set(icon)
            detail_var.set(detail)
            lbl = self._step_frames[idx]._icon_lbl  # type: ignore[attr-defined]
            lbl.configure(fg=color or C["text_dim"])
        self.after(0, _do)

    def _set_progress(self, value: float) -> None:
        """Set determinate progress bar to value (0-100). Thread-safe."""
        def _do() -> None:
            self._progress.configure(value=value)
            self._pct_label.configure(text=f"{int(value):3d}%")
        self.after(0, _do)

    def _enable_done_button(self, text: str = "开始使用") -> None:
        def _do() -> None:
            self._progress.configure(value=100)
            self._pct_label.configure(text="100%")
            self._btn.configure(
                text=text, state="normal", cursor="hand2",
                bg=C["accent"], fg="#ffffff",
                activebackground=C["accent_hover"],
            )
        self.after(0, _do)

    # ── Timeout-protected runner ────────────────────────────────────────

    def _run_with_timeout(
        self,
        fn: Any,
        timeout_sec: int,
        timeout_label: str,
    ) -> Tuple[bool, Any, Any]:
        """
        Run fn() in a daemon thread with a hard timeout.
        Returns (success, return_value, error).
        On timeout returns (False, None, error_string).
        The inner thread continues as a daemon and will be reaped on exit.
        """
        result: dict = {"ok": False, "value": None, "error": None}
        done_evt = threading.Event()

        def _run() -> None:
            try:
                result["value"] = fn()
                result["ok"] = True
            except Exception as exc:
                result["error"] = exc
            finally:
                done_evt.set()

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        if not done_evt.wait(timeout=timeout_sec):
            result["error"] = (
                f"操作超时 ({timeout_sec} 秒): {timeout_label}"
            )
        return result["ok"], result["value"], result["error"]

    # ── Step runner ────────────────────────────────────────────────────

    def _run_steps(self) -> None:
        """Launch the sequential step runner in a background thread."""
        def _worker() -> None:
            try:
                self._set_progress(0)
                self._step_sensevoice()          # 0 → 40 %
                if self._cancelled:
                    return
                ollama_ok = self._step_ollama()  # 40 → 65 %
                if self._cancelled:
                    return
                if ollama_ok:
                    self._step_ollama_model()    # 65 → 100 %
                else:
                    self._set_progress(100)
                if not self._cancelled:
                    mark_setup_complete()
                    self._all_done = True
                    self._set_big_status("配置完成，可以开始使用！", C["success"])
                    self._log("所有组件配置完成。", "ok")
                    self._enable_done_button("开始使用")
            except Exception as exc:
                import traceback
                self._log(f"未预期的错误: {exc}", "err")
                self._log(traceback.format_exc(), "err")
                self._set_big_status("配置出错，可点击按钮跳过进入", C["error"])
                self._enable_done_button("跳过，直接进入")

        threading.Thread(target=_worker, daemon=True).start()

    # ── Step 1 – SenseVoice ────────────────────────────────────────────

    def _step_sensevoice(self) -> None:
        idx = 0
        self._log("===== 步骤 1/3: 语音识别模型 (SenseVoice) =====")
        self._set_big_status("正在检查语音识别模型缓存...", C["warning"])
        self._set_step(idx, STEP_RUNNING, "正在检查模型缓存...", C["warning"])
        self._set_progress(2)

        if self._sensevoice_is_cached():
            self._log("模型已在本地缓存中，跳过下载。", "ok")
            self._set_step(idx, STEP_OK, "模型已就绪 (使用本地缓存)", C["success"])
            self._set_progress(40)
            return

        self._log("未找到缓存，需要下载模型 (约 300 MB)，请耐心等待...")
        self._set_step(idx, STEP_RUNNING, "正在下载 SenseVoice 模型...", C["warning"])
        self._set_progress(5)

        ok, err = self._download_sensevoice()
        if ok:
            self._log("SenseVoice 模型下载/加载成功。", "ok")
            self._set_step(idx, STEP_OK, "模型下载完成", C["success"])
        else:
            self._log(f"下载失败: {err}", "err")
            self._set_step(idx, STEP_WARN,
                           f"下载失败 ({err})，启动后将重试", C["warning"])
        self._set_progress(40)

    def _sensevoice_is_cached(self) -> bool:
        hf_home = Path(os.environ.get(
            "HF_HOME",
            os.environ.get("HUGGINGFACE_HUB_CACHE",
                           str(Path.home() / ".cache" / "huggingface"))
        ))
        cache_dir = hf_home / "hub" / "models--FunAudioLLM--SenseVoiceSmall"
        local_dir = get_models_dir() / "FunAudioLLM" / "SenseVoiceSmall"
        return (
            (cache_dir.exists() and any(cache_dir.iterdir()))
            or (local_dir.exists() and any(local_dir.iterdir()))
        )

    def _download_sensevoice(self) -> Tuple[bool, str]:
        """Import PyTorch + funasr and trigger model download, all with timeouts."""

        # ── 1. Import PyTorch ─────────────────────────────────────────
        self._set_big_status(
            "正在初始化深度学习引擎 (首次启动约需 1-2 分钟)...", C["warning"]
        )
        self._log(
            f"正在导入 PyTorch... (超时保护: {TIMEOUT_PYTORCH} 秒，请耐心等待)"
        )
        self._set_progress(8)

        def _import_torch() -> Any:
            import torch  # noqa: PLC0415
            return torch

        ok, torch_mod, err = self._run_with_timeout(
            _import_torch, TIMEOUT_PYTORCH, "PyTorch 导入"
        )
        if not ok:
            msg = str(err)
            self._log(f"PyTorch 导入失败: {msg}", "err")
            return False, msg

        self._log(
            f"深度学习引擎加载完成 (PyTorch {torch_mod.__version__})", "ok"
        )
        self._set_progress(15)

        # ── 2. Import funasr ──────────────────────────────────────────
        self._set_big_status("正在加载语音识别引擎 (funasr)...", C["warning"])
        self._log(f"正在导入 funasr... (超时保护: {TIMEOUT_FUNASR} 秒)")
        self._set_progress(17)

        def _import_funasr() -> Any:
            from funasr import AutoModel  # noqa: PLC0415
            return AutoModel

        ok, auto_model_cls, err = self._run_with_timeout(
            _import_funasr, TIMEOUT_FUNASR, "funasr 导入"
        )
        if not ok:
            msg = str(err)
            self._log(f"funasr 导入失败: {msg}", "err")
            return False, msg

        self._log("语音识别引擎 (funasr) 加载完成。", "ok")
        self._set_progress(25)

        # ── 3. Download / cache the model ─────────────────────────────
        models_dir = str(get_models_dir())
        os.environ.setdefault("MODELSCOPE_CACHE", models_dir)
        os.environ.setdefault("HF_HOME", models_dir)

        self._set_big_status(
            "正在下载 SenseVoice 模型 (约 300 MB，请耐心等待)...", C["warning"]
        )
        self._log(
            f"正在下载/初始化模型 {HF_MODEL_ID} (超时保护: {TIMEOUT_MODEL} 秒)"
        )
        self._log("提示: 模型约 300 MB，下载时间取决于网速，请保持网络连接...")
        self._set_progress(28)

        # Capture auto_model_cls in closure — it is already bound above
        _cls = auto_model_cls

        def _load_model() -> Any:
            return _cls(
                model=HF_MODEL_ID,
                model_revision="v2.0.4",
                trust_remote_code=True,
                vad_model="fsmn-vad",
                vad_kwargs={"max_single_segment_time": 30000},
                disable_update=True,
                hub="hf",
            )

        ok, _, err = self._run_with_timeout(
            _load_model, TIMEOUT_MODEL, "SenseVoice 模型下载"
        )
        if not ok:
            msg = str(err)
            self._log(f"模型加载失败: {msg}", "err")
            return False, msg

        return True, ""

    # ── Step 2 – Ollama ────────────────────────────────────────────────

    def _step_ollama(self) -> bool:
        """Returns True if Ollama is running at end of step."""
        idx = 1
        self._log("===== 步骤 2/3: Ollama 本地 LLM 服务 =====")
        self._set_big_status("正在检测 Ollama 服务...", C["warning"])
        self._set_step(idx, STEP_RUNNING, "正在检测 Ollama...", C["warning"])
        self._set_progress(42)

        # Check if already running
        self._log("正在检查 Ollama 服务是否已运行 (连接 localhost:11434)...")
        if self._ollama_ping():
            self._log("Ollama 服务已在运行。", "ok")
            self._set_step(idx, STEP_OK, "Ollama 服务正常", C["success"])
            self._set_progress(65)
            return True

        self._log("Ollama 服务未响应，正在查找可执行文件...")
        ollama_exe = shutil.which("ollama")
        if ollama_exe:
            self._log(f"找到 ollama 可执行文件: {ollama_exe}")
            self._log("正在后台启动 ollama serve...")
            self._set_step(idx, STEP_RUNNING, "正在启动 Ollama 服务...", C["warning"])
            self._start_ollama_serve()
            self._log("等待服务就绪 (最多 10 秒)...")
            for i in range(5):
                time.sleep(2)
                self._log(f"正在检查 Ollama 连接... ({i + 1}/5)")
                if self._ollama_ping():
                    self._log("Ollama 服务启动成功！", "ok")
                    self._set_step(idx, STEP_OK, "Ollama 服务已启动", C["success"])
                    self._set_progress(65)
                    return True
            self._log("Ollama 服务仍未响应，请手动运行 ollama serve。", "warn")
        else:
            self._log("未在 PATH 中找到 ollama 命令，需要手动安装。", "warn")

        self._set_step(idx, STEP_WARN, "请安装 Ollama 后点击[重新检测]", C["warning"])

        installed = self._prompt_install_ollama()
        if installed:
            self._set_step(idx, STEP_OK, "Ollama 服务正常", C["success"])
            self._set_progress(65)
            return True

        self._set_step(idx, STEP_WARN,
                       "跳过 Ollama (可稍后安装，转录功能不受影响)", C["warning"])
        self._log("已跳过 Ollama 安装。转录功能不受影响，仅无法生成纪要摘要。", "warn")
        self._set_progress(65)
        return False

    def _ollama_ping(self) -> bool:
        try:
            import requests  # noqa: PLC0415
            r = requests.get(f"{OLLAMA_API_BASE}/api/tags", timeout=4)
            return r.status_code == 200
        except Exception:
            return False

    def _start_ollama_serve(self) -> None:
        try:
            if sys.platform == "win32":
                subprocess.Popen(
                    ["ollama", "serve"],
                    creationflags=(
                        subprocess.CREATE_NEW_PROCESS_GROUP
                        | subprocess.DETACHED_PROCESS
                    ),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                subprocess.Popen(
                    ["ollama", "serve"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except Exception as exc:
            self._log(f"ollama serve 启动失败: {exc}", "err")

    def _prompt_install_ollama(self) -> bool:
        result: dict = {"value": False}
        event = threading.Event()

        def _show_dialog() -> None:
            dlg = _OllamaInstallDialog(self, OLLAMA_DOWNLOAD_URL)
            self.wait_window(dlg)
            result["value"] = dlg.retry_requested
            event.set()

        self.after(0, _show_dialog)
        event.wait()

        if not result["value"]:
            return False

        # User clicked retry — poll a few times
        for attempt in range(1, 7):
            self._log(f"重新检测 Ollama... (尝试 {attempt}/6)")
            time.sleep(2)
            if self._ollama_ping():
                self._log("Ollama 连接成功！", "ok")
                return True

        self._log("仍无法连接 Ollama，跳过。", "warn")
        return False

    # ── Step 3 – Ollama model ──────────────────────────────────────────

    def _step_ollama_model(self) -> None:
        idx = 2
        self._log("===== 步骤 3/3: 会议总结模型 (Qwen 2.5) =====")
        self._set_big_status("正在检查 Ollama 已安装模型...", C["warning"])
        self._set_step(idx, STEP_RUNNING, "正在检查已安装模型...", C["warning"])
        self._set_progress(67)

        self._log("正在查询 Ollama 已安装模型列表...")
        existing = self._list_ollama_models()
        if existing:
            self._log(f"已安装模型: {', '.join(existing)}")
        else:
            self._log("暂无已安装模型。")

        target = self._pick_model(existing)
        if target is None:
            matched = next(
                (m for m in existing
                 if any(m.startswith(p) for p in PREFERRED_MODELS)),
                existing[0] if existing else "(未知)",
            )
            self._log(f"已有适用模型: {matched}，跳过下载。", "ok")
            self._set_step(idx, STEP_OK, f"已有模型: {matched}", C["success"])
            self._set_progress(100)
            return

        self._log(f"开始拉取模型 {target} (约 2 GB)，请耐心等待...")
        self._set_step(idx, STEP_RUNNING, f"正在下载 {target}...", C["warning"])
        self._set_big_status(f"正在下载 Qwen 2.5 模型 (约 2 GB，请耐心等待)...",
                             C["warning"])
        self._set_progress(70)

        ok, err = self._pull_ollama_model(target)
        if ok:
            self._log(f"模型 {target} 下载完成。", "ok")
            self._set_step(idx, STEP_OK, f"模型 {target} 已就绪", C["success"])
        else:
            self._log(f"拉取失败: {err}", "err")
            self._set_step(
                idx, STEP_WARN,
                f"拉取失败，请手动运行: ollama pull {target}",
                C["warning"],
            )
        self._set_progress(100)

    def _list_ollama_models(self) -> list:
        try:
            import requests  # noqa: PLC0415
            r = requests.get(f"{OLLAMA_API_BASE}/api/tags", timeout=5)
            r.raise_for_status()
            return [m["name"] for m in r.json().get("models", [])]
        except Exception:
            return []

    def _pick_model(self, existing: list) -> Optional[str]:
        """Return which preferred model to pull, or None if one already exists."""
        for preferred in PREFERRED_MODELS:
            for name in existing:
                if name.startswith(preferred):
                    return None  # already have it
        return PREFERRED_MODELS[0]

    def _pull_ollama_model(self, model: str) -> Tuple[bool, str]:
        try:
            import requests  # noqa: PLC0415
            with requests.post(
                f"{OLLAMA_API_BASE}/api/pull",
                json={"name": model, "stream": True},
                stream=True,
                timeout=3600,
            ) as resp:
                resp.raise_for_status()
                last_log_t = 0.0
                for line in resp.iter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                        status    = chunk.get("status", "")
                        total     = chunk.get("total", 0)
                        completed = chunk.get("completed", 0)
                        if total and completed:
                            pct = int(completed / total * 100)
                            # Map 0-100% of model pull onto progress bar 70-100
                            self._set_progress(70 + int(pct * 0.30))
                            now = time.time()
                            if now - last_log_t >= 5:
                                self._log(
                                    f"{status}: "
                                    f"{completed // 1024 // 1024} MB"
                                    f" / {total // 1024 // 1024} MB"
                                    f" ({pct}%)"
                                )
                                last_log_t = now
                        elif status:
                            self._log(f"Ollama pull: {status}")
                    except json.JSONDecodeError:
                        continue
            return True, ""
        except Exception as exc:
            return False, str(exc)

    # ── Close / Done ───────────────────────────────────────────────────

    def _on_close_request(self) -> None:
        if self._all_done:
            self.destroy()
            return
        if messagebox.askyesno(
            "跳过配置",
            "配置尚未完成。\n\n跳过后，某些功能可能无法使用（语音识别、会议总结）。\n确定要跳过吗？",
            parent=self,
        ):
            self._cancelled = True
            mark_setup_complete()
            self.destroy()

    def _on_done(self) -> None:
        self.destroy()


# ── Ollama install helper dialog ──────────────────────────────────────────

class _OllamaInstallDialog(tk.Toplevel):
    """Small dialog shown when Ollama is not installed."""

    def __init__(self, parent: tk.Toplevel, download_url: str):
        super().__init__(parent)
        self.title("需要安装 Ollama")
        self.geometry("420x260")
        self.resizable(False, False)
        self.configure(bg=C["bg"])
        self.grab_set()
        self.retry_requested = False
        self._url = download_url

        self._center(parent)
        self._build()

    def _center(self, parent: tk.Toplevel) -> None:
        self.update_idletasks()
        px = parent.winfo_x() + (parent.winfo_width() - 420) // 2
        py = parent.winfo_y() + (parent.winfo_height() - 260) // 2
        self.geometry(f"420x260+{px}+{py}")

    def _build(self) -> None:
        tk.Label(
            self, text="需要安装 Ollama", font=("Segoe UI", 12, "bold"),
            bg=C["bg"], fg=C["warning"], pady=16,
        ).pack()

        msg = (
            "会议纪要功能需要 Ollama 提供本地 LLM 支持。\n\n"
            "请按以下步骤操作:\n"
            "  1. 点击下方按钮，前往 Ollama 官网下载安装程序\n"
            "  2. 安装完成后，Ollama 会自动启动\n"
            "  3. 回到本窗口，点击[我已安装，重新检测]"
        )
        tk.Label(
            self, text=msg, font=("Segoe UI", 9),
            bg=C["bg"], fg=C["text"], wraplength=380,
            justify="left", padx=20,
        ).pack(anchor="w")

        btn_frame = tk.Frame(self, bg=C["bg"], pady=14)
        btn_frame.pack(fill="x", padx=20)

        tk.Button(
            btn_frame, text="打开 Ollama 下载页面",
            font=FONT_B, bg=C["surface2"], fg=C["text"],
            activebackground=C["border"], relief="flat", bd=0,
            padx=14, pady=6, cursor="hand2",
            command=self._open_download,
        ).pack(side="left")

        tk.Button(
            btn_frame, text="我已安装，重新检测",
            font=FONT_B, bg=C["accent"], fg="#ffffff",
            activebackground=C["accent_hover"], relief="flat", bd=0,
            padx=14, pady=6, cursor="hand2",
            command=self._retry,
        ).pack(side="right")

        tk.Button(
            btn_frame, text="暂时跳过",
            font=FONT_S, bg=C["bg"], fg=C["text_dim"],
            activebackground=C["bg"], relief="flat", bd=0,
            padx=8, pady=6, cursor="hand2",
            command=self.destroy,
        ).pack(side="right", padx=6)

    def _open_download(self) -> None:
        webbrowser.open(self._url)

    def _retry(self) -> None:
        self.retry_requested = True
        self.destroy()
