"""统一分析流程：单事件分析 + 多事件批量扫描。

处理顺序：
原始波形 -> 可选数字滤波 -> 基线/sigma 估计 -> 极性归一 -> 阈值卡噪声
        -> 可选平滑 -> 求导 -> 寻峰 -> 可选波形拟合 -> 频谱
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import baseline as bl
from . import derivative as dv
from . import fitting as ft
from . import peaks as pk
from . import spectrum as sp
from .io_root import WaveformSource
from .params import AnalysisParams


@dataclass
class AnalysisResult:
    t: np.ndarray
    raw: np.ndarray
    filtered: np.ndarray
    baseline: np.ndarray
    sigma: float
    threshold: float
    signal: np.ndarray
    gated: np.ndarray
    over_threshold: np.ndarray
    smoothed: np.ndarray
    deriv: np.ndarray
    peak_list: list = field(default_factory=list)
    fit: ft.FitResult | None = None
    freq_mhz: np.ndarray = field(default_factory=lambda: np.zeros(0))
    amp_spec: np.ndarray = field(default_factory=lambda: np.zeros(0))
    psd_freq_mhz: np.ndarray = field(default_factory=lambda: np.zeros(0))
    psd_val: np.ndarray = field(default_factory=lambda: np.zeros(0))
    dt_ns: float = 1.0
    polarity: int = 1
    dc_offset: float = 0.0


def analyze(t: np.ndarray, y: np.ndarray, p: AnalysisParams) -> AnalysisResult:
    t = np.asarray(t, dtype=np.float64)
    raw = np.asarray(y, dtype=np.float64)
    dt = float(t[1] - t[0]) if t.size > 1 else 1.0

    filtered = sp.apply_filter(raw, dt, p.filt)
    dc_offset = float(np.mean(raw) - np.mean(filtered)) if raw.size else 0.0
    base = bl.estimate_baseline(filtered, p.baseline)
    signal = bl.to_signal(filtered, base.level, p.polarity)
    thr = bl.threshold_value(base.sigma, p.threshold)
    mask, gated = bl.gate(signal, thr)

    smoothed = dv.smooth(signal, p.smooth)
    deriv = dv.derivative(smoothed, dt, p.deriv)

    if p.peaks.source == "derivative":
        peak_list = pk.find_derivative_peaks(t, deriv, smoothed, p.threshold.n_sigma, p.peaks)
    elif p.peaks.source == "zero_cross":
        peak_list = pk.find_zero_crossing_peaks(t, smoothed, deriv, thr, base.sigma, p.threshold.n_sigma, p.peaks)
    else:
        peak_list = pk.find_signal_peaks(t, smoothed, thr, base.sigma, p.peaks)

    fit_source = smoothed if p.fit.source == "smoothed" else signal
    fit_result = ft.fit_waveform(t, fit_source, p.fit, sigma=base.sigma)

    freq, amp = sp.amplitude_spectrum(signal, dt, p.spectrum)
    pf, pv = sp.psd(signal, dt, p.spectrum)

    return AnalysisResult(
        t=t, raw=raw, filtered=filtered, baseline=base.level, sigma=base.sigma,
        threshold=thr, signal=signal, gated=gated, over_threshold=mask,
        smoothed=smoothed, deriv=deriv, peak_list=peak_list, fit=fit_result,
        freq_mhz=freq, amp_spec=amp, psd_freq_mhz=pf, psd_val=pv, dt_ns=dt,
        polarity=1 if p.polarity >= 0 else -1, dc_offset=dc_offset,
    )


@dataclass
class ScanResult:
    n_events: int
    amplitudes: np.ndarray
    charges: np.ndarray
    times: np.ndarray
    n_peaks: np.ndarray
    baselines: np.ndarray
    sigmas: np.ndarray


def scan(source: WaveformSource, p: AnalysisParams, n_events: int,
         start: int = 0, progress=None) -> ScanResult:
    """遍历多个事件，汇总峰参数用于幅度谱/电荷谱统计。

    progress: 可选回调 ``progress(done, total) -> bool``，返回 False 则提前终止。
    """
    stop = min(source.n_events, start + max(0, n_events))
    amps, chgs, tms, npk, bases, sigs = [], [], [], [], [], []
    total = max(1, stop - start)

    for n, i in enumerate(range(start, stop)):
        t, y = source.get_event(i)
        r = analyze(t, y, p)
        npk.append(len(r.peak_list))
        bases.append(float(np.mean(r.baseline)))
        sigs.append(r.sigma)
        for peak in r.peak_list:
            amps.append(peak.amplitude)
            chgs.append(peak.area_adc_ns)
            tms.append(peak.time_ns)
        if progress is not None and (n % 20 == 0 or n == total - 1):
            if progress(n + 1, total) is False:
                break

    return ScanResult(
        n_events=len(npk),
        amplitudes=np.asarray(amps, dtype=np.float64),
        charges=np.asarray(chgs, dtype=np.float64),
        times=np.asarray(tms, dtype=np.float64),
        n_peaks=np.asarray(npk, dtype=np.int64),
        baselines=np.asarray(bases, dtype=np.float64),
        sigmas=np.asarray(sigs, dtype=np.float64),
    )
