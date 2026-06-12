"""
启动加载动画 — 独立线程 Splash 窗口。

纯 Win32 API (ctypes) 实现，零额外依赖。
Splash 在自己的线程中运行 GetMessage 循环，动画始终流畅，
不受主线程初始化阻塞影响。

- WS_EX_TOPMOST | WS_EX_NOACTIVATE：置顶但不抢焦点
- PBS_MARQUEE 进度条：不确定模式滚动光条
- Win11 圆角：DwmSetWindowAttribute
"""

import ctypes
import threading
from ctypes import wintypes

# ---------------------------------------------------------------------------
# Win32 常量
# ---------------------------------------------------------------------------

# 窗口样式
WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
WS_CHILD = 0x40000000

# 扩展样式
WS_EX_TOPMOST = 0x00000008
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080

# 静态文本
SS_CENTER = 0x00000001

# 系统度量
SM_CXSCREEN = 0
SM_CYSCREEN = 1

# 标准光标
IDC_ARROW = 32512

# 颜色
COLOR_WINDOW = 5

# 消息
WM_CLOSE = 0x0010
WM_DESTROY = 0x0002
WM_APP = 0x8000
WM_SETFONT = 0x0030
WM_CTLCOLORSTATIC = 0x0138

# 进度条
PBS_MARQUEE = 0x08
PBM_SETMARQUEE = 0x0400 + 10

# 字体
FW_NORMAL = 400
FW_BOLD = 700
CLEARTYPE_QUALITY = 5

# Win11 圆角
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWM_WCP_ROUND = 2

# ---------------------------------------------------------------------------
# 结构体
# ---------------------------------------------------------------------------

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


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", ctypes.c_long * 2),
    ]


class INITCOMMONCONTROLSEX(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("dwICC", wintypes.DWORD),
    ]


# ---------------------------------------------------------------------------
# 全局引用（窗口过程回调用）
# ---------------------------------------------------------------------------

WNDPROC_TYPE = ctypes.WINFUNCTYPE(
    ctypes.c_longlong, wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
    wintypes.LPARAM,
)

_splash_ref = None         # SplashScreen 实例引用
_wndproc_ref = None        # 防止回调被 GC


@WNDPROC_TYPE
def _splash_wnd_proc(hwnd, msg, wparam, lparam):
    """Splash 窗口过程。"""
    inst = _splash_ref
    if inst is None:
        return ctypes.windll.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    if msg == WM_APP + 1:
        # 主线程通知更新状态文字
        ctypes.windll.user32.SetWindowTextW(inst._hwnd_status, inst._status)
        return 0

    elif msg == WM_CLOSE:
        ctypes.windll.user32.DestroyWindow(hwnd)
        return 0

    elif msg == WM_DESTROY:
        ctypes.windll.user32.PostQuitMessage(0)
        return 0

    return ctypes.windll.user32.DefWindowProcW(hwnd, msg, wparam, lparam)


# ---------------------------------------------------------------------------
# SplashScreen
# ---------------------------------------------------------------------------

