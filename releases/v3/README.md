# 薛老头

> 按住快捷键说话，松手自动输入文字 — Windows PTT 语音转文字工具

[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10+-blue)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-lightgrey)]()

---

## 是什么

一个轻量级 Windows 工具。按住热键 → 说话 → 松手，文字直接出现在光标位置。支持**本地离线识别**和**云端 API**，两者可切换。

## 特性

| 功能 | 说明 |
|------|------|
| 双引擎 | 本地 SenseVoiceSmall（离线，229MB）+ 讯飞云端 API |
| 零权限 | 全程不需要管理员权限，不弹 UAC |
| 隐私安全 | Unicode 注入模式不碰剪贴板 |
| 剪贴板模式 | 微信等 CEF 应用专用，GetClipboardSequenceNumber 检测不读内容 |
| 模糊替换词典 | `薛*超=薛奕超`，支持 `*` 和 `?` 通配符 |
| 开机自启 | 可选，开始菜单启动文件夹快捷方式 |
| 多实例保护 | 不会重复启动 |

## 快速开始

1. 从 [GitHub Releases](../../releases/latest) 下载 `薛老头.exe`，或自行打包（见下方"开发"）
2. 双击运行 → 首次弹出设置窗口 → 填入讯飞 API 凭据 + 设置快捷键
3. 托盘出现图标 → 完成
4. 任意输入框 → 按住热键说话 → 松手 → 文字出现

> **微信用户**：设置 → 文字输出方式 → 选择"剪贴板粘贴"

## 使用

| 操作 | 说明 |
|------|------|
| 按住热键 | 开始录音 |
| 松手 | 结束录音 + 文字输入到光标 |
| 双击托盘 | 打开设置 |
| 右键托盘 | 使用说明 / 设置 / 以管理员重启 / 退出 |

## 引擎模式

| 模式 | 行为 |
|------|------|
| 自动（默认） | 优先本地模型，失败切云端 |
| 仅本地 | 只用 SenseVoiceSmall，完全离线 |
| 仅云端 | 只用讯飞 API，响应最快 |

## 开发

```bash
# 环境
pip install -r requirements.txt

# 运行
python -m voice_typing              # 正常启动
python -m voice_typing --setup      # 强制打开设置

# 打包
python generate_icon.py --input logo.png   # 准备图标
pyinstaller voice-typing.spec --noconfirm  # 打包
# 输出: dist/薛老头.exe
```

## 架构

```
热键按下 → 录音 + VAD 静音检测 → 松键 → STT 识别
                                         ├── 本地 SenseVoiceSmall (sherpa-onnx)
                                         └── 云端讯飞 (WebSocket)
                                         → 后处理（去标点+替换词典）
                                         → Unicode 注入 / 剪贴板粘贴
```

## 依赖

| 库 | 用途 |
|----|------|
| `sounddevice` | 麦克风音频采集 |
| `numpy` | 音频数据处理 |
| `onnxruntime` | VAD 模型推理（silero-vad） |
| `sherpa-onnx` | SenseVoiceSmall 本地推理 |
| `websockets` | 讯飞 API WebSocket 通信 |
| `pyperclip` | 剪贴板模式（可选） |

## 常见问题

**Q: 微信里出现双标点或吞字？**
A: 设置 → 文字输出方式 → 选择"剪贴板粘贴"。

**Q: 选"仅本地"提示模型未加载？**
A: 确保 `asr-test/models/SenseVoiceSmall/` 下有 `model.int8.onnx` 和 `tokens.txt`。

**Q: 长句子本地识别卡住？**
A: 自动模式下长语音（>10s）会走云端。仅本地模式会切段处理。

**Q: 如何更换图标？**
A: 运行 `python generate_icon.py --input 你的图片.png`，重新打包。

## 致谢

- [SenseVoice](https://github.com/FunAudioLLM/SenseVoice) — 阿里达摩院开源语音模型
- [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) — 模型推理框架
- [silero-vad](https://github.com/snakers4/silero-vad) — 语音活动检测
- [讯飞开放平台](https://www.xfyun.cn/) — 云端 ASR API

## 许可证

MIT © 2026
