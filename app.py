"""그립앤코 수익성 대시보드 (가상 데이터).

    .venv\\Scripts\\python.exe -m streamlit run app.py

화면
- 수익성 개요: 순매출이 공헌이익이 되기까지 어디서 새는지(워터폴), 채널별 비용 구조, 월별 추이
- SKU 진단: 판매량 × 이익률 4분면, 많이 팔리지만 손해 보는 상품과 원인, 상위 상품 × 채널 이익률
왼쪽 '가정값' 패널에서 수수료·물류비·환율 등을 바꾸면 모든 숫자가 다시 계산된다.
"""

from __future__ import annotations

from datetime import date

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

import assumptions as A
import db
import generate
import launch
import profit

st.set_page_config(page_title=f"{A.BRAND} 수익성 대시보드", page_icon="📊", layout="wide")

# 그래프 색 (dataviz 기본 팔레트). 텍스트는 색을 입히지 않는다
BLUE, ORANGE, AQUA, YELLOW, MAGENTA, GREEN = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"
GRAY, RED = "#9c9a92", "#d03b3b"  # RED는 '적자' 상태 표시 전용
VAT = "원화 공급가액 · VAT 별도"
CH_NAME = {k: v["name"] for k, v in A.CHANNELS.items()}
CAT_NAME = {k: v["name"] for k, v in A.CATEGORIES.items()}

if not db.DB_PATH.exists():  # 처음 실행(또는 클라우드 배포) 때 가상 데이터를 만든다
    generate.write(generate.build())


# ---- 공통: 데이터·가정값·필터 ---------------------------------------------------

@st.cache_data
def inputs(start: str, end: str) -> pd.DataFrame:
    return db.query("sku_channel_inputs", {"start": start, "end": end})


@st.cache_data
def fx_base() -> dict:
    return profit.fx_table()


SIZE_NAME = A.SIZES


def fee_tables() -> tuple[pd.DataFrame, pd.DataFrame]:
    """가정값 표 2개의 기본값: 판매수수료율(%, 채널 × 카테고리), 개당 물류비(채널 통화, 채널 × 크기 등급)."""
    comm = pd.DataFrame({CAT_NAME[c]: [A.COMMISSION[ch][c] * 100 for ch in A.CHANNELS] for c in A.CATEGORIES},
                        index=[CH_NAME[ch] for ch in A.CHANNELS])
    ful = pd.DataFrame({SIZE_NAME[z]: [float(A.FULFIL[ch][z]) for ch in A.CHANNELS] for z in A.SIZES},
                       index=[f"{CH_NAME[ch]} ({A.CHANNELS[ch]['currency']})" for ch in A.CHANNELS])
    return comm, ful


def defaults() -> dict:
    """입력칸·가정값 표의 기본값. 처음 한 번만 session_state에 넣고, 입력칸에는 기본값을 따로 주지 않는다
    (둘 다 주면 Streamlit이 경고를 띄운다)."""
    comm, ful = fee_tables()
    return {"a_fx": 0.0, "a_oh": A.IMPORT_OVERHEAD * 100, "a_rs": A.RETURN_RESELLABLE * 100,
            "t_comm": comm, "t_ful": ful,
            "f_dates": (A.SALES_START, A.SALES_END), "f_ch": list(A.CHANNELS), "f_cat": list(A.CATEGORIES),
            **LAUNCH_DEFAULTS, **DATA_DEFAULTS}


def keep_state() -> None:
    """기본값을 넣고, 메뉴를 옮겨도 필터·가정값이 초기화되지 않게 한다(Streamlit은 화면에 없는 입력값을 지운다)."""
    for k, v in defaults().items():
        st.session_state[k] = st.session_state.get(k, v)


def assumption_panel() -> dict:
    """왼쪽 패널: 자주 바꿔 보는 가정값. 수수료·물류비 표는 '가정값' 메뉴에 있다. 바꾼 값은 모든 화면에 적용된다."""
    with st.sidebar:
        st.markdown("**가정값** · 바꾸면 모든 숫자가 다시 계산돼요")
        st.caption("실제 플랫폼 요율이 아닌 가정값입니다. 채널·카테고리별 수수료와 크기별 물류비는 ⚙️ 가정값 메뉴에서 고칩니다.")
        # 정확한 값을 넣기 쉽도록 숫자 칸. 범위를 정해 자릿수 실수(예: 120%)는 막는다
        fx_shift = st.number_input("환율 변동 (달러·엔, %)", -30.0, 30.0, step=0.5, format="%.1f", key="a_fx",
                                   help="+10이면 원화 약세: 아마존 매출은 늘고 매입원가도 오른다 (-30 ~ +30)")
        overhead = st.number_input("수입 부대비용 (관세·운송, %)", 0.0, 50.0, step=0.5, format="%.1f", key="a_oh",
                                   help="매입원가(원화 환산) 대비 관세·해상운송·통관 비용 (0 ~ 50)") / 100
        resell = st.number_input("반품 중 재판매 가능 (%)", 0.0, 100.0, step=5.0, format="%.0f", key="a_rs",
                                 help="반품된 상품 중 다시 팔 수 있는 비율. 나머지는 매입원가 손실 (0 ~ 100)") / 100
        if st.button("가정값 처음으로", width="stretch"):
            for k in list(st.session_state):
                if k.startswith(("a_", "t_")):
                    del st.session_state[k]
            st.rerun()
    comm, ful = st.session_state["t_comm"], st.session_state["t_ful"]
    commission = {ch: {c: comm.iloc[i][CAT_NAME[c]] / 100 for c in A.CATEGORIES} for i, ch in enumerate(A.CHANNELS)}
    fulfil = {ch: {z: ful.iloc[i][SIZE_NAME[z]] for z in A.SIZES} for i, ch in enumerate(A.CHANNELS)}
    return {"commission": commission, "fulfil": fulfil, "overhead": overhead, "resellable": resell,
            "fx_shift": fx_shift / 100}


