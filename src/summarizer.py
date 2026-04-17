"""
Meeting summarizer module using Ollama (local LLM).

Calls the Ollama HTTP API at http://localhost:11434 to generate
structured meeting notes from a transcript.

Recommended model: qwen2.5:7b (or qwen2.5:3b for lower RAM)
"""

import json
import re
import requests
from typing import Callable, Optional, Iterator


OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5:7b"

SYSTEM_PROMPT = """你是一个专业的会议助手。请根据提供的会议转录文本，生成结构化的会议纪要。

会议纪要应包含：
1. **会议主题**：简要描述本次会议的核心议题
2. **主要讨论内容**：按议题列出关键讨论点
3. **重要决策**：列出会议中做出的决定
4. **待办事项**：列出需要跟进的行动项（如有）
5. **其他重要信息**：其他值得记录的内容

请用中文输出，语言简洁专业。如果转录内容不足以提取某个部分，请注明"无"。"""


def check_ollama_available(base_url: str = OLLAMA_BASE_URL) -> tuple[bool, str]:
    """Check if Ollama server is running. Returns (ok, message)."""
    try:
        resp = requests.get(f"{base_url}/api/tags", timeout=5)
        resp.raise_for_status()
        return True, "Ollama 服务正常"
    except requests.exceptions.ConnectionError:
        return False, "无法连接 Ollama（请确认已启动 ollama serve）"
    except Exception as e:
        return False, f"Ollama 错误: {e}"


def list_ollama_models(base_url: str = OLLAMA_BASE_URL) -> list[str]:
    """Return list of locally available Ollama model names."""
    try:
        resp = requests.get(f"{base_url}/api/tags", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def summarize(
    transcript: str,
    model: str = DEFAULT_MODEL,
    base_url: str = OLLAMA_BASE_URL,
    on_token: Optional[Callable[[str], None]] = None,
) -> str:
    """
    Generate meeting notes from transcript text.

    Args:
        transcript: Full transcript text
        model: Ollama model name
        base_url: Ollama server URL
        on_token: Optional streaming callback called with each token string

    Returns:
        Complete summary text
    """
    if not transcript.strip():
        return "（转录内容为空，无法生成纪要）"

    prompt = f"以下是会议转录内容：\n\n{transcript}\n\n请生成会议纪要："

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "stream": on_token is not None,
        "options": {
            "temperature": 0.3,
            "num_predict": 2048,
        },
    }

    try:
        if on_token is not None:
            return _summarize_streaming(payload, base_url, on_token)
        else:
            return _summarize_blocking(payload, base_url)
    except requests.exceptions.ConnectionError:
        return "错误：无法连接 Ollama 服务。请确认已运行 `ollama serve`。"
    except Exception as e:
        return f"生成纪要失败: {e}"


def _summarize_blocking(payload: dict, base_url: str) -> str:
    resp = requests.post(
        f"{base_url}/api/chat",
        json=payload,
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("message", {}).get("content", "").strip()


def _summarize_streaming(
    payload: dict,
    base_url: str,
    on_token: Callable[[str], None],
) -> str:
    collected: list[str] = []
    with requests.post(
        f"{base_url}/api/chat",
        json=payload,
        stream=True,
        timeout=120,
    ) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line:
                continue
            try:
                chunk = json.loads(line)
                token = chunk.get("message", {}).get("content", "")
                if token:
                    collected.append(token)
                    on_token(token)
                if chunk.get("done"):
                    break
            except json.JSONDecodeError:
                continue
    return "".join(collected).strip()
