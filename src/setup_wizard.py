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

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Optional
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

# ── Color palette (matches main.py) ───────────────────────────────────────
C = {
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

FONT = ("Segoe UI", 10)
FONT_S = ("Segoe UI", 9)
FONT_B = ("Segoe UI", 10, "bold")
FONT_TITLE = ("Segoe UI", 14, "bold")
FONT_MONO = ("Consolas", 9)

STEP_PENDING  = "○"
STEP_RUNNING  = "⟳"
STEP_OK       = "✓"
STEP_WARN     = "⚠"
STEP_ERROR    = "✗"


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
        self.title("会议纪要 – 首次运行配置")
        self.geometry("560x580")
        self.resizable(False, False)
        self.configure(bg=C["bg"])
        self._center()
        self.protocol("WM_DELETE_WINDOW", self._on_close_request)
        self.grab_set()  # modal

        self._cancelled = False
        self._all_done = False

        # Per-step state: (icon_var, detail_var)
        self._step_states: list[tuple[tk.StringVar, tk.StringVar]] = []

        self._build_ui()
        self.after(200, self._run_steps)

    # ── Layout ─────────────────────────────────────────────────────────

    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=C["bg"], pady=14)
        hdr.pack(fill="x", padx=24)
        tk.Label(hdr, text="首次运行配置", font=FONT_TITLE,
                 bg=C["bg"], fg=C["accent"]).pack(side="left")

        tk.Label(
            self,
            text="本向导将自动下载并配置所需组件,完成后即可正常使用。",
            font=FONT_S, bg=C["bg"], fg=C["text_dim"], wraplength=512, justify="left",
        ).pack(padx=24, anchor="w")

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=24, pady=10)

        # Steps
        steps = [
            ("语音识别模型(SenseVoice)",
             "下载 FunAudioLLM/SenseVoiceSmall(约 300 MB),仅首次需要"),
            ("Ollama 本地 LLM 服务",
             "检测 Ollama 安装状态并启动服务"),
            ("会议总结模型(Qwen 2.5)",
             "拉取 qwen2.5:3b 对话模型(约 2 GB),仅首次需要"),
        ]
        self._step_frames = []
        for title, subtitle in steps:
            icon_var = tk.StringVar(value=STEP_PENDING)
            detail_var = tk.StringVar(value=subtitle)
            self._step_states.append((icon_var, detail_var))
            frame = self._make_step_row(title, icon_var, detail_var)
            self._step_frames.append(frame)

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=24, pady=10)

        # Log area
        log_lbl = tk.Label(self, text="日志", font=FONT_S,
                           bg=C["bg"], fg=C["text_dim"])
        log_lbl.pack(padx=24, anchor="w")

        log_frame = tk.Frame(self, bg=C["surface"], bd=1, relief="flat")
        log_frame.pack(fill="both", expand=True, padx=24, pady=(2, 10))

        self._log_text = tk.Text(
            log_frame, font=FONT_MONO, bg=C["surface"], fg=C["text_dim"],
            height=8, bd=0, padx=6, pady=4, state="disabled", wrap="word",
        )
        log_scroll = ttk.Scrollbar(log_frame, command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=log_scroll.set)
        log_scroll.pack(side="right", fill="y")
        self._log_text.pack(fill="both", expand=True)

        # Bottom: overall progress + button
        bottom = tk.Frame(self, bg=C["bg"], pady=10)
        bottom.pack(fill="x", padx=24)

        self._progress = ttk.Progressbar(
            bottom, mode="indeterminate", length=340
        )
        self._progress.pack(side="left", fill="x", expand=True, padx=(0, 12))

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
        self, title: str,
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
        detail_lbl = tk.Label(text_frame, textvariable=detail_var, font=FONT_S,
                              bg=C["bg"], fg=C["text_dim"], anchor="w", wraplength=450,
                              justify="left")
        detail_lbl.pack(anchor="w")

        # Keep reference to icon label for colour changes
        frame._icon_lbl = icon_lbl  # type: ignore[attr-defined]
        return frame

    # ── Helpers ────────────────────────────────────────────────────────

    def _center(self):
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = (sw - 560) // 2
        y = (sh - 580) // 2
        self.geometry(f"560x580+{x}+{y}")

    def _log(self, msg: str):
        def _do():
            self._log_text.configure(state="normal")
            self._log_text.insert("end", msg + "\n")
            self._log_text.see("end")
            self._log_text.configure(state="disabled")
        self.after(0, _do)

    def _set_step(self, idx: int, icon: str, detail: str,
                  color: Optional[str] = None):
        icon_var, detail_var = self._step_states[idx]
        def _do():
            icon_var.set(icon)
            detail_var.set(detail)
            lbl = self._step_frames[idx]._icon_lbl  # type: ignore[attr-defined]
            lbl.configure(fg=color or C["text_dim"])
        self.after(0, _do)

    def _set_progress_mode(self, mode: str):
        def _do():
            self._progress.configure(mode=mode)
            if mode == "indeterminate":
                self._progress.start(12)
            else:
                self._progress.stop()
        self.after(0, _do)

    def _set_progress_value(self, value: float):
        def _do():
            self._progress.configure(mode="determinate", value=value)
            self._progress.stop()
        self.after(0, _do)

    def _enable_done_button(self, text: str = "开始使用"):
        def _do():
            self._progress.stop()
            self._progress.configure(mode="determinate", value=100)
            self._btn.configure(
                text=text, state="normal", cursor="hand2",
                bg=C["accent"], fg="#ffffff",
                activebackground=C["accent_hover"],
            )
        self.after(0, _do)

    # ── Step runner ────────────────────────────────────────────────────

    def _run_steps(self):
        """Launch the sequential step runner in a background thread."""
        def _worker():
            try:
                self._step_sensevoice()
                if self._cancelled:
                    return
                ollama_ok = self._step_ollama()
                if self._cancelled:
                    return
                if ollama_ok:
                    self._step_ollama_model()
                if not self._cancelled:
                    mark_setup_complete()
                    self._all_done = True
                    self._enable_done_button("开始使用")
            except Exception as exc:
                self._log(f"[错误] 未预期的错误: {exc}")
                self._enable_done_button("跳过,直接进入")

        threading.Thread(target=_worker, daemon=True).start()

    # ── Step 1 – SenseVoice ────────────────────────────────────────────

    def _step_sensevoice(self):
        idx = 0
        self._set_step(idx, STEP_RUNNING, "正在检查模型缓存...", C["warning"])
        self._set_progress_mode("indeterminate")

        # Check HuggingFace cache
        if self._sensevoice_is_cached():
            self._log("[SenseVoice] 模型已缓存,跳过下载。")
            self._set_step(idx, STEP_OK, "模型已就绪(使用本地缓存)", C["success"])
            return

        self._log("[SenseVoice] 未找到缓存,首次需要下载模型(约 300 MB),请耐心等待...")
        self._set_step(idx, STEP_RUNNING, "正在下载 SenseVoice 模型...", C["warning"])

        ok, err = self._download_sensevoice()
        if ok:
            self._log("[SenseVoice] 下载完成。")
            self._set_step(idx, STEP_OK, "模型下载完成", C["success"])
        else:
            self._log(f"[SenseVoice] 下载失败: {err}")
            self._set_step(idx, STEP_WARN,
                           f"下载失败({err}),启动后将重试", C["warning"])

    def _sensevoice_is_cached(self) -> bool:
        """Heuristic: check HuggingFace hub cache for the model blobs."""
        # Standard HF cache location
        hf_home = Path(os.environ.get(
            "HF_HOME",
            os.environ.get("HUGGINGFACE_HUB_CACHE",
                           str(Path.home() / ".cache" / "huggingface"))
        ))
        cache_dir = hf_home / "hub" / "models--FunAudioLLM--SenseVoiceSmall"
        # Also check our custom models dir (if user ran from source before)
        local_dir = get_models_dir() / "FunAudioLLM" / "SenseVoiceSmall"
        return (
            (cache_dir.exists() and any(cache_dir.iterdir()))
            or (local_dir.exists() and any(local_dir.iterdir()))
        )

    def _download_sensevoice(self) -> tuple[bool, str]:
        """Trigger SenseVoice download by loading it via funasr."""
        try:
            self._log("[SenseVoice] 正在加载 PyTorch (首次较慢,请耐心等待)...")
            import torch
            self._log(f"[SenseVoice] PyTorch {torch.__version__} 加载完成")

            self._log("[SenseVoice] 正在加载 funasr 库...")
            from funasr import AutoModel
            self._log("[SenseVoice] funasr 加载完成")

            models_dir = str(get_models_dir())
            os.environ.setdefault("MODELSCOPE_CACHE", models_dir)
            os.environ.setdefault("HF_HOME", models_dir)

            self._log("[SenseVoice] 正在下载/加载模型 (约 300 MB)...")
            AutoModel(
                model=HF_MODEL_ID,
                model_revision="v2.0.4",
                trust_remote_code=True,
                vad_model="fsmn-vad",
                vad_kwargs={"max_single_segment_time": 30000},
                disable_update=True,
                hub="hf",
            )
            return True, ""
        except Exception as exc:
            import traceback
            self._log(f"[SenseVoice] 错误详情: {traceback.format_exc()}")
            return False, str(exc)

    # ── Step 2 – Ollama ────────────────────────────────────────────────

    def _step_ollama(self) -> bool:
        """Returns True if Ollama is running at end of step."""
        idx = 1
        self._set_step(idx, STEP_RUNNING, "正在检测 Ollama...", C["warning"])

        # Already running?
        if self._ollama_ping():
            self._log("[Ollama] 服务已在运行。")
            self._set_step(idx, STEP_OK, "Ollama 服务正常", C["success"])
            return True

        # Try to find the ollama executable
        ollama_exe = shutil.which("ollama")
        if ollama_exe:
            self._log(f"[Ollama] 找到可执行文件: {ollama_exe},尝试启动服务...")
            self._set_step(idx, STEP_RUNNING, "正在启动 Ollama 服务...", C["warning"])
            self._start_ollama_serve()
            time.sleep(3)
            if self._ollama_ping():
                self._log("[Ollama] 服务启动成功。")
                self._set_step(idx, STEP_OK, "Ollama 服务已启动", C["success"])
                return True
            self._log("[Ollama] 服务未响应,请手动运行 ollama serve。")

        # Not installed or not responding — guide user
        self._log("[Ollama] 未检测到 Ollama,需要手动安装。")
        self._set_step(idx, STEP_WARN, "请安装 Ollama 后点击[重新检测]", C["warning"])

        # Show a helper dialog (runs on GUI thread via event)
        installed = self._prompt_install_ollama()
        if installed:
            self._set_step(idx, STEP_OK, "Ollama 服务正常", C["success"])
            return True

        self._set_step(idx, STEP_WARN,
                       "跳过 Ollama(可稍后安装,转录功能不受影响)", C["warning"])
        return False

    def _ollama_ping(self) -> bool:
        try:
            import requests
            r = requests.get(f"{OLLAMA_API_BASE}/api/tags", timeout=4)
            return r.status_code == 200
        except Exception:
            return False

    def _start_ollama_serve(self):
        try:
            # Detached so it keeps running after wizard closes
            if sys.platform == "win32":
                subprocess.Popen(
                    ["ollama", "serve"],
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                    | subprocess.DETACHED_PROCESS,
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
            self._log(f"[Ollama] 启动失败: {exc}")

    def _prompt_install_ollama(self) -> bool:
        """
        Show an info dialog asking the user to install Ollama.
        Loop with a "retry" button until connected or user gives up.
        """
        result = {"value": False}
        event = threading.Event()

        def _show_dialog():
            dlg = _OllamaInstallDialog(self, OLLAMA_DOWNLOAD_URL)
            self.wait_window(dlg)
            result["value"] = dlg.retry_requested
            event.set()

        self.after(0, _show_dialog)
        event.wait()

        if not result["value"]:
            return False

        # User clicked retry — check again
        for attempt in range(1, 7):
            self._log(f"[Ollama] 重新检测... (尝试 {attempt}/6)")
            time.sleep(2)
            if self._ollama_ping():
                self._log("[Ollama] 连接成功！")
                return True

        self._log("[Ollama] 仍无法连接,跳过。")
        return False

    # ── Step 3 – Ollama model ──────────────────────────────────────────

    def _step_ollama_model(self):
        idx = 2
        self._set_step(idx, STEP_RUNNING, "正在检查已安装模型...", C["warning"])

        existing = self._list_ollama_models()
        target = self._pick_model(existing)

        if target is None:
            # Already have a suitable model
            matched = next(
                (m for m in existing
                 if any(m.startswith(p) for p in PREFERRED_MODELS)),
                existing[0] if existing else "(未知)",
            )
            self._log(f"[Ollama] 已有适用模型: {matched}")
            self._set_step(idx, STEP_OK, f"已有模型: {matched}", C["success"])
            return

        self._log(f"[Ollama] 开始拉取模型 {target}(约 2 GB,请稍候)...")
        self._set_step(idx, STEP_RUNNING, f"正在下载 {target}...", C["warning"])
        self._set_progress_mode("indeterminate")

        ok, err = self._pull_ollama_model(target)
        if ok:
            self._log(f"[Ollama] 模型 {target} 下载完成。")
            self._set_step(idx, STEP_OK, f"模型 {target} 已就绪", C["success"])
        else:
            self._log(f"[Ollama] 拉取失败: {err}")
            self._set_step(idx, STEP_WARN,
                           f"拉取失败,请手动运行: ollama pull {target}",
                           C["warning"])

    def _list_ollama_models(self) -> list[str]:
        try:
            import requests
            r = requests.get(f"{OLLAMA_API_BASE}/api/tags", timeout=5)
            r.raise_for_status()
            return [m["name"] for m in r.json().get("models", [])]
        except Exception:
            return []

    def _pick_model(self, existing: list[str]) -> Optional[str]:
        """Return which preferred model to pull, or None if one is already there."""
        for preferred in PREFERRED_MODELS:
            for name in existing:
                if name.startswith(preferred):
                    return None  # already have it
        return PREFERRED_MODELS[0]   # pull the smallest preferred model

    def _pull_ollama_model(self, model: str) -> tuple[bool, str]:
        try:
            import requests
            with requests.post(
                f"{OLLAMA_API_BASE}/api/pull",
                json={"name": model, "stream": True},
                stream=True,
                timeout=3600,  # large model can take a long time
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                        status = chunk.get("status", "")
                        total = chunk.get("total", 0)
                        completed = chunk.get("completed", 0)
                        if total and completed:
                            pct = int(completed / total * 100)
                            self._set_progress_value(pct)
                            self._log(
                                f"[Ollama] {status}: {completed // 1024 // 1024} MB"
                                f" / {total // 1024 // 1024} MB ({pct}%)"
                            )
                        elif status:
                            self._log(f"[Ollama] {status}")
                    except json.JSONDecodeError:
                        continue
            return True, ""
        except Exception as exc:
            return False, str(exc)

    # ── Close / Done ───────────────────────────────────────────────────

    def _on_close_request(self):
        if self._all_done:
            self.destroy()
            return
        if messagebox.askyesno(
            "跳过配置",
            "配置尚未完成。\n\n跳过后,某些功能可能无法使用(语音识别、会议总结)。\n确定要跳过吗？",
            parent=self,
        ):
            self._cancelled = True
            # Write marker anyway so wizard doesn't loop every launch
            mark_setup_complete()
            self.destroy()

    def _on_done(self):
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

    def _center(self, parent: tk.Toplevel):
        self.update_idletasks()
        px = parent.winfo_x() + (parent.winfo_width() - 420) // 2
        py = parent.winfo_y() + (parent.winfo_height() - 260) // 2
        self.geometry(f"420x260+{px}+{py}")

    def _build(self):
        tk.Label(
            self, text="需要安装 Ollama", font=("Segoe UI", 12, "bold"),
            bg=C["bg"], fg=C["warning"], pady=16,
        ).pack()

        msg = (
            "会议纪要功能需要 Ollama 提供本地 LLM 支持。\n\n"
            "请按以下步骤操作:\n"
            "  1. 点击下方按钮,前往 Ollama 官网下载安装程序\n"
            "  2. 安装完成后,Ollama 会自动启动\n"
            "  3. 回到本窗口,点击[我已安装,重新检测]"
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
            btn_frame, text="我已安装,重新检测",
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

    def _open_download(self):
        webbrowser.open(self._url)

    def _retry(self):
        self.retry_requested = True
        self.destroy()