def edit_table(name: str, fmt: str, step: float) -> None:
    """session_state[name] 표를 엑셀처럼 고치게 한다. 고친 값은 표에 바로 반영되고 메뉴를 옮겨도 남는다."""
    ver = st.session_state.get(f"{name}_ver", 0)
    key = f"{name}_editor_{ver}"

    def apply() -> None:
        st.session_state[name] = profit.apply_edits(st.session_state[name], st.session_state[key]["edited_rows"])
        st.session_state[f"{name}_ver"] = ver + 1  # 새 키로 다시 그려 고친 표를 기준으로 삼는다

    st.data_editor(st.session_state[name], key=key, on_change=apply, width="stretch",
                   column_config={c: st.column_config.NumberColumn(c, min_value=0.0, step=step, format=fmt)
                                  for c in st.session_state[name].columns})


def filters() -> tuple[str, str, list[str], list[str]]:
    c1, c2, c3 = st.columns([2, 3, 3])
    picked = c1.date_input("기간", min_value=A.SALES_START, max_value=A.SALES_END, format="YYYY-MM-DD",
                           key="f_dates")
    start, end = (picked if isinstance(picked, (tuple, list)) and len(picked) == 2 else (A.SALES_START, A.SALES_END))
    ch = c2.pills("채널", list(A.CHANNELS), format_func=CH_NAME.get, selection_mode="multi",
                  key="f_ch") or list(A.CHANNELS)
    cat = c3.pills("카테고리", list(A.CATEGORIES), format_func=CAT_NAME.get, selection_mode="multi",
                   key="f_cat") or list(A.CATEGORIES)
    return start.isoformat(), end.isoformat(), ch, cat


def data(a: dict) -> pd.DataFrame:
    start, end, ch, cat = filters()
    fx = {k: v * (1 + a["fx_shift"]) for k, v in fx_base().items()}
    df = profit.compute(inputs(start, end), fx, commission=a["commission"], fulfil=a["fulfil"],
                        overhead=a["overhead"], resellable=a["resellable"])
    df = df[df["channel"].isin(ch) & df["category"].isin(cat)]
    st.caption(f"{start} ~ {end} · 금액은 모두 {VAT} · 가상 브랜드 '{A.BRAND}'의 가상 데이터")
    return df


def won(x: float) -> str:
    if abs(x) >= 1e8:
        return f"{x / 1e8:,.2f}억"
    return f"{x / 1e4:,.0f}만"


def name_axis(df: pd.DataFrame, col: str) -> alt.Axis:
    """한글 이름표가 숨거나 막대와 겹치지 않게 왼쪽 자리를 미리 잡는다."""
    width = int(df[col].astype(str).str.len().max() * 14 + 16)
    return alt.Axis(minExtent=width, maxExtent=width, labelLimit=width, labelPadding=8, labelOverlap=False,
                    title=None)


def show_sql(name: str) -> None:
    with st.expander("이 숫자를 뽑은 SQL 보기"):
        st.code(db.sql_text(name), language="sql")
        st.caption("SQL로 SKU×채널×월 단위까지 모은 뒤, 수수료·물류비·환율 같은 가정값은 Python(profit.py)에서 적용합니다.")


# ---- 화면 ① 수익성 개요 ---------------------------------------------------------

