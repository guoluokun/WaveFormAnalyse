"""Qt GUI environment detection and Linux/WSL compatibility helpers.

The module deliberately does not import Qt.  It is used before QApplication is
created so Linux platform-plugin failures can be diagnosed without Qt aborting
the Python process.
"""

from __future__ import annotations

import importlib.util
import os
import platform
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, MutableMapping


LINUX_GUI_PACKAGES = (
    "libgl1", "libegl1", "libfontconfig1", "libfreetype6", "libx11-6",
    "libx11-xcb1", "libxext6", "libxi6", "libxrender1", "libsm6", "libice6",
    "libxcb1", "libxcb-cursor0", "libxcb-glx0", "libxcb-icccm4",
    "libxcb-image0", "libxcb-keysyms1", "libxcb-randr0",
    "libxcb-render-util0", "libxcb-render0", "libxcb-shape0", "libxcb-shm0",
    "libxcb-sync1", "libxcb-xfixes0", "libxcb-xinerama0", "libxcb-xkb1",
    "libxkbcommon0", "libxkbcommon-x11-0", "libwayland-client0",
    "libwayland-cursor0", "libwayland-egl1",
)


@dataclass
class QtDiagnostics:
    system: str
    is_wsl: bool
    session_type: str
    display: str
    wayland_display: str
    selected_platform: str
    explicit_platform: bool
    plugin_dir: str = ""
    available_plugins: tuple[str, ...] = field(default_factory=tuple)
    plugin_file: str = ""
    missing_libraries: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return not self.missing_libraries and not any(
            w.startswith("ERROR:") for w in self.warnings
        )


def is_wsl() -> bool:
    if platform.system() != "Linux":
        return False
    text = " ".join((platform.release(), platform.version())).lower()
    if "microsoft" in text or "wsl" in text:
        return True
    try:
        return "microsoft" in Path("/proc/version").read_text(errors="ignore").lower()
    except OSError:
        return False


def _pyqt5_plugin_dir() -> Path | None:
    spec = importlib.util.find_spec("PyQt5")
    if spec is None or not spec.submodule_search_locations:
        return None
    base = Path(next(iter(spec.submodule_search_locations)))
    for rel in ("Qt5/plugins/platforms", "Qt/plugins/platforms", "plugins/platforms"):
        path = base / rel
        if path.is_dir():
            return path
    return None


def _plugin_names(plugin_dir: Path | None) -> tuple[str, ...]:
    if plugin_dir is None:
        return ()
    names: set[str] = set()
    for path in plugin_dir.iterdir():
        name = path.name.lower()
        if "xcb" in name:
            names.add("xcb")
        if "wayland-generic" in name:
            names.add("wayland")
        if "wayland-egl" in name:
            names.add("wayland-egl")
        if "offscreen" in name:
            names.add("offscreen")
        if "minimal" in name and "minimalegl" not in name:
            names.add("minimal")
    return tuple(sorted(names))


def _plugin_file(plugin_dir: Path | None, qpa: str) -> Path | None:
    if plugin_dir is None:
        return None
    patterns = {
        "xcb": ("libqxcb.so",),
        "wayland": ("libqwayland-generic.so", "libqwayland-egl.so"),
        "wayland-egl": ("libqwayland-egl.so",),
        "offscreen": ("libqoffscreen.so",),
        "minimal": ("libqminimal.so",),
    }
    for name in patterns.get(qpa, ()):
        path = plugin_dir / name
        if path.exists():
            return path
    return None


