"""가상 데이터 생성기. 고정 시드라 몇 번을 돌려도 같은 데이터가 나온다.

    .venv\\Scripts\\python.exe generate.py      # data/lab.db를 새로 만든다

만드는 것
- skus: 기종별 케이스·강화유리(기종 × 모델 × 색상) + 기종 무관 그립·거치대·충전기
- sales_daily: 2025-10-01 ~ 2026-09-30 일별 SKU×채널 판매·할인·반품
- ad_spend_daily: 일별 SKU×채널 광고비
- fx_rates: 월별 달러·엔 환율
- launches / launch_weekly: 과거 기종 출시 6회의 출시 후 20주 판매(초도 발주 모형 학습용)
- planted_cases: 일부러 심어 둔 '많이 팔리지만 손해' 사례 3종(광고비 과다, 반품 과다, 가격 대비 수수료·물류비 과다)

기종 판매 흐름: 출시 후 3주 무렵 정점을 찍고 줄어들며, 긴 꼬리로 몇 년간 조금씩 팔린다.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

import assumptions as A
import db

SEED = 42

# 기종 상품 판매 규모: 케이스 주간 판매(전 채널, 정점 기준). 관심 지수 75인 아이폰 = 900개/주
CASE_PEAK_WEEKLY = 900
BRAND_FACTOR = {"iPhone": 1.0, "Galaxy": 0.75}
GLASS_VS_CASE = 0.8
VARIANT_SHARE = {"iPhone": [0.35, 0.35, 0.30], "Galaxy": [0.40, 0.20, 0.40]}
COLOR_SHARE = {"case": [0.38, 0.30, 0.17, 0.15], "glass": [0.70, 0.30],
               "grip": [0.32, 0.24, 0.18, 0.14, 0.12], "stand": [0.6, 0.4], "charger": [0.6, 0.4]}
GENERIC_DAILY = {"grip": 34, "stand": 9, "charger": 7}  # 종류 하나당 하루 판매(전 색상·채널)
WEEKDAY = [1.05, 1.0, 1.0, 1.0, 1.05, 0.95, 0.9]       # 월~일
MONTH = {11: 1.2, 12: 1.3, 1: 0.95, 2: 0.9}             # 연말 선물 수요 (나머지 1.0)
BASE_AD_RATIO = {"coupang": 0.14, "smartstore": 0.12, "own": 0.10, "amazon_us": 0.16, "amazon_jp": 0.13}

# 일부러 심어 둔 손해 사례. key = (카테고리, 기종, 모델 순번, 색상 순번 또는 종류 순번)
PLANTED = [
    {"find": ("case", "ip17", 1, 0), "channels": ["coupang"], "cause": "ads", "ad_ratio": 0.62, "boost": 1.6,
     "note": "쿠팡 광고비를 매출의 60% 넘게 써서 판매 상위권이지만 적자"},
    {"find": ("grip", None, 0, 0), "channels": ["amazon_us"], "cause": "ads", "ad_ratio": 0.50, "boost": 1.8,
     "note": "아마존 미국 광고 경쟁으로 광고비 과다"},
    {"find": ("glass", "gs26", 2, 0), "channels": ["coupang", "smartstore"], "cause": "returns",
     "return_rate": 0.40, "boost": 2.0, "note": "곡면 화면 기포 불량 로트로 전 채널 반품률 40%"},
    {"find": ("grip", None, 1, 1), "channels": ["amazon_jp"], "cause": "fees", "price_factor": 0.55, "boost": 2.2,
     "note": "가격을 크게 낮춰 많이 팔리지만, 아마존 수수료·배송 대행비가 판매가를 거의 다 먹음"},
]


def lifecycle(weeks: np.ndarray) -> np.ndarray:
    """출시 후 주차(소수 가능) → 정점 대비 판매 비율. 3주에 정점(1.0), 이후 감소 + 긴 꼬리."""
    w = np.clip(weeks, 0, None)
    peak = (w / 3) ** 1.5 * np.exp(1.5 * (1 - w / 3))
    tail = 0.18 * np.exp(-w / 55) * (w >= 1)
    return np.where(weeks < 0, 0.0, peak + tail)


def device_scale(dev: dict, category: str) -> float:
    s = CASE_PEAK_WEEKLY * BRAND_FACTOR[dev["brand"]] * (dev["interest"] / 75) ** 2
    return s * (GLASS_VS_CASE if category == "glass" else 1.0)


def build_skus(rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for dk, dev in A.DEVICES.items():
        for vi, variant in enumerate(dev["variants"]):
            for cat in ("case", "glass"):
                c = A.CATEGORIES[cat]
                for ci, color in enumerate(c["colors"]):
                    rows.append({"sku": f"{cat}-{dk}-{vi}-{ci}", "category": cat, "device": dk, "variant": variant,
                                 "color": color, "name": f"{dev['name']} {variant} {c['name']} {color}",
                                 "cost_usd": round(c["cost_usd"] * (1.1 if vi == 2 else 1.0) * rng.uniform(0.92, 1.08), 2)})
    for cat, types in A.GENERIC_TYPES.items():
        c = A.CATEGORIES[cat]
        for ti, t in enumerate(types):
            for ci, color in enumerate(c["colors"]):
                rows.append({"sku": f"{cat}-{ti}-{ci}", "category": cat, "device": None, "variant": t, "color": color,
                             "name": f"{t} {color}", "cost_usd": round(c["cost_usd"] * rng.uniform(0.92, 1.08), 2)})
    return pd.DataFrame(rows)


def planted_sku(p: dict) -> str:
    cat, dev, i, j = p["find"]
    return f"{cat}-{dev}-{i}-{j}" if dev else f"{cat}-{i}-{j}"


def expected_daily(skus: pd.DataFrame, days: pd.DatetimeIndex) -> np.ndarray:
    """SKU × 날짜의 기대 판매량(전 채널 합계)."""
    out = np.zeros((len(skus), len(days)))
    wd = np.array([WEEKDAY[d.weekday()] for d in days])
    mo = np.array([MONTH.get(d.month, 1.0) for d in days])
    for i, s in enumerate(skus.itertuples()):
        cat = A.CATEGORIES[s.category]
        color_share = COLOR_SHARE[s.category][cat["colors"].index(s.color)]
        if s.device:
            dev = A.DEVICES[s.device]
            weeks = np.array([(d.date() - dev["launch"]).days / 7 for d in days])
            vshare = VARIANT_SHARE[dev["brand"]][dev["variants"].index(s.variant)]
            out[i] = device_scale(dev, s.category) / 7 * lifecycle(weeks) * vshare * color_share * wd
        else:
            out[i] = GENERIC_DAILY[s.category] * color_share * wd * mo
    return out


def build_fx(rng: np.random.Generator, months: list[str]) -> pd.DataFrame:
    usd, jpy, rows = 1_385.0, 9.35, []
    for m in months:
        rows += [{"month": m, "currency": "USD", "krw": round(usd, 1)}, {"month": m, "currency": "JPY", "krw": round(jpy, 3)}]
        usd += rng.normal(0, 14)
        jpy += rng.normal(0, 0.09)
    return pd.DataFrame(rows)


def promo_rate(channel: str, d: date, rng: np.random.Generator) -> float:
    """그날 채널 할인율. 쿠팡·스마트스토어는 무작위 행사일, 자사몰은 매달 1~3일, 아마존은 프라임데이·블랙프라이데이."""
    if channel in ("amazon_us", "amazon_jp"):
        if d.month == 7 and 8 <= d.day <= 11:
            return 0.20
        if channel == "amazon_us" and d.month == 11 and 24 <= d.day <= 30:
            return 0.20
        return 0.0
    if channel == "own":
        return 0.15 if d.day <= 3 else 0.0
    p = {"coupang": 0.15, "smartstore": 0.10}[channel]
    return float(rng.choice([0.10, 0.15])) if rng.random() < p else 0.0


def build_sales(skus: pd.DataFrame, rng: np.random.Generator) -> tuple[pd.DataFrame, pd.DataFrame]:
    days = pd.date_range(A.SALES_START, A.SALES_END, freq="D")
    base = expected_daily(skus, days)
    planted = {(planted_sku(p), ch): p for p in PLANTED for ch in p["channels"]}
    # 불량 로트는 어느 채널에서 팔든 반품률이 높다 (손해 사례로 기록하는 건 판매가 많은 채널만)
    defect = {planted_sku(p): p["return_rate"] for p in PLANTED if p["cause"] == "returns"}
    sales, ads = [], []
    for ck, ch in A.CHANNELS.items():
        cur = ch["currency"]
        jitter = rng.lognormal(0, 0.25, len(skus))  # SKU마다 채널 선호가 조금씩 다름
        promo = np.array([promo_rate(ck, d.date(), rng) for d in days])
        lam = base * ch["share"] * jitter[:, None] * (1 + 2 * promo)[None, :]  # 할인하는 날 더 팔림
        for i, s in enumerate(skus.itertuples()):
            p = planted.get((s.sku, ck), {})
            mean = lam[i] * p.get("boost", 1.0)
            qty = rng.poisson(mean)
            price = A.CATEGORIES[s.category]["price"][cur] * p.get("price_factor", 1.0)
            rr = defect.get(s.sku, A.CATEGORIES[s.category]["return_rate"])
            ad_ratio = p.get("ad_ratio", BASE_AD_RATIO[ck] * rng.lognormal(0, 0.3))
            for t in np.nonzero(qty)[0]:
                q = int(qty[t])
                gross = price * q
                disc = gross * promo[t]
                net_of_tax = (gross - disc) / (1 + A.TAX_RATE) if ch["tax_in_price"] else gross - disc
                day = days[t].date().isoformat()
                sales.append((day, s.sku, ck, q, round(gross, 2), round(disc, 2), int(rng.binomial(q, rr))))
                ads.append((day, s.sku, ck, round(net_of_tax * ad_ratio * rng.uniform(0.7, 1.3), 2)))
    return (pd.DataFrame(sales, columns=["day", "sku", "channel", "qty", "gross", "discount", "returned"]),
            pd.DataFrame(ads, columns=["day", "sku", "channel", "spend"]))


def build_launches(rng: np.random.Generator) -> tuple[pd.DataFrame, pd.DataFrame]:
    """과거 출시 6회의 출시 후 20주 판매. 출시마다 예측 못 한 변동(±15% 안팎)을 넣어 모형이 완벽하지 않게 한다."""
    launches, weekly = [], []
    weeks = np.arange(1, A.LAUNCH_WEEKS + 1)
    for dk, dev in A.DEVICES.items():
        launches.append({"device": dk, "name": dev["name"], "brand": dev["brand"],
                         "launch_date": dev["launch"].isoformat(), "interest": dev["interest"]})
        shock = rng.lognormal(0, 0.15)
        for cat in ("case", "glass"):
            colors = A.CATEGORIES[cat]["colors"]
            mean = device_scale(dev, cat) * lifecycle(weeks.astype(float)) * shock
            for ci, color in enumerate(colors):
                qty = rng.poisson(mean * COLOR_SHARE[cat][ci] * rng.lognormal(0, 0.08, len(weeks)))
                weekly += [{"device": dk, "week": int(w), "category": cat, "color": color, "qty": int(q)}
                           for w, q in zip(weeks, qty)]
    return pd.DataFrame(launches), pd.DataFrame(weekly)


def build(seed: int = SEED) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    skus = build_skus(rng)
    months = pd.period_range(A.SALES_START, A.SALES_END, freq="M").strftime("%Y-%m").tolist()
    sales, ads = build_sales(skus, rng)
    launches, weekly = build_launches(rng)
    planted = pd.DataFrame([{"sku": planted_sku(p), "channel": ch, "cause": p["cause"], "note": p["note"]}
                            for p in PLANTED for ch in p["channels"]])
    return {"skus": skus, "fx_rates": build_fx(rng, months), "sales_daily": sales, "ad_spend_daily": ads,
            "launches": launches, "launch_weekly": weekly, "planted_cases": planted}


def write(tables: dict[str, pd.DataFrame], path: Path = db.DB_PATH) -> None:
    if path.exists():
        path.unlink()
    db.init(path)
    with db.connect(path) as c:
        for name, df in tables.items():
            df.to_sql(name, c, if_exists="append", index=False)


if __name__ == "__main__":
    t = build()
    write(t)
    print(f"{db.DB_PATH} — " + ", ".join(f"{k} {len(v):,}행" for k, v in t.items()))