def overview(a: dict) -> None:
    st.title("수익성 개요")
    st.caption("많이 판 채널이 아니라 실제로 남긴 채널을 봅니다. 순매출에서 무엇이 얼마나 빠져 공헌이익이 되는지 확인하세요.")
    df = data(a)
    if df.empty:
        st.info("선택한 조건에 판매가 없습니다.")
        return
    tot = df[profit.SUM_COLS].sum()
    k = st.columns(4)
    k[0].metric("순매출", won(tot.revenue), help="결제금액의 공급가액에서 반품 환불을 뺀 금액")
    k[1].metric("공헌이익", won(tot.profit), help="순매출 − 수수료 − 물류 − 반품 처리 − 광고 − 매출원가 (고정비 전)")
    k[2].metric("공헌이익률", f"{tot.profit / tot.revenue:.1%}")
    k[3].metric("판매 수량", f"{int(tot.qty):,}개")

    # 워터폴: 순매출에서 비용이 하나씩 빠져 공헌이익이 된다
    st.subheader("이익이 어디서 새는가")
    steps, level = [], tot.revenue
    steps.append({"항목": "순매출", "start": 0, "end": level, "kind": "합계", "value": level})
    for item in profit.COST_ITEMS:
        steps.append({"항목": profit.COST_LABEL[item], "start": level, "end": level - tot[item], "kind": "비용",
                      "value": -tot[item]})
        level -= tot[item]
    steps.append({"항목": "공헌이익", "start": 0, "end": level, "kind": "합계", "value": level})
    w = pd.DataFrame(steps)
    w["label"] = [f"{won(v)} ({v / tot.revenue:+.0%})" if i not in (0, len(w) - 1) else won(v)
                  for i, v in enumerate(w["value"])]
    w["억"] = w["start"] / 1e8
    w["억2"] = w["end"] / 1e8
    w["위"] = w[["억", "억2"]].max(axis=1)  # 금액 글자는 막대 위쪽에
    order = list(w["항목"])
    base = alt.Chart(w).encode(x=alt.X("항목:N", sort=order, title=None, axis=alt.Axis(labelAngle=0)))
    bars = base.mark_bar(cornerRadius=4, size=46).encode(
        y=alt.Y("억:Q", title="억 원 (공급가액)"), y2="억2:Q",
        color=alt.Color("kind:N", scale=alt.Scale(domain=["합계", "비용"], range=[BLUE, GRAY]), legend=None),
        tooltip=[alt.Tooltip("항목:N"), alt.Tooltip("label:N", title="금액 (순매출 대비)")])
    text = base.mark_text(dy=-8, fontSize=12).encode(y=alt.Y("위:Q"), text="label:N")
    st.altair_chart((bars + text).properties(height=320), width="stretch")
    biggest = max(profit.COST_ITEMS, key=lambda i: tot[i])
    st.caption(f"가장 큰 비용은 **{profit.COST_LABEL[biggest]}**(순매출의 {tot[biggest] / tot.revenue:.0%})입니다.")

    # 채널별 비용 구조: 순매출 100% 중 비용 항목과 이익이 차지하는 몫
    st.subheader("채널별로 남는 몫")
    ch = profit.summarize(df, ["channel"])
    ch["채널"] = ch["channel"].map(CH_NAME)
    ch = ch.sort_values("margin", ascending=False)
    parts = ch.melt(id_vars=["채널", "revenue"], value_vars=[*profit.COST_ITEMS, "profit"], var_name="item",
                    value_name="amount")
    parts["항목"] = parts["item"].map({**profit.COST_LABEL, "profit": "공헌이익"})
    parts["비중"] = parts["amount"] / parts["revenue"]
    labels = [*[profit.COST_LABEL[i] for i in profit.COST_ITEMS], "공헌이익"]
    parts["순서"] = parts["항목"].map({l: i for i, l in enumerate(labels)})
    stack = alt.Chart(parts).mark_bar(size=22, stroke="white", strokeWidth=2).encode(
        y=alt.Y("채널:N", sort=list(ch["채널"]), axis=name_axis(parts, "채널")),
        x=alt.X("비중:Q", title="순매출 대비 비중", axis=alt.Axis(format="%"), stack="zero"),
        color=alt.Color("항목:N", scale=alt.Scale(domain=labels, range=[ORANGE, YELLOW, MAGENTA, AQUA, GRAY, BLUE]),
                        legend=alt.Legend(orient="top", title=None)),
        order=alt.Order("순서:Q"),
        tooltip=["채널:N", "항목:N", alt.Tooltip("비중:Q", format=".1%")])
    st.altair_chart(stack.properties(height=48 * len(ch) + 60), width="stretch")
    st.caption("파란 막대(공헌이익)가 짧을수록 많이 팔아도 덜 남는 채널입니다. 위에서부터 이익률이 높은 순입니다.")
    table = ch[["채널", "revenue", "profit", "margin", "ad_ratio", "fee_ratio", "return_rate"]].rename(columns={
        "revenue": "순매출", "profit": "공헌이익", "margin": "공헌이익률", "ad_ratio": "광고비율",
        "fee_ratio": "수수료·물류 비율", "return_rate": "반품률"})
    with st.expander("표로 보기"):
        st.dataframe(table.style.format({"순매출": "{:,.0f}", "공헌이익": "{:,.0f}", "공헌이익률": "{:.1%}",
                                         "광고비율": "{:.1%}", "수수료·물류 비율": "{:.1%}", "반품률": "{:.1%}"}),
                     hide_index=True, width="stretch")

    # 월별 추이: 순매출과 공헌이익 (같은 단위라 한 축)
    st.subheader("월별 추이")
    mo = df.groupby("month", as_index=False)[["revenue", "profit"]].sum()
    lines = mo.melt(id_vars="month", var_name="series", value_name="amount")
    lines["구분"] = lines["series"].map({"revenue": "순매출", "profit": "공헌이익"})
    lines["억"] = lines["amount"] / 1e8
    chart = alt.Chart(lines).mark_line(strokeWidth=2, point=alt.OverlayMarkDef(size=64)).encode(
        x=alt.X("month:N", title=None, axis=alt.Axis(labelAngle=0)),
        y=alt.Y("억:Q", title="억 원 (공급가액)"),
        color=alt.Color("구분:N", scale=alt.Scale(domain=["순매출", "공헌이익"], range=[BLUE, ORANGE]),
                        legend=alt.Legend(orient="top", title=None)),
        tooltip=["month:N", "구분:N", alt.Tooltip("억:Q", format=".2f", title="억 원")])
    st.altair_chart(chart.properties(height=260), width="stretch")
    st.caption("기종 출시 직후(2025-10 아이폰 17, 2026-03 갤럭시 S26) 매출이 오릅니다. 가상 데이터의 출시일은 근사값입니다.")
    show_sql("sku_channel_inputs")


# ---- 화면 ② SKU 진단 ----------------------------------------------------------

