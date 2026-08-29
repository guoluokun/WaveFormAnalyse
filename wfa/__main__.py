"""允许 `python -m wfa [root-file]` 启动 GUI。"""

from __future__ import annotations

import sys

from .app import main


if __name__ == "__main__":
    sys.exit(main())
