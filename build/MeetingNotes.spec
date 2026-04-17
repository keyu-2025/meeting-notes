# MeetingNotes.spec — PyInstaller spec file
#
# Build with:
#   python build/build.py          (recommended — does checks first)
# Or directly:
#   pyinstaller build/MeetingNotes.spec --distpath dist --workpath build_cache
#
# Notes:
#   - Uses onedir mode (folder with exe) for fastest cold-start.
#   - Models are NOT bundled; they are downloaded at first run via the
#     setup wizard to %APPDATA%\MeetingNotes\models\.
#   - Requires CPU-only torch to keep size ~300-400 MB instead of ~2 GB.

import sys
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

# ── Paths ─────────────────────────────────────────────────────────────────
# SPECPATH is the directory containing this .spec file (build/)
spec_dir    = Path(SPECPATH)
project_dir = spec_dir.parent
src_dir     = project_dir / "src"


# ── Hidden imports ─────────────────────────────────────────────────────────
# funasr / modelscope / torch have many lazily-loaded submodules.
hidden_imports = [
    # funasr internals
    "funasr",
    "funasr.auto.auto_model",
    "funasr.models.sense_voice.model",
    "funasr.models.fsmn_vad.model",
    "funasr.frontends.wav_frontend",
    "funasr.utils.load_utils",

    # torch (CPU-only)
    "torch",
    "torch.nn",
    "torch.nn.functional",
    "torchvision",
    "torchaudio",
    "torchaudio.transforms",

    # audio
    "sounddevice",
    "pyaudio",
    "scipy",
    "scipy.signal",
    "scipy.io",
    "scipy.io.wavfile",

    # modelscope & HuggingFace hub
    "modelscope",
    "modelscope.hub.snapshot_download",
    "huggingface_hub",
    "huggingface_hub.file_download",
    "safetensors",
    "safetensors.torch",

    # HTTP
    "requests",
    "urllib3",
    "charset_normalizer",
    "certifi",
    "idna",

    # standard lib
    "tkinter",
    "tkinter.ttk",
    "tkinter.messagebox",
    "tkinter.filedialog",
    "queue",
    "threading",
    "json",
    "re",
    "webbrowser",
    "subprocess",
]

# Collect all submodules for packages that scatter imports heavily
for pkg in ("funasr", "modelscope", "torchaudio"):
    hidden_imports += collect_submodules(pkg)


# ── Data files ────────────────────────────────────────────────────────────
datas = []

def _collect_pkg_data(pkg_name):
    d, b, h = collect_all(pkg_name)
    return d

# Collect data files (config YAMLs, tokenizers, etc.) for these packages
for pkg in ("funasr", "modelscope", "torchaudio", "certifi"):
    try:
        d, _, _ = collect_all(pkg)
        datas += d
    except Exception:
        pass

# Include the src package itself
datas += [
    (str(src_dir), "src"),
]

# ── Binaries ──────────────────────────────────────────────────────────────
binaries = []

# On Windows, sounddevice ships PortAudio as a bundled DLL
try:
    import sounddevice as _sd
    sd_path = Path(_sd.__file__).parent
    for dll in sd_path.glob("*.dll"):
        binaries.append((str(dll), "."))
except Exception:
    pass

# PyAudio DLL (portaudio)
try:
    import pyaudio as _pa
    pa_path = Path(_pa.__file__).parent
    for dll in pa_path.glob("*.dll"):
        binaries.append((str(dll), "."))
except Exception:
    pass


# ── Analysis ──────────────────────────────────────────────────────────────
a = Analysis(
    [str(project_dir / "src" / "main.py")],
    pathex=[str(project_dir)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude CUDA / GPU packages to save space
        "torch.cuda",
        "torch.backends.cuda",
        "torch.backends.cudnn",
        "torchvision.models",    # not needed
        # Exclude dev/test tools
        "pytest",
        "IPython",
        "matplotlib",
        "notebook",
        "jupyter",
        "PIL",                   # Pillow not required
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)


# ── PYZ archive ───────────────────────────────────────────────────────────
pyz = PYZ(a.pure, a.zipped_data, cipher=None)


# ── EXE ───────────────────────────────────────────────────────────────────
# icon path (place a .ico file at build/icon.ico to embed it)
_icon_path = str(spec_dir / "icon.ico")
_icon = _icon_path if Path(_icon_path).exists() else None

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,      # onedir mode: binaries go into COLLECT
    name="MeetingNotes",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,                   # compress binaries if UPX is installed
    upx_exclude=[
        "vcruntime140.dll",
        "python3*.dll",
        "_tkinter*.pyd",
    ],
    console=False,              # windowed; no console window
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon,
    version=str(spec_dir / "version_info.txt") if (spec_dir / "version_info.txt").exists() else None,
)


# ── COLLECT (onedir) ──────────────────────────────────────────────────────
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=["vcruntime140.dll", "python3*.dll", "_tkinter*.pyd"],
    name="MeetingNotes",        # output folder name: dist/MeetingNotes/
)
