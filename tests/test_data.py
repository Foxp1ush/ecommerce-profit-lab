import pandas as pd
import pytest

import assumptions as A
import db
import generate
import profit

START, END = A.SALES_START.isoformat(), A.SALES_END.isoformat()


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    path = tmp_path_factory.mktemp("lab") / "lab.db"
    tables = generate.build()
    generate.write(tables, path)
    return path, tables


def test_same_seed_same_data(built):
    _, tables = built
    again = generate.build()
    for name, df in tables.items():
        pd.testing.assert_frame_equal(df, again[name], obj=name)
    assert not generate.build(seed=7)["sales_daily"].equals(tables["sales_daily"])


def test_no_negative_or_empty(built):
    _, t = built
    s = t["sales_daily"]
    assert (s[["qty", "gross", "discount", "returned"]] >= 0).all().all()
    assert (s["qty"] > 0).all() and (s["returned"] <= s["qty"]).all() and (s["discount"] <= s["gross"]).all()
    assert (t["ad_spend_daily"]["spend"] >= 0).all()
    assert not t["skus"].drop(columns="device").isna().any().any()
    assert set(s["channel"]) == set(A.CHANNELS) and s["day"].between(START, END).all()


def test_fx_covers_every_month(built):
    _, t = built
    months = set(pd.period_range(A.SALES_START, A.SALES_END, freq="M").strftime("%Y-%m"))
    fx = t["fx_rates"]
    assert {m for m in fx[fx.currency == "USD"].month} == months == {m for m in fx[fx.currency == "JPY"].month}


def test_sql_totals_match_raw(built):
    path, t = built
    inputs = db.query("sku_channel_inputs", {"start": START, "end": END}, path)
    for col in ("qty", "gross", "discount", "returned"):
        assert inputs[col].sum() == pytest.approx(t["sales_daily"][col].sum())
    assert inputs["ad_spend"].sum() == pytest.approx(t["ad_spend_daily"]["spend"].sum())
    monthly = db.query("channel_monthly", {"start": START, "end": END}, path)
    assert monthly["qty"].sum() == t["sales_daily"]["qty"].sum()
    # 기간 필터: 한 달만 고르면 그달 판매만
    one = db.query("channel_monthly", {"start": "2026-03-01", "end": "2026-03-31"}, path)
    assert set(one["month"]) == {"2026-03"}


def test_launch_history_shape(built):
    path, t = built
    assert len(t["launches"]) == 6
    weekly = db.query("launch_weekly", path=path)
    assert len(weekly) == 6 * A.LAUNCH_WEEKS * 2  # 출시 6회 × 20주 × (케이스, 강화유리)
    assert (weekly.groupby(["device", "category"])["week"].nunique() == A.LAUNCH_WEEKS).all()


def test_profit_identity_and_planted_losses(built):
    path, t = built
    df = profit.load(START, END, path=path)
    assert (df["revenue"] - df[profit.COST_ITEMS].sum(axis=1)).sum() == pytest.approx(df["profit"].sum())
    by = df.groupby(["sku", "channel"])["profit"].sum()
    for p in t["planted_cases"].itertuples():
        assert by[(p.sku, p.channel)] < 0, f"{p.sku} {p.channel} ({p.cause})는 적자여야 함"


def test_assumptions_change_profit(built):
    path, _ = built
    base = profit.load(START, END, path=path)["profit"].sum()
    pricier = {ch: {k: r + 0.05 for k, r in rates.items()} for ch, rates in A.COMMISSION.items()}
    assert profit.load(START, END, path=path, commission=pricier)["profit"].sum() < base


@pytest.mark.parametrize("sql", ["DELETE FROM skus", "DROP TABLE skus", "INSERT INTO fx_rates VALUES ('2030-01','USD',1)",
                                 "UPDATE skus SET cost_usd = 0", "WITH x AS (SELECT 1) DELETE FROM skus",
                                 "ATTACH DATABASE 'other.db' AS o", "PRAGMA writable_schema = 1",
                                 "SELECT 1; DELETE FROM skus"])
def test_sql_runner_blocks_changes(built, sql):
    path, _ = built
    with pytest.raises(db.SqlError):
        db.run_readonly(sql, path=path)
    assert len(db.table("skus", path)) == 126  # 데이터는 그대로


def test_sql_runner_reads_with_params_limit_and_timeout(built):
    path, t = built
    df, cut = db.run_readonly("SELECT SUM(qty) AS n FROM sales_daily WHERE day BETWEEN :start AND :end",
                              {"start": START, "end": END}, path=path)
    assert df["n"].iloc[0] == t["sales_daily"]["qty"].sum() and not cut
    df, cut = db.run_readonly("SELECT * FROM sales_daily", path=path, max_rows=50)
    assert len(df) == 50 and cut
    with pytest.raises(db.SqlError, match="표가 없습니다"):
        db.run_readonly("SELECT * FROM nope", path=path)
    with pytest.raises(db.SqlError, match="멈췄습니다"):
        db.run_readonly("WITH RECURSIVE r(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM r) SELECT COUNT(*) FROM r",
                        path=path, timeout=0.5)


def test_sql_runner_renames_duplicate_columns(built):
    path, _ = built
    df, _ = db.run_readonly("SELECT * FROM sales_daily s JOIN ad_spend_daily a "
                            "ON a.day = s.day AND a.sku = s.sku AND a.channel = s.channel LIMIT 5", path=path)
    assert list(df.columns) == ["day", "sku", "channel", "qty", "gross", "discount", "returned",
                                "day_2", "sku_2", "channel_2", "spend"]
    assert df.columns.is_unique and len(df) == 5
