# 薛老头

> 按住快捷键说话，松手自动输入文字。轻量、零提权、本地+云端双引擎。

## 是什么

一个 Windows 一键语音转文字工具。按住热键 → 说话 → 松手，文字直接出现在光标位置。支持**本地 SenseVoice 模型**（离线识别，229MB）和**讯飞云端 API**，两者可切换。

## 怎么用

1. 双击 `薛老头.exe`（或 `python -m voice_typing`）
2. 首次启动弹出设置窗口 → 填讯飞 API 凭据 + 选快捷键 → 保存
3. 托盘出现绿色图标 → 搞定
4. 任意输入框 → 按住热键 → 说话 → 松手 → 文字出现

## 特性

| 功能 | 说明 |
|------|------|
| 双引擎 | 本地 SenseVoiceSmall（离线，229MB）+ 讯飞云端（在线） |
| 零提权 | 全程不需要管理员权限 |
| Unicode 注入 | 不碰剪贴板，隐私安全 |
| 模糊替换词典 | `薛*超=薛奕超` 自动纠正常见识别错误 |
| 开机自启 | 可选，登录即运行 |
| 自定义图标 | 替换 `icon.ico` 后重新打包 |
| 多实例保护 | 不会重复启动 |

## 快捷键

| 操作 | 说明 |
|------|------|
| 按住热键 | 开始录音 |
| 松手 | 结束录音 + 自动输入 |
| 双击托盘图标 | 查看使用说明 |
| 右键托盘图标 | 设置 / 以管理员重启 / 退出 |

## 引擎模式

| 模式 | 行为 |
|------|------|
| 自动（默认） | 优先用本地模型，失败切云端 |
| 仅本地 | 只用 SenseVoiceSmall，离线可用 |
| 仅云端 | 只用讯飞 API，最快响应 |

## 系统要求

- Windows 10 / 11（64 位）
- 麦克风
- [可选] 讯飞开放平台 API 凭据（云端模式需要）
- [可选] SenseVoiceSmall 模型（本地模式需要，已打包在 exe 内）

## 开发

```bash
pip install -r requirements.txt
python -m voice_typing          # 开发模式运行
python -m voice_typing --setup  # 强制打开设置
```

## 打包

```bash
python generate_icon.py --input logo.png   # 先准备图标（可选）
powershell -File build.ps1                 # 一键打包
# 或手动: pyinstaller voice-typing.spec --noconfirm
# 输出: dist/薛老头.exe
```

## 许可证

MIT