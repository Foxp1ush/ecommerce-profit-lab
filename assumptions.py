"""가정값 모음. 모든 숫자는 **가상 브랜드 '그립앤코'의 가정값**이며 실제 회사·플랫폼 요율이 아니다.

화면(2단계)에서 이 기본값을 바꾸면 이익이 즉시 다시 계산된다.

세금 처리 원칙: 이익은 **공급가액(부가세·소비세 제외)** 기준으로 계산한다.
- 국내 3개 채널과 아마존 일본은 판매가에 세금이 포함돼 있어 1.1로 나눠 공급가액을 구한다.
- 아마존 미국 판매가는 판매세가 붙기 전 금액이라 그대로 쓴다.
- 판매수수료는 플랫폼이 고객 결제금액(세금 포함)에 매긴다고 가정한다.
"""

from __future__ import annotations

from datetime import date

BRAND = "그립앤코"  # 가상 브랜드

# ---- 판매 채널 (가정값) ----------------------------------------------------
# payment: 결제수수료율(모든 상품 공통), return_cost: 반품 1개 처리비(왕복 배송·검수, 채널 통화)
# tax_in_price: 판매가에 세금이 포함됐는지, share: 기본 판매 비중
# 판매수수료율은 아래 COMMISSION(채널 × 카테고리), 물류비는 FULFIL(채널 × 크기 등급)
CHANNELS = {
    "coupang":    {"name": "쿠팡",         "currency": "KRW", "payment": 0.0,   "return_cost": 6_000,
                   "tax_in_price": True,  "share": 0.36},
    "smartstore": {"name": "스마트스토어", "currency": "KRW", "payment": 0.0,   "return_cost": 6_000,
                   "tax_in_price": True,  "share": 0.22},
    "own":        {"name": "자사몰",       "currency": "KRW", "payment": 0.033, "return_cost": 6_000,
                   "tax_in_price": True,  "share": 0.10},
    "amazon_us":  {"name": "아마존 미국",  "currency": "USD", "payment": 0.0,   "return_cost": 3.5,
                   "tax_in_price": False, "share": 0.20},
    "amazon_jp":  {"name": "아마존 일본",  "currency": "JPY", "payment": 0.0,   "return_cost": 500,
                   "tax_in_price": True,  "share": 0.12},
}
TAX_RATE = 0.10  # 국내 부가세·일본 소비세 (가정값)

# 판매수수료율: 채널 × 카테고리 (결제금액 기준, 가정값)
# - 쿠팡·아마존은 카테고리별 수수료 표가 있는 구조라 카테고리마다 다르게 둔다(전자기기인 충전기를 낮게).
# - 스마트스토어는 카테고리보다 결제수단·유입경로에 따라 달라지는 구조라 같은 값으로 둔다.
# - 자사몰은 판매수수료가 없고 결제(PG) 수수료만 있다(CHANNELS의 payment).
COMMISSION = {
    "coupang":    {"case": 0.108, "glass": 0.108, "grip": 0.108, "stand": 0.108, "charger": 0.078},
    "smartstore": {"case": 0.055, "glass": 0.055, "grip": 0.055, "stand": 0.055, "charger": 0.055},
    "own":        {"case": 0.0,   "glass": 0.0,   "grip": 0.0,   "stand": 0.0,   "charger": 0.0},
    "amazon_us":  {"case": 0.15,  "glass": 0.15,  "grip": 0.15,  "stand": 0.15,  "charger": 0.08},
    "amazon_jp":  {"case": 0.10,  "glass": 0.10,  "grip": 0.10,  "stand": 0.10,  "charger": 0.08},
}

# 크기 등급: 물류비는 상품 크기·무게에 따라 달라진다 (가정값)
SIZES = {"small": "소형", "medium": "중형", "large": "대형"}
SIZE_OF = {"glass": "small", "grip": "small", "case": "medium", "charger": "medium", "stand": "large"}
# 개당 물류·배송비: 채널 × 크기 등급 (채널 통화, 아마존은 배송 대행비, 가정값)
FULFIL = {
    "coupang":    {"small": 2_100, "medium": 2_600, "large": 3_400},
    "smartstore": {"small": 2_100, "medium": 2_400, "large": 3_200},
    "own":        {"small": 2_500, "medium": 2_800, "large": 3_600},
    "amazon_us":  {"small": 3.06,  "medium": 3.60,  "large": 4.80},
    "amazon_jp":  {"small": 360,   "medium": 420,   "large": 560},
}

