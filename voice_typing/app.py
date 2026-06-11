"""
主应用：Win32 消息循环 + 托盘图标 + 热键 + 全流程编排。

线程模型：
  主线程  ─ Win32 消息循环（隐藏窗口 + 托盘 + 热键）
  辅助线程 ─ tkinter 设置窗口（按需启动）
  辅助线程 ─ STT API 调用（每次 PTT 松键后）
"""

import asyncio
import ctypes
import os
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

# 自定义消息
WM_APP_UPDATE_HOTKEY = 0x8001     # 更新热键
WM_APP_OPEN_SETTINGS = 0x8002     # 打开设置窗口
WM_APP_TRAY_CALLBACK = 0x8003     # 托盘图标回调（系统定义，但用固定 ID）

# 托盘
WM_TRAYICON = 0x8004              # 托盘通知消息
ID_TRAY = 1
IDM_SETTINGS = 1001
IDM_EXIT = 1002
IDM_RESTART_ADMIN = 1003
IDM_ABOUT = 1004

# 热键
ID_HOTKEY = 1
IDT_POLL_KEY = 1                  # 松键轮询定时器 ID

# ---------------------------------------------------------------------------
# Win32 常量 / 结构体
# ---------------------------------------------------------------------------

# 窗口
WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_EX_TOOLWINDOW = 0x00000080
CW_USEDEFAULT = 0x80000000

# 消息
WM_HOTKEY = 0x0312
WM_CLOSE = 0x0010
WM_DESTROY = 0x0002
WM_TIMER = 0x0113
WM_COMMAND = 0x0111
WM_USER = 0x0400

# 托盘
NIM_ADD = 0
NIM_MODIFY = 1
NIM_DELETE = 2
NIF_MESSAGE = 1
NIF_ICON = 2
NIF_TIP = 4
NIF_INFO = 0x10
NIIF_INFO = 1
NIIF_ERROR = 3
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205

# 窗口扩展样式
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000

# 窗口消息框
TPM_LEFTALIGN = 0
TPM_RIGHTBUTTON = 2

# ── 设置 Win32 API 参数类型（64 位兼容，ALL functions）──
_udll = ctypes.windll.user32
_kdll = ctypes.windll.kernel32
_sdll = ctypes.windll.shell32

_udll.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_udll.DefWindowProcW.restype = wintypes.LPARAM
_udll.RegisterClassExW.argtypes = [ctypes.c_void_p]
_udll.RegisterClassExW.restype = wintypes.ATOM
_udll.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
]
_udll.CreateWindowExW.restype = wintypes.HWND
_udll.GetMessageW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.UINT]
_udll.GetMessageW.restype = wintypes.BOOL
_udll.TranslateMessage.argtypes = [ctypes.c_void_p]
_udll.DispatchMessageW.argtypes = [ctypes.c_void_p]
_udll.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_udll.PostMessageW.restype = wintypes.BOOL
_udll.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
_udll.RegisterHotKey.restype = wintypes.BOOL
_udll.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
_udll.UnregisterHotKey.restype = wintypes.BOOL
_udll.GetAsyncKeyState.argtypes = [ctypes.c_int]
_udll.GetAsyncKeyState.restype = wintypes.SHORT
_udll.SetTimer.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.UINT, ctypes.c_void_p]
_udll.KillTimer.argtypes = [wintypes.HWND, wintypes.UINT]
_udll.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
_udll.FindWindowW.restype = wintypes.HWND
_udll.CreatePopupMenu.argtypes = []
_udll.CreatePopupMenu.restype = wintypes.HMENU
_udll.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.UINT, wintypes.LPCWSTR]
_udll.GetCursorPos.argtypes = [ctypes.c_void_p]
_udll.SetForegroundWindow.argtypes = [wintypes.HWND]
_udll.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, ctypes.c_void_p]
_udll.DestroyMenu.argtypes = [wintypes.HMENU]
_udll.DestroyWindow.argtypes = [wintypes.HWND]
_udll.PostQuitMessage.argtypes = [ctypes.c_int]
_udll.CreateIconFromResourceEx.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD, ctypes.c_int, ctypes.c_int, wintypes.UINT]
_udll.CreateIconFromResourceEx.restype = wintypes.HICON
_udll.DestroyIcon.argtypes = [wintypes.HICON]
_udll.MessageBeep.argtypes = [wintypes.UINT]
_kdll.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
_kdll.CreateMutexW.restype = wintypes.HANDLE
_kdll.CloseHandle.argtypes = [wintypes.HANDLE]
_kdll.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
_kdll.GetModuleHandleW.restype = wintypes.HINSTANCE
_sdll.ShellExecuteW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_int]
_sdll.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.c_void_p]

