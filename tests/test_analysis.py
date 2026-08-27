"""分析链路验证：全部基于 wfa.simdata 生成的「已知真值」模拟波形。

运行:  python -m pytest tests -v
"""

from __future__ import annotations

import numpy as np
import pytest

from wfa import io_root, pipeline, simdata
from wfa.derivative import derivative
from wfa.params import AnalysisParams, BaselineParams, DerivParams, SpectrumParams, ThresholdParams
from wfa.baseline import estimate_baseline, threshold_value
from wfa.spectrum import amplitude_spectrum, apply_filter


# --------------------------------------------------------------- 工具

# 峰位匹配容差（采样点）。双指数脉冲峰顶平缓，噪声会让 argmax 抖动数个采样点，
# 实测 3 ADC 噪声下抖动可达 5 个采样点，因此取 6。
MATCH_TOL_SAMPLES = 6


def time_axis(cfg: simdata.SimConfig) -> np.ndarray:
    return np.arange(cfg.n_samples, dtype=np.float64) * cfg.sample_ns


def flat_noise_wave(cfg: simdata.SimConfig, seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return np.full(cfg.n_samples, cfg.baseline) + rng.normal(0, cfg.noise_adc, cfg.n_samples)


def default_params() -> AnalysisParams:
    p = AnalysisParams()
    p.baseline = BaselineParams(method="pre", n_pre=100)
    p.threshold = ThresholdParams(mode="sigma", n_sigma=5.0)
    p.peaks.distance_ns = 60.0
    return p


# --------------------------------------------------------------- 基线与噪声

@pytest.mark.parametrize("method", ["pre", "median", "sigma_clip", "moving"])
def test_baseline_and_sigma_on_pure_noise(method):
    """无脉冲时，四种基线方法都应给出正确的基线与噪声 sigma。"""
    cfg = simdata.SimConfig(noise_adc=3.0)
    y = flat_noise_wave(cfg)
    res = estimate_baseline(y, BaselineParams(method=method, n_pre=200, window=101))
    assert abs(np.mean(res.level) - cfg.baseline) < 0.5
    # 移动中位数会吸收部分噪声，容差放宽
    tol = 0.35 if method == "moving" else 0.12
    assert abs(res.sigma - cfg.noise_adc) / cfg.noise_adc < tol


def test_moving_baseline_tracks_drift():
    """基线漂移 60 ADC 时，移动中位数跟踪的残差应远小于漂移量。"""
    cfg = simdata.SimConfig(drift_adc=60.0, noise_adc=2.0, n_pulse_choices=(0,))
    rng = np.random.default_rng(5)
    y = (np.full(cfg.n_samples, cfg.baseline)
         + np.linspace(0, cfg.drift_adc, cfg.n_samples)
         + rng.normal(0, cfg.noise_adc, cfg.n_samples))
    fixed = estimate_baseline(y, BaselineParams(method="pre", n_pre=100))
    moving = estimate_baseline(y, BaselineParams(method="moving", window=101))
    assert np.max(np.abs(y - fixed.level)) > 40.0
    assert np.max(np.abs(y - moving.level)) < 5 * cfg.noise_adc


def test_threshold_modes():
    sigma = 2.5
    assert threshold_value(sigma, ThresholdParams(mode="sigma", n_sigma=4.0)) == pytest.approx(10.0)
    assert threshold_value(sigma, ThresholdParams(mode="abs", abs_adc=33.0)) == pytest.approx(33.0)


def test_negative_polarity_recovers_same_amplitudes():
    """负脉冲取 polarity=-1 后，真脉冲的幅度应与正脉冲一致。

    注意：两种极性下噪声符号相反，噪声/长尾造成的小幅局部极大位置不同，
    因此只比对与真值匹配上的峰，不要求峰总数相同。
    """
    cfg_pos = simdata.SimConfig(n_events=1, polarity=1, noise_adc=1.0, seed=99)
    cfg_neg = simdata.SimConfig(n_events=1, polarity=-1, noise_adc=1.0, seed=99)
    waves_pos, truths = simdata.generate(cfg_pos)
    waves_neg, _ = simdata.generate(cfg_neg)
    t = time_axis(cfg_pos)

    p = default_params()
    rp = pipeline.analyze(t, waves_pos[0], p)
    p.polarity = -1
    rn = pipeline.analyze(t, waves_neg[0], p)

    def match(peaks, truth):
        cands = [m for m in peaks if abs(m.time_ns - truth.peak_time_ns) <= MATCH_TOL_SAMPLES * cfg_pos.sample_ns]
        assert cands, f"未找到 t={truth.peak_time_ns} 的脉冲"
        return max(cands, key=lambda m: m.amplitude)

    for truth in truths:
        mp, mn = match(rp.peak_list, truth), match(rn.peak_list, truth)
        assert mp.amplitude == pytest.approx(truth.amplitude_adc, rel=0.08)
        assert mn.amplitude == pytest.approx(mp.amplitude, rel=0.05)


# --------------------------------------------------------------- 求导

def test_derivative_matches_analytic_sine():
    """对 sin(ωt) 求导，应等于 ω·cos(ωt)。"""
    dt = 1.0
    t = np.arange(2048) * dt
    omega = 2 * np.pi / 200.0
    y = np.sin(omega * t)
    expected = omega * np.cos(omega * t)
    for method in ["central", "savgol"]:
        d = derivative(y, dt, DerivParams(method=method, window=11, poly=3))
        err = np.max(np.abs(d[20:-20] - expected[20:-20])) / omega
        assert err < 0.02, f"{method} 相对误差 {err:.3f}"


def test_derivative_of_ramp_is_constant_slope():
    dt = 2.0
    t = np.arange(500) * dt
    slope = 0.37
    d = derivative(slope * t, dt, DerivParams(method="central"))
    assert np.allclose(d, slope, atol=1e-9)


def test_second_derivative_of_parabola():
    dt = 1.0
    t = np.arange(400) * dt
    y = 0.5 * 3.0 * t ** 2                     # 二阶导应为 3.0
    d2 = derivative(y, dt, DerivParams(method="savgol", window=11, poly=3, order=2))
    assert np.allclose(d2[10:-10], 3.0, rtol=1e-6)


# --------------------------------------------------------------- 寻峰与真值比对

def test_peak_position_amplitude_charge_vs_truth():
    """单事件：峰位、峰幅、积分电荷与模拟真值对比。"""
    cfg = simdata.SimConfig(n_events=1, noise_adc=3.0, seed=1234)
    waves, truths = simdata.generate(cfg)
    t = time_axis(cfg)
    p = default_params()
    p.peaks.gate_pre_ns, p.peaks.gate_post_ns = 40.0, 400.0
    r = pipeline.analyze(t, waves[0], p)

    assert len(r.peak_list) == len(truths)
    for meas, truth in zip(r.peak_list, truths):
        assert abs(meas.time_ns - truth.peak_time_ns) <= MATCH_TOL_SAMPLES * cfg.sample_ns
        assert meas.amplitude == pytest.approx(truth.amplitude_adc, rel=0.08)
        assert meas.area_adc_ns == pytest.approx(truth.charge_adc_ns, rel=0.08)


def test_peak_finding_efficiency_and_purity_over_many_events():
    """50 个事件统计：真峰全部找到，且虚假峰比例低。"""
    cfg = simdata.SimConfig(n_events=50, noise_adc=3.0, seed=2026)
    waves, truths = simdata.generate(cfg)
    t = time_axis(cfg)
    p = default_params()

    per_event = {}
    for tr in truths:
        per_event.setdefault(tr.event, []).append(tr)

    found = matched = spurious = 0
    amp_errs = []
    for i, y in enumerate(waves):
        r = pipeline.analyze(t, y, p)
        expected = per_event.get(i, [])
        used = set()
        for meas in r.peak_list:
            hit = None
            for k, tr in enumerate(expected):
                if k in used:
                    continue
                if abs(meas.time_ns - tr.peak_time_ns) <= MATCH_TOL_SAMPLES * cfg.sample_ns:
                    hit = (k, tr)
                    break
            if hit is None:
                spurious += 1
            else:
                used.add(hit[0])
                matched += 1
                amp_errs.append(abs(meas.amplitude - hit[1].amplitude_adc) / hit[1].amplitude_adc)
        found += len(expected)

    efficiency = matched / found
    assert efficiency > 0.99, f"寻峰效率 {efficiency:.3f}"
    assert spurious / found < 0.05, f"虚假峰比例 {spurious / found:.3f}"
    assert float(np.median(amp_errs)) < 0.05


def test_rise_time_matches_pulse_shape():
    """双指数脉冲的 10%-90% 上升时间应接近解析值。"""
    cfg = simdata.SimConfig(n_events=1, noise_adc=0.5, sample_ns=1.0,
                            n_pulse_choices=(1,), seed=77)
    waves, truths = simdata.generate(cfg)
    t = time_axis(cfg)
    # 无噪声模板的解析 10-90 上升时间
    tt = np.arange(0, 400, 0.01)
    shape = simdata.pulse_template(tt, 100.0, cfg)
    peak = shape.max()
    i_peak = int(np.argmax(shape))
    t10 = tt[np.argmax(shape[:i_peak] >= 0.1 * peak)]
    t90 = tt[np.argmax(shape[:i_peak] >= 0.9 * peak)]
    expected_rise = t90 - t10

    p = default_params()
    r = pipeline.analyze(t, waves[0], p)
    assert len(r.peak_list) == len(truths) == 1
    assert r.peak_list[0].rise_ns == pytest.approx(expected_rise, abs=2.0)


def test_derivative_mode_locates_leading_edge():
    """导数寻峰模式给出的起始时刻应接近脉冲真实起点。"""
    cfg = simdata.SimConfig(n_events=1, noise_adc=2.0, n_pulse_choices=(2,), seed=555)
    waves, truths = simdata.generate(cfg)
    t = time_axis(cfg)
    p = default_params()
    p.smooth.method = "savgol"
    p.deriv.method = "savgol"
    p.peaks.source = "derivative"
    r = pipeline.analyze(t, waves[0], p)
    assert len(r.peak_list) == len(truths)
    for meas, truth in zip(r.peak_list, truths):
        assert abs(meas.t_start_ns - truth.t0_ns) < 6 * cfg.sample_ns


def test_derivative_methods_give_different_results():
    """三种求导方法必须产生不同的导数序列（防止界面切换后无效）。"""
    cfg = simdata.SimConfig(n_events=1, noise_adc=2.0, seed=31)
    waves, _ = simdata.generate(cfg)
    t = time_axis(cfg)
    outs = {}
    for method in ["central", "savgol", "forward"]:
        p = default_params()
        p.deriv.method = method
        outs[method] = pipeline.analyze(t, waves[0], p).deriv
    assert not np.allclose(outs["central"], outs["savgol"])
    assert not np.allclose(outs["central"], outs["forward"])
    assert not np.allclose(outs["savgol"], outs["forward"])

    # Savitzky-Golay 窗口越宽，噪声放大越小
    rms = []
    for w in [7, 21, 41]:
        p = default_params()
        p.deriv.method = "savgol"
        p.deriv.window = w
        rms.append(float(np.std(pipeline.analyze(t, waves[0], p).deriv)))
    assert rms[0] > rms[1] > rms[2]


# --------------------------------------------------------------- 导数过零点寻峰

def _timing_residuals(source: str, cfg: simdata.SimConfig, waves, truths,
                      tol_ns: float = 12.0):
    t = time_axis(cfg)
    per = {}
    for tr in truths:
        per.setdefault(tr.event, []).append(tr)
    p = default_params()
    p.smooth.method = "savgol"
    p.deriv.method = "savgol"
    p.peaks.source = source
    p.peaks.distance_ns = 20.0
    matched, resid = 0, []
    for i, y in enumerate(waves):
        r = pipeline.analyze(t, y, p)
        exp = per.get(i, [])
        used = set()
        for meas in r.peak_list:
            for k, tr in enumerate(exp):
                if k not in used and abs(meas.time_ns - tr.peak_time_ns) <= tol_ns:
                    used.add(k)
                    matched += 1
                    resid.append(meas.time_ns - tr.peak_time_ns)
                    break
    return matched, np.asarray(resid)


def test_zero_crossing_finds_all_isolated_pulses():
    cfg = simdata.SimConfig(n_events=30, noise_adc=3.0, seed=606)
    waves, truths = simdata.generate(cfg)
    matched, _ = _timing_residuals("zero_cross", cfg, waves, truths)
    assert matched / len(truths) > 0.95


def test_zero_crossing_timing_better_than_argmax():
    """过零点插值给出亚采样点峰位，时间残差应小于直接取最大采样点。"""
    cfg = simdata.SimConfig(n_events=40, noise_adc=2.0, seed=99)
    waves, truths = simdata.generate(cfg)
    _, resid_zc = _timing_residuals("zero_cross", cfg, waves, truths)
    _, resid_max = _timing_residuals("signal", cfg, waves, truths)
    assert resid_zc.size > 0 and resid_max.size > 0
    assert np.std(resid_zc) < np.std(resid_max)
    assert abs(np.median(resid_zc)) < cfg.sample_ns


def test_zero_crossing_rejects_pure_noise():
    """纯噪声波形不应产生峰。"""
    cfg = simdata.SimConfig(noise_adc=3.0)
    y = flat_noise_wave(cfg, seed=17)
    p = default_params()
    p.peaks.source = "zero_cross"
    p.smooth.method = "savgol"
    p.deriv.method = "savgol"
    assert pipeline.analyze(time_axis(cfg), y, p).peak_list == []


# --------------------------------------------------------------- 堆积波形

def test_pileup_dataset_is_really_piled_up():
    cfg = simdata.SimConfig(n_events=40, noise_adc=3.0, pileup_mean_gap_ns=60.0,
                            n_pulse_choices=(3, 4, 5, 6), seed=777)
    _, truths = simdata.generate(cfg)
    gaps = []
    per = {}
    for tr in truths:
        per.setdefault(tr.event, []).append(tr)
    for lst in per.values():
        ts = sorted(tr.t0_ns for tr in lst)
        gaps.extend(np.diff(ts))
    assert np.median(gaps) < 2 * cfg.tau_decay_ns          # 间隔小于衰减时间 → 明显叠加
    # 叠加使「理应测到的幅度」高于单脉冲幅度
    ratios = [tr.observed_amplitude_adc / tr.amplitude_adc for tr in truths]
    assert np.median(ratios) > 1.02
    # 部分脉冲被埋在前一个脉冲的上升段里，波形上不存在对应的峰
    assert 0.5 < np.mean([tr.resolvable for tr in truths]) < 1.0


def test_pileup_peak_finding_efficiency_and_purity():
    """堆积条件下：可分辨脉冲的寻峰效率与虚假峰率都要在可接受范围。"""
    cfg = simdata.SimConfig(n_events=40, noise_adc=3.0, pileup_mean_gap_ns=60.0,
                            n_pulse_choices=(3, 4, 5, 6), seed=777)
    waves, truths = simdata.generate(cfg)
    t = time_axis(cfg)
    per = {}
    for tr in truths:
        per.setdefault(tr.event, []).append(tr)

    p = default_params()
    p.smooth.method = "savgol"
    p.deriv.method = "savgol"
    p.peaks.source = "zero_cross"
    p.peaks.distance_ns = 20.0

    n_res = sum(tr.resolvable for tr in truths)
    matched_res = found = spurious = 0
    amp_err = []
    for i, y in enumerate(waves):
        r = pipeline.analyze(t, y, p)
        found += len(r.peak_list)
        exp = per.get(i, [])
        used = set()
        for meas in r.peak_list:
            hit = None
            for k, tr in enumerate(exp):
                if k not in used and abs(meas.time_ns - tr.peak_time_ns) <= 12.0:
                    hit = (k, tr)
                    break
            if hit is None:
                spurious += 1
            else:
                used.add(hit[0])
                matched_res += int(hit[1].resolvable)
                # 与「叠加后理应测到的幅度」比较，而不是单脉冲幅度
                amp_err.append((meas.amplitude - hit[1].observed_amplitude_adc)
                               / hit[1].observed_amplitude_adc)
    assert matched_res / n_res > 0.7
    assert spurious / max(1, found) < 0.05
    assert abs(np.median(amp_err)) < 0.05


# --------------------------------------------------------------- 频域


def test_spectrum_finds_injected_interference():
    """注入 50 MHz 干扰，幅度谱峰值频率与幅度应可复现。"""
    cfg = simdata.SimConfig(n_events=1, noise_adc=1.0, interference_mhz=50.0,
                            interference_adc=6.0, n_pulse_choices=(0,), seed=8)
    waves, _ = simdata.generate(cfg)
    y = waves[0]
    dt = cfg.sample_ns
    freq, amp = amplitude_spectrum(y, dt, SpectrumParams(window="hann"))
    f_peak = freq[int(np.argmax(amp))]
    assert f_peak == pytest.approx(50.0, abs=2.0)
    assert amp.max() == pytest.approx(cfg.interference_adc, rel=0.15)


def test_bandstop_removes_interference_lowpass_reduces_noise():
    from wfa.params import FilterParams
    cfg = simdata.SimConfig(n_events=1, noise_adc=3.0, interference_mhz=50.0,
                            interference_adc=6.0, n_pulse_choices=(0,), seed=9)
    y = simdata.generate(cfg)[0][0]
    dt = cfg.sample_ns

    stopped = apply_filter(y, dt, FilterParams(kind="bandstop", f_low=45, f_high=55, order=4))
    _, amp0 = amplitude_spectrum(y, dt, SpectrumParams())
    _, amp1 = amplitude_spectrum(stopped, dt, SpectrumParams())
    assert amp1.max() < 0.25 * amp0.max()

    lowpassed = apply_filter(y, dt, FilterParams(kind="lowpass", f_high=20.0, order=4))
    assert np.std(lowpassed) < 0.6 * np.std(y)


def test_nyquist_clamped_filter_does_not_crash():
    from wfa.params import FilterParams
    y = flat_noise_wave(simdata.SimConfig())
    out = apply_filter(y, 2.0, FilterParams(kind="lowpass", f_high=1e5, order=4))
    assert np.all(np.isfinite(out))


# --------------------------------------------------------------- ROOT 读写

@pytest.fixture(scope="module")
def demo_file(tmp_path_factory):
    cfg = simdata.SimConfig(n_events=12, n_samples=512, seed=4242)
    waves, truths = simdata.generate(cfg)
    path = tmp_path_factory.mktemp("root") / "demo.root"
    simdata.write_root(str(path), waves, cfg, n_hists=5)
    return str(path), cfg, waves, truths


def test_discover_all_three_source_kinds(demo_file):
    path, cfg, waves, _ = demo_file
    specs = io_root.discover_sources(path)
    kinds = {s.kind for s in specs}
    assert {"branch", "rntuple", "hists"} <= kinds
    branch = [s for s in specs if s.kind == "branch"][0]
    assert branch.n_events == cfg.n_events


@pytest.mark.parametrize("kind", ["branch", "rntuple", "hists"])
def test_read_back_matches_written_samples(demo_file, kind):
    path, cfg, waves, _ = demo_file
    spec = [s for s in io_root.discover_sources(path) if s.kind == kind][0]
    sample_ns = None if kind == "hists" else cfg.sample_ns
    src = io_root.open_source(path, spec, sample_ns)
    try:
        idx = min(3, src.n_events - 1)
        t, y = src.get_event(idx)
        assert y.size == cfg.n_samples
        assert np.allclose(y, waves[idx], rtol=0, atol=1e-2)
        assert t[1] - t[0] == pytest.approx(cfg.sample_ns)
    finally:
        src.close()


def test_block_cache_returns_correct_events(demo_file):
    """跨块随机跳转读取，结果必须与顺序读取一致。"""
    path, cfg, waves, _ = demo_file
    spec = [s for s in io_root.discover_sources(path) if s.kind == "branch"][0]
    src = io_root.BranchSource(path, spec.tree, spec.branch, cfg.sample_ns, block=3)
    try:
        for i in [7, 0, 11, 4, 4, 9]:
            _, y = src.get_event(i)
            assert np.allclose(y, waves[i], atol=1e-2)
        with pytest.raises(IndexError):
            src.get_event(cfg.n_events)
    finally:
        src.close()


def test_scan_aggregates_all_truth_pulses(demo_file):
    """批量扫描得到的峰数与幅度分布应与真值一致。"""
    path, cfg, waves, truths = demo_file
    spec = [s for s in io_root.discover_sources(path) if s.kind == "branch"][0]
    src = io_root.open_source(path, spec, cfg.sample_ns)
    try:
        result = pipeline.scan(src, default_params(), cfg.n_events)
    finally:
        src.close()
    assert result.n_events == cfg.n_events
    assert abs(result.amplitudes.size - len(truths)) <= 1
    truth_amps = np.array([tr.amplitude_adc for tr in truths])
    assert np.median(result.amplitudes) == pytest.approx(np.median(truth_amps), rel=0.1)
