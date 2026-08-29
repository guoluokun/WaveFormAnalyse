from __future__ import annotations

import os

from wfa import qt_compat


def test_explicit_platform_wins(monkeypatch):
    monkeypatch.setattr(qt_compat.platform, "system", lambda: "Linux")
    env = {"QT_QPA_PLATFORM": "offscreen", "DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0"}
    platform_name, explicit = qt_compat.choose_qt_platform("auto", env, ("xcb", "wayland", "offscreen"))
    assert platform_name == "offscreen"
    assert explicit is True


def test_wayland_preferred_on_wayland_session(monkeypatch):
    monkeypatch.setattr(qt_compat.platform, "system", lambda: "Linux")
    monkeypatch.setattr(qt_compat, "is_wsl", lambda: False)
    env = {"DISPLAY": ":1", "WAYLAND_DISPLAY": "wayland-0", "XDG_SESSION_TYPE": "wayland"}
    platform_name, explicit = qt_compat.choose_qt_platform("auto", env, ("xcb", "wayland"))
    assert platform_name == "wayland"
    assert explicit is False


def test_xcb_used_on_x11(monkeypatch):
    monkeypatch.setattr(qt_compat.platform, "system", lambda: "Linux")
    monkeypatch.setattr(qt_compat, "is_wsl", lambda: False)
    env = {"DISPLAY": ":0", "XDG_SESSION_TYPE": "x11"}
    platform_name, explicit = qt_compat.choose_qt_platform("auto", env, ("xcb",))
    assert platform_name == "xcb"
    assert explicit is False


def test_wsl_prefers_wayland_when_wslg_is_available(monkeypatch):
    monkeypatch.setattr(qt_compat.platform, "system", lambda: "Linux")
    monkeypatch.setattr(qt_compat, "is_wsl", lambda: True)
    env = {"DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0", "XDG_SESSION_TYPE": ""}
    platform_name, _ = qt_compat.choose_qt_platform("auto", env, ("xcb", "wayland"))
    assert platform_name == "wayland"


def test_no_display_is_reported_before_qt_import(monkeypatch):
    monkeypatch.setattr(qt_compat.platform, "system", lambda: "Linux")
    monkeypatch.setattr(qt_compat, "is_wsl", lambda: False)
    monkeypatch.setattr(qt_compat, "_pyqt5_plugin_dir", lambda: None)
    diag = qt_compat.diagnose_qt("auto", {})
    assert not diag.ok
    assert any("DISPLAY" in w for w in diag.warnings)


def test_apply_does_not_override_user_qpa(monkeypatch):
    monkeypatch.setattr(qt_compat.platform, "system", lambda: "Linux")
    monkeypatch.setattr(qt_compat, "is_wsl", lambda: False)
    monkeypatch.setattr(qt_compat, "_pyqt5_plugin_dir", lambda: None)
    env = {"QT_QPA_PLATFORM": "offscreen"}
    qt_compat.apply_qt_environment("auto", env)
    assert env["QT_QPA_PLATFORM"] == "offscreen"