def diagnosis(a: dict) -> None:
    st.title("SKU 진단")
    st.caption("판매 순위만 보면 놓치는 '많이 팔리지만 손해 보는 상품'을 찾고, 원인을 짚습니다.")
    df = data(a)
    if df.empty:
        st.info("선택한 조건에 판매가 없습니다.")
        return
    sc = profit.summarize(df, ["sku", "channel"])
    sc["채널"] = sc["channel"].map(CH_NAME)
    sc["채널 내 판매 순위"] = sc.groupby("channel")["qty"].rank(ascending=False, method="min").astype(int)
    sc["상태"] = sc["profit"].map(lambda p: "적자" if p < 0 else "흑자")
    losers = profit.diagnose(df)
    k = st.columns(3)
    k[0].metric("상품×채널 조합", f"{len(sc):,}개")
    k[1].metric("적자 조합", f"{(sc.profit < 0).sum()}개")
    k[2].metric("적자 합계", won(sc.loc[sc.profit < 0, "profit"].sum()), help="흑자로 돌리면 늘어나는 이익")

    st.subheader("판매량 × 공헌이익률")
    plot = sc[sc["qty"] >= 5].copy()  # 몇 개 안 팔린 조합은 이익률이 출렁여서 뺀다
    plot["이익률"] = plot["margin"].clip(-1, 1)
    mid = plot["qty"].median()
    pts = alt.Chart(plot).mark_circle(size=70, opacity=0.8, stroke="white", strokeWidth=1).encode(
        x=alt.X("qty:Q", title="판매 수량 (로그 눈금)", scale=alt.Scale(type="log")),
        y=alt.Y("이익률:Q", title="공헌이익률", axis=alt.Axis(format="%")),
        color=alt.Color("상태:N", scale=alt.Scale(domain=["흑자", "적자"], range=[BLUE, RED]),
                        legend=alt.Legend(orient="top", title=None)),
        tooltip=[alt.Tooltip("name:N", title="상품"), "채널:N", alt.Tooltip("qty:Q", title="판매 수량", format=",.0f"),
                 alt.Tooltip("margin:Q", title="공헌이익률", format=".1%"),
                 alt.Tooltip("profit:Q", title="공헌이익(원)", format=",.0f")])
    zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color=GRAY, strokeDash=[4, 4]).encode(y="y:Q")
    vline = alt.Chart(pd.DataFrame({"x": [mid]})).mark_rule(color=GRAY, strokeDash=[4, 4]).encode(x="x:Q")
    st.altair_chart((pts + zero + vline).properties(height=380), width="stretch")
    st.caption(f"오른쪽 아래(판매 수량이 중앙값 {mid:,.0f}개보다 많고 이익률이 0% 아래)가 '많이 팔리지만 손해 보는' 영역입니다. "
               "판매 5개 미만 조합은 뺐습니다.")

    st.subheader("많이 팔리지만 손해 보는 상품")
    if losers.empty:
        st.success("선택한 조건에서 적자인 상품×채널이 없습니다.")
    else:
        losers = losers.merge(sc[["sku", "channel", "채널", "채널 내 판매 순위"]], on=["sku", "channel"])
        losers = losers.sort_values("qty", ascending=False)
        show = losers[["name", "채널", "qty", "채널 내 판매 순위", "revenue", "profit", "margin", "cause", "cause_text"]]
        show = show.assign(cause=show["cause"].map(profit.CAUSE_LABEL)).rename(columns={
            "name": "상품", "qty": "판매 수량", "revenue": "순매출", "profit": "공헌이익", "margin": "공헌이익률",
            "cause": "주된 원인", "cause_text": "근거"})
        st.dataframe(show.style.format({"판매 수량": "{:,}", "순매출": "{:,.0f}", "공헌이익": "{:,.0f}",
                                        "공헌이익률": "{:.0%}"}), hide_index=True, width="stretch")
        st.caption("원인은 같은 채널(광고비·수수료·물류) 또는 같은 카테고리(반품)의 평균과 비교해, "
                   "순매출 대비 가장 많이 더 새는 항목입니다.")
        st.download_button("CSV로 내려받기", show.to_csv(index=False).encode("utf-8-sig"),
                           file_name="loss_making_skus.csv", mime="text/csv")

    st.subheader("상위 상품 × 채널 공헌이익률")
    top = sc.groupby("sku")["revenue"].sum().nlargest(15).index
    heat = sc[sc["sku"].isin(top)].copy()
    heat["이익률"] = heat["margin"].clip(-0.2, 0.6)  # 적자는 -20%에서 이미 진한 빨강 (적자를 눈에 띄게)
    order = list(sc[sc.sku.isin(top)].groupby("name")["revenue"].sum().sort_values(ascending=False).index)
    grid = alt.Chart(heat).mark_rect(stroke="white", strokeWidth=2).encode(
        x=alt.X("채널:N", sort=[CH_NAME[c] for c in A.CHANNELS], title=None, axis=alt.Axis(labelAngle=0, orient="top")),
        y=alt.Y("name:N", sort=order, axis=name_axis(heat, "name")),
        color=alt.Color("이익률:Q", scale=alt.Scale(domain=[-0.2, 0, 0.6], range=[RED, "#f0efec", BLUE], interpolate="lab"),
                        legend=alt.Legend(title="공헌이익률", format="%")),
        tooltip=[alt.Tooltip("name:N", title="상품"), "채널:N", alt.Tooltip("margin:Q", title="공헌이익률", format=".1%"),
                 alt.Tooltip("qty:Q", title="판매 수량", format=",.0f")])
    text = grid.mark_text(fontSize=11).encode(text=alt.Text("margin:Q", format=".0%"), color=alt.value("#1a1a19"))
    st.altair_chart((grid + text).properties(height=34 * len(top) + 40), width="stretch")
    st.caption("순매출 상위 15개 상품입니다. 같은 상품도 채널에 따라 이익률이 크게 다릅니다. 빨갈수록 적자(-20% 이하는 같은 빨강), "
               "파랄수록 많이 남습니다.")
    show_sql("sku_channel_inputs")


# ---- 화면 ③ 초도 발주 시뮬레이터 ------------------------------------------------

LAUNCH_DEFAULTS = {"l_name": "아이폰 18 (가상)", "l_brand": "iPhone", "l_interest": 88,
                   "l_lead": sum(A.LEAD_TIME_WEEKS.values()), "l_loss": 35, "l_cat": "case"}


@st.cache_data
def launch_model(weeks: int) -> dict:
    return launch.fit(launch.horizon_totals(launch.history(), weeks))


