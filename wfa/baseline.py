"""基线估计、噪声 sigma 估计与阈值卡噪声。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import median_filter

from .params import BaselineParams, ThresholdParams


def mad_sigma(x: np.ndarray) -> float:
    """用中位数绝对偏差估计高斯 sigma，对脉冲不敏感。"""
    x = np.asarray(x, dtype=np.float64)
    if x.size == 0:
        return 0.0
    return float(1.4826 * np.median(np.abs(x - np.median(x))))


@dataclass
class BaselineResult:
    level: np.ndarray          # 与波形同长的基线（常数基线已广播）
    sigma: float               # 基线噪声 RMS
    method: str
    is_constant: bool


def estimate_baseline(y: np.ndarray, p: BaselineParams) -> BaselineResult:
    """估计基线与噪声 sigma。"""
    y = np.asarray(y, dtype=np.float64)
    n = y.size
    if n == 0:
        return BaselineResult(np.zeros(0), 0.0, p.method, True)

    if p.method == "pre":
        k = int(np.clip(p.n_pre, 1, n))
        seg = y[:k]
        level = float(np.mean(seg))
        sigma = float(np.std(seg, ddof=1)) if seg.size > 1 else 0.0
        return BaselineResult(np.full(n, level), sigma, p.method, True)

    if p.method == "median":
        level = float(np.median(y))
        return BaselineResult(np.full(n, level), mad_sigma(y), p.method, True)

    if p.method == "sigma_clip":
        mask = np.ones(n, dtype=bool)
        level = float(np.median(y))
        sigma = mad_sigma(y)
        for _ in range(max(1, int(p.n_iter))):
            level = float(np.mean(y[mask])) if mask.any() else float(np.median(y))
            sigma = float(np.std(y[mask], ddof=1)) if mask.sum() > 1 else mad_sigma(y)
            if sigma <= 0:
                break
            new_mask = np.abs(y - level) < p.clip_k * sigma
            if new_mask.sum() < 8 or np.array_equal(new_mask, mask):
                break
            mask = new_mask
        return BaselineResult(np.full(n, level), sigma, p.method, True)

    if p.method == "moving":
        w = int(np.clip(p.window, 3, max(3, n)))
        if w % 2 == 0:
            w += 1
        level = median_filter(y, size=w, mode="nearest").astype(np.float64)
        return BaselineResult(level, mad_sigma(y - level), p.method, False)

    raise ValueError(f"未知基线方法: {p.method}")


def threshold_value(sigma: float, p: ThresholdParams) -> float:
    """按「n 倍 sigma」或「绝对 ADC」给出阈值（作用于基线校正、极性归一后的信号）。"""
    if p.mode == "abs":
        return float(p.abs_adc)
    if p.mode == "sigma":
        return float(p.n_sigma * sigma)
    raise ValueError(f"未知阈值模式: {p.mode}")


def to_signal(y: np.ndarray, level: np.ndarray, polarity: int) -> np.ndarray:
    """基线校正并统一极性，输出后脉冲总是正向。"""
    return (np.asarray(y, dtype=np.float64) - level) * (1 if polarity >= 0 else -1)


def gate(signal: np.ndarray, thr: float) -> tuple[np.ndarray, np.ndarray]:
    """阈值卡噪声：返回 (过阈掩码, 门控后波形)。低于阈值的采样点置 0。"""
    mask = signal >= thr
    gated = np.where(mask, signal, 0.0)
    return mask, gated
