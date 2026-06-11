"""
薛氏语音助手 — 入口点。

用法:
    python -m voice_typing          # 正常启动
    python -m voice_typing --setup  # 强制打开设置窗口
"""

import sys


def main():
    # 简单的命令行参数
    force_setup = "--setup" in sys.argv

    if force_setup:
        from voice_typing.config import SettingsWindow
        SettingsWindow().run()
        return

    from voice_typing.app import VoiceTypingApp
    app = VoiceTypingApp()
    app.run()


if __name__ == "__main__":
    main()