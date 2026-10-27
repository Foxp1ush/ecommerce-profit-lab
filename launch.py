"""신기종 초도 발주 시뮬레이터.

1) 수요 예측 — 과거 출시마다 '출시 후 H주 동안 판매량'(케이스 + 강화유리)을 구해
       log(판매량) = a + b·log(관심 지수) + c·[아이폰]
   로 회귀한다. 한 출시의 케이스와 강화유리는 함께 오르내리므로(같은 출시의 흥행이 둘 다에 영향),
   카테고리별로 따로 세지 않고 출시 단위 6개로 맞춘 뒤 과거 비중으로 나눈다.
   데이터가 적으므로 예측 범위는 t 분포로 넓게 잡는다(자유도 = 출시 수 − 계수 수).
   주차별 모양은 과거 출시들의 평균 판매 곡선을 쓴다.

2) 초도 물량 — 신문팔이(newsvendor) 모형
   초도 물량은 '재주문한 물건이 도착하기 전(리드타임 H주)'까지의 수요를 버텨야 한다.
   - 모자라면: 못 판 1개마다 개당 공헌이익을 잃는다 (품절 손실 Cu)
   - 남으면: 남은 1개마다 결국 손실로 처리되는 몫만큼 잃는다 (과다재고 손실 Co = 수입 원가 × 손실률)
   기대 이익이 가장 큰 물량 = 수요 분포의 Cu / (Cu + Co) 분위수.

3) 검증 — 출시 1회씩 빼고 나머지로 예측해 실제와 비교(leave-one-out 백테스트).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import assumptions as A
import db

FEATURES = ["const", "log_interest", "iphone"]
CATS = ("case", "glass")
T_DRAWS = 200_000  # t 분포 분위수를 표본으로 구할 때 쓰는 개수 (고정 시드라 결과가 같다)


def history(path=db.DB_PATH) -> pd.DataFrame:
    """출시 × 카테고리 × 주차 판매량 (전 색상 합계)."""
    return db.query("launch_weekly", path=path)


def horizon_totals(hist: pd.DataFrame, weeks: int) -> pd.DataFrame:
    """출시별 '출시 후 1~weeks주' 판매 합계(케이스·강화유리 따로, 그리고 합계)와 설명 변수."""
    h = hist[hist["week"] <= weeks]
    t = h.pivot_table(index=["device", "name", "brand", "launch_date", "interest"], columns="category",
                      values="qty", aggfunc="sum").reset_index()
    t["qty"] = t[list(CATS)].sum(axis=1)
    return t.assign(const=1.0, log_interest=np.log(t["interest"]), iphone=(t["brand"] == "iPhone").astype(float))


def category_share(totals: pd.DataFrame) -> dict[str, float]:
    """출시 초기 판매에서 카테고리가 차지하는 평균 비중."""
    s = {c: float((totals[c] / totals["qty"]).mean()) for c in CATS}
    return {c: v / sum(s.values()) for c, v in s.items()}


def fit(totals: pd.DataFrame) -> dict:
    """출시 단위 log(판매량) 최소제곱 회귀. 예측 구간 계산용 공분산과 자유도까지 돌려준다."""
    X = totals[FEATURES].to_numpy()
    y = np.log(totals["qty"].to_numpy())
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    dof = max(len(y) - len(beta), 1)
    return {"beta": beta, "sigma2": float(resid @ resid / dof), "xtx_inv": np.linalg.pinv(X.T @ X), "dof": dof,
            "share": category_share(totals)}


def features(interest: float, brand: str) -> np.ndarray:
    return np.array([1.0, np.log(interest), 1.0 if brand == "iPhone" else 0.0])


def predict(model: dict, interest: float, brand: str) -> tuple[float, float, int]:
    """새 기종 H주 총수요(케이스+강화유리)의 로그 평균·척도·자유도 (계수 불확실성 포함)."""
    x = features(interest, brand)
    sd = float(np.sqrt(model["sigma2"] * (1 + x @ model["xtx_inv"] @ x)))
    return float(x @ model["beta"]), sd, model["dof"]


def samples(mu: float, sd: float, dof: int, n: int = T_DRAWS, seed: int = 0) -> np.ndarray:
    """총수요 표본: exp(mu + sd × t(dof))."""
    return np.exp(mu + sd * np.random.default_rng(seed).standard_t(dof, n))


def quantiles(draws: np.ndarray, ps=(0.1, 0.5, 0.9)) -> list[float]:
    return [float(v) for v in np.quantile(draws, ps)]


def shape(hist: pd.DataFrame, category: str) -> pd.Series:
    """과거 출시들의 평균 판매 곡선: 주차 → 20주 합계 대비 비율."""
    h = hist[hist["category"] == category]
    share = h["qty"] / h.groupby("device")["qty"].transform("sum")
    return share.groupby(h["week"]).mean() / share.groupby(h["week"]).mean().sum()


def variant_split(brand: str, path=db.DB_PATH) -> pd.Series:
    """같은 브랜드 가장 최근 기종의 모델별(기본·프로·울트라 등) 판매 비중 — 새 기종 물량을 나눌 때 쓴다."""
    launches = db.table("launches", path)
    latest = launches[launches.brand == brand].sort_values("launch_date")["device"].iloc[-1]
    with db.connect(path) as c:
        v = pd.read_sql_query("SELECT k.variant, SUM(s.qty) AS qty FROM sales_daily s JOIN skus k ON k.sku = s.sku "
                              "WHERE k.device = ? GROUP BY k.variant", c, params=(latest,))
    order = A.DEVICES[latest]["variants"]
    return v.set_index("variant")["qty"].reindex(order).fillna(0) / v["qty"].sum()


def color_split(path=db.DB_PATH) -> dict[str, pd.Series]:
    """카테고리별 과거 출시 색상 비중."""
    w = db.table("launch_weekly", path)
    return {c: (g := w[w.category == c].groupby("color")["qty"].sum().reindex(A.CATEGORIES[c]["colors"])) / g.sum()
            for c in CATS}


# ---- 신문팔이 모형 ------------------------------------------------------------

def best_quantity(demand: np.ndarray, cu: float, co: float) -> float:
    """기대 이익이 가장 큰 물량 = 수요 분포의 Cu/(Cu+Co) 분위수."""
    return float(np.quantile(demand, cu / (cu + co)))


def profit_curve(demand: np.ndarray, cu: float, co: float, qmax: float, points: int = 120,
                 qmin: float = 0.0) -> pd.DataFrame:
    """주문 물량별 기대 이익(원)과 품절 확률. 이익 = 판 개수 × Cu − 남은 개수 × Co."""
    qs = np.linspace(qmin, qmax, points)
    sold = np.minimum(demand[None, :], qs[:, None])
    left = np.maximum(qs[:, None] - demand[None, :], 0)
    return pd.DataFrame({"qty": qs, "expected_profit": (sold * cu - left * co).mean(axis=1),
                         "stockout": (demand[None, :] > qs[:, None]).mean(axis=1)})


def outcome(q: float, demand: float, cu: float, co: float) -> float:
    """실제 수요가 demand일 때 q개를 주문했던 결과 이익."""
    return min(q, demand) * cu - max(q - demand, 0) * co


def unit_economics(profit_df: pd.DataFrame) -> dict[str, dict[str, float]]:
    """카테고리별 개당 공헌이익(품절 시 잃는 것)과 개당 수입 원가(남으면 묶이는 것), 원화."""
    out = {}
    for c in CATS:
        d = profit_df[profit_df["category"] == c]
        landed = (d["cogs"].sum() / (d["qty"] - d["returned"] * A.RETURN_RESELLABLE).sum())
        out[c] = {"margin": d["profit"].sum() / d["qty"].sum(), "landed": landed}
    return out


# ---- 검증 -------------------------------------------------------------------

def forecast(model: dict, interest: float, brand: str, seed: int = 0) -> dict[str, np.ndarray]:
    """카테고리별 H주 수요 표본 (총수요 표본 × 과거 카테고리 비중)."""
    total = samples(*predict(model, interest, brand), seed=seed)
    return {c: total * model["share"][c] for c in CATS}


def backtest(hist: pd.DataFrame, weeks: int, cu: dict, co: dict) -> pd.DataFrame:
    """출시 1회씩 빼고 나머지 5회로 예측해 실제와 비교한다.

    비교 기준(naive) = 같은 브랜드의 직전 출시 실적만큼 주문(없으면 나머지 출시 평균).
    profit = 그 물량으로 실제 수요를 맞았을 때 이익, best_profit = 수요를 정확히 알았다면 얻었을 이익.
    """
    totals = horizon_totals(hist, weeks)
    rows = []
    for r in totals.itertuples():
        others = totals[totals.device != r.device]
        demand = forecast(fit(others), r.interest, r.brand)
        prev = others[(others.brand == r.brand) & (others.launch_date < r.launch_date)].sort_values("launch_date")
        for c in CATS:
            actual = getattr(r, c)
            lo, med, hi = quantiles(demand[c])
            q = best_quantity(demand[c], cu[c], co[c])
            naive = prev[c].iloc[-1] if len(prev) else others[c].mean()
            rows.append({"device": r.device, "name": r.name, "category": c, "actual": actual,
                         "pred": med, "lo": lo, "hi": hi, "error": med / actual - 1, "covered": lo <= actual <= hi,
                         "order": q, "naive_order": naive,
                         "profit": outcome(q, actual, cu[c], co[c]),
                         "naive_profit": outcome(naive, actual, cu[c], co[c]),
                         "best_profit": outcome(actual, actual, cu[c], co[c])})
    return pd.DataFrame(rows)


def backtest_summary(bt: pd.DataFrame) -> dict[str, float]:
    """평균 오차, 80% 범위 적중률, 완벽한 예측 대비 놓친 이익(모형 vs 직전 출시 따라 하기)."""
    model_gap = (bt["best_profit"] - bt["profit"]).sum()
    naive_gap = (bt["best_profit"] - bt["naive_profit"]).sum()
    return {"mape": float(bt["error"].abs().mean()), "coverage": float(bt["covered"].mean()),
            "model_gap": float(model_gap), "naive_gap": float(naive_gap),
            "gap_cut": float(1 - model_gap / naive_gap) if naive_gap else 0.0}
