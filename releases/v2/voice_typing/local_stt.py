"""
本地 ASR 模块 — SenseVoiceSmall via sherpa-onnx。

模型：asr-test/models/SenseVoiceSmall/model.int8.onnx (~229MB, INT8 量化)
引擎：sherpa-onnx OfflineRecognizer
"""

import os
import sys
import time
from pathlib import Path

import numpy as np

# 模型路径（相对于项目根目录）
_MODEL_DIR = Path(__file__).parent.parent / "asr-test" / "models" / "SenseVoiceSmall"
_MODEL_FILE = "model.int8.onnx"
_TOKENS_FILE = "tokens.txt"

# 模块级单例
_recognizer = None
_load_error = ""  # 失败原因


def _get_model_dir() -> Path:
    """搜索模型目录，返回第一个找到的路径。"""
    tried = []

    # 1. 环境变量
    env_path = os.environ.get("VOICE_TYPING_MODEL_DIR", "")
    if env_path:
        p = Path(env_path)
        tried.append(str(p))
        if (p / _MODEL_FILE).exists():
            return p

    # 2. 打包后：sys._MEIPASS 解压目录
    if getattr(sys, "frozen", False):
        for base in [Path(sys._MEIPASS), Path(sys.executable).parent]:
            p = base / "SenseVoiceSmall"
            tried.append(str(p))
            if (p / _MODEL_FILE).exists():
                return p

    # 3. 开发模式：项目目录
    p = Path(__file__).parent.parent / "asr-test" / "models" / "SenseVoiceSmall"
    tried.append(str(p))
    if (p / _MODEL_FILE).exists():
        return p

    # 4. 默认路径
    tried.append(str(_MODEL_DIR))

    lines = ["SenseVoice 模型未找到。"]
    lines.append(f"  运行模式: {'打包' if getattr(sys, 'frozen', False) else '开发'}")
    if getattr(sys, "frozen", False):
        lines.append(f"  sys._MEIPASS: {getattr(sys, '_MEIPASS', 'N/A')}")
        lines.append(f"  exe 目录: {Path(sys.executable).parent}")
        mp = Path(sys._MEIPASS)
        if mp.exists():
            items = list(mp.glob("*"))
            lines.append(f"  _MEIPASS 顶层 ({len(items)} 项):")
            for c in sorted(items):
                tag = "[D]" if c.is_dir() else f"[F {c.stat().st_size//1024}KB]"
                lines.append(f"    {tag} {c.name}")
    lines.append("搜索路径:")
    for t in tried:
        p = Path(t)
        ok = "存在" if p.exists() else "不存在"
        lines.append(f"  [{ok}] {t}")
        if p.exists() and p.is_dir():
            for f in sorted(p.iterdir()):
                lines.append(f"      {f.name} ({f.stat().st_size//1024}KB)")
    raise FileNotFoundError("\n".join(lines))


def _load_recognizer():
    """延迟加载识别器（模块级单例）。"""
    global _recognizer, _load_error
    if _recognizer is not None:
        return True
    if _load_error:
        return False

    try:
        from sherpa_onnx import OfflineRecognizer

        model_dir = _get_model_dir()
        model_path = model_dir / _MODEL_FILE
        tokens_path = model_dir / _TOKENS_FILE

        if not model_path.exists():
            raise FileNotFoundError(f"模型文件不存在: {model_path}")

        _recognizer = OfflineRecognizer.from_sense_voice(
            model=str(model_path),
            tokens=str(tokens_path),
            num_threads=4,
            language="zh",
            use_itn=True,
        )
        return True
    except Exception as e:
        _load_error = str(e)
        return False


def preload():
    """后台预加载模型（启动时调用，不阻塞 UI）。"""
    import threading
    t = threading.Thread(target=_load_recognizer, daemon=True)
    t.start()
    return t


def is_available() -> bool:
    """本地模型是否可用。"""
    global _load_error
    result = _load_recognizer()
    if not result and _load_error:
        # 如果上次失败了，重置并重试一次（模型可能已被移回）
        _load_error = ""
        return _load_recognizer()
    return result


def get_load_error() -> str:
    """获取模型加载失败原因。"""
    return _load_error


def transcribe(pcm_bytes: bytes) -> str:
    """
    使用本地 SenseVoiceSmall 模型转写 PCM 音频。

    pcm_bytes: 16kHz / 16bit / mono 原始 PCM
    返回: 识别文本（可能为空字符串）
    """
    if not _load_recognizer():
        raise RuntimeError(_load_error or "本地模型加载失败")

    samples = np.frombuffer(pcm_bytes, dtype=np.int16)

    stream = _recognizer.create_stream()
    stream.accept_waveform(16000, samples)
    _recognizer.decode_stream(stream)

    text = stream.result.text.strip()
    return text
