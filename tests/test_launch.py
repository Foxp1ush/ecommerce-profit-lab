import numpy as np
import pytest

import assumptions as A
import generate
import launch

WEEKS = sum(A.LEAD_TIME_WEEKS.values())


@pytest.fixture(scope="module")
def path(tmp_path_factory):
    p = tmp_path_factory.mktemp("lab") / "lab.db"
    generate.write(generate.build(), p)
    return p


@pytest.fixture(scope="module")
def model(path):
    return launch.fit(launch.horizon_totals(launch.history(path), WEEKS))


def test_more_interest_more_demand(model):
    low = launch.forecast(model, 60, "Galaxy")["case"]
    high = launch.forecast(model, 90, "Galaxy")["case"]
    assert np.median(high) > np.median(low)
    assert model["beta"][1] > 0  # 관심 지수 계수는 양수
    assert sum(model["share"].values()) == pytest.approx(1.0)


def test_newsvendor_moves_with_costs(model):
    d = launch.forecast(model, 80, "iPhone")["case"]
    base = launch.best_quantity(d, cu=8000, co=1000)
    assert launch.best_quantity(d, cu=16000, co=1000) > base  # 품절 손실이 크면 더 많이
    assert launch.best_quantity(d, cu=8000, co=4000) < base   # 남는 손실이 크면 더 적게
    curve = launch.profit_curve(d, 8000, 1000, qmax=float(np.quantile(d, 0.999)), points=400)
    peak = curve.loc[curve["expected_profit"].idxmax(), "qty"]
    assert peak == pytest.approx(base, rel=0.03)  # 곡선 꼭대기 = 공식으로 구한 권장 물량


def test_backtest_beats_naive(path):
    bt = launch.backtest(launch.history(path), WEEKS, {"case": 8000, "glass": 4000}, {"case": 1150, "glass": 500})
    s = launch.backtest_summary(bt)
    assert len(bt) == 12
    assert s["model_gap"] < s["naive_gap"] and s["gap_cut"] > 0
    assert 0.5 <= s["coverage"] <= 1.0 and s["mape"] < 0.2


def test_splits_sum_to_one(path):
    for c, s in launch.color_split(path).items():
        assert s.sum() == pytest.approx(1.0) and list(s.index) == A.CATEGORIES[c]["colors"]
    for brand in ("iPhone", "Galaxy"):
        assert launch.variant_split(brand, path).sum() == pytest.approx(1.0)
