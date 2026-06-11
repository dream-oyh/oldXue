#!/usr/bin/env python3
"""
讯飞语音听写 (iAT) API 测试脚本

--- 使用方式 ---

1. 用麦克风录音测试：
   python test_asr.py --app-id xxx --api-key xxx --api-secret xxx

2. 用 WAV 文件测试（16kHz / 16bit / mono）：
   python test_asr.py --app-id xxx --api-key xxx --api-secret xxx --file audio.wav

3. 先保存凭据到 config.json，下次免输：
   python test_asr.py --app-id xxx --api-key xxx --api-secret xxx --save-config
   python test_asr.py  # 自动读取 config.json
"""

import argparse
import asyncio
import base64
import hashlib
import hmac
import json
import os
import sys
import time
import wave
from datetime import datetime, timezone
from pathlib import Path

# Windows 终端默认 GBK，强制 UTF-8 输出避免 emoji 乱码报错
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

IAT_URL = "wss://ws-api.xfyun.cn/v2/iat"
HOST = "ws-api.xfyun.cn"
AUDIO_RATE = 16000        # 采样率
AUDIO_BITS = 16           # 位深度
AUDIO_CHANNELS = 1        # 单声道
FRAME_SIZE = 8000         # 每帧字节数（0.25s 音频）
SEND_INTERVAL = 0.04      # 发送间隔（秒）
RECORD_SECONDS = 5        # 麦克风录音时长

CONFIG_PATH = Path(os.environ.get("APPDATA", Path.home() / ".config")) / "voice-typing" / "config.json"

# ---------------------------------------------------------------------------
# 鉴权：HMAC-SHA256 签名
# ---------------------------------------------------------------------------

