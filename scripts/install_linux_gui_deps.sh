#!/usr/bin/env bash
set -euo pipefail

if ! command -v apt-get >/dev/null 2>&1; then
  echo "This helper supports Ubuntu/Debian systems with apt-get." >&2
  exit 1
fi

sudo apt-get update
sudo apt-get install -y \
  libgl1 libegl1 libfontconfig1 libfreetype6 \
  libx11-6 libx11-xcb1 libxext6 libxi6 libxrender1 libsm6 libice6 \
  libxcb1 libxcb-cursor0 libxcb-glx0 libxcb-icccm4 libxcb-image0 \
  libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-render0 \
  libxcb-shape0 libxcb-shm0 libxcb-sync1 libxcb-xfixes0 \
  libxcb-xinerama0 libxcb-xkb1 libxkbcommon0 libxkbcommon-x11-0 \
  libwayland-client0 libwayland-cursor0 libwayland-egl1

echo "Linux Qt runtime dependencies installed."
echo "Run: python main.py --qt-diagnostics"
