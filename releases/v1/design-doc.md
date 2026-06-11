# 薛氏语音助手 — 设计方案 (Win11)

> Windows 11 轻量级语音转文本工具。PTT（按住说话），讯飞 API 驱动，安装即用。

---

## 1. 产品定位

一个**安装即用**的语音转文字产品。用户安装后填入讯飞 API Key、选一个快捷键，即可在任意应用中按住快捷键说话、松开自动输入文字。

**核心约束：**
- 仅支持中文
- 极轻量（PyInstaller 打包后 < 70MB，启动 < 2 秒）
- 仅 Windows 11
- 无需本地 GPU / 模型推理硬件
- **全程无需管理员权限**

---

## 2. 用户体验流程

```
安装 → 首次启动弹出设置窗口（填 Key + 选快捷键 + 测试麦克风）
         → 后台常驻（托盘图标）
              ↓
         按住快捷键 → 🔔提示音 → 说话 → 松开 → 文字出现在光标位置
              ↓
         失败时：托盘气泡通知 + 错误提示音
              ↓
         没说话就松手：静默丢弃，不浪费 API
```

---

## 3. 技术选型

| 层面 | 选择 | 理由 |
|------|------|------|
| 语言 | Python 3.10+ | 音频生态完善、足够轻量 |
| 音频采集 | `sounddevice` | 基于 PortAudio，可指定 16kHz 采样 |
| VAD（语音活动检测） | `silero-vad` | ONNX 模型仅 2MB，CPU 推理 |
| STT API | **讯飞语音听写** | 中文优秀、国内注册方便、免费额度大 |
| WS 客户端 | `websockets` | 已有验证代码（test_asr.py），成熟稳定 |
| 热键监听 | `RegisterHotKey` + `GetAsyncKeyState`（ctypes） | **无需管理员** |
| 文字输出 | 剪贴板 + `SendInput` Ctrl+V（ctypes） | 绕过输入法冲突，零依赖 |
| 用户反馈 | 系统托盘 + `MessageBeep` | 零文件依赖 |
| 设置 UI | `tkinter`（首次/手动打开） | Python 内置 |
| 配置存储 | 本地 JSON 文件 | 零服务器依赖 |
| 打包 | PyInstaller 单 exe | 安装即用 |

---

## 4. 架构

### 4.1 整体流程

```
快捷键按下 → MessageBeep → 录音+VAD（积攒语音段，不发API）
                               ↓
                          松键 → MessageBeep → 逐段发送讯飞 → 拼接结果 → 粘贴
                               ↓
                          （无有效语音）→ 静默丢弃
```

核心改动：录音期间 VAD 只做**切分和积攒**，不发送。松键后才开始调 API。这样：
- 和 `test_asr.py` 已验证逻辑一致
- 每段语音独立一个 WebSocket 连接
- 避免录音中途网络波动影响采集

### 4.2 线程模型（双线程）

```
线程 1（UI）：tkinter 设置窗口
             首次启动/手动打开 → 填完保存后退出
             设置窗口关闭 → 线程结束

线程 2（常驻）：纯 Win32 消息循环，始终运行
              ├── 隐藏窗口（接收 WM_HOTKEY）
              ├── RegisterHotKey — 全局热键注册
              ├── GetAsyncKeyState 轮询 — 松键检测
              ├── Shell_NotifyIcon — 托盘图标 + 右键菜单
              ├── 收到热键 → 录音 + VAD → 松键 → 调 API → 粘贴
              └── PostMessage 接收跨线程通知（换热键 / 退出）
```

跨线程通信：tkinter 线程通过 `PostMessage(hwnd, WM_APP+1, ...)` 通知 Win32 线程更新热键或退出。

### 4.3 退出流程

