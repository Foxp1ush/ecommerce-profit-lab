"""공헌이익 계산. 모든 금액은 원화 공급가액(부가세·소비세 제외).

한 행(SKU × 채널 × 월)의 계산
  결제금액      = 정가 매출 − 할인                               (채널 통화, 세금 포함 여부는 채널 설정)
  순매출        = 결제금액의 공급가액 − 반품 환불분               (환불 = 반품 수량 × 개당 공급가액)
  − 판매·결제 수수료 = 결제금액 × (채널·카테고리별 판매수수료율 + 결제수수료율)   (세금 포함 결제금액 기준 가정)
  − 물류·배송비 = 판매 수량 × 채널·크기 등급별 개당 물류비
  − 반품 처리비 = 반품 수량 × 개당 반품 처리비
  − 광고비
  − 매출원가    = (판매 수량 − 다시 팔 수 있는 반품) × 매입원가(달러) × 그달 환율 × (1 + 수입 부대비용)
  = 공헌이익
환율: 아마존 미국은 달러, 아마존 일본은 엔을 그달 환율로 원화 환산한다.
"""

from __future__ import annotations

import pandas as pd

import assumptions as A
import db

COST_ITEMS = ["commission", "fulfil", "return_cost", "ad", "cogs"]  # 순매출에서 빠지는 순서
COST_LABEL = {"commission": "판매·결제 수수료", "fulfil": "물류·배송비", "return_cost": "반품 처리비",
              "ad": "광고비", "cogs": "매출원가"}


def fx_table(path=db.DB_PATH) -> dict[tuple[str, str], float]:
    """(월, 통화) → 1단위당 원화. 원화는 1."""
    fx = db.table("fx_rates", path)
    return {(r.month, r.currency): r.krw for r in fx.itertuples()}


def compute(inputs: pd.DataFrame, fx: dict, channels: dict | None = None, overhead: float | None = None,
            resellable: float | None = None, commission: dict | None = None,
            fulfil: dict | None = None) -> pd.DataFrame:
    """sku_channel_inputs 쿼리 결과에 원화 공헌이익 열들을 붙인다. 인자를 주면 그 가정값으로 다시 계산한다.

    commission = {채널: {카테고리: 판매수수료율}}, fulfil = {채널: {크기 등급: 개당 물류비}}
    """
    channels = channels or A.CHANNELS
    commission = commission or A.COMMISSION
    fulfil = fulfil or A.FULFIL
    overhead = A.IMPORT_OVERHEAD if overhead is None else overhead
    resellable = A.RETURN_RESELLABLE if resellable is None else resellable
    df = inputs.copy()
    ch = df["channel"].map(channels)
    cur = ch.map(lambda c: c["currency"])
    rate = [1.0 if c == "KRW" else fx[(m, c)] for m, c in zip(df["month"], cur)]
    usd = [fx[(m, "USD")] for m in df["month"]]
    df["fx"], df["usd"] = rate, usd
    tax = ch.map(lambda c: 1 + A.TAX_RATE if c["tax_in_price"] else 1.0)
    pay = df["gross"] - df["discount"]
    supply = pay / tax
    refund = (supply / df["qty"]) * df["returned"]
    df["refund"] = refund * df["fx"]
    df["revenue"] = (supply - refund) * df["fx"]
    rate_of = [commission[c][k] for c, k in zip(df["channel"], df["category"])]
    df["commission"] = pay * (pd.Series(rate_of, index=df.index) + ch.map(lambda c: c["payment"])) * df["fx"]
    unit = [fulfil[c][A.SIZE_OF[k]] for c, k in zip(df["channel"], df["category"])]
    df["fulfil"] = df["qty"] * pd.Series(unit, index=df.index) * df["fx"]
    df["return_cost"] = df["returned"] * ch.map(lambda c: c["return_cost"]) * df["fx"]
    df["ad"] = df["ad_spend"] * df["fx"]
    df["cogs"] = (df["qty"] - df["returned"] * resellable) * df["cost_usd"] * df["usd"] * (1 + overhead)
    df["profit"] = df["revenue"] - df[COST_ITEMS].sum(axis=1)
    return df


