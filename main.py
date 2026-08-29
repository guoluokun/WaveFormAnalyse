"""WaveFormAnalyse 源码入口。

用法:
    python main.py [--qt-platform auto|wayland|xcb|offscreen|minimal]
                   [--qt-diagnostics] [可选的 root 文件路径]
"""

from __future__ import annotations

import sys

from wfa.app import main


if __name__ == "__main__":
    sys.exit(main())
