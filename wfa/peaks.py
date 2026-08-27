"""寻峰与峰参数提取。

输入约定：``signal`` 已完成基线校正与极性归一（脉冲为正向）。

提供三种寻峰依据：
- ``find_signal_peaks``：信号波形局部极大（scipy.find_peaks），通用
- ``find_derivative_peaks``：导数极大（最陡上升沿），适合定位堆积脉冲起点
- ``find_zero_crossing_peaks``：导数由正变负的过零点，峰位由插值给出，
  可达亚采样点精度，对平缓峰顶的定时最稳
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
from scipy.signal import find_peaks, peak_widths

from .baseline import mad_sigma
from .params import PeakParams

_trapz = getattr(np, "trapezoid", np.trapz)

COLUMNS = [
    ("index", "采样点"),
    ("time_ns", "峰位 (ns)"),
    ("amplitude", "幅度 (ADC)"),
    ("prominence", "凸起 (ADC)"),
    ("fwhm_ns", "FWHM (ns)"),
    ("t_start_ns", "起点 (ns)"),
    ("t_end_ns", "终点 (ns)"),
    ("area_adc_ns", "积分电荷 (ADC·ns)"),
    ("rise_ns", "上升时间10-90 (ns)"),
    ("cfd50_ns", "CFD50 时刻 (ns)"),
]


@dataclass
class Peak:
    index: int
    time_ns: float
    amplitude: float
    prominence: float
    fwhm_ns: float
    t_start_ns: float
    t_end_ns: float
    area_adc_ns: float
    rise_ns: float
    cfd50_ns: float


# ------------------------------------------------------------------ 公共工具

def _walk_to_level(y: np.ndarray, start: int, step: int, level: float,
                   rise_tol: float) -> int:
    """从峰位向一侧行走，确定积分边界。

    终止条件：采样值回落到 level 以下，或出现新的上升沿（相邻点比当前点高出
    rise_tol，说明遇到堆积脉冲的谷底），或到达波形边界。
    """
    i = int(start)
    n = y.size
    while 0 <= i + step < n:
        nxt = y[i + step]
        if nxt < level:
            break
        if nxt > y[i] + rise_tol:
            break
        i += step
    return int(np.clip(i, 0, n - 1))


def _crossing_time(t: np.ndarray, y: np.ndarray, lo: int, hi: int, level: float) -> float:
    """在 [lo, hi] 上升段内线性插值求首次跨过 level 的时刻；未跨过则返回 nan。"""
    for i in range(lo, min(hi, y.size - 1)):
        if y[i] <= level <= y[i + 1]:
            dy = y[i + 1] - y[i]
            frac = 0.0 if dy == 0 else (level - y[i]) / dy
            return float(t[i] + frac * (t[i + 1] - t[i]))
    return float("nan")


def _parabolic_vertex(y: np.ndarray, j: int) -> tuple[float, float]:
    """用相邻三点抛物线插值峰顶，返回 (亚采样点位置, 峰值)。"""
    if 0 < j < y.size - 1:
        y0, y1, y2 = float(y[j - 1]), float(y[j]), float(y[j + 1])
        denom = y0 - 2.0 * y1 + y2
        if denom < 0:                      # 只有凹向下才是极大
            delta = 0.5 * (y0 - y2) / denom
            if abs(delta) <= 1.0:
                return j + delta, y1 - 0.25 * (y0 - y2) * delta
    return float(j), float(y[j])


def _enforce_min_distance(idx: np.ndarray, heights: np.ndarray, distance: int) -> np.ndarray:
    """按幅度从高到低保留峰，剔除距离已保留峰小于 distance 的候选。"""
    if idx.size == 0 or distance <= 1:
        return idx
    keep = np.ones(idx.size, dtype=bool)
    for k in np.argsort(heights)[::-1]:
        if not keep[k]:
            continue
        close = (np.abs(idx - idx[k]) < distance) & keep
        close[k] = False
        keep[close] = False
    return idx[keep]


def _gate_bounds(signal: np.ndarray, i: int, amp: float, thr: float,
                 sigma: float, p: PeakParams, dt: float) -> tuple[int, int]:
    """确定电荷积分区间：固定门宽优先，否则自动沿脉冲边界搜索。"""
    if dt > 0 and (p.gate_pre_ns > 0 or p.gate_post_ns > 0):
        lo = int(np.clip(i - round(p.gate_pre_ns / dt), 0, signal.size - 1))
        hi = int(np.clip(i + round(p.gate_post_ns / dt), 0, signal.size - 1))
    else:
        edge_level = max(thr, 0.1 * amp)
        rise_tol = 3.0 * max(sigma, 1e-12)
        lo = _walk_to_level(signal, i, -1, edge_level, rise_tol)
        hi = _walk_to_level(signal, i, +1, edge_level, rise_tol)
    if hi <= lo:
        hi = min(signal.size - 1, lo + 1)
    return lo, hi


def _measure(t: np.ndarray, signal: np.ndarray, i: int, amp: float, thr: float,
             sigma: float, p: PeakParams, dt: float) -> tuple[int, int, float, float, float]:
    """给定峰所在采样点，算出积分区间、电荷、上升时间与 CFD50 时刻。"""
    lo, hi = _gate_bounds(signal, i, amp, thr, sigma, p, dt)
    area = float(_trapz(signal[lo:hi + 1], t[lo:hi + 1]))
    search_lo = max(0, lo - 1)             # 允许单采样点上升沿被插值到
    t10 = _crossing_time(t, signal, search_lo, i, 0.1 * amp)
    t90 = _crossing_time(t, signal, search_lo, i, 0.9 * amp)
    cfd = _crossing_time(t, signal, search_lo, i, 0.5 * amp)
    return lo, hi, area, float(t90 - t10), cfd


# ------------------------------------------------------------------ 三种寻峰

def find_signal_peaks(t: np.ndarray, signal: np.ndarray, thr: float,
                      sigma: float, p: PeakParams) -> list[Peak]:
    """在信号波形上寻峰，并提取幅度、宽度、电荷、上升时间与 CFD 时刻。"""
    t = np.asarray(t, dtype=np.float64)
    signal = np.asarray(signal, dtype=np.float64)
    if signal.size < 3:
        return []
    dt = float(t[1] - t[0]) if t.size > 1 else 1.0

    distance = max(1, int(round(p.distance_ns / dt))) if dt > 0 else 1
    prominence = p.prominence_sigma * sigma if p.prominence_sigma > 0 and sigma > 0 else None
    width = (p.min_width_ns / dt) if p.min_width_ns > 0 and dt > 0 else None

    idx, props = find_peaks(signal, height=thr, distance=distance,
                            prominence=prominence, width=width)
    if idx.size == 0:
        return []

    proms = props.get("prominences", np.full(idx.size, np.nan))
    try:
        widths = peak_widths(signal, idx, rel_height=0.5)[0] * dt
    except Exception:
        widths = np.full(idx.size, np.nan)

    peaks: list[Peak] = []
    for k, i in enumerate(idx):
        i = int(i)
        amp = float(signal[i])
        lo, hi, area, rise, cfd = _measure(t, signal, i, amp, thr, sigma, p, dt)
        peaks.append(Peak(
            index=i,
            time_ns=float(t[i]),
            amplitude=amp,
            prominence=float(proms[k]),
            fwhm_ns=float(widths[k]),
            t_start_ns=float(t[lo]),
            t_end_ns=float(t[hi]),
            area_adc_ns=area,
            rise_ns=rise,
            cfd50_ns=cfd,
        ))
    return peaks


def find_derivative_peaks(t: np.ndarray, deriv: np.ndarray, signal: np.ndarray,
                          n_sigma: float, p: PeakParams) -> list[Peak]:
    """用导数最大值（最陡上升沿）定位脉冲，适合堆积波形的起点识别。

    阈值取导数噪声的 n_sigma 倍（导数噪声用 MAD 估计）。
    """
    t = np.asarray(t, dtype=np.float64)
    deriv = np.asarray(deriv, dtype=np.float64)
    if deriv.size < 3:
        return []
    dt = float(t[1] - t[0]) if t.size > 1 else 1.0
    d_thr = max(n_sigma * mad_sigma(deriv), 1e-12)
    distance = max(1, int(round(p.distance_ns / dt))) if dt > 0 else 1

    idx, _ = find_peaks(deriv, height=d_thr, distance=distance)
    if idx.size == 0:
        return []
    peaks: list[Peak] = []
    for i in idx:
        i = int(i)
        j = i                              # 从最陡点向后找到信号局部极大
        while j < signal.size - 1 and signal[j + 1] >= signal[j]:
            j += 1
        peaks.append(Peak(
            index=j,
            time_ns=float(t[j]),
            amplitude=float(signal[j]),
            prominence=float(deriv[i]),    # 此处记录最大斜率
            fwhm_ns=float("nan"),
            t_start_ns=float(t[i]),
            t_end_ns=float(t[j]),
            area_adc_ns=float(_trapz(signal[i:j + 1], t[i:j + 1])),
            rise_ns=float(t[j] - t[i]),
            cfd50_ns=float("nan"),
        ))
    return peaks


def find_zero_crossing_peaks(t: np.ndarray, signal: np.ndarray, deriv: np.ndarray,
                             thr: float, sigma: float, n_sigma: float,
                             p: PeakParams) -> list[Peak]:
    """导数过零点寻峰：导数由正变负处即为信号极大值。

    - 峰位由导数过零点线性插值得到，精度可达亚采样点
    - 幅度由峰顶三点抛物线插值得到，比直接取最大采样点偏差更小
    - 过零点前必须出现显著上升斜率（> n_sigma × 导数噪声），否则视为噪声抖动
    """
    t = np.asarray(t, dtype=np.float64)
    signal = np.asarray(signal, dtype=np.float64)
    deriv = np.asarray(deriv, dtype=np.float64)
    if deriv.size < 5:
        return []
    dt = float(t[1] - t[0]) if t.size > 1 else 1.0

    cross = np.nonzero((deriv[:-1] > 0.0) & (deriv[1:] <= 0.0))[0]
    if cross.size == 0:
        return []

    d_thr = max(n_sigma * mad_sigma(deriv), 1e-12)
    distance = max(1, int(round(p.distance_ns / dt))) if dt > 0 else 1

    cand_i, cand_amp, cand_t, cand_slope = [], [], [], []
    for c in cross:
        c = int(c)
        j = c if signal[c] >= signal[c + 1] else c + 1
        pos, amp = _parabolic_vertex(signal, j)
        if amp < thr:
            continue
        # 回溯到本次上升段的起点（导数保持为正的那一段），取整段最大斜率。
        # 只看过零点前几个点是不够的：峰顶附近斜率本来就趋于 0。
        b = c
        while b > 0 and deriv[b - 1] > 0.0:
            b -= 1
        slope = float(np.max(deriv[b:c + 1]))
        if slope < d_thr:
            continue
        frac = deriv[c] / (deriv[c] - deriv[c + 1])   # 分母恒 > 0
        cand_i.append(j)
        cand_amp.append(amp)
        cand_t.append(float(t[c] + frac * dt))
        cand_slope.append(slope)

    if not cand_i:
        return []
    idx = np.asarray(cand_i)
    amps = np.asarray(cand_amp)
    kept = _enforce_min_distance(idx, amps, distance)
    keep_set = set(kept.tolist())

    peaks: list[Peak] = []
    seen = set()
    for k, i in enumerate(idx):
        if i not in keep_set or i in seen:
            continue
        seen.add(i)
        amp = float(amps[k])
        lo, hi, area, rise, cfd = _measure(t, signal, int(i), amp, thr, sigma, p, dt)
        peaks.append(Peak(
            index=int(i),
            time_ns=cand_t[k],
            amplitude=amp,
            prominence=cand_slope[k],      # 此处记录过零点前的最大斜率
            fwhm_ns=float("nan"),
            t_start_ns=float(t[lo]),
            t_end_ns=float(t[hi]),
            area_adc_ns=area,
            rise_ns=rise,
            cfd50_ns=cfd,
        ))
    peaks.sort(key=lambda pk: pk.time_ns)
    return peaks


def rows(peaks: list[Peak]) -> list[list[str]]:
    """转成界面表格/CSV 用的字符串行。"""
    out = []
    for pk in peaks:
        d = asdict(pk)
        row = []
        for key, _ in COLUMNS:
            v = d[key]
            row.append(str(v) if isinstance(v, int) else f"{v:.4g}")
        out.append(row)
    return out