def _missing_link_libraries(path: Path | None) -> tuple[str, ...]:
    if path is None or platform.system() != "Linux":
        return ()
    try:
        proc = subprocess.run(
            ["ldd", str(path)], capture_output=True, text=True, timeout=5, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return ()
    missing = []
    for line in (proc.stdout + "\n" + proc.stderr).splitlines():
        if "=> not found" in line:
            missing.append(line.split("=>", 1)[0].strip())
    return tuple(sorted(set(missing)))


def choose_qt_platform(
    requested: str = "auto",
    env: Mapping[str, str] | None = None,
    available_plugins: tuple[str, ...] | None = None,
) -> tuple[str, bool]:
    """Return (platform, explicit).

    An explicit QT_QPA_PLATFORM always wins.  On Linux, Wayland is preferred
    when a Wayland compositor is available and the PyQt wheel contains the
    Wayland plugin; X11/xcb is otherwise used when DISPLAY is available.
    Empty platform means "let Qt use the native default" (Windows/macOS).
    """
    env = os.environ if env is None else env
    if requested != "auto":
        return requested, True
    explicit = env.get("QT_QPA_PLATFORM", "").strip()
    if explicit:
        return explicit.split(":", 1)[0], True
    if platform.system() != "Linux":
        return "", False

    plugins = set(available_plugins or ())
    wayland = bool(env.get("WAYLAND_DISPLAY"))
    x11 = bool(env.get("DISPLAY"))
    session = env.get("XDG_SESSION_TYPE", "").lower()

    # Native Ubuntu GNOME Wayland and WSLg both expose WAYLAND_DISPLAY.  Qt5
    # otherwise often defaults to xcb, which is exactly the failure mode this
    # launcher is intended to avoid.
    if wayland and "wayland" in plugins and (session == "wayland" or is_wsl() or not x11):
        return "wayland", False
    if x11 and "xcb" in plugins:
        return "xcb", False
    if wayland and "wayland" in plugins:
        return "wayland", False
    if x11:
        return "xcb", False
    return "", False


def diagnose_qt(
    requested: str = "auto",
    env: Mapping[str, str] | None = None,
) -> QtDiagnostics:
    env = os.environ if env is None else env
    system = platform.system()
    plugin_dir = _pyqt5_plugin_dir() if system == "Linux" else None
    plugins = _plugin_names(plugin_dir)
    selected, explicit = choose_qt_platform(requested, env, plugins)
    selected_file = _plugin_file(plugin_dir, selected) if selected else None
    missing = _missing_link_libraries(selected_file)
    warnings: list[str] = []

    if system == "Linux":
        if not env.get("DISPLAY") and not env.get("WAYLAND_DISPLAY") and selected not in {"offscreen", "minimal"}:
            warnings.append("ERROR: 未检测到 DISPLAY 或 WAYLAND_DISPLAY，当前会话不能显示桌面 GUI。")
        if selected in {"xcb", "wayland", "wayland-egl"} and plugin_dir is None:
            warnings.append("ERROR: 未找到 PyQt5 的 Qt platform plugins 目录，请重新安装 PyQt5。")
        elif selected and selected not in plugins and selected not in {"wayland-egl"}:
            warnings.append(f"ERROR: 当前 PyQt5 未提供 Qt platform plugin: {selected}")
        if selected == "xcb" and env.get("WAYLAND_DISPLAY") and not explicit:
            warnings.append("当前会话提供 Wayland，但未找到可用的 Qt Wayland 插件，因此回退到 xcb。")
        if missing:
            warnings.append("ERROR: Qt platform plugin 存在，但其系统动态库依赖不完整。")

    return QtDiagnostics(
        system=system,
        is_wsl=is_wsl(),
        session_type=env.get("XDG_SESSION_TYPE", ""),
        display=env.get("DISPLAY", ""),
        wayland_display=env.get("WAYLAND_DISPLAY", ""),
        selected_platform=selected or "native-default",
        explicit_platform=explicit,
        plugin_dir=str(plugin_dir or ""),
        available_plugins=plugins,
        plugin_file=str(selected_file or ""),
        missing_libraries=missing,
        warnings=tuple(warnings),
    )


def apply_qt_environment(
    requested: str = "auto",
    env: MutableMapping[str, str] | None = None,
) -> QtDiagnostics:
    env = os.environ if env is None else env
    diag = diagnose_qt(requested, env)
    selected = diag.selected_platform
    if selected != "native-default" and not diag.explicit_platform:
        env["QT_QPA_PLATFORM"] = selected
    return diag


def linux_install_command() -> str:
    return "sudo apt update && sudo apt install -y " + " ".join(LINUX_GUI_PACKAGES)


def format_diagnostics(diag: QtDiagnostics) -> str:
    lines = [
        "WaveFormAnalyse Qt diagnostics",
        f"  System: {diag.system}{' (WSL)' if diag.is_wsl else ''}",
        f"  XDG_SESSION_TYPE: {diag.session_type or '(unset)'}",
        f"  DISPLAY: {diag.display or '(unset)'}",
        f"  WAYLAND_DISPLAY: {diag.wayland_display or '(unset)'}",
        f"  Selected Qt platform: {diag.selected_platform}",
    ]
    if diag.plugin_dir:
        lines.append(f"  Qt plugin dir: {diag.plugin_dir}")
        lines.append("  Available plugins: " + (", ".join(diag.available_plugins) or "(none detected)"))
    if diag.plugin_file:
        lines.append(f"  Selected plugin file: {diag.plugin_file}")
    if diag.missing_libraries:
        lines.append("  Missing libraries: " + ", ".join(diag.missing_libraries))
    for warning in diag.warnings:
        lines.append("  " + warning)
    if diag.system == "Linux" and not diag.ok:
        lines.extend(("", "Recommended Ubuntu/Debian runtime dependencies:", "  " + linux_install_command()))
    return "\n".join(lines)