@st.cache_data
def launch_backtest(weeks: int, cu: tuple, co: tuple) -> pd.DataFrame:
    return launch.backtest(launch.history(), weeks, dict(zip(launch.CATS, cu)), dict(zip(launch.CATS, co)))


def unit_values(a: dict, loss: float) -> tuple[dict, dict, dict]:
    """최근 1년 데이터와 지금 가정값으로 카테고리별 Cu(개당 공헌이익), Co(개당 수입 원가 × 손실률)."""
    fx = {k: v * (1 + a["fx_shift"]) for k, v in fx_base().items()}
    df = profit.compute(inputs(A.SALES_START.isoformat(), A.SALES_END.isoformat()), fx, commission=a["commission"],
                        fulfil=a["fulfil"], overhead=a["overhead"], resellable=a["resellable"])
    ue = launch.unit_economics(df)
    return ue, {c: max(ue[c]["margin"], 1.0) for c in launch.CATS}, {c: ue[c]["landed"] * loss for c in launch.CATS}


def simulator(a: dict) -> None:
    st.title("신기종 초도 발주 시뮬레이터")
    st.caption("새 기종이 나올 때 케이스·강화유리를 처음에 얼마나 주문할지 정합니다. 해외 생산은 다시 주문해도 도착까지 오래 걸리므로, "
               "초도 물량이 그동안의 수요를 버텨야 합니다. 너무 많으면 재고가 남고, 모자라면 팔 기회를 놓칩니다.")
    c1, c2, c3 = st.columns(3)
    name = c1.text_input("신기종 이름", key="l_name")
    brand = c1.segmented_control("브랜드", ["iPhone", "Galaxy"], key="l_brand") or "iPhone"
    interest = c2.slider("출시 전 관심 지수 (0~100)", 30, 100, key="l_interest",
                         help="가상 지표. 실무에서는 사전예약·검색량·기사 수 같은 출시 전 신호를 하나의 지수로 만든다고 가정합니다. "
                              f"과거: " + ", ".join(f"{d['name']} {d['interest']}" for d in A.DEVICES.values()))
    weeks = c2.slider("재주문 도착까지 (주)", 3, 16, key="l_lead",
                      help=f"기본 = 생산 {A.LEAD_TIME_WEEKS['production']}주 + 해상 운송 {A.LEAD_TIME_WEEKS['sea']}주. "
                           "초도 물량은 이 기간의 수요를 버텨야 합니다.")
    loss = c3.slider("남은 재고 중 결국 손실이 되는 비율 (%)", 0, 100, key="l_loss",
                     help="기종 액세서리는 시간이 지나면 잘 안 팔립니다. 남은 재고를 할인·폐기할 때 수입 원가의 몇 %를 잃는지 가정합니다.") / 100
    ue, cu, co = unit_values(a, loss)
    c3.caption("개당 가치 (최근 1년 실적·지금 가정값 기준, 공급가액): " + " · ".join(
        f"{CAT_NAME[c]} 공헌이익 {ue[c]['margin']:,.0f}원 / 수입 원가 {ue[c]['landed']:,.0f}원" for c in launch.CATS))

    model = launch_model(weeks)
    demand = launch.forecast(model, interest, brand)
    prev = launch.horizon_totals(launch.history(), weeks)
    prev = prev[prev.brand == brand].sort_values("launch_date").iloc[-1]
    rec = {c: launch.best_quantity(demand[c], cu[c], co[c]) for c in launch.CATS}

    st.subheader(f"{name or '신기종'} 권장 초도 물량")
    cols = st.columns(2)
    for col, c in zip(cols, launch.CATS):
        lo, med, hi = launch.quantiles(demand[c])
        q = rec[c]
        stockout = float((demand[c] > q).mean())
        with col.container(border=True):
            st.markdown(f"**{CAT_NAME[c]}**")
            k1, k2 = st.columns(2)
            k1.metric("권장 초도 물량", f"{round(q, -1):,.0f}개")
            k2.metric(f"{weeks}주 예상 수요 (중앙값)", f"{med:,.0f}개", help="80% 확률로 이 범위 안")
            st.caption(f"80% 범위 {lo:,.0f} ~ {hi:,.0f}개 · 이 물량이면 품절 확률 {stockout:.0%} · "
                       f"직전 {brand} 출시({prev['name']}) 같은 기간 실적 {prev[c]:,.0f}개")
    ratio = {c: cu[c] / (cu[c] + co[c]) for c in launch.CATS}
    st.caption("권장 물량이 예상 수요(중앙값)보다 많은 이유: 1개를 못 팔아 잃는 공헌이익이 1개가 남아 잃는 돈보다 커서, "
               "수요 분포의 " + " · ".join(f"{CAT_NAME[c]} {ratio[c]:.0%}" for c in launch.CATS)
               + " 지점까지 준비하는 것이 기대 이익이 가장 큽니다.")

    cat = st.segmented_control("자세히 볼 카테고리", list(launch.CATS), format_func=CAT_NAME.get, key="l_cat") or "case"

    # 주차별 예상 판매: 중앙값 선 + 80% 범위 띠, 재주문 도착 시점 표시
    st.subheader("주차별 예상 판매")
    sh = launch.shape(launch.history(), cat)
    within = sh[sh.index <= weeks].sum()
    lo, med, hi = launch.quantiles(demand[cat])
    wk = pd.DataFrame({"주차": sh.index, "중앙값": med * sh.values / within, "하단": lo * sh.values / within,
                       "상단": hi * sh.values / within})
    band = alt.Chart(wk).mark_area(opacity=0.18, color=BLUE).encode(
        x=alt.X("주차:Q", title="출시 후 주차", axis=alt.Axis(tickMinStep=1)), y=alt.Y("하단:Q", title="주간 판매 (개)"),
        y2="상단:Q")
    line = alt.Chart(wk).mark_line(color=BLUE, strokeWidth=2, point=alt.OverlayMarkDef(size=48)).encode(
        x="주차:Q", y="중앙값:Q",
        tooltip=[alt.Tooltip("주차:Q"), alt.Tooltip("중앙값:Q", format=",.0f"), alt.Tooltip("하단:Q", format=",.0f", title="80% 하단"),
                 alt.Tooltip("상단:Q", format=",.0f", title="80% 상단")])
    rule = alt.Chart(pd.DataFrame({"x": [weeks + 0.5], "label": [f"재주문 도착 ({weeks}주 뒤)"]}))
    rline = rule.mark_rule(color=GRAY, strokeDash=[4, 4]).encode(x="x:Q")
    rtext = rule.mark_text(align="left", dx=6, dy=-6, color="#52514e").encode(x="x:Q", y=alt.value(12), text="label:N")
    st.altair_chart((band + line + rline + rtext).properties(height=280), width="stretch")
    st.caption(f"파란 띠 = 80% 범위. 점선 왼쪽({weeks}주)까지의 판매를 초도 물량으로 버텨야 합니다. "
               "곡선 모양은 과거 출시 6회의 평균입니다.")

    # 주문 물량별 기대 이익
    st.subheader("주문 물량별 기대 이익")
    # 결정이 갈리는 구간만 확대해서 본다: 수요 10% 지점의 절반 ~ 99% 지점의 1.2배
    qlo, qhi = 0.5 * float(np.quantile(demand[cat], 0.1)), 1.2 * float(np.quantile(demand[cat], 0.99))
    qlo = min(qlo, 0.9 * float(prev[cat]))
    curve = launch.profit_curve(demand[cat], cu[cat], co[cat], qmax=qhi, qmin=qlo)
    curve["만원"] = curve["expected_profit"] / 1e4
    marks = pd.DataFrame({"안": ["권장 물량", "예상 수요 중앙값만큼", f"직전 출시({prev['name']}) 실적만큼"],
                          "qty": [rec[cat], med, float(prev[cat])]})
    marks["만원"] = [launch.profit_curve(demand[cat], cu[cat], co[cat], q, 2)["expected_profit"].iloc[-1] / 1e4
                    for q in marks["qty"]]
    base = alt.Chart(curve).mark_line(color=BLUE, strokeWidth=2).encode(
        x=alt.X("qty:Q", title="초도 주문 물량 (개)", axis=alt.Axis(format=",.0f"), scale=alt.Scale(zero=False)),
        y=alt.Y("만원:Q", title="기대 이익 (만 원, 공급가액)", scale=alt.Scale(zero=False)),
        tooltip=[alt.Tooltip("qty:Q", format=",.0f", title="물량"), alt.Tooltip("만원:Q", format=",.0f", title="기대 이익(만 원)"),
                 alt.Tooltip("stockout:Q", format=".0%", title="품절 확률")])
    dots = alt.Chart(marks).mark_point(filled=True, size=110, stroke="white", strokeWidth=1.5).encode(
        x=alt.X("qty:Q", axis=alt.Axis(format=",.0f")), y="만원:Q",
        color=alt.Color("안:N", scale=alt.Scale(domain=list(marks["안"]), range=[BLUE, ORANGE, GRAY]),
                        legend=alt.Legend(orient="top", title=None)),
        tooltip=["안:N", alt.Tooltip("qty:Q", format=",.0f", title="물량"),
                 alt.Tooltip("만원:Q", format=",.0f", title="기대 이익(만 원)")])
    st.altair_chart((base + dots).properties(height=300), width="stretch")
    best = marks.iloc[0]["만원"]
    st.caption("곡선의 꼭대기가 권장 물량입니다. 다른 안의 기대 이익 차이: " + " · ".join(
        f"{r.안} {r.만원 - best:+,.0f}만 원" for r in marks.iloc[1:].itertuples()))

    # 색상·모델별 나누기
    st.subheader("색상·모델별 주문 수량")
    colors = launch.color_split()[cat]
    variants = launch.variant_split(brand)
    split = pd.DataFrame([{"모델": v, **{col: int(round(rec[cat] * vs * cs, -1)) for col, cs in colors.items()}}
                          for v, vs in variants.items()])
    split["합계"] = split.drop(columns="모델").sum(axis=1)
    st.dataframe(split, hide_index=True, width="stretch")
    st.caption(f"색상 비중 = 과거 출시 평균, 모델 비중 = 가장 최근 {brand} 기종의 판매 비중. 10개 단위 반올림.")
    st.download_button("발주 수량 CSV 내려받기", split.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"initial_order_{cat}.csv", mime="text/csv")

    with st.expander("이 모형은 얼마나 맞았나 (과거 출시로 검증)"):
        bt = launch_backtest(weeks, tuple(cu[c] for c in launch.CATS), tuple(co[c] for c in launch.CATS))
        s = launch.backtest_summary(bt)
        k = st.columns(3)
        k[0].metric("평균 오차", f"{s['mape']:.1%}", help="예측 중앙값과 실제의 차이")
        k[1].metric("80% 범위 적중", f"{s['coverage']:.0%}", help=f"{len(bt)}건 중 실제가 범위 안에 든 비율")
        k[2].metric("놓친 이익 감소", f"{s['gap_cut']:.0%}",
                    help="수요를 정확히 알았을 때 대비 놓친 이익이, '직전 출시만큼 주문'보다 얼마나 줄었나")
        show = bt.assign(카테고리=bt["category"].map(CAT_NAME))[
            ["name", "카테고리", "actual", "pred", "lo", "hi", "order", "naive_order"]].rename(columns={
            "name": "출시", "actual": "실제", "pred": "예측(중앙값)", "lo": "80% 하단", "hi": "80% 상단",
            "order": "모형 권장 물량", "naive_order": "직전 출시만큼"})
        st.dataframe(show.style.format({c: "{:,.0f}" for c in show.columns[2:]}), hide_index=True, width="stretch")
        st.caption("출시 1회씩 빼고 나머지 5회만으로 예측한 결과입니다(그 출시는 모르는 상태에서 맞혀 보기). "
                   f"모형 놓친 이익 {won(s['model_gap'])}원 vs 직전 출시 따라 하기 {won(s['naive_gap'])}원.")

    with st.expander("계산 방법"):
        st.markdown(f"""
1. **수요 예측**: 과거 출시 6회의 '출시 후 {weeks}주 판매량(케이스+강화유리)'을 관심 지수·브랜드로 설명하는 회귀식
   `log(판매량) = a + b·log(관심 지수) + c·[아이폰]`을 세우고, 새 기종의 수요를 범위와 함께 예측합니다.
   한 출시의 케이스·강화유리는 같이 오르내리므로 출시 단위로 예측한 뒤 과거 비중
   ({' · '.join(f"{CAT_NAME[c]} {model['share'][c]:.0%}" for c in launch.CATS)})으로 나눕니다.
   데이터가 6개뿐이라 범위를 t 분포로 넓게 잡습니다.
2. **초도 물량**: 1개가 모자라면 개당 공헌이익(Cu)을, 1개가 남으면 수입 원가 × 손실률(Co)을 잃습니다.
   기대 이익이 가장 큰 물량은 수요 분포의 Cu ÷ (Cu + Co) 지점입니다(재고 관리의 신문팔이 모형).
3. **한계**: 가상 데이터이고, 관심 지수는 가정한 지표입니다. 재주문은 한 번, 항공 운송 같은 긴급 보충은 고려하지 않았습니다.
""")


