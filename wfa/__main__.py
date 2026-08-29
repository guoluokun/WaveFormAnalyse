"""允许 `python -m wfa [root-file]` 启动 GUI。"""

from __future__ import annotations

import sys


def main() -> int:
    # 复用顶层 main.py 的参数解析和 Qt 环境诊断，保证两种启动方式行为一致。
    from main import main as app_main
    return app_main()


if __name__ == "__main__":
    sys.exit(main())
