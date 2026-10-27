"""생성된 가상 데이터가 그럴듯한지 한눈에 보는 요약.

    .venv\\Scripts\\python.exe check.py
"""

from __future__ import annotations

import pandas as pd

import assumptions as A
import db
import profit

START, END = A.SALES_START.isoformat(), A.SALES_END.isoformat()


def won(x: float) -> str:
    return f"{x / 1e8:,.2f}억" if abs(x) >= 1e8 else f"{x / 1e4:,.0f}만"


def main() -> None:
    df = profit.load(START, END)
    name = {k: v["name"] for k, v in A.CHANNELS.items()}
    print(f"[전체] 기간 {START} ~ {END} · 순매출 {won(df.revenue.sum())} · 공헌이익 {won(df.profit.sum())} "
          f"({df.profit.sum() / df.revenue.sum():.1%}) · 판매 {df.qty.sum():,}개\n")

    print("[채널별] 순매출 비중 · 공헌이익률")
    ch = df.groupby("channel")[["revenue", "profit", "qty"]].sum()
    for k, r in ch.iterrows():
        print(f"  {name[k]:<8} {r.revenue / ch.revenue.sum():5.1%}  이익률 {r.profit / r.revenue:6.1%}  {won(r.revenue)}")

    print("\n[카테고리별] 개당 순매출 · 반품률 · 공헌이익률")
    cat = df.groupby("category")[["revenue", "profit", "qty", "returned"]].sum()
    for k, r in cat.iterrows():
        print(f"  {A.CATEGORIES[k]['name']:<8} {r.revenue / r.qty:8,.0f}원  반품 {r.returned / r.qty:5.1%}  "
              f"이익률 {r.profit / r.revenue:6.1%}")

    print("\n[월별] 순매출 (기종 출시 효과: 2026-03 갤럭시 S26)")
    mo = df.groupby("month")["revenue"].sum()
    print("  " + "  ".join(f"{m[2:]} {won(v)}" for m, v in mo.items()))

    print("\n[비용 구성] 순매출 대비")
    for item in profit.COST_ITEMS:
        print(f"  {profit.COST_LABEL[item]:<10} {df[item].sum() / df.revenue.sum():5.1%}")

    print("\n[심어 둔 손해 사례] 판매 순위(그 채널 안) · 공헌이익")
    sc = df.groupby(["sku", "channel"])[["revenue", "profit", "qty"]].sum().reset_index()
    sc["rank"] = sc.groupby("channel")["qty"].rank(ascending=False, method="min").astype(int)
    for p in db.table("planted_cases").itertuples():
        r = sc[(sc.sku == p.sku) & (sc.channel == p.channel)].iloc[0]
        print(f"  {p.sku:<16} {name[p.channel]:<8} {p.cause:<7} 판매 {r['rank']}위 / "
              f"{(sc.channel == p.channel).sum()}개 · 공헌이익 {won(r.profit)} — {p.note}")

    losers = sc[sc.profit < 0].sort_values("profit")
    print(f"\n[적자 SKU×채널] {len(losers)}개 (심어 둔 것 외에도 자연스럽게 생긴 적자가 섞여 있음)")
    for r in losers.head(8).itertuples():
        print(f"  {r.sku:<16} {name[r.channel]:<8} 공헌이익 {won(r.profit)}  판매 {r.qty:,}개")


if __name__ == "__main__":
    pd.set_option("display.width", 160)
    main()
