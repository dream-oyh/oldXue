"""
配置模块：设置窗口 + 配置读写 + 开机自启。

- tkinter 设置窗口（首次启动 / 手动打开）
- JSON 配置文件读写
- 麦克风测试 + 噪声门限自动校准
- 快捷键捕获
- 开机自启动（开始菜单启动文件夹快捷方式）
"""

import json
import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

# ---------------------------------------------------------------------------
# 配置文件路径
# ---------------------------------------------------------------------------

CONFIG_DIR = Path(os.environ.get("APPDATA", Path.home() / ".config")) / "voice-typing"
CONFIG_PATH = CONFIG_DIR / "config.json"
REPLACEMENTS_PATH = CONFIG_DIR / "replacements.json"

# 默认配置
DEFAULT_CONFIG = {
    "app_id": "",
    "api_key": "",
    "api_secret": "",
    "hotkey": "ctrl+alt+space",
    "hotkey_modifiers": 3,          # MOD_CONTROL | MOD_ALT
    "hotkey_vk": 0x20,              # Space
    "max_record_seconds": 60,
    "noise_gate_threshold": -40.0,
    "silence_split_seconds": 2.5,
    "stt_engine": "auto",   # "local" / "cloud" / "auto"（auto=优先本地，失败走云端）
    "output_method": "unicode",  # "unicode" / "clipboard"（微信等 CEF 应用建议选 clipboard）
    "feedback_sound": True,
    "auto_start": False,
    "usage_count": 0,
    "usage_reset_date": "",
}

# 可用的修饰键
MODIFIER_MAP = {
    "ctrl": 0x0002,
    "alt": 0x0001,
    "shift": 0x0004,
    "win": 0x0008,
}
MODIFIER_NAMES = list(MODIFIER_MAP.keys())

# VK 常用映射（字母键 0x41-0x5A，数字 0x30-0x39，F1-F12 0x70-0x7B）
VK_NAMES = {v: chr(v).lower() for v in range(0x41, 0x5B)}  # A-Z
VK_NAMES.update({v: str(v - 0x30) for v in range(0x30, 0x3A)})  # 0-9
VK_NAMES.update({v + 0x6F: f"f{v+1}" for v in range(12)})  # F1-F12
VK_NAMES[0x20] = "space"
VK_NAMES[0x2E] = "delete"


def _modifiers_to_str(modifiers: int) -> str:
    """位掩码 → "ctrl+shift" 格式。"""
    parts = []
    for name, mask in MODIFIER_MAP.items():
        if modifiers & mask:
            parts.append(name)
    return "+".join(parts)


def _vk_to_str(vk: int) -> str:
    """虚拟键码 → 显示名。"""
    return VK_NAMES.get(vk, f"vk({vk:#x})")


# ---------------------------------------------------------------------------
# 配置读写
# ---------------------------------------------------------------------------

def load_config() -> dict:
    """从文件读取配置，没有则返回默认。"""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            saved = json.load(f)
            # 合并默认值（兼容新增字段）
            config = {**DEFAULT_CONFIG, **saved}
            return config
    return dict(DEFAULT_CONFIG)


def save_config(config: dict):
    """保存配置到文件。"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def is_configured() -> bool:
    """检查是否已完成首次配置。"""
    config = load_config()
    return bool(config["app_id"] and config["api_key"] and config["api_secret"])


# ---------------------------------------------------------------------------
# 词语替换词典
# ---------------------------------------------------------------------------

def load_replacements() -> dict:
    """加载词语替换词典。"""
    if REPLACEMENTS_PATH.exists():
        with open(REPLACEMENTS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_replacements(data: dict):
    """保存词语替换词典。"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(REPLACEMENTS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 开机自启动
# ---------------------------------------------------------------------------

def _get_startup_dir() -> Path:
    """Windows 用户启动文件夹路径。"""
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _get_shortcut_path() -> Path:
    """自启动快捷方式完整路径。"""
    return _get_startup_dir() / "薛老头.lnk"


def _get_target_info() -> tuple[str, str, str]:
    """
    返回 (目标路径, 参数, 工作目录) 用于快捷方式创建。

    PyInstaller 打包后：exe 路径，无参数
    开发模式：pythonw.exe，参数 -m voice_typing
    """
    if getattr(sys, "frozen", False):
        # 打包后：sys.executable 就是 exe 本身
        exe_path = sys.executable
        return exe_path, "", os.path.dirname(exe_path)
    else:
        # 开发模式：用 pythonw.exe（无控制台窗口）
        pythonw = sys.executable.replace("python.exe", "pythonw.exe")
        # 项目根目录：voice_typing 包的父目录
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return pythonw, "-m voice_typing", project_root


