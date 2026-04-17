# Meeting Notes - 本地会议纪要工具

## 项目概述
Windows 本地端会议纪要工具。截持本地麦克风和系统音频流，实时转录，自动生成会议纪要。

## 核心需求
1. **音频捕获**: 同时捕获麦克风输入 + 系统音频输出（loopback）
2. **实时转录**: 使用 SenseVoice Small 模型（FunAudioLLM/SenseVoiceSmall）
3. **会议总结**: 使用本地 LLM (Ollama + Qwen 2.5) 生成会议纪要
4. **结果保存**: 保存为本地文本文件（含转录全文 + 纪要摘要）
5. **简单 GUI**: 桌面窗口界面

## 技术约束
- **仅 CPU 运行**，不依赖 GPU
- **Windows 平台**（Windows 10/11）
- **全部本地运行**，无需联网
- **自动语言识别**（SenseVoice 原生支持 50+ 语言）

## 技术栈
- **语言**: Python 3.11+
- **音频捕获**: PyAudio + sounddevice（系统音频 loopback 用 WASAPI）
- **语音转录**: FunASR + SenseVoice Small（funasr 库）
  - 模型: FunAudioLLM/SenseVoiceSmall (HuggingFace)
  - 非自回归架构，10秒音频仅需70ms（CPU）
  - 支持 ASR + 语言识别 + 情绪识别 + 声音事件检测
- **会议总结**: Ollama（本地运行 Qwen 2.5 7B 或更小模型）
- **GUI**: tkinter（Python 内置，无需额外依赖）
- **打包**: PyInstaller → Windows exe

## 功能设计

### GUI 界面
- 顶部: 音频设备选择（麦克风 + 系统音频）
- 中部: 实时转录文字显示区域（滚动文本框）
- 底部: 开始/停止录制按钮、生成纪要按钮、保存按钮
- 状态栏: 录制时长、模型状态

### 工作流程
1. 用户选择音频输入设备（麦克风、系统音频、或两者）
2. 点击"开始录制" → 实时捕获音频 → 实时转录显示
3. 点击"停止录制" → 停止捕获
4. 点击"生成纪要" → 调用 Ollama LLM 总结转录文本
5. 点击"保存" → 保存转录文本 + 纪要到本地文件

### 文件保存格式
```
会议纪要_2026-04-17_1430.txt
---
日期: 2026-04-17
时间: 14:30 - 15:45
时长: 1小时15分钟

## 会议纪要
[LLM 生成的结构化纪要]

## 完整转录
[时间戳] 文字内容
[时间戳] 文字内容
...
```

## 项目结构
```
meeting-notes/
├── CLAUDE.md           # 本文件
├── requirements.txt    # Python 依赖
├── setup.py           # 安装配置
├── src/
│   ├── __init__.py
│   ├── main.py        # 入口 + GUI
│   ├── audio.py       # 音频捕获模块
│   ├── transcriber.py # SenseVoice 转录模块
│   ├── summarizer.py  # Ollama LLM 总结模块
│   └── utils.py       # 工具函数
├── models/            # 本地模型缓存目录
├── output/            # 会议纪要输出目录
└── README.md          # 用户说明
```

## 注意事项
- Windows 系统音频 loopback 需要 WASAPI 支持
- SenseVoice 用 funasr 库加载，首次运行会自动下载模型
- Ollama 需要用户预先安装并拉取模型（README 中说明）
- GUI 要简洁美观，不要太丑，用 ttk 主题美化
- 实时转录要流式显示，不能等整段音频结束才显示
- 音频分段处理：每 5-10 秒一个片段送入模型
