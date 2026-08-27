"""波形平滑与求导。

求导单位为 ADC/ns（dt 以 ns 为单位传入）。
"""

from __future__ import annotations

import numpy as np
from scipy.signal import savgol_filter

from .params import DerivParams, SmoothParams


def _odd_window(w: int, n: int, minimum: int = 3) -> int:
    w = int(np.clip(w, minimum, max(minimum, n)))
    if w % 2 == 0:
        w -= 1
    return max(minimum, w)


def smooth(y: np.ndarray, p: SmoothParams) -> np.ndarray:
    """可选平滑，求导前使用可显著压制噪声放大。"""
    y = np.asarray(y, dtype=np.float64)
    if p.method == "none" or y.size < 3:
        return y
    if p.method == "movavg":
        w = _odd_window(p.window, y.size)
        kernel = np.ones(w) / w
        return np.convolve(y, kernel, mode="same")
    if p.method == "savgol":
        w = _odd_window(p.window, y.size, minimum=5)
        poly = int(np.clip(p.poly, 1, w - 1))
        return savgol_filter(y, w, poly)
    raise ValueError(f"未知平滑方法: {p.method}")


def derivative(y: np.ndarray, dt: float, p: DerivParams) -> np.ndarray:
    """求导，返回与输入等长的导数序列。"""
    y = np.asarray(y, dtype=np.float64)
    if y.size < 3 or dt <= 0:
        return np.zeros_like(y)
    order = int(np.clip(p.order, 1, 2))

    if p.method == "central":
        out = np.gradient(y, dt)
        if order == 2:
            out = np.gradient(out, dt)
        return out

    if p.method == "forward":
        out = y
        for _ in range(order):
            d = np.diff(out) / dt
            out = np.concatenate([d, d[-1:]])
        return out

    if p.method == "savgol":
        w = _odd_window(p.window, y.size, minimum=5)
        poly = int(np.clip(p.poly, order + 1, w - 1))
        return savgol_filter(y, w, poly, deriv=order, delta=dt)

    raise ValueError(f"未知求导方法: {p.method}")