# ---- 상품 카테고리 (가정값) -------------------------------------------------
# price: 채널 통화별 판매가(세금 포함 여부는 채널 설정을 따름), cost_usd: 개당 매입원가(중국 생산, 달러)
# return_rate: 기본 반품률, by_device: 기종별 상품인지, colors: 색상
CATEGORIES = {
    "case":  {"name": "케이스",      "price": {"KRW": 24_900, "USD": 16.99, "JPY": 2_480}, "cost_usd": 2.10,
              "return_rate": 0.05, "by_device": True,  "colors": ["블랙", "클리어", "샌드", "블루"]},
    "glass": {"name": "강화유리",    "price": {"KRW": 14_900, "USD": 11.99, "JPY": 1_680}, "cost_usd": 0.90,
              "return_rate": 0.08, "by_device": True,  "colors": ["기본", "프라이버시"]},
    "grip":  {"name": "그립·스트랩", "price": {"KRW": 15_900, "USD": 12.99, "JPY": 1_780}, "cost_usd": 1.20,
              "return_rate": 0.03, "by_device": False, "colors": ["블랙", "화이트", "핑크", "그레이", "민트"]},
    "stand": {"name": "거치대",      "price": {"KRW": 29_900, "USD": 22.99, "JPY": 3_280}, "cost_usd": 3.80,
              "return_rate": 0.04, "by_device": False, "colors": ["블랙", "실버"]},
    "charger": {"name": "충전기",    "price": {"KRW": 39_900, "USD": 29.99, "JPY": 4_280}, "cost_usd": 7.50,
                "return_rate": 0.06, "by_device": False, "colors": ["화이트", "블랙"]},
}
# 기종 무관 상품의 종류 (카테고리 → 종류 이름 목록)
GENERIC_TYPES = {"grip": ["C형 스트랩", "링 그립"], "stand": ["접이식", "자석형"], "charger": ["무선 패드", "충전 스탠드"]}

# ---- 수입·발주 (가정값) ----------------------------------------------------
IMPORT_OVERHEAD = 0.12      # 관세·해상운송·통관: 매입원가(원화 환산)의 12%
LEAD_TIME_WEEKS = {"production": 3, "sea": 4}  # 생산 3주 + 해상 운송 4주
RETURN_RESELLABLE = 0.3     # 반품 중 다시 팔 수 있는 비율. 나머지는 매입원가 손실

# ---- 기종 (가상 데이터: 이름만 빌림, 출시일은 근사값) ----------------------------
# interest: 출시 전 관심 지수(가상, 0~100), variants: 같은 기종의 모델 구분
DEVICES = {
    "ip15":  {"name": "아이폰 15",  "brand": "iPhone", "launch": date(2023, 9, 22), "interest": 74,
              "variants": ["기본", "프로", "프로 맥스"]},
    "gs24":  {"name": "갤럭시 S24", "brand": "Galaxy", "launch": date(2024, 1, 31), "interest": 61,
              "variants": ["기본", "플러스", "울트라"]},
    "ip16":  {"name": "아이폰 16",  "brand": "iPhone", "launch": date(2024, 9, 20), "interest": 79,
              "variants": ["기본", "프로", "프로 맥스"]},
    "gs25":  {"name": "갤럭시 S25", "brand": "Galaxy", "launch": date(2025, 2, 7), "interest": 66,
              "variants": ["기본", "플러스", "울트라"]},
    "ip17":  {"name": "아이폰 17",  "brand": "iPhone", "launch": date(2025, 9, 19), "interest": 86,
              "variants": ["기본", "프로", "프로 맥스"]},
    "gs26":  {"name": "갤럭시 S26", "brand": "Galaxy", "launch": date(2026, 2, 27), "interest": 70,
              "variants": ["기본", "플러스", "울트라"]},
}

# ---- 데이터 기간 ------------------------------------------------------------
SALES_START = date(2025, 10, 1)
SALES_END = date(2026, 9, 30)
LAUNCH_WEEKS = 20  # 출시 후 몇 주까지 판매 기록을 남길지 (초도 발주 모형 학습용)