def load(start: str, end: str, path=db.DB_PATH, **kw) -> pd.DataFrame:
    """기간 안의 SKU × 채널 × 월 공헌이익."""
    return compute(db.query("sku_channel_inputs", {"start": start, "end": end}, path), fx_table(path), **kw)


# ---- 집계·진단 --------------------------------------------------------------

SUM_COLS = ["qty", "returned", "refund", "revenue", *COST_ITEMS, "profit"]


def summarize(df: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """by 단위로 합치고 비율 열을 붙인다: 이익률, 광고비율, 반품률, 수수료·물류 비율, 반품 부담."""
    keep = [c for c in ("name", "category", "device") if c in df.columns and c not in by and "sku" in by]
    g = df.groupby(by, as_index=False).agg({**{c: "sum" for c in SUM_COLS}, **{c: "first" for c in keep}})
    rev = g["revenue"].where(g["revenue"] != 0)
    g["margin"] = g["profit"] / rev
    g["ad_ratio"] = g["ad"] / rev
    g["fee_ratio"] = (g["commission"] + g["fulfil"]) / rev
    g["return_rate"] = g["returned"] / g["qty"]
    # 반품 부담: 환불 + 반품 처리비가 반품 전 매출에서 차지하는 비율
    g["return_burden"] = (g["refund"] + g["return_cost"]) / (g["revenue"] + g["refund"])
    return g


CAUSE_LABEL = {"ads": "광고비 과다", "returns": "반품 과다", "fees": "판매가 대비 수수료·물류비 과다"}


def diagnose(df: pd.DataFrame) -> pd.DataFrame:
    """SKU × 채널 단위의 적자 행마다 가장 큰 원인을 찾는다.

    기준(같은 필터 안의 평균)과 비교해 '얼마나 더 많이 새는지'(순매출 대비 %p)가 가장 큰 항목을 원인으로 본다.
    - 광고비: 같은 채널 평균과 비교
    - 수수료·물류비: 같은 채널 · 같은 카테고리 평균과 비교 (수수료율·물류비가 카테고리·크기마다 달라서)
    - 반품: 같은 카테고리 평균과 비교
    """
    rows = summarize(df, ["sku", "channel"])
    by_ch = summarize(df, ["channel"]).set_index("channel")
    by_cat = summarize(df, ["category"]).set_index("category")
    by_cc = summarize(df, ["channel", "category"]).set_index(["channel", "category"])
    out = rows[rows["profit"] < 0].copy()
    if out.empty:
        return out.assign(cause=[], cause_text=[])
    excess = pd.DataFrame({
        "ads": out["ad_ratio"] - out["channel"].map(by_ch["ad_ratio"]),
        "fees": out["fee_ratio"] - pd.Series([by_cc.loc[(c, k), "fee_ratio"]
                                              for c, k in zip(out["channel"], out["category"])], index=out.index),
        "returns": out["return_burden"] - out["category"].map(by_cat["return_burden"]),
    }, index=out.index)
    out["cause"] = excess.idxmax(axis=1)

    def text(r) -> str:
        if r["cause"] == "ads":
            return f"광고비가 순매출의 {r['ad_ratio']:.0%} (이 채널 평균 {by_ch.loc[r['channel'], 'ad_ratio']:.0%})"
        if r["cause"] == "fees":
            return (f"수수료·물류비가 순매출의 {r['fee_ratio']:.0%} "
                    f"(이 채널 같은 카테고리 평균 {by_cc.loc[(r['channel'], r['category']), 'fee_ratio']:.0%})"
                    " — 판매가가 낮음")
        return f"반품률 {r['return_rate']:.0%} (이 카테고리 평균 {by_cat.loc[r['category'], 'return_rate']:.0%})"

    out["cause_text"] = out.apply(text, axis=1)
    return out


def apply_edits(df: pd.DataFrame, edited_rows: dict) -> pd.DataFrame:
    """화면 표에서 고친 칸({행 번호: {열 이름: 새 값}})을 반영한 새 표. 지운 칸(None)은 원래 값을 둔다."""
    out = df.copy()
    for row, changes in edited_rows.items():
        for col, value in changes.items():
            if value is not None:
                out.iloc[int(row), out.columns.get_loc(col)] = float(value)
    return out
