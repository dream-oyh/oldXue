#!/usr/bin/env python3
"""测试 SenseVoice 模型加载 / 推理 / 释放 各阶段内存占用"""

import os, sys, time, wave, gc, numpy as np
import psutil

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MODEL_PATH = "./models/SenseVoiceSmall/model.int8.onnx"
TOKENS_PATH = "./models/SenseVoiceSmall/tokens.txt"
AUDIO_FILE = "recording.wav"

process = psutil.Process(os.getpid())


def mem_mb():
    """返回当前进程 RSS（MB）"""
    return process.memory_info().rss / (1024 * 1024)


def phase(label, sleep=0.3):
    """打印当前内存快照"""
    time.sleep(sleep)
    gc.collect()
    m = mem_mb()
    print(f"  [{label:20s}]  RSS = {m:7.1f} MB")
    return m


# ========== 测试流程 ==========

print("=" * 55)
print("SenseVoice 内存实测")
print("=" * 55)

# ---- Phase 0: 基线 ----
m0 = phase("baseline")
print()

# ---- Phase 1: 导入 sherpa_onnx ----
from sherpa_onnx import OfflineRecognizer
m1 = phase("after import", sleep=1)
print(f"  import 开销: +{m1-m0:.1f} MB\n")

# ---- Phase 2: 加载模型 ----
print("  loading model ...")
t0 = time.perf_counter()
recognizer = OfflineRecognizer.from_sense_voice(
    model=MODEL_PATH,
    tokens=TOKENS_PATH,
    num_threads=4,
    language="zh",
    use_itn=True,
)
t_load = time.perf_counter() - t0
m2 = phase("after load", sleep=2)
print(f"  模型加载: {t_load*1000:.0f}ms, 内存增长: +{m2-m1:.1f} MB\n")

# ---- Phase 3: 读取音频 ----
with wave.open(AUDIO_FILE, "rb") as wf:
    raw = wf.readframes(wf.getnframes())
audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
m3 = phase("after read audio")
print(f"  音频数据: {len(audio)} samples, 内存增长: +{m3-m2:.1f} MB\n")

# ---- Phase 4: 推理 ----
print("  running inference ...")
t0 = time.perf_counter()
stream = recognizer.create_stream()
stream.accept_waveform(16000, audio)
recognizer.decode_stream(stream)
text = stream.result.text
t_infer = time.perf_counter() - t0
m4 = phase("after inference")
print(f"  推理: {t_infer*1000:.0f}ms, 内存增长: +{m4-m3:.1f} MB")
print(f"  结果: {text}\n")

# ---- Phase 5: 释放 stream ----
del stream, audio, raw
gc.collect()
m5 = phase("after del stream+audio")
print(f"  释放后: {m5-m2:.1f} MB (相对模型加载后)\n")

# ---- Phase 6: 删除 recognizer (释放模型) ----
print("  deleting recognizer ...")
del recognizer
gc.collect()
time.sleep(2)
m6 = phase("after del recognizer")
print(f"  删除模型后: {m6-m0:.1f} MB (相对基线)\n")

# ---- Phase 7: 连续推理 5 次，看内存是否线性增长 ----
print("-" * 55)
print("连续推理 5 次 (不重建 recognizer)")
print("-" * 55)

# 重新读取音频（上面被 del 了）
with wave.open(AUDIO_FILE, "rb") as wf:
    raw2 = wf.readframes(wf.getnframes())
audio2 = np.frombuffer(raw2, dtype=np.int16).astype(np.float32) / 32768.0

# 重新加载
recognizer2 = OfflineRecognizer.from_sense_voice(
    model=MODEL_PATH, tokens=TOKENS_PATH,
    num_threads=4, language="zh", use_itn=True,
)
time.sleep(2)
gc.collect()
m_base = mem_mb()
print(f"  加载后基线: {m_base:.1f} MB\n")

for i in range(5):
    stream = recognizer2.create_stream()
    stream.accept_waveform(16000, audio2)
    recognizer2.decode_stream(stream)
    _ = stream.result.text
    del stream
    m = mem_mb()
    print(f"  第{i+1}次推理后: {m:.1f} MB  (增量 +{m-m_base:.1f} MB)")
    time.sleep(0.2)

gc.collect()
time.sleep(1)
m_final = mem_mb()
print(f"\n  5次后 gc: {m_final:.1f} MB  (总增长 +{m_final-m_base:.1f} MB)")

# ---- 总结 ----
print()
print("=" * 55)
print("总结")
print("=" * 55)
print(f"  基线:               {m0:.0f} MB")
print(f"  模型加载后:          {m2:.0f} MB  (+{m2-m0:.0f} MB)")
print(f"  删除模型后:          {m6:.0f} MB  (回收 {m2-m6:.0f} MB)")
print(f"  模型固定占用:        {m2-m1:.0f} MB")
print(f"  连续推理内存是否增长: {'是 ⚠️' if m_final-m_base > 10 else '否 ✅'}")