# ---- 화면 ④ 데이터 보기 (SQL 직접 실행) -------------------------------------------

SQL_EXAMPLES = {
    "채널별 판매 수량": "-- 채널별로 몇 개 팔렸나 (엑셀의 피벗 테이블)\n"
                      "SELECT channel, SUM(qty) AS 판매수량\nFROM sales_daily\nGROUP BY channel\nORDER BY 판매수량 DESC;",
    "반품률 높은 상품 10개": "-- 50개 넘게 팔린 상품 중 반품률이 높은 순 (JOIN으로 상품 이름 붙이기)\n"
                          "SELECT k.name AS 상품, SUM(s.qty) AS 판매, SUM(s.returned) AS 반품,\n"
                          "       ROUND(1.0 * SUM(s.returned) / SUM(s.qty), 3) AS 반품률\n"
                          "FROM sales_daily s\nJOIN skus k ON k.sku = s.sku\nGROUP BY k.name\n"
                          "HAVING SUM(s.qty) >= 50\nORDER BY 반품률 DESC\nLIMIT 10;",
    "쿠팡 월별 광고비": "-- 날짜를 월로 잘라 묶기 (substr = 엑셀의 LEFT)\n"
                      "SELECT substr(day, 1, 7) AS 월, ROUND(SUM(spend)) AS 광고비\nFROM ad_spend_daily\n"
                      "WHERE channel = 'coupang'\nGROUP BY 월\nORDER BY 월;",
    "아마존 미국 매출을 원화로": "-- 그달 환율 표를 붙여 달러 → 원화 (두 표 JOIN)\n"
                             "SELECT substr(s.day, 1, 7) AS 월, ROUND(SUM(s.gross - s.discount), 2) AS 달러_매출,\n"
                             "       f.krw AS 환율, ROUND(SUM(s.gross - s.discount) * f.krw) AS 원화_매출\n"
                             "FROM sales_daily s\nJOIN fx_rates f ON f.month = substr(s.day, 1, 7) AND f.currency = 'USD'\n"
                             "WHERE s.channel = 'amazon_us'\nGROUP BY 월\nORDER BY 월;",
    "기종별 출시 후 4주 판매": "SELECT l.name AS 기종, l.interest AS 관심지수, SUM(w.qty) AS 판매_4주\n"
                           "FROM launch_weekly w\nJOIN launches l ON l.device = w.device\nWHERE w.week <= 4\n"
                           "GROUP BY l.name\nORDER BY 판매_4주 DESC;",
    "프로젝트 쿼리: 상품×채널×월 비용 투입값": db.sql_text("sku_channel_inputs"),
    "프로젝트 쿼리: 채널별 월 판매": db.sql_text("channel_monthly"),
    "프로젝트 쿼리: 출시 후 주간 판매": db.sql_text("launch_weekly"),
}
DATA_DEFAULTS = {"d_table": "sales_daily", "sql_ex": next(iter(SQL_EXAMPLES)),
                 "sql_text": next(iter(SQL_EXAMPLES.values()))}


