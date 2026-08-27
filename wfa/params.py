"""分析参数定义。界面与批量脚本共用同一套参数对象。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BaselineParams:
    method: str = "pre"        # pre | median | sigma_clip | moving
    n_pre: int = 50            # 前置采样点数（method=pre）
    clip_k: float = 3.0        # 迭代裁剪阈值（method=sigma_clip）
    n_iter: int = 5
    window: int = 101          # 移动中位数窗口（method=moving）


@dataclass
class ThresholdParams:
    mode: str = "sigma"        # sigma | abs
    n_sigma: float = 5.0
    abs_adc: float = 20.0


@dataclass
class FilterParams:
    kind: str = "none"         # none | lowpass | highpass | bandpass | bandstop
    f_low: float = 10.0        # MHz
    f_high: float = 200.0      # MHz
    order: int = 4


@dataclass
class SmoothParams:
    method: str = "none"       # none | movavg | savgol
    window: int = 11
    poly: int = 3


@dataclass
class DerivParams:
    method: str = "central"    # central | savgol | forward
    window: int = 11
    poly: int = 3
    order: int = 1             # 1 = 一阶导，2 = 二阶导


@dataclass
class PeakParams:
    source: str = "signal"     # signal | derivative
    distance_ns: float = 20.0
    prominence_sigma: float = 5.0   # 以基线 sigma 为单位，0 表示不限制；过小会把长尾上的局部极大误判为峰
    min_width_ns: float = 0.0
    gate_pre_ns: float = 0.0   # 电荷积分门：峰前长度，0 = 自动寻找脉冲边界
    gate_post_ns: float = 0.0  # 电荷积分门：峰后长度，0 = 自动寻找脉冲边界


@dataclass
class SpectrumParams:
    window: str = "hann"       # hann | hamming | blackman | boxcar
    nperseg: int = 256
    log_y: bool = True


@dataclass
class AnalysisParams:
    polarity: int = 1          # +1 正脉冲，-1 负脉冲
    baseline: BaselineParams = field(default_factory=BaselineParams)
    threshold: ThresholdParams = field(default_factory=ThresholdParams)
    filt: FilterParams = field(default_factory=FilterParams)
    smooth: SmoothParams = field(default_factory=SmoothParams)
    deriv: DerivParams = field(default_factory=DerivParams)
    peaks: PeakParams = field(default_factory=PeakParams)
    spectrum: SpectrumParams = field(default_factory=SpectrumParams)
