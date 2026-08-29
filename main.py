"""波形分析程序入口。

用法:
    python main.py [--qt-platform auto|wayland|xcb|offscreen|minimal]
                   [--qt-diagnostics] [可选的 root 文件路径]
"""

from __future__ import annotations

import argparse
import sys


def _parse_args(argv: list[str]):
    parser = argparse.ArgumentParser(description="WaveFormAnalyse")
    parser.add_argument("root_file", nargs="?", help="启动后直接打开的 ROOT 文件")
    parser.add_argument(
        "--qt-platform", default="auto",
        choices=("auto", "wayland", "wayland-egl", "xcb", "offscreen", "minimal"),
        help="Qt 图形平台，默认 auto 自动检测",
    )
    parser.add_argument(
        "--qt-diagnostics", action="store_true",
        help="打印 Qt/WSL/Linux 图形环境诊断信息后继续启动",
    )
    return parser.parse_args(argv)


def main() -> int:
    args = _parse_args(sys.argv[1:])

    # 必须在导入 PyQt/pyqtgraph 之前完成平台选择，否则 Qt5 可能先加载 xcb
    # 并在缺少系统动态库时直接 abort/core dump。
    from wfa.qt_compat import apply_qt_environment, format_diagnostics

    diag = apply_qt_environment(args.qt_platform)
    if args.qt_diagnostics or not diag.ok:
        print(format_diagnostics(diag), file=sys.stderr)
    if not diag.ok:
        return 2

    from pyqtgraph.Qt import QtWidgets
    from wfa.ui import MainWindow

    app = QtWidgets.QApplication([sys.argv[0]])
    win = MainWindow()
    win.show()

    if args.root_file:
        win.load_path(args.root_file)

    return app.exec() if hasattr(app, "exec") else app.exec_()


if __name__ == "__main__":
    sys.exit(main())
