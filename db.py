"""SQLite 저장소. 원본(가상) 데이터를 담고, 집계는 sql/ 폴더의 SQL 파일로 한다."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "lab.db"
SQL_DIR = ROOT / "sql"

SCHEMA = """
CREATE TABLE IF NOT EXISTS skus (
    sku TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,          -- assumptions.CATEGORIES 키
    device TEXT,                     -- assumptions.DEVICES 키. 기종 무관 상품은 NULL
    variant TEXT NOT NULL DEFAULT '',
    color TEXT NOT NULL,
    cost_usd REAL NOT NULL           -- 개당 매입원가(달러)
);
CREATE TABLE IF NOT EXISTS fx_rates (
    month TEXT NOT NULL,             -- YYYY-MM
    currency TEXT NOT NULL,          -- USD | JPY
    krw REAL NOT NULL,               -- 1 단위당 원화
    PRIMARY KEY (month, currency)
);
-- 일별 SKU×채널 판매. 금액은 채널 통화, 세금 포함 여부는 채널 설정을 따른다
CREATE TABLE IF NOT EXISTS sales_daily (
    day TEXT NOT NULL,
    sku TEXT NOT NULL REFERENCES skus(sku),
    channel TEXT NOT NULL,
    qty INTEGER NOT NULL,
    gross REAL NOT NULL,             -- 정가 × 수량
    discount REAL NOT NULL,          -- 할인액
    returned INTEGER NOT NULL,       -- 반품 수량
    PRIMARY KEY (day, sku, channel)
);
CREATE TABLE IF NOT EXISTS ad_spend_daily (
    day TEXT NOT NULL,
    sku TEXT NOT NULL REFERENCES skus(sku),
    channel TEXT NOT NULL,
    spend REAL NOT NULL,             -- 채널 통화, 세금 제외
    PRIMARY KEY (day, sku, channel)
);
-- 과거 기종 출시 기록 (초도 발주 모형 학습용)
CREATE TABLE IF NOT EXISTS launches (
    device TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    brand TEXT NOT NULL,
    launch_date TEXT NOT NULL,
    interest INTEGER NOT NULL        -- 출시 전 관심 지수(가상)
);
CREATE TABLE IF NOT EXISTS launch_weekly (
    device TEXT NOT NULL REFERENCES launches(device),
    week INTEGER NOT NULL,           -- 출시 후 몇 주째 (1부터)
    category TEXT NOT NULL,
    color TEXT NOT NULL,
    qty INTEGER NOT NULL,            -- 전 채널 합계
    PRIMARY KEY (device, week, category, color)
);
-- 데이터에 일부러 심어 둔 '많이 팔리지만 손해' 사례. 화면은 쓰지 않고, 검증·README용
CREATE TABLE IF NOT EXISTS planted_cases (
    sku TEXT NOT NULL,
    channel TEXT NOT NULL,
    cause TEXT NOT NULL,             -- ads | returns | fees
    note TEXT NOT NULL
);
"""


@contextmanager
def connect(path: Path = DB_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init(path: Path = DB_PATH) -> None:
    with connect(path) as c:
        c.executescript(SCHEMA)


def sql_text(name: str) -> str:
    """sql/<name>.sql 내용 (화면에 쿼리를 그대로 보여 줄 때도 쓴다)."""
    return (SQL_DIR / f"{name}.sql").read_text(encoding="utf-8")


def query(name: str, params: dict | None = None, path: Path = DB_PATH) -> pd.DataFrame:
    """sql/<name>.sql을 실행해 표로 돌려준다. 쿼리 안의 :이름 자리에 params가 들어간다."""
    with connect(path) as c:
        return pd.read_sql_query(sql_text(name), c, params=params or {})


def table(name: str, path: Path = DB_PATH) -> pd.DataFrame:
    with connect(path) as c:
        return pd.read_sql_query(f"SELECT * FROM {name}", c)


# ---- 화면에서 SQL 직접 실행 (읽기 전용) ---------------------------------------------

# 표 설명 (데이터 보기 화면용)
TABLE_DOCS = {
    "skus": ("상품 목록", {"sku": "상품 코드", "name": "상품 이름", "category": "카테고리 코드(case·glass·grip·stand·charger)",
                          "device": "기종 코드(기종 무관 상품은 빈칸)", "variant": "모델 또는 종류", "color": "색상",
                          "cost_usd": "개당 매입원가(달러)"}),
    "sales_daily": ("일별 판매 (상품 × 채널)", {"day": "날짜", "sku": "상품 코드", "channel": "채널 코드",
                                             "qty": "판매 수량", "gross": "정가 × 수량 (채널 통화)",
                                             "discount": "할인액 (채널 통화)", "returned": "반품 수량"}),
    "ad_spend_daily": ("일별 광고비 (상품 × 채널)", {"day": "날짜", "sku": "상품 코드", "channel": "채널 코드",
                                                 "spend": "광고비 (채널 통화, 세금 제외)"}),
    "fx_rates": ("월별 환율", {"month": "월(YYYY-MM)", "currency": "통화(USD·JPY)", "krw": "1단위당 원화"}),
    "launches": ("과거 기종 출시", {"device": "기종 코드", "name": "기종 이름", "brand": "브랜드",
                                  "launch_date": "출시일(근사)", "interest": "출시 전 관심 지수(가상)"}),
    "launch_weekly": ("출시 후 주차별 판매", {"device": "기종 코드", "week": "출시 후 몇 주째", "category": "카테고리 코드",
                                          "color": "색상", "qty": "판매 수량(전 채널)"}),
    "planted_cases": ("일부러 심어 둔 손해 사례 (정답지)", {"sku": "상품 코드", "channel": "채널 코드",
                                                    "cause": "원인(ads·returns·fees)", "note": "설명"}),
}


class SqlError(Exception):
    """사용자가 입력한 SQL을 실행할 수 없을 때. 메시지를 그대로 화면에 보여 준다."""


def _korean(msg: str) -> str:
    """자주 나오는 SQLite 오류를 알아보기 쉬운 말로 (원문도 함께)."""
    import re
    rules = [(r"no such table: (\S+)", "'{}'라는 표가 없습니다. 위의 표 목록에서 이름을 확인해 주세요."),
             (r"no such column: (\S+)", "'{}'라는 칸이 없습니다. 표 설명에서 칸 이름을 확인해 주세요."),
             (r'near "(.*?)": syntax error', "문법 오류: '{}' 근처를 확인해 주세요."),
             (r"only execute one statement", "한 번에 SQL 한 문장만 실행할 수 있습니다. 세미콜론(;) 뒤를 지워 주세요."),
             (r"ambiguous column name: (\S+)", "'{}' 칸이 여러 표에 있습니다. 표 이름을 붙여 주세요(예: s.sku)."),
             (r"Incorrect number of bindings|You did not supply a value for binding", "':이름' 자리에 넣을 값이 없습니다.")]
    for pattern, text in rules:
        if m := re.search(pattern, msg):
            return text.format(*m.groups()) + f"  (원문: {msg})"
    return f"SQL 오류: {msg}"


def _read_only(action, *_):
    """조회에 필요한 동작만 허용한다(쓰기·삭제·다른 파일 연결 등은 거부)."""
    allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}
    return sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY


def run_readonly(sql: str, params: dict | None = None, path: Path = DB_PATH, max_rows: int = 1_000,
                 timeout: float = 5.0) -> tuple[pd.DataFrame, bool]:
    """조회(SELECT) 한 문장만 실행한다. (결과 표, 잘렸는지) — 최대 max_rows행, timeout초를 넘기면 멈춘다.

    세 겹으로 막는다: 읽기 전용으로 연 연결, 조회 동작만 허락하는 검사기, 시간 제한.
    """
    import time
    if not sql.strip():
        raise SqlError("SQL을 입력해 주세요.")
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        conn.set_authorizer(_read_only)
        deadline = time.monotonic() + timeout
        conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 10_000)
        try:
            cur = conn.execute(sql, params or {})
            rows = cur.fetchmany(max_rows + 1)
        except sqlite3.DatabaseError as e:
            msg = str(e)
            if "not authorized" in msg or "readonly" in msg:
                raise SqlError("조회(SELECT)만 할 수 있습니다. 데이터를 바꾸거나 지우는 SQL은 실행되지 않습니다.") from e
            if "interrupted" in msg:
                raise SqlError(f"{timeout:.0f}초가 넘게 걸려 멈췄습니다. 조건(WHERE)을 더 좁혀 주세요.") from e
            raise SqlError(_korean(msg)) from e
        except sqlite3.ProgrammingError as e:
            raise SqlError(_korean(str(e))) from e
        if cur.description is None:
            raise SqlError("조회(SELECT) 결과가 없는 SQL입니다.")
        # 두 표를 SELECT * 로 붙이면 같은 이름의 칸(day, sku 등)이 두 번 나온다.
        # 화면의 표는 같은 이름을 두 번 못 쓰므로 두 번째부터 _2, _3을 붙인다.
        cols, seen = [], {}
        for name in (d[0] for d in cur.description):
            seen[name] = seen.get(name, 0) + 1
            cols.append(name if seen[name] == 1 else f"{name}_{seen[name]}")
        return pd.DataFrame(rows[:max_rows], columns=cols), len(rows) > max_rows
    finally:
        conn.close()
