"""频域分析：幅度谱、功率谱密度与 Butterworth 数字滤波。

时间单位统一为 ns，频率输出单位为 MHz。
"""

from __future__ import annotations

import numpy as np
from scipy.signal import butter, sosfiltfilt, welch, get_window

from .params import FilterParams, SpectrumParams

_NS_TO_S = 1e-9


def sampling_rate_mhz(dt_ns: float) -> float:
    return 1e3 / dt_ns if dt_ns > 0 else 0.0


def amplitude_spectrum(y: np.ndarray, dt_ns: float,
                       p: SpectrumParams) -> tuple[np.ndarray, np.ndarray]:
    """单边幅度谱：返回 (频率 MHz, 幅度 ADC)。"""
    y = np.asarray(y, dtype=np.float64)
    n = y.size
    if n < 4 or dt_ns <= 0:
        return np.zeros(0), np.zeros(0)
    win = get_window(p.window, n) if p.window != "boxcar" else np.ones(n)
    yw = (y - y.mean()) * win
    spec = np.fft.rfft(yw)
    # 归一化到幅度：补偿窗函数增益
    amp = 2.0 * np.abs(spec) / max(win.sum(), 1e-12)
    freq_hz = np.fft.rfftfreq(n, d=dt_ns * _NS_TO_S)
    return freq_hz / 1e6, amp


def psd(y: np.ndarray, dt_ns: float, p: SpectrumParams) -> tuple[np.ndarray, np.ndarray]:
    """Welch 功率谱密度：返回 (频率 MHz, PSD ADC^2/Hz)。"""
    y = np.asarray(y, dtype=np.float64)
    if y.size < 8 or dt_ns <= 0:
        return np.zeros(0), np.zeros(0)
    nperseg = int(np.clip(p.nperseg, 8, y.size))
    freq_hz, pxx = welch(y - y.mean(), fs=1.0 / (dt_ns * _NS_TO_S),
                         window=p.window, nperseg=nperseg)
    return freq_hz / 1e6, pxx


def apply_filter(y: np.ndarray, dt_ns: float, p: FilterParams) -> np.ndarray:
    """零相位 Butterworth 滤波（sosfiltfilt，不引入群延迟）。"""
    y = np.asarray(y, dtype=np.float64)
    if p.kind == "none" or y.size < 12 or dt_ns <= 0:
        return y

    nyq_mhz = sampling_rate_mhz(dt_ns) / 2.0
    if nyq_mhz <= 0:
        return y

    def norm(f_mhz: float) -> float:
        return float(np.clip(f_mhz / nyq_mhz, 1e-6, 0.999))

    order = int(np.clip(p.order, 1, 10))
    if p.kind == "lowpass":
        sos = butter(order, norm(p.f_high), btype="lowpass", output="sos")
    elif p.kind == "highpass":
        sos = butter(order, norm(p.f_low), btype="highpass", output="sos")
    elif p.kind in ("bandpass", "bandstop"):
        lo, hi = norm(p.f_low), norm(p.f_high)
        if lo >= hi:
            return y
        sos = butter(order, [lo, hi], btype=p.kind, output="sos")
    else:
        raise ValueError(f"未知滤波类型: {p.kind}")

    padlen = min(3 * (sos.shape[0] * 2), y.size - 1)
    return sosfiltfilt(sos, y, padlen=max(0, padlen))
