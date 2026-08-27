"""参数控制面板：所有分析参数的交互控件。"""

from __future__ import annotations

from pyqtgraph.Qt import QtCore, QtWidgets

from ..params import (
    AnalysisParams, BaselineParams, DerivParams, FilterParams,
    PeakParams, SmoothParams, SpectrumParams, ThresholdParams,
)

BASELINE_METHODS = [
    ("前置采样均值", "pre"),
    ("全局中位数", "median"),
    ("迭代 sigma 裁剪", "sigma_clip"),
    ("移动中位数跟踪", "moving"),
]
THRESHOLD_MODES = [("n × sigma", "sigma"), ("绝对 ADC 值", "abs")]
FILTER_KINDS = [
    ("不滤波", "none"), ("低通", "lowpass"), ("高通", "highpass"),
    ("带通", "bandpass"), ("带阻", "bandstop"),
]
SMOOTH_METHODS = [("不平滑", "none"), ("滑动平均", "movavg"), ("Savitzky-Golay", "savgol")]
DERIV_METHODS = [("中心差分", "central"), ("Savitzky-Golay", "savgol"), ("前向差分", "forward")]
PEAK_SOURCES = [("信号波形极大值", "signal"), ("导数过零点", "zero_cross"),
                ("导数上升沿", "derivative")]
FFT_WINDOWS = [("Hann", "hann"), ("Hamming", "hamming"), ("Blackman", "blackman"), ("矩形窗", "boxcar")]
POLARITIES = [("正脉冲", 1), ("负脉冲", -1)]


class _NoWheelMixin:
    """屏蔽滚轮改值：鼠标经过控件滚动时只滚动面板，避免误触。

    参数只能通过点击箭头、键盘或双击输入修改。
    """

    def wheelEvent(self, event):  # noqa: N802 - Qt 命名
        event.ignore()


class NoWheelSpinBox(_NoWheelMixin, QtWidgets.QSpinBox):
    pass


class NoWheelDoubleSpinBox(_NoWheelMixin, QtWidgets.QDoubleSpinBox):
    pass


class NoWheelComboBox(_NoWheelMixin, QtWidgets.QComboBox):
    pass


def _combo(items) -> QtWidgets.QComboBox:
    box = NoWheelComboBox()
    box.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
    for text, value in items:
        box.addItem(text, value)
    return box


def _spin(lo, hi, val, step=1) -> QtWidgets.QSpinBox:
    s = NoWheelSpinBox()
    s.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setValue(val)
    return s


def _dspin(lo, hi, val, step=0.1, decimals=3) -> QtWidgets.QDoubleSpinBox:
    s = NoWheelDoubleSpinBox()
    s.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
    s.setDecimals(decimals)
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setValue(val)
    return s


