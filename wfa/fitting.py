"""通用波形拟合模型与残差分析。

目标不是针对某一种探测器，而是提供几个常见、易理解的模型，方便快速验证
波形形状、拟合区间和预处理算法。所有拟合都作用于已经完成基线校正和极性
归一后的信号。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import curve_fit

from .params import FitParams


@dataclass
class FitResult:
    success: bool
    model: str
    x: np.ndarray
    y_fit: np.ndarray
    residual: np.ndarray
    param_names: tuple[str, ...] = field(default_factory=tuple)
    params: np.ndarray = field(default_factory=lambda: np.zeros(0))
    errors: np.ndarray = field(default_factory=lambda: np.zeros(0))
    chi2: float = float("nan")
    ndf: int = 0
    reduced_chi2: float = float("nan")
    rms: float = float("nan")
    message: str = ""


def gaussian(x, amplitude, center, sigma):
    sigma = max(abs(float(sigma)), 1e-12)
    return amplitude * np.exp(-0.5 * ((np.asarray(x) - center) / sigma) ** 2)


def exponential(x, amplitude, t0, tau):
    tau = max(abs(float(tau)), 1e-12)
    x = np.asarray(x, dtype=np.float64)
    z = np.maximum(x - t0, 0.0)
    return np.where(x >= t0, amplitude * np.exp(-z / tau), 0.0)


def double_exponential(x, amplitude, t0, tau_rise, tau_decay):
    """快上升慢衰减脉冲，amplitude 定义为模型峰值，与传入 x 范围无关。"""
    tr = max(abs(float(tau_rise)), 1e-12)
    td = max(abs(float(tau_decay)), tr * (1.0 + 1e-9))
    x = np.asarray(x, dtype=np.float64)
    z = np.maximum(x - t0, 0.0)
    shape = np.where(x >= t0, np.exp(-z / td) - np.exp(-z / tr), 0.0)
    # 解析峰位，避免用当前 x 数组的最大值归一而导致拟合区间改变模型定义。
    z_peak = tr * td / (td - tr) * np.log(td / tr)
    peak = np.exp(-z_peak / td) - np.exp(-z_peak / tr)
    return amplitude * shape / max(float(peak), 1e-12)


def _fit_window(t: np.ndarray, y: np.ndarray, p: FitParams):
    if p.x_min_ns == 0.0 and p.x_max_ns == 0.0:
        mask = np.ones(t.size, dtype=bool)
    else:
        lo, hi = sorted((p.x_min_ns, p.x_max_ns))
        mask = (t >= lo) & (t <= hi)
    return t[mask], y[mask], mask


def _initial_guess(model: str, x: np.ndarray, y: np.ndarray):
    if x.size == 0:
        raise ValueError("拟合区间为空")
    amp = max(float(np.max(y)), 1e-9)
    i = int(np.argmax(y))
    center = float(x[i])
    span = max(float(x[-1] - x[0]), 1e-9)
    dt = max(float(np.median(np.diff(x))) if x.size > 1 else 1.0, 1e-9)

    if model == "gaussian":
        return gaussian, ("amplitude", "center_ns", "sigma_ns"), [amp, center, max(span / 12.0, dt)], ([0.0, x[0], dt / 10.0], [np.inf, x[-1], max(span * 2.0, dt)])
    if model == "exponential":
        return exponential, ("amplitude", "t0_ns", "tau_ns"), [amp, center, max(span / 5.0, dt)], ([0.0, x[0], dt / 10.0], [np.inf, x[-1], max(span * 10.0, dt)])
    if model == "double_exp":
        t0 = max(float(x[0]), center - span / 20.0)
        return double_exponential, ("amplitude", "t0_ns", "tau_rise_ns", "tau_decay_ns"), [amp, t0, max(span / 100.0, dt), max(span / 10.0, 2 * dt)], ([0.0, x[0], dt / 20.0, dt / 10.0], [np.inf, x[-1], max(span, dt), max(span * 10.0, dt)])
    raise ValueError(f"未知拟合模型: {model}")


def fit_waveform(t: np.ndarray, y: np.ndarray, p: FitParams, sigma: float = 0.0) -> FitResult:
    """拟合一条波形并返回拟合曲线、残差和基本质量指标。"""
    t = np.asarray(t, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    if not p.enabled:
        return FitResult(False, p.model, t, np.full_like(y, np.nan), np.full_like(y, np.nan), message="拟合未启用")

    try:
        xw, yw, mask = _fit_window(t, y, p)
        min_points = 6 if p.model == "double_exp" else 5
        if xw.size < min_points:
            raise ValueError(f"拟合区间至少需要 {min_points} 个采样点")
        func, names, p0, bounds = _initial_guess(p.model, xw, yw)
        popt, pcov = curve_fit(func, xw, yw, p0=p0, bounds=bounds, maxfev=max(1000, int(p.maxfev)))
        perr = np.sqrt(np.maximum(np.diag(pcov), 0.0)) if pcov.ndim == 2 else np.full(len(popt), np.nan)
        y_full = np.full_like(y, np.nan)
        y_full[mask] = func(xw, *popt)
        residual = np.full_like(y, np.nan)
        residual[mask] = yw - y_full[mask]
        r = residual[mask]
        rms = float(np.sqrt(np.mean(r * r)))
        ndf = max(0, int(xw.size - len(popt)))
        noise = float(sigma) if sigma > 0 else rms
        chi2 = float(np.sum((r / noise) ** 2)) if noise > 0 else float("nan")
        red = chi2 / ndf if ndf > 0 and np.isfinite(chi2) else float("nan")
        return FitResult(True, p.model, t, y_full, residual, names, np.asarray(popt), np.asarray(perr), chi2, ndf, red, rms, "OK")
    except Exception as exc:
        return FitResult(False, p.model, t, np.full_like(y, np.nan), np.full_like(y, np.nan), message=str(exc))


def format_parameters(result: FitResult) -> str:
    if not result.success:
        return result.message
    parts = []
    for name, value, err in zip(result.param_names, result.params, result.errors):
        if np.isfinite(err):
            parts.append(f"{name}={value:.5g}±{err:.2g}")
        else:
            parts.append(f"{name}={value:.5g}")
    return ", ".join(parts)