```
用户点"退出" 或 托盘右键选"退出"
  → PostMessage(hwnd, WM_CLOSE, 0, 0)   // 唤醒 GetMessage
  → 窗口过程收到 WM_CLOSE
     → UnregisterHotKey
     → DestroyWindow → PostQuitMessage(0)
  → GetMessage 返回 0 → 消息循环退出
  → 主线程 join Win32 线程
  → 清理资源 → sys.exit()
```

### 4.4 模块划分

| 模块 | 职责 | 实现方式 |
|------|------|----------|
| **Hotkey** | 全局热键监听 + 松键检测 | `RegisterHotKey`(按下) + `GetAsyncKeyState`(松键) |
| **Capture** | 麦克风录音 + VAD + 噪声门限 + 分段积攒 | `sounddevice` + `silero-vad` |
| **STT** | 逐段发送讯飞 API，返回文本 | `websockets` + HMAC 签名 |
| **Typing** | 剪贴板粘贴，输出到光标 | `pyperclip` + `SendInput` Ctrl+V |
| **Feedback** | 录音状态提示（音效 + 托盘） | `MessageBeep` + `Shell_NotifyIcon` |
| **Config** | 设置窗口 + 配置读写 | `tkinter` + JSON |

---

## 5. 热键方案

### 5.1 `RegisterHotKey` + `GetAsyncKeyState`

Windows 原生机制，无需管理员权限。全程 ctypes 调用，零三方依赖。

**按下检测**：

```
1. CreateWindowEx 创建隐藏窗口（线程 2）
2. RegisterHotKey(hwnd, id, modifiers, vk)
3. GetMessage() 等待 WM_HOTKEY
4. 收到 → 触发录音
```

**松键检测**：

`RegisterHotKey` 不通知松开。收到 `WM_HOTKEY` 后启动 20ms 定时器轮询：

```
WM_HOTKEY 到达
  ├── 1. 开始录音 + MessageBeep
  ├── 2. 检查 recording == True → 忽略（防止重复触发）
  ├── 3. 启动 20ms 轮询 GetAsyncKeyState(vk)
  │      ├── & 0x8000 → 还在按 → 继续录音
  │      └── & 0x8000 == 0 → 松键 → 停止录音
  └── 4. 松键 → MessageBeep → 检查语音段 → 发 API → 恢复 recording=False
```

**防抖**：`recording` 标志位阻止按键弹起前再次触发。

**修饰键映射**：

```
MOD_ALT     = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT   = 0x0004
MOD_WIN     = 0x0008
```

**限制**：必须含至少一个修饰键。`RegisterHotKey` 不支持单键注册，组合键也恰好符合 PTT 需求。

### 5.2 跨线程热键更新

设置窗口改完快捷键后，tkinter 线程发消息给 Win32 线程：

```
tkinter 线程:
    PostMessage(hwnd, WM_APP+1, wparam, lparam)
    // wparam: 新的 modifiers (MAKEWORD)
    // lparam: 新的 vk

Win32 线程窗口过程:
    case WM_APP+1:
        UnregisterHotKey(hwnd, OLD_ID)
        RegisterHotKey(hwnd, NEW_ID, new_modifiers, new_vk)
```

---

## 6. 录音与 VAD

### 6.1 参数

```
采样率：16000 Hz
位深：  16 bit
声道：  单声道
帧长：  512 采样点（32ms）    ← 对齐 silero-vad 要求
格式：  PCM (int16)
```

### 6.2 处理管线（仅积攒，不发送）

```
声卡 → PCM 帧（每 512 samples / 32ms）
         ├── 转 float32，归一化到 [-1, 1]
         ├── RMS 能量计算
         │      ├── < 噪声门限 → 丢弃（不计入静音）
         │      └── >= 噪声门限 → 送入 VAD
         │             ├── VAD 判无语音 → 静音计数器 +1
         │             └── VAD 判有语音 → 拼入当前段 + 静音计数器归零
         │
         ├── 连续静音 > 1.5s（~47 帧）+ 当前段非空
         │      → 封段，加入 segments 列表，开新空段
         │
         └── 录音时长 > 57s
                → MessageBeep 急促警告
                → 在最近静音点封段（无静音点则硬截断）
                    → 开新段继续，直至松键
```

