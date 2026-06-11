#!/usr/bin/env python3
"""方案 B: SenseVoiceSmall via sherpa-onnx (纯 CPU)"""

import argparse
import os
import sys
import time
import wave

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MODEL_DIR = "./models/SenseVoiceSmall"
MODEL_FILE = "model.int8.onnx"
TOKENS_FILE = "tokens.txt"


def main():
    parser = argparse.ArgumentParser(description="SenseVoiceSmall via sherpa-onnx")
    parser.add_argument("--file", default="recording.wav", help="WAV file path")
    args = parser.parse_args()

    if not os.path.exists(args.file):
        print(f"[ERROR] file not found: {args.file}")
        sys.exit(1)

    model_path = os.path.join(MODEL_DIR, MODEL_FILE)
    tokens_path = os.path.join(MODEL_DIR, TOKENS_FILE)

    if not os.path.exists(model_path):
        print(f"[ERROR] model not found: {model_path}")
        sys.exit(1)
    if not os.path.exists(tokens_path):
        print(f"[ERROR] tokens not found: {tokens_path}")
        sys.exit(1)

    # 模型大小
    total_mb = (os.path.getsize(model_path) + os.path.getsize(tokens_path)) / (1024 * 1024)
    print(f"[SenseVoice] model size: {total_mb:.0f}MB")

    # 读取音频并转为 float32 数组
    with wave.open(args.file, "rb") as wf:
        sr = wf.getframerate()
        n_frames = wf.getnframes()
        dur = n_frames / sr
        print(f"[WAV] {wf.getnchannels()}ch, {sr}Hz, {dur:.1f}s")
        assert sr == 16000, "must be 16kHz"
        raw = wf.readframes(n_frames)

    # PCM int16 → float32 in [-1, 1]
    import numpy as np
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

    # 导入 & 创建识别器
    from sherpa_onnx import OfflineRecognizer

    t0 = time.perf_counter()
    recognizer = OfflineRecognizer.from_sense_voice(
        model=model_path,
        tokens=tokens_path,
        num_threads=4,
        sample_rate=16000,
        decoding_method="greedy_search",
        language="zh",
        use_itn=True,
    )
    t_load = time.perf_counter() - t0
    print(f"[SenseVoice] recognizer created in {t_load*1000:.0f}ms")

    # 识别
    print(f"[SenseVoice] recognizing...")
    t1 = time.perf_counter()
    stream = recognizer.create_stream()
    stream.accept_waveform(16000, samples)
    recognizer.decode_stream(stream)
    text = stream.result.text
    t_infer = time.perf_counter() - t1
    t_total = time.perf_counter() - t0

    print(f"\n[SenseVoice] ========== Timing ==========")
    print(f"[SenseVoice] model load:   {t_load*1000:6.0f}ms")
    print(f"[SenseVoice] inference:    {t_infer*1000:6.0f}ms")
    print(f"[SenseVoice] total:        {t_total*1000:6.0f}ms")
    print(f"[SenseVoice] ========== ====== ==========")
    print(f"[SenseVoice] result: {text}")

    return text


if __name__ == "__main__":
    main()