def data_view() -> None:
    st.title("데이터 보기")
    st.caption(f"대시보드가 쓰는 원본 표(가상 데이터)를 보고, SQL을 직접 실행해 볼 수 있습니다. "
               "**조회만 가능**하며 데이터를 바꾸거나 지우는 SQL은 실행되지 않습니다. 금액은 채널 통화(원·달러·엔) 그대로입니다.")

    st.subheader("표 둘러보기")
    name = st.selectbox("표", list(db.TABLE_DOCS), key="d_table",
                        format_func=lambda t: f"{t} — {db.TABLE_DOCS[t][0]}")
    title, cols = db.TABLE_DOCS[name]
    count = db.run_readonly(f"SELECT COUNT(*) AS n FROM {name}")[0]["n"].iloc[0]
    c1, c2 = st.columns([1, 2])
    c1.markdown(f"**{title}** · {count:,}행")
    c1.dataframe(pd.DataFrame({"칸": list(cols), "뜻": list(cols.values())}), hide_index=True, width="stretch")
    c2.dataframe(db.run_readonly(f"SELECT * FROM {name} LIMIT 100")[0], hide_index=True, width="stretch", height=300)
    c2.caption("처음 100행만 보여 줍니다. 채널 코드: " + ", ".join(f"{k} = {v}" for k, v in CH_NAME.items()))

    st.subheader("SQL 직접 실행")

    def load_example() -> None:
        st.session_state["sql_text"] = SQL_EXAMPLES[st.session_state["sql_ex"]]
        st.session_state.pop("sql_result", None)

    st.selectbox("예시 불러오기", list(SQL_EXAMPLES), key="sql_ex", on_change=load_example)
    sql = st.text_area("SQL", key="sql_text", height=220)
    params = {}
    if ":start" in sql or ":end" in sql:
        params = {"start": A.SALES_START.isoformat(), "end": A.SALES_END.isoformat()}
        st.caption(f":start, :end 자리에는 전체 기간({params['start']} ~ {params['end']})을 넣어 실행합니다. "
                   "대시보드에서는 화면의 기간 필터 값이 들어갑니다.")
    if st.button("실행", type="primary"):
        try:
            st.session_state["sql_result"] = db.run_readonly(sql, params)
        except db.SqlError as e:
            st.session_state.pop("sql_result", None)
            st.error(str(e))
    if (res := st.session_state.get("sql_result")) is not None:
        df, cut = res
        st.caption(f"결과 {len(df):,}행" + (" — 1,000행까지만 보여 줍니다. LIMIT이나 WHERE로 줄여 보세요." if cut else "")
                   + (" · 같은 이름의 칸이 여러 번 나와 뒤의 것에 _2, _3을 붙였습니다(두 표를 SELECT * 로 붙이면 생김)."
                      if any(c.rsplit("_", 1)[-1].isdigit() and c.rsplit("_", 1)[0] in df.columns for c in df.columns)
                      else ""))
        st.dataframe(df, hide_index=True, width="stretch")
        st.download_button("결과 CSV 내려받기", df.to_csv(index=False).encode("utf-8-sig"), file_name="query_result.csv",
                           mime="text/csv")
    with st.expander("SQL 기본 문법 한눈에"):
        st.markdown("""
| SQL | 하는 일 | 엑셀로 치면 |
|---|---|---|
| `SELECT 칸1, 칸2` | 보여 줄 칸 고르기 | 열 고르기 |
| `FROM 표` | 어느 표에서 | 어느 시트에서 |
| `WHERE 조건` | 줄 걸러 내기 | 필터 |
| `GROUP BY 칸` + `SUM()` `COUNT()` | 같은 값끼리 묶어 합계·개수 | 피벗 테이블 |
| `HAVING 조건` | 묶은 결과를 다시 걸러 내기 | 피벗 결과에 필터 |
| `JOIN 표 ON 연결 조건` | 다른 표를 옆에 붙이기 | VLOOKUP |
| `ORDER BY 칸 DESC` | 정렬 (DESC = 큰 것부터) | 정렬 |
| `LIMIT 10` | 앞에서 10줄만 | 위에서 10줄 |
""")