### 6.3 松键后处理

```
松键
  ├── 当前段非空 → 封段，加入 segments 列表
  ├── segments 为空 → 静默丢弃，return
  └── segments 非空 → 逐段调讯飞 WS
         ├── 段 1 → WS 连接 → 识别结果 1
         ├── 段 2 → WS 连接 → 识别结果 2
         └── ... → 拼接: "结果1结果2..."
                  → 粘贴输出
```

### 6.4 噪声门限自动校准

设置界面的麦克风测试环节自动校准：

```
1. 用户点"测试麦克风"
2. 录 3 秒环境音（不说话）
3. 取 RMS 的 95 分位数 + 6dB margin → 作为默认噪声门限
4. 用户可在设置界面微调滑块（±20dB）
5. 保存到 config.json
```

用 95 分位数而非峰值，避免突发噪声（关门声、键盘敲击）拉高门限。

### 6.5 VAD 模型加载

启动时一次性加载 silero-vad ONNX 模型到内存，避免每次按键都加载 1-2 秒。

```python
VAD_SAMPLE_RATE = 16000
vad_model, vad_utils = torch.hub.load(...)  # 或直接用 onnxruntime
# 常驻内存，直到程序退出
```

---

## 7. 讯飞 API 接入

### 7.1 接口详情

- **产品**：语音听写（`iat` 接口）
- **协议**：WebSocket, `wss://iat-api.xfyun.cn/v2/iat`
- **鉴权**：HMAC-SHA256 签名，需 AppID + APIKey + APISecret
- **音频格式**：16kHz, 16bit, mono PCM, 帧大小 1280 字节（40ms）
- **实现参考**：项目已提供验证通过的 `test_asr.py`

### 7.2 签名构造

```python
signature_origin = "host: iat-api.xfyun.cn\n" \
                 + "date: {RFC1123时间}\n" \
                 + "GET /v2/iat HTTP/1.1"

signature = base64(HMAC-SHA256(APISecret, signature_origin))
authorization = base64(f"{api_key}:{signature}")

# WS URL:
wss://iat-api.xfyun.cn/v2/iat?authorization={authorization}&date={...}&host=...
```

### 7.3 分帧发送（单段）

```
WS 连接建立
  → 发送开始帧（JSON, status=0，含业务参数）
  → 循环发送音频帧（binary, 每帧 1280 bytes）
  → 发送结束帧（JSON, status=2）
  → 接收响应（JSON, status=2 为最终结果）
  → 关闭连接
```

每段语音独立走完上述流程。多段时按顺序处理（可并行，但初期串行即可）。

### 7.4 重试策略

```
WS 连接失败 → 重试 2 次，间隔 1s/3s
连接中断     → 托盘提示"网络不稳定，请重试"
API 错误     → 解析错误码并中文提示
超时(10s)   → 托盘提示"识别超时，请重试"
```

---

## 8. 文字输出

### 8.1 输入法冲突问题

直接 `SendInput` 逐字符注入中文会被输入法拦截——输入法处于"组合态"时键盘事件被解释为拼音编码。

### 8.2 剪贴板粘贴路线

```
1. 保存当前剪贴板内容（pyperclip.paste()）
2. 识别文本写入剪贴板（pyperclip.copy()）
3. SendInput Ctrl+V（ctypes，约20行）
4. 等待 100ms
5. 检查剪贴板内容：
   ├── = 我们写入的文本 → 粘贴可能没成功
   │   → 保留文本 + 托盘提示"请手动 Ctrl+V"
   ├── = 旧剪贴板内容 → 粘贴成功 + 恢复旧内容（用户期间没做复制）
   └── = 其他内容 → 用户期间做了复制，保留用户新内容
```

### 8.3 管理员窗口

