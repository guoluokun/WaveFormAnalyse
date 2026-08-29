# Linux / Ubuntu / WSL2 GUI compatibility

WaveFormAnalyse uses PyQt5 + pyqtgraph for the GUI. The numerical stack (`numpy`, `scipy`, `uproot`, `awkward`) is portable; most Linux failures come from Qt platform-plugin runtime dependencies.

## Ubuntu/Debian

Install the Python environment first, then the Qt runtime libraries:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
bash scripts/install_linux_gui_deps.sh
```

Run diagnostics:

```bash
python main.py --qt-diagnostics
```

The launcher detects the graphics session before importing PyQt5:

- GNOME Wayland: prefers `wayland` when the plugin exists.
- Linux X11: uses `xcb`.
- WSL2 + WSLg: prefers `wayland` when `WAYLAND_DISPLAY` is present.
- Windows/macOS: leaves platform selection to Qt.
- Existing `QT_QPA_PLATFORM` is respected.

If `xcb` is selected, the launcher runs `ldd` on the PyQt5 xcb plugin and reports missing `.so` libraries before `QApplication` is created. This prevents the common Qt abort/core-dump path where `libqxcb.so` is found but cannot be loaded.

Manual troubleshooting:

```bash
python main.py --qt-platform wayland --qt-diagnostics
python main.py --qt-platform xcb --qt-diagnostics
QT_DEBUG_PLUGINS=1 python main.py --qt-platform xcb
```

## WSL2 / WSLg

On Windows:

```powershell
wsl --update
wsl --shutdown
```

Inside WSL:

```bash
echo $DISPLAY
echo $WAYLAND_DISPLAY
ls /mnt/wslg
python main.py --qt-diagnostics
```

For performance, keep the project and large ROOT files in the Linux filesystem (`~/projects`, `~/data`) instead of `/mnt/c/...` when possible.

## Headless systems

For CI or diagnostics without a desktop session:

```bash
python main.py --qt-platform offscreen --qt-diagnostics
```

`offscreen` is not intended for normal interactive use.