# ---- 화면 ⑤ 가정값 -----------------------------------------------------------

def settings() -> None:
    st.title("가정값")
    st.caption("칸을 눌러 숫자를 고치면 모든 화면에 바로 반영됩니다. 모두 가상 브랜드의 가정값이며 실제 플랫폼 요율이 아닙니다. "
               "되돌리려면 왼쪽 '가정값 처음으로'를 누르세요.")
    st.subheader("판매수수료율 (%) — 채널 × 카테고리")
    edit_table("t_comm", "%.1f", 0.1)
    st.caption("쿠팡·아마존은 카테고리별 수수료 표가 있는 구조라 카테고리마다 다르게 두었습니다(전자기기인 충전기를 낮게). "
               "스마트스토어는 카테고리보다 결제수단·유입경로에 따라 달라지는 구조라 같은 값으로, "
               f"자사몰은 판매수수료 없이 결제(PG) 수수료 {A.CHANNELS['own']['payment']:.1%}만 따로 붙습니다.")
    st.subheader("개당 물류·배송비 — 채널 × 크기 등급")
    edit_table("t_ful", "%.2f", 0.1)
    sizes = {z: [CAT_NAME[c] for c, s in A.SIZE_OF.items() if s == z] for z in A.SIZES}
    st.caption("채널 통화 기준(아마존은 배송 대행비). 크기 등급: "
               + " · ".join(f"{SIZE_NAME[z]} = {', '.join(v)}" for z, v in sizes.items()))


# ---- 메뉴 -------------------------------------------------------------------

keep_state()
a = assumption_panel()
nav = st.navigation([st.Page(lambda: overview(a), title="수익성 개요", url_path="overview", icon="📈"),
                     st.Page(lambda: diagnosis(a), title="SKU 진단", url_path="sku", icon="🔍"),
                     st.Page(lambda: simulator(a), title="초도 발주 시뮬레이터", url_path="launch", icon="📦"),
                     st.Page(data_view, title="데이터 보기", url_path="data", icon="🗄️"),
                     st.Page(settings, title="가정값", url_path="settings", icon="⚙️")])
nav.run()
