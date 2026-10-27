import pytest
from streamlit.testing.v1 import AppTest
from streamlit.util import calc_hash

import assumptions as A
import db
import generate
import profit

START, END = A.SALES_START.isoformat(), A.SALES_END.isoformat()


@pytest.fixture(scope="module")
def path(tmp_path_factory):
    p = tmp_path_factory.mktemp("lab") / "lab.db"
    generate.write(generate.build(), p)
    return p


def test_diagnosis_finds_planted_causes(path):
    """심어 둔 손해 사례 5건을 모두 적자로 찾고, 원인도 맞힌다."""
    found = profit.diagnose(profit.load(START, END, path=path)).set_index(["sku", "channel"])
    for p in db.table("planted_cases", path).itertuples():
        assert (p.sku, p.channel) in found.index, f"{p.sku} {p.channel} 못 찾음"
        assert found.loc[(p.sku, p.channel), "cause"] == p.cause


def test_summary_ratios(path):
    df = profit.load(START, END, path=path)
    ch = profit.summarize(df, ["channel"]).set_index("channel")
    assert ch["revenue"].sum() == pytest.approx(df["revenue"].sum())
    assert ch.loc["amazon_us", "margin"] == pytest.approx(ch.loc["amazon_us", "profit"] / ch.loc["amazon_us", "revenue"])
    assert (ch["return_rate"] <= 1).all()


def test_fx_and_overhead_move_profit(path):
    df = profit.load(START, END, path=path)
    fx = profit.fx_table(path)
    weaker_won = {k: v * 1.1 for k, v in fx.items()}  # 원화 약세 10%
    shifted = profit.compute(db.query("sku_channel_inputs", {"start": START, "end": END}, path), weaker_won)
    amazon = df["channel"].str.startswith("amazon")
    # 아마존 매출은 원화로 늘고, 매입원가(달러)는 모든 채널에서 오른다
    assert shifted.loc[amazon, "revenue"].sum() > df.loc[amazon, "revenue"].sum()
    assert shifted["cogs"].sum() > df["cogs"].sum()
    assert profit.load(START, END, path=path, overhead=0.3)["profit"].sum() < df["profit"].sum()


@pytest.mark.parametrize("page", ["overview", "sku", "launch", "data", "settings"])
def test_pages_render(page):
    at = AppTest.from_file("app.py", default_timeout=120)
    at._page_hash = calc_hash(page)
    at.run()
    assert not at.exception
    assert not at.warning


def test_apply_table_edits():
    import pandas as pd
    df = pd.DataFrame({"케이스": [10.8, 5.5], "충전기": [7.8, 5.5]}, index=["쿠팡", "스마트스토어"])
    out = profit.apply_edits(df, {0: {"케이스": 12}, 1: {"충전기": None}})
    assert out.loc["쿠팡", "케이스"] == 12 and out.loc["스마트스토어", "충전기"] == 5.5
    assert df.loc["쿠팡", "케이스"] == 10.8  # 원래 표는 그대로


def test_category_fees_and_size_fulfil(path):
    """같은 채널이라도 카테고리마다 수수료율, 크기 등급마다 물류비가 다르게 적용된다."""
    df = profit.load(START, END, path=path)
    cp = df[df.channel == "coupang"]
    pay = (cp["gross"] - cp["discount"])
    rate = (cp["commission"] / pay).groupby(cp["category"]).mean()
    assert rate["charger"] == pytest.approx(A.COMMISSION["coupang"]["charger"])
    assert rate["case"] == pytest.approx(A.COMMISSION["coupang"]["case"])
    unit = (cp["fulfil"] / cp["qty"]).groupby(cp["category"]).mean()
    assert unit["glass"] == pytest.approx(A.FULFIL["coupang"]["small"])
    assert unit["stand"] == pytest.approx(A.FULFIL["coupang"]["large"])