# Hotkey modifiers
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008

# ---------------------------------------------------------------------------
# 结构体定义
# ---------------------------------------------------------------------------

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", POINT),
    ]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HICON),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uTimeoutOrVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
    ]


# ---------------------------------------------------------------------------
# 窗口过程（全局回调）
# ---------------------------------------------------------------------------

# 函数指针类型
WNDPROC_TYPE = ctypes.WINFUNCTYPE(
    ctypes.c_longlong, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)

# 全局引用，防止被 GC
_wndproc_ref = None
_app_instance = None  # VoiceTypingApp 实例引用


@WNDPROC_TYPE
def _wnd_proc(hwnd, msg, wparam, lparam):
    """隐藏窗口的窗口过程。"""
    app = _app_instance
    if app is None:
        return ctypes.windll.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    if msg == WM_HOTKEY:
        app._on_hotkey_press()
        return 0

    elif msg == WM_TIMER:
        if wparam == IDT_POLL_KEY:
            app._poll_key_release()
        return 0

    elif msg == WM_TRAYICON:
        if lparam == 0x0203:  # WM_LBUTTONDBLCLK
            app._open_settings_window()
        elif lparam == WM_RBUTTONUP:
            app._show_tray_menu()
        return 0

    elif msg == WM_COMMAND:
        cmd = wparam & 0xFFFF
        if cmd == IDM_SETTINGS:
            app._open_settings_window()
        elif cmd == IDM_EXIT:
            app._quit()
        elif cmd == IDM_RESTART_ADMIN:
            app._restart_as_admin()
        elif cmd == IDM_ABOUT:
            app._show_usage_tip()
        return 0

    elif msg == WM_APP_UPDATE_HOTKEY:
        app._reload_hotkey()
        return 0

    elif msg == WM_APP_OPEN_SETTINGS:
        app._open_settings_window()
        return 0

    elif msg == WM_CLOSE:
        app._on_close()
        return 0

    elif msg == WM_DESTROY:
        ctypes.windll.user32.PostQuitMessage(0)
        return 0

    return ctypes.windll.user32.DefWindowProcW(hwnd, msg, wparam, lparam)


# ---------------------------------------------------------------------------
# VoiceTypingApp
# ---------------------------------------------------------------------------

