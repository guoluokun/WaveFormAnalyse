from __future__ import annotations

from wfa import qt_compat


def test_explicit_platform_wins(monkeypatch):
    monkeypatch.setattr(qt_compat.platform, "system", lambda: "Linux")
    env = {"QT_QPA_PLATFORM": "offscreen", "DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0"}
    name, explicit = qt_compat.choose_qt_platform("auto", env, ("xcb", "wayland", "offscreen"))
    assert name == "offscreen"
    assert explicit is True


def test_wayland_preferred_on_wayland_session(monkeypatch):
    monkeypatch.setattr(qt_compat.platform, "system", lambda: "Linux")
    monkeypatch.setattr(qt_compat, "is_wsl", lambda: False)
    env = {"DISPLAY": ":1", "WAYLAND_DISPLAY": "wayland-0", "XDG_SESSION_TYPE": "wayland"}
    name, explicit = qt_compat.choose_qt_platform("auto", env, ("xcb", "wayland"))
    assert name == "wayland"
    assert explicit is False


def test_xcb_used_on_x11(monkeypatch):
    monkeypatch.setattr(qt_compat.platform, "system", lambda: "Linux")
    monkeypatch.setattr(qt_compat, "is_wsl", lambda: False)
    env = {"DISPLAY": ":0", "XDG_SESSION_TYPE": "x11"}
    name, explicit = qt_compat.choose_qt_platform("auto", env, ("xcb",))
    assert name == "xcb"
    assert explicit is False


def test_wsl_prefers_wayland(monkeypatch):
    monkeypatch.setattr(qt_compat.platform, "system", lambda: "Linux")
    monkeypatch.setattr(qt_compat, "is_wsl", lambda: True)
    env = {"DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0"}
    name, _ = qt_compat.choose_qt_platform("auto", env, ("xcb", "wayland"))
    assert name == "wayland"


def test_no_display_reported_before_qt_import(monkeypatch):
    monkeypatch.setattr(qt_compat.platform, "system", lambda: "Linux")
    monkeypatch.setattr(qt_compat, "is_wsl", lambda: False)
    monkeypatch.setattr(qt_compat, "_pyqt5_plugin_dir", lambda: None)
    diag = qt_compat.diagnose_qt("auto", {})
    assert not diag.ok
    assert any("DISPLAY" in item for item in diag.warnings)
