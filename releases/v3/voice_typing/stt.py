"""
讯飞语音听写 (iAT) API 封装。

基于 asr-test/test_asr.py（已验证通过），协议要点：
- 域名为 ws-api.xfyun.cn（非 iat-api）
- 鉴权用 api_key/signature/headers 三段式
- 音频帧 base64 编码后放 JSON 里（非 raw binary）
- 首帧即带音频数据
"""

import asyncio
import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

import websockets

# ---------------------------------------------------------------------------
# 常量 — 务必与工作版 test_asr.py 一致
# ---------------------------------------------------------------------------

IAT_URL = "wss://ws-api.xfyun.cn/v2/iat"
HOST = "ws-api.xfyun.cn"
AUDIO_RATE = 16000
FRAME_SIZE = 8000          # 每帧 0.25s 音频
SEND_INTERVAL = 0.04       # 帧间间隔
MAX_RETRIES = 2
RETRY_DELAYS = [1.0, 3.0]
REQUEST_TIMEOUT = 10.0


# ---------------------------------------------------------------------------
# 鉴权
# ---------------------------------------------------------------------------

def build_auth_url(app_id: str, api_key: str, api_secret: str) -> str:
    """构造带鉴权签名的完整 WebSocket URL。"""
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

    params = urlencode({
        "authorization": authorization,
        "date": date_str,
        "host": HOST,
    })
    return f"{IAT_URL}?{params}"


# ---------------------------------------------------------------------------
# 帧构造
# ---------------------------------------------------------------------------

def _build_first_frame(app_id: str, audio_chunk: bytes) -> str:
    """首帧：status=0，common + business + data + 音频。"""
    payload = {
        "common": {"app_id": app_id},
        "business": {
            "domain": "iat",
            "language": "zh_cn",
            "accent": "mandarin",
            "ptt": 1,
            "vad_eos": 10000,
            "nunum": 1,
        },
        "data": {
            "status": 0,
            "format": "audio/L16;rate=16000",
            "encoding": "raw",
            "audio": base64.b64encode(audio_chunk).decode("utf-8"),
        },
    }
    return json.dumps(payload, ensure_ascii=False)


def _build_continue_frame(audio_chunk: bytes) -> str:
    """中间帧：status=1。"""
    payload = {
        "data": {
            "status": 1,
            "format": "audio/L16;rate=16000",
            "encoding": "raw",
            "audio": base64.b64encode(audio_chunk).decode("utf-8"),
        },
    }
    return json.dumps(payload, ensure_ascii=False)


def _build_last_frame(audio_chunk: bytes = b"") -> str:
    """尾帧：status=2。"""
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
# 错误
# ---------------------------------------------------------------------------

class IatError(Exception):
    """讯飞 API 错误。"""
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


# ---------------------------------------------------------------------------
# SttClient
# ---------------------------------------------------------------------------

class SttClient:
    """讯飞语音听写客户端。"""

    def __init__(self, app_id: str, api_key: str, api_secret: str):
        self.app_id = app_id
        self.api_key = api_key
        self.api_secret = api_secret

    async def transcribe(self, audio_data: bytes) -> str:
        """发送 PCM 音频，返回识别文本。"""
        last_error = None

        for attempt in range(MAX_RETRIES + 1):
            try:
                return await asyncio.wait_for(
                    self._transcribe_once(audio_data),
                    timeout=REQUEST_TIMEOUT,
                )
            except asyncio.TimeoutError:
                last_error = IatError(-1, "识别超时，请重试")
            except IatError:
                raise
            except Exception as e:
                last_error = e
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_DELAYS[attempt])

        raise IatError(-1, f"网络不稳定，已重试 {MAX_RETRIES} 次") from last_error

    async def _transcribe_once(self, audio_data: bytes) -> str:
        """单次 WebSocket 识别（sender/receiver 并发）。"""
        ws_url = build_auth_url(self.app_id, self.api_key, self.api_secret)

        ws = await websockets.connect(ws_url, ping_interval=5)

        full_text = ""
        send_done = False

        async def sender():
            nonlocal send_done
            offset = 0
            data_len = len(audio_data)

            while True:
                chunk = audio_data[offset : offset + FRAME_SIZE]
                offset += FRAME_SIZE

                if offset >= data_len:
                    frame = _build_last_frame(chunk) if chunk else _build_last_frame()
                    await ws.send(frame)
                    send_done = True
                    break
                else:
                    if offset - FRAME_SIZE == 0:
                        frame = _build_first_frame(self.app_id, chunk)
                    else:
                        frame = _build_continue_frame(chunk)
                    await ws.send(frame)

                await asyncio.sleep(SEND_INTERVAL)

        async def receiver():
            nonlocal full_text
            error = None
            async for msg in ws:
                if isinstance(msg, bytes):
                    msg = msg.decode("utf-8")

                result = json.loads(msg)
                code = result.get("code", -1)

                if code != 0:
                    message = result.get("message", "unknown error")
                    error = IatError(code, message)
                    break  # 不抛异常，优雅退出

                data = result.get("data", {})
                status = data.get("status", 1)

                ws_result = data.get("result", {}).get("ws", [])
                for seg in ws_result:
                    for cw in seg.get("cw", []):
                        full_text += cw.get("w", "")

                if status == 2:
                    break

            if error and not full_text:
                raise error  # 没有拿到任何文字才报错

        send_task = asyncio.create_task(sender())
        recv_task = asyncio.create_task(receiver())

        await asyncio.gather(send_task, recv_task)
        await ws.close()

        return full_text
