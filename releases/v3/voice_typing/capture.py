"""
音频采集模块：麦克风录音 + VAD 语音检测 + 分段。

- sounddevice 采集 16kHz / 16bit / mono PCM
- silero-vad ONNX 模型判断语音/静音
- 噪声门限过滤底噪
- 按静音点切分语音段，松键后统一返回

VAD 模型首次运行从 GitHub 下载（~2MB），之后缓存在 config 目录。
"""

import os
import queue
import threading
from pathlib import Path

import numpy as np
import sounddevice as sd

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "int16"
FRAME_SAMPLES = 512          # 每帧采样数（32ms，对齐 silero-vad）
FRAME_DURATION = FRAME_SAMPLES / SAMPLE_RATE  # 秒
MAX_RECORD_SECONDS = 60
MAX_FRAMES = int(MAX_RECORD_SECONDS / FRAME_DURATION)

# VAD 参数
VAD_SPEECH_THRESHOLD = 0.5        # >此值判为语音
VAD_SILENCE_THRESHOLD = 0.35      # <此值判为非语音（迟滞）
SILENCE_FRAMES_TO_SPLIT = 47      # 连续静音约 1.5s (32ms*47≈1.5s)
PRE_SPEECH_PADDING = 30           # 语音段前保留 30 帧 (~960ms)
POST_SPEECH_PADDING = 6           # 语音段后保留 6 帧 (~200ms)

# VAD 模型
VAD_MODEL_FILENAME = "silero_vad.onnx"
VAD_MODEL_URL = (
    "https://github.com/snakers4/silero-vad/raw/master/"
    "src/silero_vad/data/silero_vad.onnx"
)

# ---------------------------------------------------------------------------
# 模型下载
# ---------------------------------------------------------------------------

def _get_model_dir() -> Path:
    """获取模型存储目录。"""
    base = Path(os.environ.get("APPDATA", Path.home() / ".config"))
    model_dir = base / "voice-typing"
    model_dir.mkdir(parents=True, exist_ok=True)
    return model_dir


def _ensure_model() -> Path:
    """确保 VAD 模型存在，不存在则从 GitHub 下载。"""
    model_path = _get_model_dir() / VAD_MODEL_FILENAME
    if not model_path.exists():
        _download_model(model_path)
    return model_path


def _download_model(target: Path):
    """下载 silero-vad ONNX 模型。"""
    import urllib.request

    print(f"Downloading VAD model from {VAD_MODEL_URL} ...")
    try:
        urllib.request.urlretrieve(VAD_MODEL_URL, target)
        print(f"VAD model saved to {target}")
    except Exception as e:
        if target.exists():
            target.unlink()
        raise RuntimeError(f"VAD 模型下载失败: {e}") from e


# ---------------------------------------------------------------------------
# VAD 后处理
# ---------------------------------------------------------------------------

# 模块级 ONNX 会话 + 元数据（单例）
_vad_session = None
_vad_load_failed = False    # 加载失败标记
_vad_state_shape = None
_vad_sr_shape = None


def preload_vad():
    """预加载 VAD 模型（启动时调用）。"""
    processor = _VadProcessor(-40)
    processor._load_model()