class VoiceTypingApp:
    """主应用：消息循环 + 托盘 + 业务流程。"""

    def __init__(self):
        global _app_instance
        _app_instance = self

        from . import config

        self.config = config.load_config()
        self.hwnd: int = 0
        self.hicon: int = 0

        # 录音状态
        self._recording = False
        self._session = None
        self._hotkey_vk = 0

        # 互斥体
        self._mutex = None

    # ═══════════════════════════════════════════════════════════════
    # 入口
    # ═══════════════════════════════════════════════════════════════

    def run(self):
        """启动应用。"""
        # ── Splash 启动（独立线程，第一时间出现） ──
        from .splash import SplashScreen

        splash = SplashScreen()
        splash.show()

        # 多实例保护
        if not self._acquire_mutex():
            splash.destroy()
            if self._activate_existing():
                return
            # 残留互斥体已清理，重新获取
            if not self._acquire_mutex():
                splash = SplashScreen()
                splash.show()
                splash.set_status("启动失败：互斥体冲突")
                import time; time.sleep(2)
                splash.destroy()
                return

        splash.set_status("正在检查配置…")

        # 检查是否已配置
        from .config import is_configured

        if not is_configured():
            splash.destroy()  # 暂隐 Splash，让设置窗口在前
            self._open_settings_window_sync()  # 首次启动，阻塞等配置完成
            from .config import load_config

            self.config = load_config()
            if not is_configured():
                # 用户关闭了设置窗口没保存
                return
            # 设置完成，重新显示 Splash
            splash = SplashScreen()
            splash.show()

        splash.set_status("正在加载资源…")

        # 加载图标
        try:
            self._load_icons()
        except Exception as e:
            splash.destroy()
            self._fatal_error("启动失败", f"无法加载图标文件:\n{e}")

        splash.set_status("正在启动服务…")

        # 后台预加载 VAD 模型（2MB，不阻塞启动）
        try:
            from .capture import preload_vad
            threading.Thread(target=preload_vad, daemon=True).start()
        except Exception:
            pass

        # 后台预加载本地 STT 模型（非"仅云端"模式时）
        if self.config.get("stt_engine", "auto") != "cloud":
            try:
                from .local_stt import preload
                preload()
            except Exception:
                pass

        splash.set_status("准备就绪")
        splash.destroy()

        # 启动 Win32 消息循环（阻塞于此）
        try:
            self._message_loop()
        except Exception as e:
            self._fatal_error("启动失败", f"窗口初始化失败:\n{e}")

    # ═══════════════════════════════════════════════════════════════
    # 使用说明
    # ═══════════════════════════════════════════════════════════════

    def _show_usage_tip(self):
        """在独立线程中弹出使用说明窗口。"""
        def _run():
            hotkey = self.config.get("hotkey", "未设置")
            engine = self.config.get("stt_engine", "auto")
            engine_names = {"auto": "自动（本地优先）", "local": "仅本地（SenseVoiceSmall）", "cloud": "仅云端（讯飞）"}
            engine_name = engine_names.get(engine, engine)

            import tkinter as tk
            from tkinter import ttk

            win = tk.Tk()
            win.title("薛老头 — 使用说明")
            win.resizable(False, False)

            pad = {"padx": 16, "pady": 4}
            ttk.Label(win, text="薛老头", font=("", 14, "bold")).pack(**pad)
            ttk.Label(win, text="按住说话，松手输入 — PTT 语音转文字",
                      foreground="gray").pack(**pad)

            ttk.Separator(win).pack(fill="x", **pad)

            info = [
                ("快捷键", hotkey),
                ("识别引擎", engine_name),
                ("输出方式", self.config.get("output_method", "unicode")),
            ]
            for label, value in info:
                frame = ttk.Frame(win)
                frame.pack(fill="x", **pad)
                ttk.Label(frame, text=label + "：", width=10).pack(side="left")
                ttk.Label(frame, text=value).pack(side="left")

            ttk.Separator(win).pack(fill="x", **pad)

            ttk.Label(win, text="使用方法：").pack(anchor="w", padx=16)
            steps = [
                f"1. 按住 {hotkey} 开始录音",
                "2. 对着麦克风说话",
                "3. 松手 — 文字自动输入到光标位置",
            ]
            for s in steps:
                ttk.Label(win, text=s, foreground="dimgray").pack(anchor="w", padx=32)

            ttk.Label(win, text="右键托盘图标 → 设置、重启、退出",
                      foreground="gray").pack(pady=(8, 4))

            win.update_idletasks()
            w, h = win.winfo_width(), win.winfo_height()
            sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
            win.geometry(f"+{(sw-w)//2}+{(sh-h)//2}")
            win.grab_set()
            win.mainloop()

        threading.Thread(target=_run, daemon=True).start()

    # ═══════════════════════════════════════════════════════════════
    # 致命错误
    # ═══════════════════════════════════════════════════════════════

    def _fatal_error(self, title: str, message: str):
        """致命错误弹窗，确认后退出。"""
        ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)  # MB_ICONERROR
        sys.exit(1)

    # ═══════════════════════════════════════════════════════════════
    # 互斥体
    # ═══════════════════════════════════════════════════════════════

    def _acquire_mutex(self) -> bool:
        """创建命名互斥体，防止多实例。开发模式下先杀旧进程。"""
        if not getattr(sys, "frozen", False):
            import subprocess, os
            subprocess.call(
                f'powershell -Command "Get-Process python -ErrorAction SilentlyContinue'
                f' | Where-Object Id -ne {os.getpid()} | Stop-Process -Force"',
                shell=True, creationflags=0x08000000,
            )
        self._mutex = ctypes.windll.kernel32.CreateMutexW(None, False,
                                                          "VoiceTypingApp_SingleInstance")
        return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS

    def _activate_existing(self):
        """通知已有实例，或残留互斥体时强制启动。"""
        hwnd = ctypes.windll.user32.FindWindowW("VoiceTypingClass", None)
        if hwnd:
            ctypes.windll.user32.PostMessageW(hwnd, WM_APP_OPEN_SETTINGS, 0, 0)
            print("薛老头已在运行中")
            return True
        else:
            # 互斥体还在但找不到窗口 → 残留，关闭旧互斥体重来
            if self._mutex:
                ctypes.windll.kernel32.CloseHandle(self._mutex)
                self._mutex = None
            return False

    # ═══════════════════════════════════════════════════════════════
    # 图标加载
    # ═══════════════════════════════════════════════════════════════

    def _load_icons(self):
        from .feedback import load_icon
        self.hicon = load_icon()
        self._icon_loaded = True

    # ═══════════════════════════════════════════════════════════════
    # Win32 消息循环
    # ═══════════════════════════════════════════════════════════════

    def _message_loop(self):
        """注册窗口类、创建隐藏窗口、进入消息循环。"""
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        hinstance = kernel32.GetModuleHandleW(None)

        # 注册窗口类
        global _wndproc_ref
        _wndproc_ref = _wnd_proc  # 保持引用
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = ctypes.cast(_wndproc_ref, ctypes.c_void_p)
        wc.hInstance = hinstance
        wc.lpszClassName = "VoiceTypingClass"
        atom = user32.RegisterClassExW(ctypes.byref(wc))
        if not atom:
            raise OSError("RegisterClassExW 失败")

        # 创建隐藏窗口
        self.hwnd = user32.CreateWindowExW(
            WS_EX_TOOLWINDOW,                        # 不在任务栏显示
            "VoiceTypingClass",
            "薛老头",
            WS_OVERLAPPEDWINDOW,
            CW_USEDEFAULT, CW_USEDEFAULT, 200, 200,
            None, None, hinstance, None,
        )
        if not self.hwnd:
            raise OSError("CreateWindowExW 失败")

        # 添加托盘图标
        self._add_tray()

        # 注册热键
        self._register_hotkey()

        # 启动通知：告知用户当前快捷键
        hotkey = self.config.get("hotkey", "未设置")
        self._tray_balloon(
            "薛老头已就绪",
            f"按住 {hotkey} 说话，松手自动输入文字",
        )

        # 消息循环
        msg = MSG()
        while True:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret <= 0:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        # 清理
        self._remove_tray()

    def _on_close(self):
        """WM_CLOSE 处理。"""
        # 注销热键
        ctypes.windll.user32.UnregisterHotKey(self.hwnd, ID_HOTKEY)
        # 销毁窗口 → 触发 WM_DESTROY → PostQuitMessage
        ctypes.windll.user32.DestroyWindow(self.hwnd)

    # ═══════════════════════════════════════════════════════════════
    # 热键
    # ═══════════════════════════════════════════════════════════════

    def _register_hotkey(self):
        """注册全局热键。"""
        modifiers = self.config.get("hotkey_modifiers", 6)
        vk = self.config.get("hotkey_vk", 0x56)
        if not vk:
            return

        result = ctypes.windll.user32.RegisterHotKey(self.hwnd, ID_HOTKEY, modifiers, vk)
        if not result:
            self._tray_balloon("快捷键注册失败", "请检查是否被其他应用占用", is_error=True)
        else:
            self._hotkey_vk = vk

    def _reload_hotkey(self):
        """重新加载热键（设置变更后）。"""
        from .config import load_config

        self.config = load_config()
        ctypes.windll.user32.UnregisterHotKey(self.hwnd, ID_HOTKEY)
        self._register_hotkey()

        # 更新托盘 Tooltip + 通知用户新快捷键
        self._update_tray_tip()
        hotkey = self.config.get("hotkey", "未设置")
        self._tray_balloon(
            "快捷键已更新",
            f"按住 {hotkey} 说话，松手自动输入文字",
        )

    def _on_hotkey_press(self):
        """热键按下回调。"""
        if self._recording:
            return  # 防重复触发
        self._recording = True

        try:
            from .capture import CaptureSession
            noise_gate = self.config.get("noise_gate_threshold", -40.0)
            self._session = CaptureSession(noise_gate_threshold=noise_gate)
            self._session.start()
        except Exception as e:
            self._recording = False
            self._show_error(f"麦克风启动失败: {e}")
            return

        ctypes.windll.user32.SetTimer(self.hwnd, IDT_POLL_KEY, 20, None)

    def _poll_key_release(self):
        """轮询热键是否松开。"""
        if not self._recording:
            ctypes.windll.user32.KillTimer(self.hwnd, IDT_POLL_KEY)
            return

        state = ctypes.windll.user32.GetAsyncKeyState(self._hotkey_vk)
        if state & 0x8000:
            return

        # 松键！
        ctypes.windll.user32.KillTimer(self.hwnd, IDT_POLL_KEY)
        self._recording = False

        # 停止录音 + 处理（异常保护：ctypes 回调吞异常，必须自行捕获）
        segments = []
        session = self._session
        frame_count = session.frame_count if session else 0
        dur = session.duration if session else 0.0
        self._session = None

        try:
            if session:
                segments = session.stop()
        except Exception as e:
            self._show_error(f"语音处理失败: {e}")
            return

        if not segments:
            return

        threading.Thread(target=self._process_segments, args=(segments,),
                         daemon=True).start()

    def _process_segments(self, segments: list[bytes]):
        """串行识别 → 拼接 → 统一后处理 → 一次性粘贴。"""
        engine = self.config.get("stt_engine", "auto")
        texts = []

        for segment in segments:
            text = self._transcribe_segment(segment, engine)
            if text is None:
                continue
            text = self._post_process(text)
            if text:
                texts.append(text)

        if texts:
            # 拼接 + 最终标点去重（消除段边界粘连）
            puncts = "，。！？、；：,.!?;:"
            full = "".join(texts)
            chars = []
            for ch in full:
                if ch in puncts and chars and chars[-1] in puncts:
                    continue  # 跳过连续标点
                chars.append(ch)
            full = "".join(chars).rstrip("。！？.!?")
            self._output_text(full)
            self._update_usage()

    def _transcribe_segment(self, segment: bytes, engine: str) -> str | None:
        """根据引擎策略转写单个语音段。返回文本或 None（失败时）。"""
        # --- 尝试本地 ---
        if engine in ("local", "auto"):
            try:
                from .local_stt import is_available, transcribe, get_load_error, MAX_LOCAL_SECONDS
                # 长音频跳过本地（SenseVoice 不适合长句），直接走云端
                audio_sec = len(segment) / 32000
                if audio_sec > MAX_LOCAL_SECONDS and engine == "auto":
                    pass  # 跳过本地
                elif is_available():
                    result = transcribe(segment)
                    if result:
                        return result
                    if engine == "local":
                        self._show_error("本地模型未识别到文字，已自动切换云端")
                        # 继续往下走云端
                elif engine == "local":
                    err = get_load_error() or "模型目录不存在"
                    self._show_error(f"本地模型不可用，已自动切换云端\n{err}")
                    # 继续往下走云端
            except Exception as e:
                if engine == "local":
                    self._show_error(f"本地识别异常，已自动切换云端: {e}")
                # 继续往下走云端

        # --- 尝试云端 ---
        if engine in ("cloud", "auto"):
            try:
                from .stt import SttClient, IatError
                app_id = self.config.get("app_id", "")
                api_key = self.config.get("api_key", "")
                api_secret = self.config.get("api_secret", "")
                client = SttClient(app_id, api_key, api_secret)
                return asyncio.run(client.transcribe(segment))
            except IatError as e:
                self._show_error(f"识别失败: {e.message}")
            except Exception as e:
                self._show_error(f"网络错误: {e}")

        return None

    def _post_process(self, text: str) -> str:
        """文本后处理：去末尾标点、模糊匹配词语替换。"""
        import re
        from fnmatch import translate as wildcard_to_regex
        from .config import load_replacements

        # 1. 段内去重连续标点：，，→，
        puncts = "，。！？、；：,.!?;:"
        chars = []
        for ch in text:
            if ch in puncts and chars and chars[-1] == ch:
                continue
            chars.append(ch)
        text = "".join(chars)

        # 3. 词语替换（支持通配符 * 模糊匹配）
        replacements = load_replacements()
        exact = {}   # 精确替换
        fuzzy = []   # 模糊替换 [(pattern_regex, replacement)]

        for pattern, target in replacements.items():
            if "*" in pattern or "?" in pattern:
                # fnmatch.translate 生成的 regex 带 \Z 锚定整句，去掉
                regex = wildcard_to_regex(pattern).removesuffix("\\Z").removesuffix("(?ms)")
                fuzzy.append((re.compile(regex), target))
            else:
                exact[pattern] = target

        # 先处理模糊匹配（如 薛*超 → 薛奕超）
        for regex, target in fuzzy:
            text = regex.sub(target, text)

        # 再处理精确匹配
        for wrong, correct in exact.items():
            if wrong in text:
                text = text.replace(wrong, correct)

        return text

    def _output_text(self, text: str):
        """输出文字到光标位置。"""
        from .typing_output import paste_text

        method = self.config.get("output_method", "unicode")
        paste_text(text, method=method)

    def _update_usage(self):
        """更新本地用量计数。"""
        from .config import save_config, load_config

        config = load_config()
        now = time.strftime("%Y-%m")
        reset_date = config.get("usage_reset_date", "")
        if reset_date != now:
            config["usage_count"] = 1
            config["usage_reset_date"] = now
        else:
            config["usage_count"] = config.get("usage_count", 0) + 1
        save_config(config)
        self.config = config
        self._update_tray_tip()

    def _show_error(self, message: str):
        """显示错误——弹窗 + 托盘气泡双重保障。"""
        from .feedback import beep_error
        beep_error()
        self._tray_balloon("薛老头", message, is_error=True)
        # MessageBox 弹窗，用户一定看到
        ctypes.windll.user32.MessageBoxW(
            self.hwnd, message, "薛老头 - 错误", 0x10,  # MB_ICONERROR
        )

    # ═══════════════════════════════════════════════════════════════
    # 托盘图标
    # ═══════════════════════════════════════════════════════════════

    def _add_tray(self):
        """添加托盘图标。"""
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = ID_TRAY
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAYICON
        nid.hIcon = self.hicon

        tip = self._make_tip_text()
        nid.szTip = tip

        ctypes.windll.shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))

    def _modify_tray(self):
        """更新托盘图标。"""
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = ID_TRAY
        nid.uFlags = NIF_ICON
        nid.hIcon = self.hicon
        ctypes.windll.shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def _remove_tray(self):
        """删除托盘图标。"""
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = ID_TRAY
        ctypes.windll.shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))

    def _update_tray_tip(self):
        """更新托盘 Tooltip。"""
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = ID_TRAY
        nid.uFlags = NIF_TIP
        nid.szTip = self._make_tip_text()
        ctypes.windll.shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def _make_tip_text(self) -> str:
        hotkey = self.config.get("hotkey", "未设置")
        count = self.config.get("usage_count", 0)
        return f"薛老头 | {hotkey} | 本月 {count} 次"

    def _tray_balloon(self, title: str, text: str, is_error: bool = False):
        """弹出托盘气泡通知。"""
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = ID_TRAY
        nid.uFlags = NIF_INFO
        nid.szInfoTitle = title
        nid.szInfo = text
        nid.dwInfoFlags = NIIF_ERROR if is_error else NIIF_INFO
        nid.uTimeoutOrVersion = 5000  # ms
        ctypes.windll.shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    # ═══════════════════════════════════════════════════════════════
    # 托盘右键菜单
    # ═══════════════════════════════════════════════════════════════

    def _show_tray_menu(self):
        """弹出托盘右键菜单。"""
        user32 = ctypes.windll.user32

        menu = user32.CreatePopupMenu()
        user32.AppendMenuW(menu, 0x0000, IDM_SETTINGS, "设置")
        user32.AppendMenuW(menu, 0x0000, IDM_ABOUT, "使用说明")
        user32.AppendMenuW(menu, 0x0800, 0, "")  # 分隔线
        user32.AppendMenuW(menu, 0x0000, IDM_RESTART_ADMIN, "以管理员身份重启")
        user32.AppendMenuW(menu, 0x0800, 0, "")  # 分隔线
        user32.AppendMenuW(menu, 0x0000, IDM_EXIT, "退出")

        # 获取光标位置
        pt = POINT()
        user32.GetCursorPos(ctypes.byref(pt))

        # 设置前台窗口（确保菜单点击后正确消失）
        user32.SetForegroundWindow(self.hwnd)

        # 弹出菜单
        user32.TrackPopupMenu(
            menu,
            TPM_LEFTALIGN | TPM_RIGHTBUTTON,
            pt.x, pt.y,
            0, self.hwnd, None,
        )

        user32.DestroyMenu(menu)

    # ═══════════════════════════════════════════════════════════════
    # 设置窗口
    # ═══════════════════════════════════════════════════════════════

    def _open_settings_window_sync(self):
        """同步打开设置窗口（首次启动时阻塞）。"""
        from .config import SettingsWindow

        def _on_saved(config: dict):
            """设置保存后通知 Win32 线程。"""
            self.config = config
            if self.hwnd:
                ctypes.windll.user32.PostMessageW(self.hwnd, WM_APP_UPDATE_HOTKEY, 0, 0)

        SettingsWindow(on_save_callback=_on_saved).run()

    def _open_settings_window(self):
        """异步打开设置窗口（托盘菜单触发，不阻塞消息循环）。"""
        def _run():
            self._open_settings_window_sync()
        threading.Thread(target=_run, daemon=True).start()

    # ═══════════════════════════════════════════════════════════════
    # 以管理员身份重启
    # ═══════════════════════════════════════════════════════════════

    def _restart_as_admin(self):
        """用 ShellExecute + runas 触发 UAC，以管理员权限重启自身。"""
        import sys

        # 释放互斥体，让新实例能获取
        if self._mutex:
            ctypes.windll.kernel32.CloseHandle(self._mutex)
            self._mutex = None

        # 删除托盘图标
        self._remove_tray()

        # 确定可执行文件路径
        if getattr(sys, "frozen", False):
            exe_path = sys.executable
        else:
            # 开发模式：用 python 解释器
            exe_path = sys.executable

        # ShellExecute runas → 弹 UAC → 用户确认 → 新进程以管理员启动
        ctypes.windll.shell32.ShellExecuteW(
            None,                      # hwnd
            "runas",                   # 触发 UAC 提权
            exe_path,                  # 目标可执行文件
            "-m voice_typing" if not getattr(sys, "frozen", False) else "",
            None,                      # 工作目录（默认当前目录）
            1,                         # SW_SHOWNORMAL
        )

        # 退出当前进程
        self._quit()

    # ═══════════════════════════════════════════════════════════════
    # 退出
    # ═══════════════════════════════════════════════════════════════

    def _quit(self):
        """退出应用。"""
        ctypes.windll.user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)