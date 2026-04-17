import os
"""
build/build.py — Automated PyInstaller build script for Meeting Notes.

Run this on Windows from the project root:
    python build/build.py

Prerequisites (install once):
    pip install pyinstaller
    pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
    pip install -r requirements.txt

The script will:
  1. Verify the Python environment.
  2. Check that torch is CPU-only (warn if CUDA version detected).
  3. Run PyInstaller using build/MeetingNotes.spec.
  4. Copy the output to dist/MeetingNotes/.
  5. Print next steps for Inno Setup packaging.
"""

import subprocess
import sys
import shutil
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).parent          # build/
PROJECT_ROOT = SCRIPT_DIR.parent              # project root
SPEC_FILE    = SCRIPT_DIR / "MeetingNotes.spec"
DIST_DIR     = PROJECT_ROOT / "dist"
BUILD_DIR    = PROJECT_ROOT / "build_cache"   # PyInstaller's workpath


def main():
    print("=" * 60)
    print("  Meeting Notes — Windows Build Script")
    print("=" * 60)

    _check_platform()
    _check_pyinstaller()
    _check_torch_cpu()
    _run_pyinstaller()
    _post_build_summary()


# ── Checks ────────────────────────────────────────────────────────────────

def _check_platform():
    if sys.platform != "win32":
        print("\n[警告] 此脚本设计在 Windows 上运行以生成 .exe 文件。")
        print("  在其他平台构建将生成对应平台的可执行文件，但无法在 Windows 上运行。")
        resp = "y" if os.environ.get("CI") else input("  继续？[y/N] ").strip().lower()
        if resp != "y":
            sys.exit(0)
    else:
        print("[✓] 平台: Windows")


def _check_pyinstaller():
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--version"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print("\n[✗] 未找到 PyInstaller。请先安装：")
        print("    pip install pyinstaller")
        sys.exit(1)
    version = result.stdout.strip()
    print(f"[✓] PyInstaller: {version}")


def _check_torch_cpu():
    """Warn if CUDA-enabled torch is installed (greatly inflates exe size)."""
    try:
        import torch
        if torch.cuda.is_available():
            print("\n[警告] 检测到 CUDA 版 PyTorch。")
            print("  建议改用 CPU-only 版本以大幅减小打包体积（约 200 MB vs 2 GB）：")
            print("    pip uninstall torch torchaudio -y")
            print("    pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu")
            resp = input("  仍然继续使用 CUDA 版本打包？[y/N] ").strip().lower()
            if resp != "y":
                sys.exit(0)
        else:
            # Check the build tag to confirm CPU-only wheel
            version_info = torch.__version__
            print(f"[✓] PyTorch: {version_info} (CPU-only)")
    except ImportError:
        print("\n[✗] 未找到 PyTorch。请安装：")
        print("    pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu")
        sys.exit(1)


# ── Build ─────────────────────────────────────────────────────────────────

def _run_pyinstaller():
    if not SPEC_FILE.exists():
        print(f"\n[✗] 未找到 spec 文件: {SPEC_FILE}")
        sys.exit(1)

    print(f"\n[→] 开始 PyInstaller 构建...")
    print(f"    spec: {SPEC_FILE}")
    print(f"    dist: {DIST_DIR}")
    print(f"    work: {BUILD_DIR}\n")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        str(SPEC_FILE),
        "--distpath", str(DIST_DIR),
        "--workpath", str(BUILD_DIR),
        "--noconfirm",           # overwrite without asking
        "--clean",               # clean cache before build
    ]

    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    if result.returncode != 0:
        print("\n[✗] PyInstaller 构建失败，请查看上方错误信息。")
        sys.exit(result.returncode)

    print("\n[✓] PyInstaller 构建成功。")


# ── Post-build ────────────────────────────────────────────────────────────

def _post_build_summary():
    exe_path = DIST_DIR / "MeetingNotes" / "MeetingNotes.exe"
    onefile_path = DIST_DIR / "MeetingNotes.exe"

    found = None
    if exe_path.exists():
        found = exe_path
        size_mb = sum(
            f.stat().st_size for f in (DIST_DIR / "MeetingNotes").rglob("*") if f.is_file()
        ) / 1024 / 1024
        print(f"\n[✓] 输出目录: {DIST_DIR / 'MeetingNotes'}")
        print(f"    总大小: {size_mb:.0f} MB")
    elif onefile_path.exists():
        found = onefile_path
        size_mb = onefile_path.stat().st_size / 1024 / 1024
        print(f"\n[✓] 输出文件: {onefile_path}")
        print(f"    大小: {size_mb:.0f} MB")
    else:
        print("\n[?] 未在预期位置找到 exe，请检查 dist/ 目录。")

    iss_file = SCRIPT_DIR / "installer.iss"
    print("\n" + "=" * 60)
    print("  后续步骤（可选）：打包为 Windows 安装程序")
    print("=" * 60)
    print(f"  1. 安装 Inno Setup: https://jrsoftware.org/isdl.php")
    print(f"  2. 用 Inno Setup 打开: {iss_file}")
    print(f"  3. 点击 Build → Compile 生成安装程序 (.exe installer)")
    print(f"\n  或使用命令行：")
    print(f"    iscc build\\installer.iss")
    print()


if __name__ == "__main__":
    main()