def build_auth_url(app_id: str, api_key: str, api_secret: str) -> str:
    """构造带鉴权签名的 WebSocket URL。"""
    # RFC 1123 时间（UTC）
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%a, %d %b %Y %H:%M:%S GMT")

    # 签名原文
    signature_origin = (
        f"host: {HOST}\n"
        f"date: {date_str}\n"
        f"GET /v2/iat HTTP/1.1"
    )

    # HMAC-SHA256 → base64
    signature_raw = hmac.new(
        api_secret.encode("utf-8"),
        signature_origin.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    signature = base64.b64encode(signature_raw).decode("utf-8")

    # authorization = base64(api_key="xxx", algorithm="hmac-sha256", ...)
    auth_raw = (
        f'api_key="{api_key}",'
        f'algorithm="hmac-sha256",'
        f'headers="host date request-line",'
        f'signature="{signature}"'
    )
    authorization = base64.b64encode(auth_raw.encode("utf-8")).decode("utf-8")

    # 拼接 URL（日期中的空格/逗号由 urlencode 处理）
    from urllib.parse import urlencode
    params = urlencode({
        "authorization": authorization,
        "date": date_str,
        "host": HOST,
    })
    return f"{IAT_URL}?{params}"


# ---------------------------------------------------------------------------
# WebSocket 帧构造
# ---------------------------------------------------------------------------

def build_first_frame(app_id: str, audio_chunk: bytes) -> str:
    """首帧：status=0，包含 common + business + data。"""
    payload = {
        "common": {"app_id": app_id},
        "business": {
            "domain": "iat",
            "language": "zh_cn",
            "accent": "mandarin",
            "ptt": 1,          # 开启标点符号
            "vad_eos": 10000,
            "nunum": 1,        # 数字转阿拉伯数字
        },
        "data": {
            "status": 0,
            "format": "audio/L16;rate=16000",
            "encoding": "raw",
            "audio": base64.b64encode(audio_chunk).decode("utf-8"),
        },
    }
    return json.dumps(payload, ensure_ascii=False)


def build_continue_frame(audio_chunk: bytes) -> str:
    """中间帧：status=1，仅 data。"""
    payload = {
        "data": {
            "status": 1,
            "format": "audio/L16;rate=16000",
            "encoding": "raw",
            "audio": base64.b64encode(audio_chunk).decode("utf-8"),
        },
    }
    return json.dumps(payload, ensure_ascii=False)


def build_last_frame(audio_chunk: bytes = b"") -> str:
    """尾帧：status=2，结束标志。"""
    payload = {
        "data": {
            "status": 2,
            "format": "audio/L16;rate=16000",
            "encoding": "raw",
            "audio": base64.b64encode(audio_chunk).decode("utf-8") if audio_chunk else "",
        },
    }
    return json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 音频读取 / 录音
# ---------------------------------------------------------------------------

def read_wav_frames(filepath: str) -> bytes:
    """读取 WAV 文件的原始 PCM 数据。"""
    with wave.open(filepath, "rb") as wf:
        print(f"[WAV] {wf.getnchannels()}ch, {wf.getframerate()}Hz, "
              f"{wf.getsampwidth()}byte/sample, {wf.getnframes()} frames")
        if wf.getframerate() != AUDIO_RATE:
            print(f"[WARN] sample rate != {AUDIO_RATE}Hz, convert: ffmpeg -i in.wav -ar 16000 -ac 1 out.wav")
        if wf.getnchannels() != AUDIO_CHANNELS:
            print(f"[WARN] not mono, please convert")
        return wf.readframes(wf.getnframes())


def record_mic(duration: float = RECORD_SECONDS) -> bytes:
    """从麦克风录音，返回原始 PCM 字节。"""
    try:
        import sounddevice as sd
    except ImportError:
        print("[ERROR] pip install sounddevice")
        sys.exit(1)

    print(f"[REC] recording {duration}s ... speak now")
    audio = sd.rec(
        int(duration * AUDIO_RATE),
        samplerate=AUDIO_RATE,
        channels=AUDIO_CHANNELS,
        dtype="int16",
    )
    sd.wait()
    print("[REC] done")
    return audio.tobytes()


# ---------------------------------------------------------------------------
# WebSocket 通信
# ---------------------------------------------------------------------------

async def call_iat(
    app_id: str,
    api_key: str,
    api_secret: str,
    audio_data: bytes,
) -> str:
    """连接讯飞语音听写 WebSocket，流式发送+接收，返回识别文本。"""
    try:
        import websockets
    except ImportError:
        print("[ERROR] pip install websockets")
        sys.exit(1)

    t_start = time.perf_counter()

    ws_url = build_auth_url(app_id, api_key, api_secret)

    # 计时：连接
    t_conn_start = time.perf_counter()
    ws = await websockets.connect(ws_url, ping_interval=5)
    t_conn = time.perf_counter() - t_conn_start
    print(f"[TIMING] connect: {t_conn*1000:.0f}ms")
    print(f"[AUTH] signed OK")

    full_text = ""
    recv_count = 0
    first_result_at = None
    send_done = False

    # --- 发送协程：逐帧发音频 ---
    async def sender():
        nonlocal send_done
        offset = 0
        total_frames = 0
        data_len = len(audio_data)
        t_send_start = time.perf_counter()

        while True:
            chunk = audio_data[offset : offset + FRAME_SIZE]
            chunk_len = len(chunk)
            offset += FRAME_SIZE

            if offset >= data_len:
                frame = build_last_frame(chunk) if chunk else build_last_frame()
                await ws.send(frame)
                total_frames += 1
                send_done = True
                t_send = time.perf_counter() - t_send_start
                print(f"[SEND] frame {total_frames:>3d} LAST  | {chunk_len:>5d}B | "
                      f"total {total_frames} frames in {t_send*1000:.0f}ms")
                break
            elif total_frames == 0:
                frame = build_first_frame(app_id, chunk)
                await ws.send(frame)
                total_frames += 1
            else:
                frame = build_continue_frame(chunk)
                await ws.send(frame)
                total_frames += 1

            await asyncio.sleep(SEND_INTERVAL)

    # --- 接收协程：流式读取结果 ---
    async def receiver():
        nonlocal full_text, recv_count, first_result_at
        try:
            async for msg in ws:
                if isinstance(msg, bytes):
                    msg = msg.decode("utf-8")

                result = json.loads(msg)
                code = result.get("code", -1)

                if code != 0:
                    message = result.get("message", "unknown error")
                    print(f"[ERROR] code={code}, msg={message}")
                    break

                data = result.get("data", {})
                status = data.get("status", 1)

                # 解析文字
                ws_result = data.get("result", {}).get("ws", [])
                seg_text = ""
                for seg in ws_result:
                    for cw in seg.get("cw", []):
                        seg_text += cw.get("w", "")

                if seg_text:
                    elapsed = time.perf_counter() - t_start
                    if first_result_at is None:
                        first_result_at = elapsed

                    recv_count += 1
                    tag = {0: "[FIRST]", 1: "[MID  ]", 2: "[FINAL]"}.get(status, f"[S={status}]")
                    print(f"{tag} +{elapsed*1000:6.0f}ms | #{recv_count} | {seg_text}")

                    # 累积结果（wpgs 模式下每个结果可能是新 utterance）
                    full_text += seg_text

                if status == 2:
                    break
        except Exception as e:
            print(f"[RECV ERROR] {e}")

    # --- 并发执行发送和接收 ---
    send_task = asyncio.create_task(sender())
    recv_task = asyncio.create_task(receiver())

    await asyncio.gather(send_task, recv_task)
    await ws.close()

    t_total = time.perf_counter() - t_start
    print(f"\n[TIMING] ========== Summary ==========")
    print(f"[TIMING] connect:      {t_conn*1000:6.0f}ms")
    if first_result_at is not None:
        print(f"[TIMING] first result: {first_result_at*1000:6.0f}ms (TTFR)")
    print(f"[TIMING] total:        {t_total*1000:6.0f}ms")
    print(f"[TIMING] results recv: {recv_count}")

    return full_text


# ---------------------------------------------------------------------------
# 配置读写
# ---------------------------------------------------------------------------

def load_config() -> dict:
    """从默认路径读取配置。"""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_config(app_id: str, api_key: str, api_secret: str):
    """保存凭据到配置文件。"""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    config = {
        "app_id": app_id,
        "api_key": api_key,
        "api_secret": api_secret,
    }
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    print(f"[SAVE] credentials saved to {CONFIG_PATH}")


# ---------------------------------------------------------------------------
# 命令行入口
# ---------------------------------------------------------------------------

async def main():
    parser = argparse.ArgumentParser(
        description="iFlytek IAT ASR API test",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Record from mic (5s)
  python test_asr.py --app-id xxx --api-key xxx --api-secret xxx

  # Use WAV file
  python test_asr.py --app-id xxx --api-key xxx --api-secret xxx --file test.wav

  # Save credentials for later use
  python test_asr.py --app-id xxx --api-key xxx --api-secret xxx --save-config
  python test_asr.py
        """,
    )
    parser.add_argument("--app-id", help="APPID from xfyun console")
    parser.add_argument("--api-key", help="APIKey from xfyun console")
    parser.add_argument("--api-secret", help="APISecret from xfyun console")
    parser.add_argument("--file", help="WAV file path (16kHz/16bit/mono)")
    parser.add_argument("--duration", type=float, default=RECORD_SECONDS,
                        help=f"Mic recording duration in seconds (default {RECORD_SECONDS})")
    parser.add_argument("--save-config", action="store_true",
                        help="Save credentials to local config file")
    args = parser.parse_args()

    # Get credentials: CLI > config file
    config = load_config()
    app_id = args.app_id or config.get("app_id", "")
    api_key = args.api_key or config.get("api_key", "")
    api_secret = args.api_secret or config.get("api_secret", "")

    # Verify credentials
    missing = []
    if not app_id:
        missing.append("--app-id")
    if not api_key:
        missing.append("--api-key")
    if not api_secret:
        missing.append("--api-secret")
    if missing:
        print(f"[ERROR] missing: {', '.join(missing)}")
        print("        get credentials from https://console.xfyun.cn/")
        sys.exit(1)

    # Save credentials
    if args.save_config:
        save_config(app_id, api_key, api_secret)

    # Prepare audio data
    if args.file:
        if not os.path.exists(args.file):
            print(f"[ERROR] file not found: {args.file}")
            sys.exit(1)
        audio_data = read_wav_frames(args.file)
    else:
        audio_data = record_mic(args.duration)

    duration_sec = len(audio_data) / AUDIO_RATE / 2
    print(f"[AUDIO] {len(audio_data)} bytes ({duration_sec:.1f}s)")

    # Call API
    print("=" * 50)
    text = await call_iat(app_id, api_key, api_secret, audio_data)
    print("=" * 50)

    if text:
        print(f"\n[RESULT] {text}")
    else:
        print("\n[RESULT] no text recognized")


if __name__ == "__main__":
    asyncio.run(main())