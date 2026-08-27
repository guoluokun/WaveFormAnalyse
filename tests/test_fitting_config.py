"""通用拟合与分析配置测试。"""

from __future__ import annotations

import json

import numpy as np
import pytest

from wfa import config, fitting
from wfa.params import AnalysisParams, FitParams


def test_config_round_trip(tmp_path):
    p = AnalysisParams()
    p.polarity = -1
    p.baseline.method = "sigma_clip"
    p.threshold.n_sigma = 6.5
    p.smooth.method = "savgol"
    p.fit.enabled = True
    p.fit.model = "gaussian"
    p.fit.x_min_ns = 100.0
    p.fit.x_max_ns = 300.0

    path = tmp_path / "analysis.json"
    config.save_json(path, p)
    q = config.load_json(path)

    assert q.polarity == -1
    assert q.baseline.method == "sigma_clip"
    assert q.threshold.n_sigma == pytest.approx(6.5)
    assert q.smooth.method == "savgol"
    assert q.fit.enabled is True
    assert q.fit.model == "gaussian"
    assert q.fit.x_min_ns == pytest.approx(100.0)
    assert q.fit.x_max_ns == pytest.approx(300.0)


def test_config_ignores_unknown_fields(tmp_path):
    path = tmp_path / "future.json"
    path.write_text(json.dumps({"polarity": -1, "future_option": 123,
                                "fit": {"model": "gaussian", "future_fit": True}}), encoding="utf-8")
    p = config.load_json(path)
    assert p.polarity == -1
    assert p.fit.model == "gaussian"


def test_gaussian_fit_recovers_parameters():
    rng = np.random.default_rng(42)
    t = np.linspace(0.0, 500.0, 1001)
    truth = (120.0, 245.0, 28.0)
    y = fitting.gaussian(t, *truth) + rng.normal(0.0, 1.0, t.size)
    p = FitParams(enabled=True, model="gaussian", x_min_ns=120.0, x_max_ns=380.0)
    r = fitting.fit_waveform(t, y, p, sigma=1.0)

    assert r.success, r.message
    assert r.params[0] == pytest.approx(truth[0], rel=0.03)
    assert r.params[1] == pytest.approx(truth[1], abs=1.0)
    assert r.params[2] == pytest.approx(truth[2], rel=0.05)
    assert r.rms < 1.3
    assert r.ndf > 0


def test_double_exponential_amplitude_is_independent_of_x_range():
    pars = (80.0, 100.0, 8.0, 90.0)
    x1 = np.linspace(0.0, 500.0, 1001)
    x2 = np.linspace(50.0, 300.0, 501)
    y1 = fitting.double_exponential(x1, *pars)
    y2 = fitting.double_exponential(x2, *pars)
    assert np.max(y1) == pytest.approx(pars[0], rel=2e-3)
    assert np.max(y2) == pytest.approx(pars[0], rel=2e-3)


def test_disabled_fit_is_safe_noop():
    t = np.arange(100, dtype=float)
    y = np.sin(t / 10.0)
    r = fitting.fit_waveform(t, y, FitParams(enabled=False))
    assert not r.success
    assert "未启用" in r.message
    assert np.all(np.isnan(r.y_fit))