普通进程 `SendInput` 无法注入管理员窗口（UIPI 隔离）。走步骤 5 第一条——文本保留剪贴板，提示手动粘贴。

---

## 9. 用户反馈系统

### 9.1 提示音：MessageBeep

```python
import ctypes
ctypes.windll.user32.MessageBeep(-1)  # 系统默认提示音，走声卡
```

- 开始录音：`MessageBeep(-1)` 一声
- 结束录音：`MessageBeep(-1)` 一声
- 快到 60s：连两声，间隔 100ms
- 错误：`MessageBeep(0x10)` （MB_ICONHAND）

> 零字节内嵌数据，零文件依赖。未来如需区分录/停音效，可升级为内嵌 WAV。

### 9.2 托盘图标

运行时在内存中构造 `.ico`（3 色纯色方块 16x16），零依赖：

| 颜色 | 含义 |
|------|------|
| 绿色 | 就绪（麦克风可用） |
| 红色 | 错误（麦克风不可用 / API 配置错误） |
| 灰色 | 未配置（首次使用前） |
| 绿闪 | 正在录音中 |

图标在 `Shell_NotifyIcon(NIM_ADD, ...)` 之前动态生成，PyInstaller 打包时无需 `.ico` 文件。

### 9.3 事件-反馈对照

| 事件 | 反馈 |
|------|------|
| 开始录音 | `MessageBeep(-1)` + 托盘变绿闪 |
| 结束录音 | `MessageBeep(-1)` + 托盘恢复绿色 |
| 快到 57s | 连两声急促提示 |
| 识别成功 | 无（文字直接出现） |
| 识别失败 | `MessageBeep(0x10)` + 托盘气泡 |
| 无有效语音松键 | 无（静默丢弃） |
| API 额度不足 | 托盘气泡 |
| 多实例启动 | 激活已有实例托盘，自身退出 |

---

## 10. 设置界面

### 10.1 首次启动

极简 tkinter 窗口（Python 内置，零额外依赖）：

```
┌─────────────────────────────────────┐
│         薛氏语音助手 - 设置          │
│                                     │
│  API AppID    [__________________]  │
│  API Key      [__________________]  │
│  API Secret   [__________________]  │
│                                     │
│  快捷键  [点击后按下组合键 ▾]        │
│  当前: Ctrl+Shift+V                 │
│  （必须包含 Ctrl/Alt/Shift/Win）     │
│                                     │
│  [🎤 测试麦克风]   音量条: ████░░   │
│  噪声门限: [-40 dB ▓▓▓▓▓░░░░]      │
│                                     │
│      [保存并启动]                    │
└─────────────────────────────────────┘
```

- 快捷键输入框：点击获得焦点 → 用户按下组合键 → 自动填入，仅允许含修饰键的组合
- 麦克风测试：录 3 秒 → 回放 → 自动校准噪声门限（95 分位数 + 6dB）→ 可手动微调

### 10.2 配置存储

路径：`%APPDATA%\voice-typing\config.json`

```json
{
  "app_id": "",
  "api_key": "",
  "api_secret": "",
  "hotkey": "ctrl+shift+v",
  "hotkey_modifiers": 6,
  "hotkey_vk": 86,
  "max_record_seconds": 60,
  "noise_gate_threshold": -40,
  "silence_split_seconds": 1.5,
  "feedback_sound": true,
  "usage_count": 0,
  "usage_reset_date": "2026-06-01"
}
```

---

## 11. 用量管理

- 本地计数器：每次成功调用 API 后 `usage_count += 1`
- 每月自动重置：对比 `usage_reset_date`，跨月归零
- 托盘 Tooltip：`薛氏语音助手 | 本月已用 127 次`
- 讯飞免费额度约 500 次/天，默认不硬限制

---

## 12. 错误处理总表