class SplashScreen:
    """
    启动加载窗口。

    用法:
        splash = SplashScreen()
        splash.show()                  # 显示并等待窗口就绪
        splash.set_status("加载中…")   # 更新文字
        splash.destroy()               # 关闭
    """

    def __init__(self, title: str = "薛老头", status: str = "正在启动…"):
        self._title = title
        self._status = status
        self._hwnd: int = 0
        self._hwnd_status: int = 0
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None

    # ── 公开 API ──

    def show(self):
        """启动 Splash 线程，阻塞直到窗口创建完成。"""
        self._thread = threading.Thread(target=self._run, daemon=True, name="splash")
        self._thread.start()
        self._ready.wait()

    def set_status(self, text: str):
        """更新状态文字（主线程安全调用）。"""
        self._status = text
        if self._hwnd:
            ctypes.windll.user32.PostMessageW(self._hwnd, WM_APP + 1, 0, 0)

    def destroy(self):
        """关闭 Splash 窗口并等待线程退出。"""
        if self._hwnd:
            ctypes.windll.user32.PostMessageW(self._hwnd, WM_CLOSE, 0, 0)
            self._hwnd = 0
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)

    # ── Splash 线程入口 ──

    def _run(self):
        global _splash_ref, _wndproc_ref

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        gdi32 = ctypes.windll.gdi32
        comctl32 = ctypes.windll.comctl32
        dwmapi = ctypes.windll.dwmapi

        # ── 64-bit 兼容：设置关键返回类型（默认 c_int 会截断句柄） ──
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.DefWindowProcW.restype = ctypes.c_longlong
        user32.LoadCursorW.restype = wintypes.HICON

        hinstance = kernel32.GetModuleHandleW(None)

        # ── 初始化通用控件（进度条需要） ──
        icc = INITCOMMONCONTROLSEX()
        icc.dwSize = ctypes.sizeof(INITCOMMONCONTROLSEX)
        icc.dwICC = 0x00000020  # ICC_PROGRESS_CLASS
        comctl32.InitCommonControlsEx(ctypes.byref(icc))

        # ── 注册窗口类 ──
        _splash_ref = self
        _wndproc_ref = _splash_wnd_proc

        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = ctypes.cast(_wndproc_ref, ctypes.c_void_p)
        wc.hInstance = hinstance
        wc.hCursor = user32.LoadCursorW(None, IDC_ARROW)
        wc.hbrBackground = wintypes.HBRUSH(COLOR_WINDOW + 1)
        wc.lpszClassName = "VoiceTypingSplash"
        atom = user32.RegisterClassExW(ctypes.byref(wc))
        if not atom:
            _splash_ref = None
            self._ready.set()
            return

        # ── 计算居中位置 ──
        width, height = 320, 130
        screen_w = user32.GetSystemMetrics(SM_CXSCREEN)
        screen_h = user32.GetSystemMetrics(SM_CYSCREEN)
        x = (screen_w - width) // 2
        y = (screen_h - height) // 2

        # ── 创建窗口 ──
        hwnd = user32.CreateWindowExW(
            WS_EX_TOPMOST | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW,
            "VoiceTypingSplash",
            self._title,
            WS_POPUP,
            x, y, width, height,
            None, None, hinstance, None,
        )
        if not hwnd:
            _splash_ref = None
            self._ready.set()
            return

        self._hwnd = hwnd

        # ── Win11 圆角 ──
        try:
            corner = ctypes.c_int(DWM_WCP_ROUND)
            dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(corner), ctypes.sizeof(corner),
            )
        except Exception:
            pass  # Win10 及更早系统不支持，忽略

        # ── 创建字体 ──
        # 标题：14pt bold Segoe UI  (-MulDiv(14, 96, 72) = -19)
        h_font_title = gdi32.CreateFontW(
            -19, 0, 0, 0, FW_BOLD, 0, 0, 0, 0, 0, 0,
            CLEARTYPE_QUALITY, 0, "Segoe UI",
        )
        # 状态文字：9pt normal  (-MulDiv(9, 96, 72) = -12)
        h_font_status = gdi32.CreateFontW(
            -12, 0, 0, 0, FW_NORMAL, 0, 0, 0, 0, 0, 0,
            CLEARTYPE_QUALITY, 0, "Segoe UI",
        )

        # ── 创建子控件 ──
        # 应用名
        hwnd_title = user32.CreateWindowExW(
            0, "STATIC", self._title,
            WS_CHILD | WS_VISIBLE | SS_CENTER,
            15, 22, 290, 24, hwnd, 0, hinstance, None,
        )
        user32.SendMessageW(hwnd_title, WM_SETFONT, h_font_title, 0)

        # 状态文字
        self._hwnd_status = user32.CreateWindowExW(
            0, "STATIC", self._status,
            WS_CHILD | WS_VISIBLE | SS_CENTER,
            15, 55, 290, 20, hwnd, 0, hinstance, None,
        )
        user32.SendMessageW(self._hwnd_status, WM_SETFONT, h_font_status, 0)

        # 进度条
        hwnd_pb = user32.CreateWindowExW(
            0, "msctls_progress32", None,
            WS_CHILD | WS_VISIBLE | PBS_MARQUEE,
            25, 90, 270, 8, hwnd, 0, hinstance, None,
        )
        user32.SendMessageW(hwnd_pb, PBM_SETMARQUEE, 1, 40)

        # ── 显示 ──
        user32.ShowWindow(hwnd, 1)  # SW_SHOWNORMAL
        user32.UpdateWindow(hwnd)

        # ── 通知主线程：窗口就绪 ──
        self._ready.set()

        # ── 消息循环 ──
        msg = MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        # ── 清理 ──
        try:
            if h_font_title:
                gdi32.DeleteObject(h_font_title)
            if h_font_status:
                gdi32.DeleteObject(h_font_status)
            user32.UnregisterClassW("VoiceTypingSplash", hinstance)
        except Exception:
            pass  # daemon 线程，进程退出时 OS 自动回收
        _splash_ref = None