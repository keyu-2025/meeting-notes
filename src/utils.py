"""
Utility functions for Meeting Notes application.
"""

import os
import sys
import datetime
from pathlib import Path


def get_app_data_dir() -> Path:
    """
    Return the persistent app data directory.
    - Windows packaged exe: %APPDATA%\\MeetingNotes\\
    - Dev / other platforms: ~/.meeting-notes/
    """
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path.home()
    app_dir = base / "MeetingNotes"
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


def get_models_dir() -> Path:
    """
    Return the models cache directory.
    When running as a packaged exe, models are stored in AppData so they
    survive app updates. In dev mode, use the project-local models/ folder.
    """
    if getattr(sys, "frozen", False):
        base = get_app_data_dir() / "models"
    else:
        base = Path(__file__).parent.parent / "models"
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_output_dir() -> Path:
    """
    Return the output directory for saved meeting notes.
    When frozen, place output/ next to the exe so users can find it easily.
    In dev mode, use the project-local output/ folder.
    """
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent / "output"
    else:
        base = Path(__file__).parent.parent / "output"
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_setup_marker_path() -> Path:
    """Return the path to the first-run setup marker file."""
    return get_app_data_dir() / ".setup_complete"


def is_first_run() -> bool:
    """Return True if the app has never completed the setup wizard."""
    return not get_setup_marker_path().exists()


def mark_setup_complete() -> None:
    """Write the setup marker so the wizard is not shown again."""
    get_setup_marker_path().touch()


def format_timestamp(seconds: float) -> str:
    """Convert seconds to HH:MM:SS string."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def format_duration(seconds: float) -> str:
    """Format duration as human-readable string."""
    if seconds < 60:
        return f"{int(seconds)}秒"
    elif seconds < 3600:
        m = int(seconds // 60)
        s = int(seconds % 60)
        return f"{m}分{s}秒"
    else:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        return f"{h}小时{m}分钟"


def generate_filename(prefix: str = "会议纪要") -> str:
    """Generate a timestamped filename."""
    now = datetime.datetime.now()
    return f"{prefix}_{now.strftime('%Y-%m-%d_%H%M')}.txt"


def save_meeting_notes(
    transcript_lines: list[tuple[float, str]],
    summary: str,
    start_time: datetime.datetime,
    end_time: datetime.datetime,
) -> Path:
    """
    Save transcript and summary to a text file.

    Args:
        transcript_lines: List of (timestamp_seconds, text) tuples
        summary: LLM-generated meeting summary
        start_time: Recording start datetime
        end_time: Recording end datetime

    Returns:
        Path to the saved file
    """
    output_dir = get_output_dir()
    filename = generate_filename()
    filepath = output_dir / filename

    duration_secs = (end_time - start_time).total_seconds()

    lines = [
        f"会议纪要_{start_time.strftime('%Y-%m-%d_%H%M')}.txt",
        "---",
        f"日期: {start_time.strftime('%Y-%m-%d')}",
        f"时间: {start_time.strftime('%H:%M')} - {end_time.strftime('%H:%M')}",
        f"时长: {format_duration(duration_secs)}",
        "",
        "## 会议纪要",
        summary if summary else "（未生成会议纪要）",
        "",
        "## 完整转录",
    ]

    for ts, text in transcript_lines:
        lines.append(f"[{format_timestamp(ts)}] {text}")

    content = "\n".join(lines)
    filepath.write_text(content, encoding="utf-8")
    return filepath