| 场景 | 处理 |
|------|------|
| 快捷键冲突 | 设置界面检测 `RegisterHotKey` 返回值，冲突提示 |
| 麦克风不可用 | 启动检测，不可用时托盘标红 + Tooltip 提示 |
| 误触（无有效语音） | VAD 判 → segments 空 → 静默丢弃，不调 API |
| 网络断开 | WS 重试 2 次，仍失败 → 提示"网络不稳定" |
| API 超时 | 10 秒无响应 → 提示"识别超时，请重试" |
| API 返回错误 | 解析错误码，中文提示（额度不足/签名错误/格式错） |
| 60 秒内无静音 | 57s 警告 + 硬截断 |
| 粘贴失败 | 文本留剪贴板 + 托盘提示"请手动 Ctrl+V" |
| 多实例启动 | 互斥体检测 + 激活已有实例托盘，自己退出 |

---

## 13. 依赖与体积

```
sounddevice          ~200KB
numpy              ~20MB    (sounddevice 依赖 + VAD)
silero-vad model     ~2MB
onnxruntime         ~15MB
websockets           ~1MB    (替代 httpx)
pyperclip            ~30KB
-------------------------------------------
Python 包合计       ~38MB
PyInstaller 打包后   ~50-65MB
```

> 去掉了 `pyautogui`（用 ctypes `SendInput` 替代）、`httpx`（用 `websockets` 替代）、`winsound`（用 `MessageBeep` 替代）。

---

## 14. 开发路线图

### Phase 1 — MVP（核心通路）
- [ ] 项目骨架 + 模块 stub
- [ ] Hotkey 模块：`RegisterHotKey` + 隐藏窗口 + `GetAsyncKeyState` 轮询
- [ ] Capture 模块：`sounddevice` 录音 + `silero-vad` + 噪声门限 + 分段积攒
- [ ] STT 模块：基于 `test_asr.py`，封装为可复用类
- [ ] Typing 模块：剪贴板粘贴 + `SendInput` Ctrl+V + 冲突检测
- [ ] Feedback 模块：`MessageBeep` + 内存生成托盘图标
- [ ] Config 模块：tkinter 设置窗口 + JSON 读写
- [ ] 系统托盘 + 右键菜单（含退出）
- [ ] 多实例保护（`CreateMutexW`）
- [ ] PyInstaller 打包脚本

### Phase 2 — 完善
- [ ] 开机自启
- [ ] 用量统计显示
- [ ] 60 秒超限处理
- [ ] 麦克风自动校准
- [ ] 多麦克风设备选择

### Phase 3 — SteamOS（后期）
- [ ] 热键改用 evdev
- [ ] 输出改用 ydotool
- [ ] 手柄震动反馈
- [ ] systemd user service

---

## 15. 决策记录

| # | 问题 | 决策 | 状态 |
|---|------|------|------|
| 1 | 松键检测 | `GetAsyncKeyState` 20ms 轮询 | ✅ |
| 2 | 提示音 | `MessageBeep`（系统声卡） | ✅ |
| 3 | WS 库 | `websockets`（与 test_asr.py 一致） | ✅ |
| 4 | VAD 中途发送 | 仅积攒，松键后逐段发送 | ✅ |
| 5 | VAD 帧长 | 512 samples (32ms)，对齐 silero-vad | ✅ |
| 6 | Ctrl+V 实现 | ctypes `SendInput`，去掉 pyautogui | ✅ |
| 7 | 托盘图标 | 内存动态生成 ico | ✅ |
| 8 | 跨线程换热键 | `PostMessage(WM_APP+1)` | ✅ |
| 9 | 退出流程 | `PostMessage(WM_CLOSE)` → `PostQuitMessage` | ✅ |
| 10 | 噪声门限校准 | 95 分位数 + 6dB margin | ✅ |
| 11 | 消息循环架构 | 双线程（tkinter + Win32） | ✅ |
| 12 | API Key 模式 | A（用户自带） | ✅ |

---

*文档版本：v0.4 — Win11 聚焦 · 全部问题修正*
