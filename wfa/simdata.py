"""模拟数据生成器：产生带「已知真值」的 ROOT 波形文件，用于验证分析链路。

模拟内容：
- 基线 + 白噪声（可选基线漂移）
- 可选正弦干扰（用于验证频谱与带阻滤波）
- 双指数脉冲 A·(exp(-t/τd) - exp(-t/τr))，每事件 1~3 个，位置与幅度随机
- 真值（峰位、峰幅、积分电荷）从无噪声模板数值计算后写入 CSV

命令行:
    python -m wfa.simdata --out demo_data.root --events 200
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, field

import numpy as np

_trapz = getattr(np, "trapezoid", np.trapz)


@dataclass
class SimConfig:
    n_events: int = 200
    n_samples: int = 1024
    sample_ns: float = 2.0        # 500 MS/s
    baseline: float = 1000.0
    noise_adc: float = 3.0
    drift_adc: float = 0.0        # 基线线性漂移幅度（整段总变化量）
    interference_mhz: float = 0.0  # 正弦干扰频率，0 = 无
    interference_adc: float = 4.0
    tau_rise_ns: float = 8.0
    tau_decay_ns: float = 60.0
    amp_mean: float = 150.0
    amp_sigma: float = 30.0
    n_pulse_choices: tuple = (1, 2, 3)
    pretrigger_ns: float = 200.0  # 前置基线区，脉冲不会落在这段内
    pileup_mean_gap_ns: float = 0.0  # >0 时按指数分布的间隔连续放脉冲，制造堆积
    polarity: int = 1             # +1 正脉冲，-1 负脉冲
    seed: int = 20260821


@dataclass
class Truth:
    """单个脉冲的真值。

    - ``amplitude_adc`` / ``charge_adc_ns``：该脉冲单独存在时的幅度与电荷
    - ``observed_amplitude_adc``：无噪声总波形在该脉冲峰位处的取值，
      即堆积叠加后「理应被测到」的幅度。堆积时它大于单脉冲幅度，
      用来区分算法误差与堆积本身带来的偏差。
    - ``resolvable``：无噪声总波形在该脉冲峰位附近是否还存在局部极大。
      堆积严重时后来的脉冲会落在前一个脉冲的上升段上，波形里根本没有
      对应的峰，任何寻峰算法都无法找到——这类脉冲标记为 False。
    """
    event: int
    t0_ns: float
    peak_time_ns: float
    amplitude_adc: float
    charge_adc_ns: float
    observed_amplitude_adc: float = 0.0
    resolvable: bool = True


def pulse_template(t_rel: np.ndarray, amp_scale: float, cfg: SimConfig) -> np.ndarray:
    """双指数脉冲模板，t_rel 为相对起始时间（ns），负值处为 0。"""
    out = np.zeros_like(t_rel)
    m = t_rel >= 0
    out[m] = amp_scale * (np.exp(-t_rel[m] / cfg.tau_decay_ns)
                          - np.exp(-t_rel[m] / cfg.tau_rise_ns))
    return out


def make_event(index: int, cfg: SimConfig,
               rng: np.random.Generator) -> tuple[np.ndarray, list[Truth]]:
    """生成一条波形与其真值列表。"""
    t = np.arange(cfg.n_samples, dtype=np.float64) * cfg.sample_ns
    clean = np.zeros_like(t)
    truths: list[Truth] = []

    n_pulse = int(rng.choice(cfg.n_pulse_choices))
    margin = 6.0 * cfg.tau_decay_ns
    t_span = t[-1] - margin
    t_low = min(max(cfg.pretrigger_ns, 0.1 * t_span), 0.8 * t_span)

    if cfg.pileup_mean_gap_ns > 0 and n_pulse > 0:
        # 堆积模式：脉冲间隔服从指数分布，脉冲之间会明显互相叠加
        gaps = rng.exponential(cfg.pileup_mean_gap_ns, max(0, n_pulse - 1))
        starts = t_low + np.concatenate([[0.0], np.cumsum(gaps)])
        starts = starts[starts < 0.9 * t[-1]]
    else:
        # 孤立模式：保证脉冲间隔足够大，真值不会被堆积掩盖
        starts = np.sort(rng.uniform(t_low, 0.9 * t_span, n_pulse))
        if starts.size > 1:
            keep = [starts[0]]
            for s in starts[1:]:
                if s - keep[-1] > margin:
                    keep.append(s)
            starts = np.asarray(keep)

    peak_idx = []
    for t0 in starts:
        amp_scale = max(10.0, rng.normal(cfg.amp_mean, cfg.amp_sigma))
        shape = pulse_template(t - t0, amp_scale, cfg)
        clean += shape
        i_peak = int(np.argmax(shape))
        peak_idx.append(i_peak)
        truths.append(Truth(
            event=index,
            t0_ns=float(t0),
            peak_time_ns=float(t[i_peak]),
            amplitude_adc=float(shape[i_peak]),
            charge_adc_ns=float(_trapz(shape, t)),
        ))

    # 叠加完成后回填「理应被测到」的幅度（含堆积贡献）与可分辨标记
    w = max(2, int(round(cfg.tau_rise_ns / cfg.sample_ns)))
    for truth, i_peak in zip(truths, peak_idx):
        truth.observed_amplitude_adc = float(clean[i_peak])
        lo = max(1, i_peak - w)
        hi = min(clean.size - 1, i_peak + w)
        seg = clean[lo - 1:hi + 2]
        truth.resolvable = bool(
            np.any((seg[1:-1] >= seg[:-2]) & (seg[1:-1] >= seg[2:]))
        ) if seg.size >= 3 else True

    y = np.full(cfg.n_samples, cfg.baseline, dtype=np.float64)
    if cfg.drift_adc:
        y += np.linspace(0.0, cfg.drift_adc, cfg.n_samples)
    if cfg.interference_mhz:
        phase = rng.uniform(0, 2 * np.pi)
        y += cfg.interference_adc * np.sin(
            2 * np.pi * cfg.interference_mhz * 1e6 * t * 1e-9 + phase)
    y += rng.normal(0.0, cfg.noise_adc, cfg.n_samples)
    y += cfg.polarity * clean
    return y, truths


def generate(cfg: SimConfig) -> tuple[list[np.ndarray], list[Truth]]:
    rng = np.random.default_rng(cfg.seed)
    waves, truths = [], []
    for i in range(cfg.n_events):
        y, tr = make_event(i, cfg, rng)
        waves.append(y)
        truths.extend(tr)
    return waves, truths


def write_root(path: str, waves: list[np.ndarray], cfg: SimConfig,
               n_hists: int = 20, write_rntuple: bool = True) -> None:
    """写入 ROOT 文件：TTree 变长分支 + 若干 TH1 + 可选 RNTuple。"""
    import awkward as ak
    import uproot

    jag = ak.Array([w.astype(np.float32).tolist() for w in waves])
    n = len(waves)
    with uproot.recreate(path) as f:
        f.mktree("wf", {
            "wave": ak.types.from_datashape("var * float32", highlevel=False),
            "evt": np.int32,
            "dt_ns": np.float64,
        })
        f["wf"].extend({
            "wave": jag,
            "evt": np.arange(n, dtype=np.int32),
            "dt_ns": np.full(n, cfg.sample_ns),
        })
        if write_rntuple:
            f["wf_rntuple"] = {"wave": jag}
        edges = np.arange(cfg.n_samples + 1, dtype=np.float64) * cfg.sample_ns
        for i in range(min(n_hists, n)):
            f["wave_h_%03d" % i] = (waves[i], edges)


def write_truth_csv(path: str, truths: list[Truth]) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["event", "t0_ns", "peak_time_ns", "amplitude_adc",
                    "charge_adc_ns", "observed_amplitude_adc", "resolvable"])
        for tr in truths:
            w.writerow([tr.event, f"{tr.t0_ns:.4f}", f"{tr.peak_time_ns:.4f}",
                        f"{tr.amplitude_adc:.4f}", f"{tr.charge_adc_ns:.4f}",
                        f"{tr.observed_amplitude_adc:.4f}", int(tr.resolvable)])


def main() -> None:
    ap = argparse.ArgumentParser(description="生成带真值的模拟波形 ROOT 文件")
    ap.add_argument("--out", default="demo_data.root")
    ap.add_argument("--truth", default="", help="真值 CSV 路径，默认与 --out 同名")
    ap.add_argument("--events", type=int, default=200)
    ap.add_argument("--samples", type=int, default=1024)
    ap.add_argument("--sample-ns", type=float, default=2.0)
    ap.add_argument("--noise", type=float, default=3.0)
    ap.add_argument("--drift", type=float, default=0.0)
    ap.add_argument("--interference-mhz", type=float, default=0.0)
    ap.add_argument("--pileup-gap-ns", type=float, default=0.0,
                    help=">0 时生成堆积波形，脉冲间隔按该均值的指数分布抽样")
    ap.add_argument("--pulses", type=int, nargs="+", default=[1, 2, 3],
                    help="每事件脉冲数的候选值")
    ap.add_argument("--polarity", type=int, default=1, choices=[1, -1])
    ap.add_argument("--seed", type=int, default=20260821)
    args = ap.parse_args()

    cfg = SimConfig(
        n_events=args.events, n_samples=args.samples, sample_ns=args.sample_ns,
        noise_adc=args.noise, drift_adc=args.drift,
        interference_mhz=args.interference_mhz, polarity=args.polarity,
        pileup_mean_gap_ns=args.pileup_gap_ns,
        n_pulse_choices=tuple(args.pulses),
        seed=args.seed,
    )
    waves, truths = generate(cfg)
    write_root(args.out, waves, cfg)
    truth_path = args.truth or (args.out.rsplit(".", 1)[0] + "_truth.csv")
    write_truth_csv(truth_path, truths)
    mode = f"堆积模式(平均间隔 {cfg.pileup_mean_gap_ns} ns)" if cfg.pileup_mean_gap_ns > 0 else "孤立脉冲模式"
    print(f"已写入 {args.out}: {cfg.n_events} 事件 x {cfg.n_samples} 采样点, "
          f"dt = {cfg.sample_ns} ns, 噪声 sigma = {cfg.noise_adc} ADC, {mode}")
    print(f"真值 {truth_path}: {len(truths)} 个脉冲")


if __name__ == "__main__":
    main()