class ControlPanel(QtWidgets.QWidget):
    """参数面板。任何控件变化都会发出 changed 信号。"""

    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        inner = QtWidgets.QWidget()
        scroll.setWidget(inner)
        self._v = QtWidgets.QVBoxLayout(inner)
        self._v.setSpacing(6)

        self._build_polarity()
        self._build_baseline()
        self._build_threshold()
        self._build_filter()
        self._build_smooth_deriv()
        self._build_peaks()
        self._build_spectrum()
        self._v.addStretch(1)

        self._connect_all(inner)
        self._set_tooltips()
        self.changed.connect(self._sync_enabled)
        self._sync_enabled()

    # ---------------- 构建各分组 ----------------
    def _group(self, title: str) -> QtWidgets.QFormLayout:
        box = QtWidgets.QGroupBox(title)
        form = QtWidgets.QFormLayout(box)
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        self._v.addWidget(box)
        return form

    def _build_polarity(self):
        form = self._group("脉冲极性")
        self.polarity = _combo(POLARITIES)
        form.addRow("极性", self.polarity)

    def _build_baseline(self):
        form = self._group("基线分析")
        self.bl_method = _combo(BASELINE_METHODS)
        self.bl_npre = _spin(1, 100000, 50, 10)
        self.bl_clip_k = _dspin(0.5, 20.0, 3.0, 0.5, 2)
        self.bl_iter = _spin(1, 50, 5)
        self.bl_window = _spin(3, 100001, 101, 10)
        form.addRow("方法", self.bl_method)
        form.addRow("前置采样点数", self.bl_npre)
        form.addRow("裁剪 k", self.bl_clip_k)
        form.addRow("迭代次数", self.bl_iter)
        form.addRow("移动窗口", self.bl_window)

    def _build_threshold(self):
        form = self._group("噪声阈值")
        self.th_mode = _combo(THRESHOLD_MODES)
        self.th_nsigma = _dspin(0.1, 100.0, 5.0, 0.5, 2)
        self.th_abs = _dspin(0.0, 1e6, 20.0, 1.0, 3)
        form.addRow("模式", self.th_mode)
        form.addRow("n sigma", self.th_nsigma)
        form.addRow("绝对 ADC", self.th_abs)

    def _build_filter(self):
        form = self._group("数字滤波（频域）")
        self.f_kind = _combo(FILTER_KINDS)
        self.f_low = _dspin(0.001, 1e6, 10.0, 1.0, 3)
        self.f_high = _dspin(0.001, 1e6, 200.0, 1.0, 3)
        self.f_order = _spin(1, 10, 4)
        form.addRow("类型", self.f_kind)
        form.addRow("下截止 (MHz)", self.f_low)
        form.addRow("上截止 (MHz)", self.f_high)
        form.addRow("阶数", self.f_order)

    def _build_smooth_deriv(self):
        form = self._group("平滑与求导")
        self.sm_method = _combo(SMOOTH_METHODS)
        self.sm_window = _spin(3, 10001, 11, 2)
        self.sm_poly = _spin(1, 10, 3)
        self.dv_method = _combo(DERIV_METHODS)
        self.dv_window = _spin(5, 10001, 11, 2)
        self.dv_poly = _spin(1, 10, 3)
        self.dv_order = _spin(1, 2, 1)
        form.addRow("平滑方法", self.sm_method)
        form.addRow("平滑窗口", self.sm_window)
        form.addRow("平滑多项式阶", self.sm_poly)
        form.addRow("求导方法", self.dv_method)
        form.addRow("求导窗口", self.dv_window)
        form.addRow("求导多项式阶", self.dv_poly)
        form.addRow("导数阶数", self.dv_order)

    def _build_peaks(self):
        form = self._group("寻峰")
        self.pk_source = _combo(PEAK_SOURCES)
        self.pk_distance = _dspin(0.0, 1e6, 20.0, 1.0, 3)
        self.pk_prom = _dspin(0.0, 100.0, 5.0, 0.5, 2)
        self.pk_width = _dspin(0.0, 1e6, 0.0, 1.0, 3)
        self.pk_gate_pre = _dspin(0.0, 1e6, 0.0, 1.0, 3)
        self.pk_gate_post = _dspin(0.0, 1e6, 0.0, 1.0, 3)
        form.addRow("寻峰依据", self.pk_source)
        form.addRow("最小峰间距 (ns)", self.pk_distance)
        form.addRow("最小凸起 (×sigma)", self.pk_prom)
        form.addRow("最小宽度 (ns)", self.pk_width)
        form.addRow("积分门-峰前 (ns)", self.pk_gate_pre)
        form.addRow("积分门-峰后 (ns)", self.pk_gate_post)
        hint = QtWidgets.QLabel("积分门为 0 时按脉冲边界自动积分（长尾脉冲会被截断，"
                               "测电荷建议设固定门宽）")
        hint.setWordWrap(True)
        form.addRow("", hint)

    def _build_spectrum(self):
        form = self._group("频谱")
        self.sp_window = _combo(FFT_WINDOWS)
        self.sp_nperseg = _spin(8, 1 << 20, 256, 64)
        self.sp_logy = QtWidgets.QCheckBox("纵轴对数")
        self.sp_logy.setChecked(True)
        form.addRow("窗函数", self.sp_window)
        form.addRow("PSD 段长", self.sp_nperseg)
        form.addRow("", self.sp_logy)

    def _connect_all(self, root: QtWidgets.QWidget):
        for w in root.findChildren(QtWidgets.QComboBox):
            w.currentIndexChanged.connect(self.changed)
        for w in root.findChildren(QtWidgets.QSpinBox):
            w.valueChanged.connect(self.changed)
        for w in root.findChildren(QtWidgets.QDoubleSpinBox):
            w.valueChanged.connect(self.changed)
        for w in root.findChildren(QtWidgets.QCheckBox):
            w.toggled.connect(self.changed)

    def _set_tooltips(self):
        self.bl_npre.setToolTip("仅「前置采样均值」使用")
        self.bl_clip_k.setToolTip("仅「迭代 sigma 裁剪」使用")
        self.bl_iter.setToolTip("仅「迭代 sigma 裁剪」使用")
        self.bl_window.setToolTip("仅「移动中位数跟踪」使用")
        self.th_nsigma.setToolTip("仅「n × sigma」模式使用")
        self.th_abs.setToolTip("仅「绝对 ADC 值」模式使用")
        self.sm_poly.setToolTip("仅 Savitzky-Golay 平滑使用")
        self.dv_window.setToolTip("仅 Savitzky-Golay 求导使用；中心差分/前向差分没有窗口参数")
        self.dv_poly.setToolTip("仅 Savitzky-Golay 求导使用")
        self.pk_prom.setToolTip("仅「信号波形极大值」模式使用")
        self.pk_width.setToolTip("仅「信号波形极大值」模式使用")
        self.dv_method.setToolTip("只影响「导数」页签与导数类寻峰；波形页签的两张图不受影响")

    def _sync_enabled(self):
        """按当前选择把用不到的参数置灰，避免调了没反应。"""
        bl = self.bl_method.currentData()
        self.bl_npre.setEnabled(bl == "pre")
        self.bl_clip_k.setEnabled(bl == "sigma_clip")
        self.bl_iter.setEnabled(bl == "sigma_clip")
        self.bl_window.setEnabled(bl == "moving")

        th = self.th_mode.currentData()
        self.th_nsigma.setEnabled(th == "sigma")
        self.th_abs.setEnabled(th == "abs")

        fk = self.f_kind.currentData()
        self.f_low.setEnabled(fk in ("highpass", "bandpass", "bandstop"))
        self.f_high.setEnabled(fk in ("lowpass", "bandpass", "bandstop"))
        self.f_order.setEnabled(fk != "none")

        sm = self.sm_method.currentData()
        self.sm_window.setEnabled(sm != "none")
        self.sm_poly.setEnabled(sm == "savgol")

        dv = self.dv_method.currentData()
        self.dv_window.setEnabled(dv == "savgol")
        self.dv_poly.setEnabled(dv == "savgol")

        src = self.pk_source.currentData()
        self.pk_prom.setEnabled(src == "signal")
        self.pk_width.setEnabled(src == "signal")

    # ---------------- 取参数 ----------------
    def params(self) -> AnalysisParams:
        return AnalysisParams(
            polarity=self.polarity.currentData(),
            baseline=BaselineParams(
                method=self.bl_method.currentData(),
                n_pre=self.bl_npre.value(),
                clip_k=self.bl_clip_k.value(),
                n_iter=self.bl_iter.value(),
                window=self.bl_window.value(),
            ),
            threshold=ThresholdParams(
                mode=self.th_mode.currentData(),
                n_sigma=self.th_nsigma.value(),
                abs_adc=self.th_abs.value(),
            ),
            filt=FilterParams(
                kind=self.f_kind.currentData(),
                f_low=self.f_low.value(),
                f_high=self.f_high.value(),
                order=self.f_order.value(),
            ),
            smooth=SmoothParams(
                method=self.sm_method.currentData(),
                window=self.sm_window.value(),
                poly=self.sm_poly.value(),
            ),
            deriv=DerivParams(
                method=self.dv_method.currentData(),
                window=self.dv_window.value(),
                poly=self.dv_poly.value(),
                order=self.dv_order.value(),
            ),
            peaks=PeakParams(
                source=self.pk_source.currentData(),
                distance_ns=self.pk_distance.value(),
                prominence_sigma=self.pk_prom.value(),
                min_width_ns=self.pk_width.value(),
                gate_pre_ns=self.pk_gate_pre.value(),
                gate_post_ns=self.pk_gate_post.value(),
            ),
            spectrum=SpectrumParams(
                window=self.sp_window.currentData(),
                nperseg=self.sp_nperseg.value(),
                log_y=self.sp_logy.isChecked(),
            ),
        )
