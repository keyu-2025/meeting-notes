# 会议纪要

Windows 本地端会议纪要工具。实时捕获麦克风 + 系统音频，使用 SenseVoice 实时转录，使用本地 Ollama LLM 生成结构化会议纪要。

**全部本地运行，无需联网，支持中文/英文/50+ 语言自动识别。**

---

## 目录

- [用户指南](#用户指南终端用户)：下载安装包，双击运行
- [开发者指南](#开发者指南从源码构建)：从源码构建和打包

---

## 用户指南（终端用户）

> 无需安装 Python，无需命令行操作。

### 第一步：下载安装程序

从 [Releases 页面](https://github.com/your-repo/meeting-notes/releases) 下载最新版 `MeetingNotes_Setup_x.x.x.exe`。

### 第二步：安装

双击安装程序，按提示完成安装（默认安装到 `C:\Program Files\MeetingNotes`）。

### 第三步：首次运行（自动配置）

双击桌面快捷方式或开始菜单中的"会议纪要"图标启动应用。

**首次启动时**，会弹出配置向导，自动完成以下操作：

| 步骤 | 内容 | 大小 | 时间 |
|------|------|------|------|
| ① 语音识别模型 | 下载 SenseVoice Small | ~300 MB | ~2 min |
| ② Ollama 服务 | 检测安装状态，若未安装则引导下载 | — | 手动 |
| ③ 会议总结模型 | 自动拉取 Qwen 2.5:3b | ~2 GB | ~5 min |

> **关于 Ollama**：Ollama 是一个独立的本地 AI 运行时，需要单独安装。
> 向导会在浏览器中打开 [Ollama 下载页面](https://ollama.com/download/windows)。
> 安装完成后回到向导点击"我已安装，重新检测"即可。

配置完成后，向导不会再次出现。

### 第四步：使用

配置完成后，主界面打开：

```
┌─────────────────────────────────────────────┐
│  会议纪要                          状态信息  │
├─────────────────────────────────────────────┤
│  麦克风:    [下拉选择音频输入设备]            │
│  系统音频:  [下拉选择 WASAPI 环回设备]        │
│  LLM 模型:  [下拉选择]    Ollama状态          │
├─────────────────────────────────────────────┤
│  [ 实时转录 ] [ 会议纪要 ]                   │
│                                             │
│  转录内容实时显示区域...                     │
│                                             │
├─────────────────────────────────────────────┤
│  00:00:00    [开始录制] [生成纪要] [保存]    │
└─────────────────────────────────────────────┘
```

1. **选择音频设备**：麦克风捕获你的声音；系统音频捕获电脑播放的声音（如视频会议）
2. **点击"开始录制"** → 实时转录内容显示在"实时转录"标签页
3. **点击"停止录制"** → 结束捕获
4. **点击"生成纪要"** → Ollama 分析转录，生成结构化纪要（在"会议纪要"标签页）
5. **点击"保存"** → 保存到 `<安装目录>\output\` 目录

### 系统要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Windows 10 1809+ / Windows 11 |
| 内存 | 8 GB+（运行 Qwen 2.5:3b 最低要求） |
| 磁盘空间 | 约 3 GB（程序 ~400 MB + 模型 ~2.3 GB） |
| 网络 | 首次运行时需要联网下载模型，之后完全离线 |

### 常见问题

**Q: 首次启动很慢？**
A: 正在后台加载 SenseVoice 模型（约 300 MB），加载完成后"开始录制"按钮会变为可用。

**Q: 没有系统音频设备可选？**
A: 打开 Windows 声音设置 → 录制 → 右键空白区域勾选"显示禁用的设备" → 启用"立体声混音"。

**Q: Ollama 显示连接失败？**
A: Ollama 安装后有时需要手动启动。打开命令提示符运行 `ollama serve`，或重启电脑。

**Q: 生成纪要时提示"无法连接 Ollama"？**
A: 同上，确认 `ollama serve` 正在运行，或在任务栏找到 Ollama 图标确认其状态。

**Q: 转录内容乱码/识别不准确？**
A: SenseVoice 对 16kHz 输入效果最好。确认麦克风距离适中、环境不过于嘈杂。

---

## 开发者指南（从源码构建）

### 环境准备

- Python 3.11+（推荐用 [pyenv-win](https://github.com/pyenv-win/pyenv-win) 管理）
- Git
- Windows 10/11（用于打包 exe；开发可在 Linux/macOS 进行）

### 克隆并安装依赖

```bash
git clone https://github.com/your-repo/meeting-notes.git
cd meeting-notes

# 安装 CPU-only PyTorch（比 CUDA 版本小 ~1.8 GB，打包体积更小）
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu

# 安装其余依赖
pip install -r requirements.txt
```

> **重要**：必须先安装 CPU-only torch，再安装 requirements.txt。
> 否则 `pip install -r requirements.txt` 会拉取默认的 CUDA torch（~2 GB）。

### 运行（开发模式）

```bash
python -m src.main
```

首次运行会弹出配置向导（与打包版本相同逻辑）。向导完成后重新运行即可正常使用。

如需跳过向导直接测试主界面，删除标记文件：
```bash
# Windows
del "%APPDATA%\MeetingNotes\.setup_complete"
```

### 项目结构

```
meeting-notes/
├── CLAUDE.md               # 项目规范（AI 辅助开发指引）
├── requirements.txt        # Python 依赖
├── README.md               # 本文件
├── src/
│   ├── __init__.py
│   ├── main.py             # 入口 + GUI（tkinter）
│   ├── audio.py            # 音频捕获（麦克风 + WASAPI loopback）
│   ├── transcriber.py      # SenseVoice 实时转录
│   ├── summarizer.py       # Ollama LLM 会议总结
│   ├── setup_wizard.py     # 首次运行配置向导
│   └── utils.py            # 工具函数、文件保存、路径管理
├── build/
│   ├── build.py            # 自动化打包脚本
│   ├── MeetingNotes.spec   # PyInstaller 配置文件
│   ├── installer.iss       # Inno Setup 安装程序脚本
│   └── icon.ico            # （可选）应用图标
├── models/                 # 开发模式下的模型缓存（.gitignore）
└── output/                 # 会议纪要输出目录（.gitignore）
```

### 打包为 Windows exe

#### 1. 安装打包工具

```bash
pip install pyinstaller
```

#### 2. 运行打包脚本

```bash
# 在 Windows 上，从项目根目录运行
python build/build.py
```

脚本会自动：
- 检查 Python 环境和 PyInstaller 版本
- 警告若检测到 CUDA 版 torch（建议换 CPU-only 版）
- 运行 PyInstaller，输出到 `dist/MeetingNotes/`
- 打印后续打包为安装程序的指引

#### 3. 制作 Windows 安装程序（可选）

安装 [Inno Setup 6](https://jrsoftware.org/isdl.php)，然后：

```bash
# 命令行编译
iscc build\installer.iss

# 或在 Inno Setup IDE 中打开 build\installer.iss，点击 Build → Compile
```

输出文件：`dist\MeetingNotes_Setup_1.0.0.exe`

#### 打包体积参考

| torch 版本 | 预期打包大小 |
|------------|-------------|
| CPU-only   | ~350–450 MB |
| CUDA（默认）| ~2–2.5 GB  |

> 模型文件（SenseVoice ~300 MB、Qwen 2.5:3b ~2 GB）不打包进 exe，
> 由首次运行向导自动下载到 `%APPDATA%\MeetingNotes\models\`。

### 修改 Ollama 默认模型

编辑 `src/summarizer.py`：

```python
DEFAULT_MODEL = "qwen2.5:7b"   # 改为你想用的模型名
```

编辑 `src/setup_wizard.py`：

```python
PREFERRED_MODELS = ["qwen2.5:3b", "qwen2.5:7b"]  # 按优先级排列，最小的放最前
```

### 保存文件格式

```
output/会议纪要_2026-04-17_1430.txt
---
日期: 2026-04-17
时间: 14:30 - 15:45
时长: 1小时15分钟

## 会议纪要
[LLM 生成的结构化纪要]

## 完整转录
[00:00:05] 大家好，今天我们...
[00:00:12] 主要议题是...
```