class _VadProcessor:
    """离线 VAD：对完整音频帧序列做语音检测 + 切分。"""

    def __init__(self, noise_gate_threshold: float = -40.0):
        self.noise_threshold = noise_gate_threshold

    def _load_model(self):
        """延迟加载 ONNX 模型（模块级单例）。加载失败则标记 VAD 不可用。"""
        global _vad_session, _vad_load_failed, _vad_state_shape, _vad_sr_shape
        if _vad_session is not None:
            return True
        if _vad_load_failed:
            return False
        try:
            import onnxruntime as ort
            model_path = str(_ensure_model())
            _vad_session = ort.InferenceSession(model_path)

            for inp in _vad_session.get_inputs():
                shape = tuple(d if isinstance(d, int) else 1 for d in inp.shape)
                if inp.name == "state":
                    _vad_state_shape = shape
                elif inp.name == "sr":
                    _vad_sr_shape = shape
            return True
        except Exception:
            _vad_load_failed = True
            return False

    def _compute_rms(self, frame: np.ndarray) -> float:
        """计算一帧的 RMS 能量 (dBFS)。"""
        if len(frame) == 0:
            return -100.0
        rms = np.sqrt(np.mean(frame.astype(np.float64) ** 2))
        if rms < 1e-10:
            return -100.0
        return 20.0 * np.log10(rms / 32768.0)

    def _run_vad_frame(self, frame_16k: np.ndarray, in_state: np.ndarray | None):
        """单帧 VAD 推理（帧为 16kHz/512samples，内部降采样到 8kHz）。"""
        global _vad_session, _vad_state_shape, _vad_sr_shape

        # 降采样 16kHz→8kHz：每两个采样取一个
        frame_8k = frame_16k[::2].astype(np.float32) / 32768.0
        ort_input = {"input": frame_8k.reshape(1, -1)}

        if _vad_state_shape is not None and in_state is not None:
            ort_input["state"] = in_state
        elif _vad_state_shape is not None:
            ort_input["state"] = np.zeros(_vad_state_shape, dtype=np.float32)

        if _vad_sr_shape is not None:
            ort_input["sr"] = np.array(8000, dtype=np.int64)

        outputs = _vad_session.run(None, ort_input)
        prob = outputs[0].item()
        out_state = outputs[1] if len(outputs) > 1 else None
        return prob, out_state

    def process(self, frames: list[np.ndarray]) -> list[bytes]:
        """
        对帧序列做 VAD + 切分，返回语音段列表（每段为 PCM bytes）。
        VAD 不可用时回退为整段原始音频（讯飞自带 VAD 兜底）。
        """
        if not frames:
            return []

        if not self._load_model():
            # VAD 不可用 → 整段原始 PCM 直出
            return [np.concatenate(frames).tobytes()]

        # 逐帧计算 RMS + VAD（维护流式 state）
        n = len(frames)
        is_speech = [False] * n
        state = None

        for i, frame in enumerate(frames):
            rms_db = self._compute_rms(frame)
            if rms_db < self.noise_threshold:
                is_speech[i] = False
                # 即使跳过，也要推进 VAD state（否则状态错位）
                _, state = self._run_vad_frame(frame, state)
            else:
                prob, state = self._run_vad_frame(frame, state)
                is_speech[i] = prob > VAD_SPEECH_THRESHOLD

        # 用迟滞平滑：消除短暂切换
        smoothed = self._smooth_speech(is_speech)

        # 找语音段区间
        segments = self._find_segments(smoothed)

        # 逐段提取 + 硬限制：单段最长 10 秒，超了强制切分
        MAX_SEG_FRAMES = 312  # 10s / 32ms ≈ 312 帧
        OVERLAP = 31          # 段间重叠 ~1s

        result = []
        for start, end in segments:
            seg_len = end - start
            if seg_len <= MAX_SEG_FRAMES:
                pcm = np.concatenate(frames[start:end]).tobytes()
                result.append(pcm)
            else:
                # 长段强制切
                pos = start
                while pos < end:
                    cut = min(pos + MAX_SEG_FRAMES, end)
                    pcm = np.concatenate(frames[pos:cut]).tobytes()
                    result.append(pcm)
                    if cut >= end:
                        break
                    pos = cut - OVERLAP

        return result

    def _smooth_speech(self, is_speech: list[bool]) -> list[bool]:
        """迟滞 + 最短语音/静音过滤。"""
        n = len(is_speech)
        smoothed = list(is_speech)

        min_speech_frames = 3   # 最短 ~100ms 才算有效语音
        min_silence_frames = 94  # 静音 > 3 秒才切分 (94*32ms≈3s)

        run_start = 0
        for i in range(1, n + 1):
            if i < n and smoothed[i] == smoothed[run_start]:
                continue
            # run 结束于 i-1
            run_len = i - run_start
            if smoothed[run_start]:
                # 语音段：太短的改判为静音
                if run_len < min_speech_frames:
                    for j in range(run_start, i):
                        smoothed[j] = False
            else:
                # 静音段：太短的改判为语音
                if run_len < min_silence_frames:
                    for j in range(run_start, i):
                        smoothed[j] = True
            run_start = i

        return smoothed

    def _find_segments(self, is_speech: list[bool]) -> list[tuple[int, int]]:
        """找出所有语音段，加上前后 padding。"""
        n = len(is_speech)
        segments = []
        i = 0

        while i < n:
            if not is_speech[i]:
                i += 1
                continue
            start = i
            while i < n and is_speech[i]:
                i += 1
            end = i  # end 是 exclusive

            # 加 padding
            seg_start = max(0, start - PRE_SPEECH_PADDING)
            seg_end = min(n, end + POST_SPEECH_PADDING)

            # 合并相邻段（如果 padding 导致重叠）
            if segments and seg_start <= segments[-1][1]:
                segments[-1] = (segments[-1][0], seg_end)
            else:
                segments.append((seg_start, seg_end))

        return segments


# ---------------------------------------------------------------------------
# 录音
# ---------------------------------------------------------------------------

class CaptureSession:
    """
    一次 PTT 录音会话。

    用法：
        session = CaptureSession(noise_gate=-40)
        session.start()
        ...  # 用户按住键
        segments = session.stop()  # 返回 list[bytes]
    """

    def __init__(self, noise_gate_threshold: float = -40.0):
        self._noise_threshold = noise_gate_threshold
        self._frames: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._overflow = False

    def start(self):
        """开始录音。"""
        self._frames.clear()
        self._overflow = False
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype=DTYPE,
            blocksize=FRAME_SAMPLES,
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> list[bytes]:
        """
        停止录音，进行 VAD + 切分，返回语音段列表。

        返回: list[bytes]，每个元素是一段有效语音的 PCM 数据（16kHz 16bit mono）。
              返回空列表表示没有检测到有效语音。
        """
        if self._stream is None:
            return []

        self._stream.stop()
        self._stream.close()
        self._stream = None

        if not self._frames or self._overflow:
            return []

        processor = _VadProcessor(self._noise_threshold)
        return processor.process(self._frames)

    @property
    def frame_count(self) -> int:
        return len(self._frames)

    @property
    def duration(self) -> float:
        return len(self._frames) * FRAME_DURATION

    def _callback(self, indata: np.ndarray, frames: int, time_info, status):
        """sounddevice 回调（音频线程）。"""
        if status:
            if status.input_overflow:
                self._overflow = True
            return

        if len(self._frames) >= MAX_FRAMES:
            return

        frame = indata[:, 0].copy()
        self._frames.append(frame)