def set_auto_start(enable: bool):
    """启用/禁用开机自启动。"""
    shortcut_path = _get_shortcut_path()

    if enable:
        target, args, cwd = _get_target_info()
        # 用 PowerShell 创建 .lnk（WScript.Shell COM，Windows 原生支持）
        ps_script = (
            f'$ws = New-Object -ComObject WScript.Shell; '
            f'$sc = $ws.CreateShortcut("{shortcut_path}"); '
            f'$sc.TargetPath = "{target}"; '
            f'$sc.Arguments = "{args}"; '
            f'$sc.WorkingDirectory = "{cwd}"; '
            f'$sc.Description = "薛老头 - PTT 语音转文字"; '
            f'$sc.Save()'
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True, creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
    else:
        if shortcut_path.exists():
            shortcut_path.unlink()


def is_auto_start_enabled() -> bool:
    """检查自启动快捷方式是否存在。"""
    return _get_shortcut_path().exists()


# ---------------------------------------------------------------------------
# 设置窗口
# ---------------------------------------------------------------------------

class SettingsWindow:
    """tkinter 设置窗口。"""

    def __init__(self, on_save_callback=None):
        """
        on_save_callback: 保存后回调（通知 Win32 线程换热键等）。
                          签名: callback(new_config: dict)
        """
        self._on_save = on_save_callback
        self._config = load_config()
        self._capturing_hotkey = False
        self._hotkey_modifiers = 0
        self._hotkey_vk = 0

        self._root = tk.Tk()
        self._root.title("薛老头 - 设置")
        self._root.resizable(False, False)

        self._build_ui()
        self._load_to_ui()

    # ── UI 构建 ──

    def _build_ui(self):
        pad = {"padx": 12, "pady": 4}

        # --- API 凭据 ---
        ttk.Label(self._root, text="讯飞 API 凭据", font=("", 10, "bold")).pack(
            anchor="w", **pad
        )

        self._app_id_var = tk.StringVar()
        self._api_key_var = tk.StringVar()
        self._api_secret_var = tk.StringVar()

        for label, var, show in [
            ("API AppID", self._app_id_var, None),
            ("API Key", self._api_key_var, None),
            ("API Secret", self._api_secret_var, "*"),
        ]:
            frame = ttk.Frame(self._root)
            frame.pack(fill="x", **pad)
            ttk.Label(frame, text=label, width=12).pack(side="left")
            entry = ttk.Entry(frame, textvariable=var, show=show or "", width=42)
            entry.pack(side="left")
            if show:
                show_btn = ttk.Button(
                    frame, text="👁", width=3,
                    command=lambda e=entry, s=show: self._toggle_show(e, s),
                )
                show_btn.pack(side="left", padx=(4, 0))

        # --- 快捷键 ---
        ttk.Separator(self._root).pack(fill="x", **pad)
        ttk.Label(self._root, text="快捷键", font=("", 10, "bold")).pack(
            anchor="w", **pad
        )

        self._hotkey_var = tk.StringVar(value="点击后按下组合键")
        self._hotkey_btn = ttk.Button(
            self._root, textvariable=self._hotkey_var, width=42,
            command=self._start_hotkey_capture,
        )
        self._hotkey_btn.pack(**pad)

        ttk.Label(
            self._root,
            text="必须包含 Ctrl / Alt / Shift / Win 中的一个",
            font=("", 8), foreground="gray",
        ).pack(anchor="w", padx=12)

        self._hotkey_status = tk.StringVar(value="")
        ttk.Label(self._root, textvariable=self._hotkey_status,
                  foreground="red").pack(anchor="w", padx=12)

        # --- STT 引擎选择 ---
        ttk.Separator(self._root).pack(fill="x", **pad)
        ttk.Label(self._root, text="识别引擎", font=("", 10, "bold")).pack(anchor="w", **pad)
        self._engine_var = tk.StringVar(value="auto")
        engine_frame = ttk.Frame(self._root)
        engine_frame.pack(fill="x", **pad)
        for val, label in [("auto", "自动（优先本地）"), ("local", "仅本地"), ("cloud", "仅云端")]:
            ttk.Radiobutton(engine_frame, text=label, variable=self._engine_var,
                            value=val).pack(side="left", padx=(0, 12))

        # --- 文字输出方式 ---
        ttk.Separator(self._root).pack(fill="x", **pad)
        ttk.Label(self._root, text="文字输出方式", font=("", 10, "bold")).pack(anchor="w", **pad)
        self._output_var = tk.StringVar(value="unicode")
        output_frame = ttk.Frame(self._root)
        output_frame.pack(fill="x", **pad)
        for val, label, desc in [
            ("unicode", "Unicode 注入", "不碰剪贴板（微信中可能出现吞字/双标点）"),
            ("clipboard", "剪贴板粘贴", "100% 兼容（不读取用户剪贴板内容）"),
        ]:
            ttk.Radiobutton(output_frame, text=f"{label} — {desc}",
                           variable=self._output_var, value=val).pack(anchor="w")

        # --- 麦克风测试 ---
        ttk.Separator(self._root).pack(fill="x", **pad)
        ttk.Label(self._root, text="麦克风", font=("", 10, "bold")).pack(
            anchor="w", **pad
        )

        mic_frame = ttk.Frame(self._root)
        mic_frame.pack(fill="x", **pad)
        self._mic_btn = ttk.Button(
            mic_frame, text="🎤 测试麦克风", command=self._test_mic
        )
        self._mic_btn.pack(side="left")
        self._mic_status = tk.StringVar(value="")
        ttk.Label(mic_frame, textvariable=self._mic_status).pack(
            side="left", padx=(8, 0)
        )

        # 噪声门限滑块
        gate_frame = ttk.Frame(self._root)
        gate_frame.pack(fill="x", **pad)
        ttk.Label(gate_frame, text="噪声门限:").pack(side="left")
        self._gate_var = tk.DoubleVar(value=-40)
        self._gate_scale = ttk.Scale(
            gate_frame, from_=-60, to=-10, variable=self._gate_var,
            orient="horizontal", length=200, command=self._on_gate_change,
        )
        self._gate_scale.pack(side="left", padx=(8, 4))
        self._gate_label = tk.StringVar(value="-40 dB")
        ttk.Label(gate_frame, textvariable=self._gate_label, width=6).pack(side="left")

        # --- 开机自启 ---
        ttk.Separator(self._root).pack(fill="x", **pad)
        self._auto_start_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            self._root,
            text="开机自动启动（登录时自动运行）",
            variable=self._auto_start_var,
        ).pack(anchor="w", **pad)

        # --- 词语替换词典 ---
        ttk.Separator(self._root).pack(fill="x", **pad)
        ttk.Label(self._root, text="词语替换（每行: 错误词=正确词）",
                  font=("", 10, "bold")).pack(anchor="w", **pad)

        repl_frame = ttk.Frame(self._root)
        repl_frame.pack(fill="x", **pad)
        self._replacements_text = tk.Text(repl_frame, height=5, width=42)
        self._replacements_text.pack(side="left", fill="both", expand=True)

        ttk.Label(self._root,
                  text="支持通配符: 薛*超=薛奕超 可匹配 薛一超/薛大超 等",
                  font=("", 8), foreground="gray").pack(anchor="w", padx=12)

        # --- 底部按钮 ---
        ttk.Separator(self._root).pack(fill="x", **pad)

        btn_frame = ttk.Frame(self._root)
        btn_frame.pack(fill="x", **pad)
        ttk.Button(btn_frame, text="保存并启动", command=self._save).pack(
            side="right"
        )

    # ── 数据绑定 ──

    def _load_to_ui(self):
        c = self._config
        self._app_id_var.set(c["app_id"])
        self._api_key_var.set(c["api_key"])
        self._api_secret_var.set(c["api_secret"])
        self._hotkey_modifiers = c.get("hotkey_modifiers", 0)
        self._hotkey_vk = c.get("hotkey_vk", 0)
        if self._hotkey_modifiers and self._hotkey_vk:
            display = (_modifiers_to_str(self._hotkey_modifiers) + "+"
                       + _vk_to_str(self._hotkey_vk))
            self._hotkey_var.set(display)
        self._gate_var.set(c.get("noise_gate_threshold", -40))
        self._on_gate_change()
        self._engine_var.set(c.get("stt_engine", "auto"))
        self._output_var.set(c.get("output_method", "unicode"))
        self._auto_start_var.set(c.get("auto_start", False))
        # 加载替换词典
        repl = load_replacements()
        lines = [f"{k}={v}" for k, v in repl.items()]
        self._replacements_text.insert("1.0", "\n".join(lines))

    def _save_to_config(self):
        self._config["app_id"] = self._app_id_var.get().strip()
        self._config["api_key"] = self._api_key_var.get().strip()
        self._config["api_secret"] = self._api_secret_var.get().strip()
        self._config["hotkey_modifiers"] = self._hotkey_modifiers
        self._config["hotkey_vk"] = self._hotkey_vk
        if self._hotkey_modifiers and self._hotkey_vk:
            self._config["hotkey"] = (
                _modifiers_to_str(self._hotkey_modifiers) + "+"
                + _vk_to_str(self._hotkey_vk)
            )
        self._config["stt_engine"] = self._engine_var.get()
        self._config["output_method"] = self._output_var.get()
        self._config["noise_gate_threshold"] = self._gate_var.get()
        self._config["auto_start"] = self._auto_start_var.get()

    # ── 操作 ──

    def _start_hotkey_capture(self):
        self._capturing_hotkey = True
        self._hotkey_var.set("请按下组合键...")
        self._hotkey_btn.configure(text="请按下组合键...")
        self._root.bind("<KeyPress>", self._on_hotkey_key)
        self._root.bind("<KeyRelease>", lambda e: None)
        self._root.focus_set()

    def _on_hotkey_key(self, event: tk.Event):
        if not self._capturing_hotkey:
            return

        # 忽略单独的修饰键
        if event.keysym.lower() in ("control_l", "control_r", "alt_l", "alt_r",
                                     "shift_l", "shift_r", "win_l", "win_r",
                                     "super_l", "super_r"):
            return

        # 提取修饰键（兼容 Win: Alt=0x20000, X11: Alt=0x0008）
        modifiers = 0
        if event.state & 0x0004:
            modifiers |= MODIFIER_MAP["ctrl"]
        if event.state & (0x20000 | 0x0008):
            modifiers |= MODIFIER_MAP["alt"]
        if event.state & 0x0001:
            modifiers |= MODIFIER_MAP["shift"]

        # 必须有修饰键
        if modifiers == 0:
            self._hotkey_status.set("必须包含 Ctrl/Alt/Shift/Win 修饰键")
            return

        # 获取虚拟键码
        vk = event.keycode  # tkinter 的 keycode 已经是 Win32 VK

        self._hotkey_modifiers = modifiers
        self._hotkey_vk = vk
        display = _modifiers_to_str(modifiers) + "+" + _vk_to_str(vk)
        self._hotkey_var.set(display)
        self._hotkey_status.set("")
        self._capturing_hotkey = False
        self._root.unbind("<KeyPress>")

    def _test_mic(self):
        """测试麦克风并自动校准噪声门限。"""
        try:
            import sounddevice as sd
            import numpy as np
        except ImportError:
            self._mic_status.set("❌ 请安装 sounddevice")
            return

        self._mic_status.set("⏳ 录音 3 秒...")
        self._mic_btn.configure(state="disabled")
        self._root.update()

        try:
            duration = 3.0
            audio = sd.rec(
                int(duration * 16000), samplerate=16000,
                channels=1, dtype="float32",
            )
            sd.wait()

            # 计算 RMS 的 95 分位数作为环境噪声
            rms = np.sqrt(np.mean(audio ** 2))
            rms_db = 20.0 * np.log10(rms + 1e-10)

            # 取 95 分位数——不是峰值，避免突发噪声影响
            frame_size = 512
            n_frames = len(audio) // frame_size
            rms_values = []
            for i in range(n_frames):
                chunk = audio[i * frame_size : (i + 1) * frame_size, 0]
                chunk_rms = np.sqrt(np.mean(chunk ** 2))
                rms_values.append(20.0 * np.log10(chunk_rms + 1e-10))

            p95 = np.percentile(rms_values, 95) if rms_values else rms_db
            gate_threshold = p95 + 6.0  # 环境噪声以上 6dB
            gate_threshold = max(-60, min(-10, gate_threshold))  # 限于 -60~-10

            self._gate_var.set(round(gate_threshold, 1))
            self._on_gate_change()
            self._mic_status.set(f"✅ 环境噪声 ~{rms_db:.0f} dB，门限 {gate_threshold:.0f} dB")

        except Exception as e:
            self._mic_status.set(f"❌ 错误: {e}")
        finally:
            self._mic_btn.configure(state="normal")

    def _on_gate_change(self, *_):
        val = self._gate_var.get()
        self._gate_label.set(f"{val:.0f} dB")

    def _toggle_show(self, entry: ttk.Entry, current_show: str | None):
        if entry.cget("show"):
            entry.configure(show="")
        else:
            entry.configure(show="*")

    def _save(self):
        """保存配置并退出设置窗口。"""
        api_id = self._app_id_var.get().strip()
        api_key = self._api_key_var.get().strip()
        api_secret = self._api_secret_var.get().strip()

        if not all([api_id, api_key, api_secret]):
            messagebox.showwarning("提示", "请填写完整的 API 凭据")
            return

        if not self._hotkey_modifiers or not self._hotkey_vk:
            messagebox.showwarning("提示", "请设置快捷键（点击快捷键区域后按下组合键）")
            return

        self._save_to_config()
        save_config(self._config)

        # 应用开机自启动设置
        set_auto_start(self._config["auto_start"])

        # 保存词语替换词典
        raw = self._replacements_text.get("1.0", "end-1c").strip()
        repl = {}
        for line in raw.split("\n"):
            line = line.strip()
            if "=" in line:
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip()
                if k and v:
                    repl[k] = v
        save_replacements(repl)

        if self._on_save:
            self._on_save(self._config)

        self._root.destroy()

    def run(self):
        """运行设置窗口（阻塞）。"""
        # 窗口居中
        self._root.update_idletasks()
        w = self._root.winfo_width()
        h = self._root.winfo_height()
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self._root.geometry(f"+{x}+{y}")
        self._root.mainloop()
