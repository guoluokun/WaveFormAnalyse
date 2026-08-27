"""波形分析程序入口。

用法:
    python main.py [可选的 root 文件路径]
"""

from __future__ import annotations

import sys

from pyqtgraph.Qt import QtWidgets

from wfa.ui import MainWindow


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow()
    win.show()

    if len(sys.argv) > 1:
        win.load_path(sys.argv[1])

    return app.exec() if hasattr(app, "exec") else app.exec_()


if __name__ == "__main__":
    sys.exit(main())
