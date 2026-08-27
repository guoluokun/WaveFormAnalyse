"""波形分析主窗口。"""

from __future__ import annotations

import csv
import os

import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

from .. import io_root, peaks as pk_mod, pipeline
from .controls import ControlPanel, NoWheelDoubleSpinBox, NoWheelComboBox, NoWheelSpinBox

pg.setConfigOptions(antialias=True, background="w", foreground="k")

PEN_RAW = pg.mkPen("#555555", width=2)
PEN_BASELINE = pg.mkPen("#d62728", width=2, style=QtCore.Qt.PenStyle.DashLine)
PEN_SIGNAL = pg.mkPen("#1f77b4", width=2)
PEN_GATED = pg.mkPen("#2ca02c", width=3)
PEN_THR = pg.mkPen("#ff7f0e", width=2, style=QtCore.Qt.PenStyle.DashLine)
PEN_DERIV = pg.mkPen("#7b3fa0", width=2)
PEN_ZERO = pg.mkPen("#999999", width=1, style=QtCore.Qt.PenStyle.DotLine)
PEN_SPEC = pg.mkPen("#1f77b4", width=2)
PEN_PSD = pg.mkPen("#d62728", width=2)
BRUSH_HIST = pg.mkBrush(31, 119, 180, 120)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("波形分析 - Waveform Analyzer")
        self.resize(1500, 950)

        self._path: str | None = None
        self._specs: list[io_root.SourceSpec] = []
        self._source: io_root.WaveformSource | None = None
        self._result: pipeline.AnalysisResult | None = None
        self._scan: pipeline.ScanResult | None = None
        self._auto_view = True      # 未手动缩放时，每次重绘都自动适配视图

        self.controls = ControlPanel()
        self.controls.changed.connect(self.reanalyze)

        dock = QtWidgets.QDockWidget("分析参数", self)
        dock.setWidget(self.controls)
        dock.setFeatures(QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetMovable)
        dock.setMinimumWidth(300)
        self.addDockWidget(QtCore.Qt.DockWidgetArea.LeftDockWidgetArea, dock)

        self._build_toolbar()
        self._build_tabs()
        for plot in self._all_plots():
            plot.getViewBox().sigRangeChangedManually.connect(self._on_manual_range)
        shortcut_cls = getattr(QtWidgets, "QShortcut", None) or getattr(QtGui, "QShortcut")
        self._fit_shortcut = shortcut_cls(QtGui.QKeySequence("R"), self)
        self._fit_shortcut.activated.connect(self.fit_view)
        self.statusBar().showMessage("请打开 ROOT 文件")

    # ---------------------------------------------------------------- 界面搭建
    def _build_toolbar(self):
        bar = QtWidgets.QToolBar("主工具栏")
        bar.setMovable(False)
        self.addToolBar(bar)

        open_btn = QtWidgets.QPushButton("打开 ROOT 文件")
        open_btn.clicked.connect(self.open_file)
        bar.addWidget(open_btn)

        bar.addWidget(QtWidgets.QLabel("  数据源 "))
        self.source_box = NoWheelComboBox()
        self.source_box.setMinimumWidth(420)
        self.source_box.currentIndexChanged.connect(self._on_source_changed)
        bar.addWidget(self.source_box)

        bar.addWidget(QtWidgets.QLabel("  采样间隔(ns) "))
        self.dt_spin = NoWheelDoubleSpinBox()
        self.dt_spin.setDecimals(4)
        self.dt_spin.setRange(0.0001, 1e6)
        self.dt_spin.setValue(1.0)
        self.dt_spin.valueChanged.connect(self._on_source_changed)
        bar.addWidget(self.dt_spin)

        self.use_hist_axis = QtWidgets.QCheckBox("用直方图自带 x 轴")
        self.use_hist_axis.setChecked(True)
        self.use_hist_axis.toggled.connect(self._on_source_changed)
        bar.addWidget(self.use_hist_axis)

        bar.addSeparator()
        prev_btn = QtWidgets.QPushButton("← 上一事件")
        prev_btn.clicked.connect(lambda: self.event_spin.setValue(self.event_spin.value() - 1))
        bar.addWidget(prev_btn)

        self.event_spin = NoWheelSpinBox()
        self.event_spin.setRange(0, 0)
        self.event_spin.valueChanged.connect(self.reanalyze)
        bar.addWidget(self.event_spin)

        next_btn = QtWidgets.QPushButton("下一事件 →")
        next_btn.clicked.connect(lambda: self.event_spin.setValue(self.event_spin.value() + 1))
        bar.addWidget(next_btn)

        self.event_label = QtWidgets.QLabel("  / 0")
        bar.addWidget(self.event_label)

        bar.addSeparator()
        fit_btn = QtWidgets.QPushButton("适配视图")
        fit_btn.setToolTip("把所有图恢复到完整显示数据的合适缩放（快捷键 R）")
        fit_btn.clicked.connect(self.fit_view)
        bar.addWidget(fit_btn)

    def _all_plots(self) -> list:
        return [self.p_raw, self.p_sig, self.p_deriv,
                self.p_amp, self.p_psd, self.p_hamp, self.p_hchg]

    def _on_manual_range(self, *_):
        """用户手动缩放/平移后停止自动适配，直到点「适配视图」。"""
        self._auto_view = False

    def fit_view(self):
        """所有图恢复自动缩放并立即适配到数据范围。"""
        self._auto_view = True
        for plot in self._all_plots():
            vb = plot.getViewBox()
            vb.enableAutoRange(x=True, y=True)
            vb.autoRange(padding=0.05)

    def _build_tabs(self):
        self.tabs = QtWidgets.QTabWidget()
        self.setCentralWidget(self.tabs)
        self.tabs.addTab(self._build_wave_tab(), "波形")
        self.tabs.addTab(self._build_deriv_tab(), "导数")
        self.tabs.addTab(self._build_spec_tab(), "频谱")
        self.tabs.addTab(self._build_peak_tab(), "峰列表")
        self.tabs.addTab(self._build_scan_tab(), "批量统计")

    def _build_wave_tab(self) -> QtWidgets.QWidget:
        layout = pg.GraphicsLayoutWidget()
        self.p_raw = layout.addPlot(row=0, col=0, title="原始波形 / 基线 / 阈值")
        self.p_sig = layout.addPlot(row=1, col=0, title="滤波 + 基线校正 + 极性归一后的信号")
        for p in (self.p_raw, self.p_sig):
            p.showGrid(x=True, y=True, alpha=0.25)
            p.setLabel("bottom", "时间", units="ns")
            p.setLabel("left", "幅度", units="ADC")
            p.addLegend(offset=(-10, 10))
        self.p_sig.setXLink(self.p_raw)

        # 上视图：原始波形 + 基线 + 阈值（阈值换算回原始 ADC 刻度）
        self.c_raw = self.p_raw.plot([], [], pen=PEN_RAW, name="原始波形")
        self.c_base = self.p_raw.plot([], [], pen=PEN_BASELINE, name="基线")
        self.c_thr_raw = self.p_raw.plot([], [], pen=PEN_THR, name="阈值")
        # 下视图：滤波与基线校正后的信号 + 过阈部分 + 峰
        self.c_sig = self.p_sig.plot([], [], pen=PEN_SIGNAL, name="处理后信号")
        self.c_gated = self.p_sig.plot([], [], pen=PEN_GATED, name="过阈部分")
        self.l_thr = pg.InfiniteLine(angle=0, pen=PEN_THR, movable=False)
        self.p_sig.addItem(self.l_thr)
        self.s_peaks = pg.ScatterPlotItem(symbol="d", size=13,
                                          brush=pg.mkBrush(214, 39, 40, 220),
                                          pen=pg.mkPen("k", width=1))
        self.p_sig.addItem(self.s_peaks)
        return layout

    def _build_deriv_tab(self) -> QtWidgets.QWidget:
        layout = pg.GraphicsLayoutWidget()
        self.p_deriv = layout.addPlot(row=0, col=0, title="波形导数 dV/dt")
        self.p_deriv.showGrid(x=True, y=True, alpha=0.3)
        self.p_deriv.setLabel("bottom", "时间", units="ns")
        self.p_deriv.setLabel("left", "导数", units="ADC/ns")
        self.p_deriv.addLegend(offset=(-10, 10))
        self.c_deriv = self.p_deriv.plot([], [], pen=PEN_DERIV, name="导数")
        self.p_deriv.addItem(pg.InfiniteLine(pos=0, angle=0, pen=PEN_ZERO))
        self.s_dpeaks = pg.ScatterPlotItem(symbol="t1", size=13,
                                           brush=pg.mkBrush(255, 127, 14, 220),
                                           pen=pg.mkPen("k", width=1))
        self.p_deriv.addItem(self.s_dpeaks)
        return layout

    def _build_spec_tab(self) -> QtWidgets.QWidget:
        layout = pg.GraphicsLayoutWidget()
        self.p_amp = layout.addPlot(row=0, col=0, title="幅度谱 (FFT)")
        self.p_psd = layout.addPlot(row=1, col=0, title="功率谱密度 (Welch)")
        self.p_amp.setLabel("bottom", "频率", units="MHz")
        self.p_amp.setLabel("left", "幅度", units="ADC")
        self.p_psd.setLabel("bottom", "频率", units="MHz")
        self.p_psd.setLabel("left", "PSD", units="ADC²/Hz")
        for p in (self.p_amp, self.p_psd):
            p.showGrid(x=True, y=True, alpha=0.3)
        self.c_amp = self.p_amp.plot([], [], pen=PEN_SPEC)
        self.c_psd = self.p_psd.plot([], [], pen=PEN_PSD)
        return layout

    def _build_peak_tab(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        top = QtWidgets.QHBoxLayout()
        self.peak_info = QtWidgets.QLabel("尚无数据")
        top.addWidget(self.peak_info)
        top.addStretch(1)
        btn = QtWidgets.QPushButton("导出峰表 CSV")
        btn.clicked.connect(self.export_peaks)
        top.addWidget(btn)
        v.addLayout(top)

        self.peak_table = QtWidgets.QTableWidget(0, len(pk_mod.COLUMNS))
        self.peak_table.setHorizontalHeaderLabels([c[1] for c in pk_mod.COLUMNS])
        self.peak_table.horizontalHeader().setStretchLastSection(True)
        self.peak_table.setEditTriggers(QtWidgets.QTableWidget.EditTrigger.NoEditTriggers)
        v.addWidget(self.peak_table)
        return w

    def _build_scan_tab(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel("扫描事件数"))
        self.scan_n = NoWheelSpinBox()
        self.scan_n.setRange(1, 10_000_000)
        self.scan_n.setValue(1000)
        top.addWidget(self.scan_n)
        top.addWidget(QtWidgets.QLabel("bin 数"))
        self.scan_bins = NoWheelSpinBox()
        self.scan_bins.setRange(10, 5000)
        self.scan_bins.setValue(100)
        self.scan_bins.valueChanged.connect(self._plot_scan)
        top.addWidget(self.scan_bins)
        run = QtWidgets.QPushButton("开始扫描")
        run.clicked.connect(self.run_scan)
        top.addWidget(run)
        exp = QtWidgets.QPushButton("导出峰参数 CSV")
        exp.clicked.connect(self.export_scan)
        top.addWidget(exp)
        self.scan_info = QtWidgets.QLabel("未扫描")
        top.addWidget(self.scan_info)
        top.addStretch(1)
        v.addLayout(top)

        layout = pg.GraphicsLayoutWidget()
        self.p_hamp = layout.addPlot(row=0, col=0, title="幅度谱（所有峰）")
        self.p_hchg = layout.addPlot(row=1, col=0, title="电荷谱（所有峰积分）")
        self.p_hamp.setLabel("bottom", "幅度", units="ADC")
        self.p_hchg.setLabel("bottom", "积分电荷", units="ADC·ns")
        for p in (self.p_hamp, self.p_hchg):
            p.setLabel("left", "计数")
            p.showGrid(x=True, y=True, alpha=0.3)
        v.addWidget(layout)
        return w

    # ---------------------------------------------------------------- 数据加载
    def open_file(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "选择 ROOT 文件", "", "ROOT 文件 (*.root);;所有文件 (*)")
        if not path:
            return
        self.load_path(path)

    def load_path(self, path: str):
        """加载 ROOT 文件并列出所有可用波形数据源。"""
        try:
            specs = io_root.discover_sources(path)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "打开失败", f"无法解析文件:\n{exc}")
            return
        if not specs:
            QtWidgets.QMessageBox.warning(
                self, "未找到波形",
                "文件中没有识别到一维数值序列分支或 TH1 直方图。")
            return

        self._path = path
        self._specs = specs
        self.source_box.blockSignals(True)
        self.source_box.clear()
        for s in specs:
            self.source_box.addItem(s.label)
        self.source_box.setCurrentIndex(0)
        self.source_box.blockSignals(False)
        self.setWindowTitle(f"波形分析 - {os.path.basename(path)}")
        self._on_source_changed()

    def _on_source_changed(self):
        if not self._path or not self._specs:
            return
        idx = max(0, self.source_box.currentIndex())
        spec = self._specs[idx]
        if self._source is not None:
            self._source.close()
            self._source = None
        sample_ns = self.dt_spin.value()
        if spec.kind == "hists" and self.use_hist_axis.isChecked():
            sample_ns = None
        try:
            self._source = io_root.open_source(self._path, spec, sample_ns)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "读取失败", str(exc))
            return
        n = self._source.n_events
        self.event_spin.blockSignals(True)
        self.event_spin.setRange(0, max(0, n - 1))
        self.event_spin.setValue(0)
        self.event_spin.blockSignals(False)
        self.event_label.setText(f"  / {n - 1}")
        self.scan_n.setValue(min(1000, max(1, n)))
        self._auto_view = True      # 换数据源后重新适配视图
        self.reanalyze()

    # ---------------------------------------------------------------- 分析绘图
    def reanalyze(self):
        if self._source is None:
            return
        params = self.controls.params()
        try:
            t, y = self._source.get_event(self.event_spin.value())
            self._result = pipeline.analyze(t, y, params)
        except Exception as exc:
            self.statusBar().showMessage(f"分析失败: {exc}")
            return
        self._plot_result(self._result)
        self._fill_peak_table(self._result)

        r = self._result
        base_txt = f"{np.mean(r.baseline):.2f}"
        self.statusBar().showMessage(
            f"事件 {self.event_spin.value()} | 采样点 {r.raw.size} | dt = {r.dt_ns:.4g} ns | "
            f"采样率 {1e3 / r.dt_ns:.4g} MHz | 基线 = {base_txt} ADC | "
            f"sigma = {r.sigma:.3f} ADC | 阈值 = {r.threshold:.3f} ADC | "
            f"峰数 = {len(r.peak_list)}"
        )

    def _plot_result(self, r: pipeline.AnalysisResult):
        self.c_raw.setData(r.t, r.raw)
        # 基线与阈值都是在滤波后的波形上算的；高通/带通去掉了直流，
        # 这里补回 dc_offset 才能画在原始 ADC 刻度上，否则上视图会被拉伸
        base_raw = r.baseline + r.dc_offset
        self.c_base.setData(r.t, base_raw)
        self.c_thr_raw.setData(r.t, base_raw + r.polarity * r.threshold)
        self.c_sig.setData(r.t, r.signal)
        gated = np.where(r.over_threshold, r.gated, np.nan)
        self.c_gated.setData(r.t, gated, connect="finite")
        self.l_thr.setPos(r.threshold)

        if r.peak_list:
            xs = [p.time_ns for p in r.peak_list]
            ys = [p.amplitude for p in r.peak_list]
            self.s_peaks.setData(xs, ys)
            # 导数图上的标记：过零点模式标在过零处，其余模式标在上升沿处
            if self.controls.pk_source.currentData() == "zero_cross":
                marks = np.asarray(xs, dtype=np.float64)
            else:
                marks = np.asarray([p.t_start_ns for p in r.peak_list], dtype=np.float64)
            sidx = np.clip(np.searchsorted(r.t, marks), 0, r.deriv.size - 1)
            self.s_dpeaks.setData(r.t[sidx], r.deriv[sidx])
        else:
            self.s_peaks.setData([], [])
            self.s_dpeaks.setData([], [])

        self.c_deriv.setData(r.t, r.deriv)
        # 标题里写明当前求导方法与结果特征，切换方法时能直接看出差别
        # （导数图纵轴自动缩放，只看曲线形状容易误以为没变化）
        order_txt = "二阶导数 d²V/dt²" if self.controls.dv_order.value() == 2 else "一阶导数 dV/dt"
        self.p_deriv.setTitle(
            f"{order_txt} · {self.controls.dv_method.currentText()}"
            f"（平滑：{self.controls.sm_method.currentText()}）"
            f" · 最大斜率 {r.deriv.max():.4g} · 噪声 RMS {np.std(r.deriv):.4g}"
        )
        self.p_sig.setTitle(
            f"滤波（{self.controls.f_kind.currentText()}）+ 基线校正"
            f"（{self.controls.bl_method.currentText()}）+ 极性归一后的信号"
        )

        log_y = self.controls.sp_logy.isChecked()
        self.p_amp.setLogMode(False, log_y)
        self.p_psd.setLogMode(False, log_y)
        if r.freq_mhz.size:
            # 去掉直流点，避免对数坐标下出现 -inf
            self.c_amp.setData(r.freq_mhz[1:], np.maximum(r.amp_spec[1:], 1e-12))
        if r.psd_freq_mhz.size:
            self.c_psd.setData(r.psd_freq_mhz[1:], np.maximum(r.psd_val[1:], 1e-30))

        if self._auto_view:
            self.fit_view()

    def _fill_peak_table(self, r: pipeline.AnalysisResult):
        rows = pk_mod.rows(r.peak_list)
        self.peak_table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, val in enumerate(row):
                self.peak_table.setItem(i, j, QtWidgets.QTableWidgetItem(val))
        total_charge = sum(p.area_adc_ns for p in r.peak_list)
        self.peak_info.setText(
            f"事件 {self.event_spin.value()}：{len(rows)} 个峰，"
            f"总积分电荷 {total_charge:.4g} ADC·ns，阈值 {r.threshold:.3f} ADC"
        )

    # ---------------------------------------------------------------- 批量扫描
    def run_scan(self):
        if self._source is None:
            return
        params = self.controls.params()
        total = min(self.scan_n.value(), self._source.n_events)
        dlg = QtWidgets.QProgressDialog("正在扫描事件...", "取消", 0, total, self)
        dlg.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)

        def progress(done, tot):
            dlg.setValue(done)
            QtWidgets.QApplication.processEvents()
            return not dlg.wasCanceled()

        try:
            self._scan = pipeline.scan(self._source, params, total, progress=progress)
        except Exception as exc:
            dlg.close()
            QtWidgets.QMessageBox.critical(self, "扫描失败", str(exc))
            return
        dlg.close()
        self._plot_scan()

    def _plot_scan(self):
        s = self._scan
        if s is None:
            return
        bins = self.scan_bins.value()
        self._hist_to(self.p_hamp, s.amplitudes, bins)
        self._hist_to(self.p_hchg, s.charges, bins)
        mean_pk = float(np.mean(s.n_peaks)) if s.n_peaks.size else 0.0
        mean_sig = float(np.mean(s.sigmas)) if s.sigmas.size else 0.0
        self.scan_info.setText(
            f"  已扫描 {s.n_events} 事件，共 {s.amplitudes.size} 个峰，"
            f"平均 {mean_pk:.2f} 峰/事件，平均噪声 sigma {mean_sig:.3f} ADC"
        )

    @staticmethod
    def _hist_to(plot, data: np.ndarray, bins: int):
        plot.clear()
        if data.size == 0:
            return
        lo, hi = float(np.min(data)), float(np.max(data))
        if hi <= lo:
            hi = lo + 1.0
        counts, edges = np.histogram(data, bins=bins, range=(lo, hi))
        plot.plot(edges, counts, stepMode="center", fillLevel=0,
                  brush=BRUSH_HIST, pen=PEN_SPEC)

    # ---------------------------------------------------------------- 导出
    def export_peaks(self):
        if self._result is None or not self._result.peak_list:
            QtWidgets.QMessageBox.information(self, "无数据", "当前事件没有找到峰。")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "保存峰表", f"peaks_event{self.event_spin.value()}.csv", "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow([c[0] for c in pk_mod.COLUMNS])
            writer.writerows(pk_mod.rows(self._result.peak_list))
        self.statusBar().showMessage(f"已保存 {path}")

    def export_scan(self):
        s = self._scan
        if s is None or s.amplitudes.size == 0:
            QtWidgets.QMessageBox.information(self, "无数据", "请先执行批量扫描。")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "保存扫描结果", "scan_peaks.csv", "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["time_ns", "amplitude", "area_adc_ns"])
            for tm, amp, chg in zip(s.times, s.amplitudes, s.charges):
                writer.writerow([f"{tm:.6g}", f"{amp:.6g}", f"{chg:.6g}"])
        self.statusBar().showMessage(f"已保存 {path}")

    def closeEvent(self, event):
        if self._source is not None:
            self._source.close()
        super().closeEvent(event)
