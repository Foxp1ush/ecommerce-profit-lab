# SQL 연습 노트

> 대시보드 **🗄️ 데이터 보기** 화면의 "SQL 직접 실행" 상자에 붙여 넣어 실행하며 복습한다.
> VS Code에서 이 파일을 열고 `Ctrl + Shift + V`를 누르면 보기 좋게 미리보기로 열린다. 정답은 접혀 있으니 먼저 직접 써 볼 것.

---

## 1. 한눈에 보는 문법

| SQL | 하는 일 | 엑셀로 치면 |
|---|---|---|
| `SELECT 칸 AS 이름` | 보여 줄 칸 고르기, 이름표 붙이기 | 열 고르기 |
| `FROM 표 별명` | 어느 표에서 (칸 이름은 그 표가 정함) | 어느 시트에서 |
| `WHERE 조건` | 줄 걸러 내기 | 필터 |
| `WHERE 칸 IN ('a', 'b')` | 목록 중 하나면 남기기 | 필터에서 여러 개 체크 |
| `GROUP BY 칸` | **결과 한 줄의 단위** 정하기 | 피벗 테이블의 '행' |
| `SUM()` `COUNT(*)` `ROUND()` | 묶음마다 합계·개수·반올림 | 피벗의 '값' |
| `CASE WHEN 조건 THEN 값 ELSE 0 END` | 조건부 계산 | IF |
| `JOIN 표 별명 ON 연결 조건` | 다른 표를 옆에 붙이기 | VLOOKUP |
| `HAVING 조건` | 묶은 결과를 다시 걸러 내기 | 피벗 결과에 필터 |
| `ORDER BY 칸 DESC` | 정렬 (DESC = 큰 것부터) | 정렬 |
| `LIMIT 10` | 앞에서 10줄만 | 위에서 10줄 |

**처리 순서** (적는 순서와 다르다):
`FROM → JOIN → WHERE → GROUP BY → HAVING → SELECT → ORDER BY → LIMIT`
- 그래서 SELECT에서 붙인 이름표(`AS 월`)를 ORDER BY에서는 쓸 수 있다.

## 2. 이 프로젝트의 표

| 표 | 한 줄의 의미 | 주요 칸 |
|---|---|---|
| `sales_daily` | 날짜 × 상품 × 채널 판매 | day, sku, channel, qty, gross(정가×수량), discount, returned |
| `ad_spend_daily` | 날짜 × 상품 × 채널 광고비 | day, sku, channel, spend |
| `skus` | 상품 정보 | sku, name, category, cost_usd |
| `fx_rates` | 월별 환율 | month(`2025-10`), currency(`USD`·`JPY`), krw |

- 채널 코드: `coupang` 쿠팡 · `smartstore` 스마트스토어 · `own` 자사몰 · `amazon_us` 아마존 미국 · `amazon_jp` 아마존 일본
- **금액은 채널 통화 그대로**다(국내 원, 아마존 미국 달러, 아마존 일본 엔). 채널끼리 금액을 비교하려면 환율을 곱해야 한다(과제 2).

---

## 3. 과제

### 기본: 쿠팡 월별 광고비 → 아마존 일본으로 바꾸기
- 배운 것: `WHERE channel = '...'` 값만 바꾸면 다른 채널. 글자 값은 **작은따옴표**로 감싼다.
- `SUM(spend)`를 `COUNT(*)`로 바꾸면 "그달 광고 기록이 몇 줄인가"가 나온다 → 묶음마다 계산한다는 감각.

<details><summary>정답</summary>

```sql
SELECT substr(day, 1, 7) AS 월, ROUND(SUM(spend)) AS 광고비
FROM ad_spend_daily
WHERE channel = 'amazon_jp'
GROUP BY 월
ORDER BY 월;
```
</details>

### 과제 1: 세 채널 광고비를 한 줄에 나란히 (가로형 표)
- 목표: 월 | 쿠팡 | 스마트스토어 | 자사몰
- 배운 것: `CASE WHEN`(= 엑셀 IF)으로 채널별 칸 만들기, `IN`, 가로형은 `GROUP BY 월`만
- 정답 확인: 12줄, 첫 줄 2025-10 · 20,815,211 · 6,793,423 · **2,721,683**

<details><summary>정답</summary>

```sql
SELECT substr(day, 1, 7) AS 월,
  ROUND(SUM(CASE WHEN channel = 'coupang' THEN spend ELSE 0 END)) AS 쿠팡,
  ROUND(SUM(CASE WHEN channel = 'smartstore' THEN spend ELSE 0 END)) AS 스마트스토어,
  ROUND(SUM(CASE WHEN channel = 'own' THEN spend ELSE 0 END)) AS 자사몰
FROM ad_spend_daily
WHERE channel IN ('coupang', 'smartstore', 'own')
GROUP BY 월
ORDER BY 월;
```
한 걸음 더: 마지막에 `ROUND(SUM(spend)) AS 합계` 칸을 붙이면 세 칸의 합과 맞는지 검산할 수 있다.
</details>

### 과제 2: 쿠팡 vs 아마존 일본을 원화로 맞춰 비교 (JOIN)
- 목표: 월 | 쿠팡 | 아마존일본_원화
- 배운 것: `JOIN fx_rates f ON 월이 같고 AND 통화가 JPY`, 표 별명(`a`, `f`), 아마존 일본 칸에서 `spend * f.krw`
- 정답 확인: 12줄, 첫 줄 2025-10 · 20,815,211 · **4,464,666**, 마지막 줄 2026-09 · 5,771,831 · **1,535,442**
- `JOIN fx_rates f`의 `f`는 이 쿼리 안에서 붙인 별명. `f.month`, `f.krw`는 fx_rates 표에 원래 있는 칸.

<details><summary>정답</summary>

```sql
SELECT substr(a.day, 1, 7) AS 월,
  ROUND(SUM(CASE WHEN a.channel = 'coupang' THEN a.spend ELSE 0 END)) AS 쿠팡,
  ROUND(SUM(CASE WHEN a.channel = 'amazon_jp' THEN a.spend * f.krw ELSE 0 END)) AS 아마존일본_원화
FROM ad_spend_daily a
JOIN fx_rates f ON f.month = substr(a.day, 1, 7) AND f.currency = 'JPY'
WHERE a.channel IN ('coupang', 'amazon_jp')
GROUP BY 월
ORDER BY 월;
```
</details>

### 과제 3: 채널별 ROAS — 광고비 1원당 매출 (두 표 JOIN, 조건 3개)
**ROAS**(Return On Ad Spend) = 매출 ÷ 광고비. 5면 광고비 1원을 써서 매출 5원을 냈다는 뜻이다. 광고 효율을 볼 때 가장 많이 쓰는 지표.

- 목표: 채널 | 매출 | 광고비 | ROAS — ROAS 높은 순
- 매출 = `gross - discount` (실제 결제된 금액)
- 판매 표(`sales_daily`)와 광고비 표(`ad_spend_daily`)를 **날짜·상품·채널이 모두 같은 줄끼리** 붙여야 한다.
- 정답 확인: 5줄, 맨 위 자사몰(own) ROAS **11.01**, 맨 아래 아마존 미국 **5.11**

<details><summary>힌트 1: 조건 3개짜리 JOIN</summary>

```sql
FROM sales_daily s
JOIN ad_spend_daily a ON a.day = s.day AND a.sku = s.sku AND a.channel = s.channel
```
조건을 하나라도 빼면 한 줄에 여러 줄이 붙어 합계가 부풀려진다.
</details>

<details><summary>힌트 2: 나눗셈</summary>

`SUM(s.gross - s.discount) / SUM(a.spend)` — 합계끼리 나눈다. 줄마다 나눈 뒤 평균을 내면 틀린 값이 된다.
</details>

<details><summary>힌트 3: 통화는?</summary>

채널마다 통화가 달라도 **같은 채널 안에서 매출÷광고비를 나누면 통화가 지워진다**(달러÷달러). 그래서 ROAS는 환율 없이 채널끼리 비교할 수 있다. 매출·광고비 칸 자체는 채널 통화 그대로다.
</details>

<details><summary>정답</summary>

```sql
SELECT s.channel AS 채널,
  ROUND(SUM(s.gross - s.discount)) AS 매출,
  ROUND(SUM(a.spend)) AS 광고비,
  ROUND(SUM(s.gross - s.discount) / SUM(a.spend), 2) AS ROAS
FROM sales_daily s
JOIN ad_spend_daily a ON a.day = s.day AND a.sku = s.sku AND a.channel = s.channel
GROUP BY s.channel
ORDER BY ROAS DESC;
```
</details>

#### 과제 3 보너스: ROAS가 가장 낮은 상품 5개 (표 3개 JOIN + HAVING)
- 목표: 상품 이름 | 채널 | 판매수량 | ROAS — 100개 넘게 팔린 상품×채널 중 ROAS 낮은 순 5개
- 새로 쓸 것: 상품 이름은 `skus` 표에 있다(JOIN 하나 더), 묶은 뒤 거르기는 `HAVING SUM(s.qty) >= 100`
- 정답 확인: 1위 **아이폰 17 프로 케이스 블랙 · coupang · ROAS 1.78**, 2위 **C형 스트랩 블랙 · amazon_us · 2.03**
  - 이 둘은 데이터에 일부러 심어 둔 '광고비 과다로 손해 보는 상품'이다. SKU 진단 화면이 찾은 것을 SQL로도 찾아낸 셈.

<details><summary>정답</summary>

```sql
SELECT k.name AS 상품, s.channel AS 채널, SUM(s.qty) AS 판매수량,
  ROUND(SUM(s.gross - s.discount) / SUM(a.spend), 2) AS ROAS
FROM sales_daily s
JOIN ad_spend_daily a ON a.day = s.day AND a.sku = s.sku AND a.channel = s.channel
JOIN skus k ON k.sku = s.sku
GROUP BY k.name, s.channel
HAVING SUM(s.qty) >= 100
ORDER BY ROAS
LIMIT 5;
```
</details>

### 과제 5: 무슨 요일에 많이 팔리나 (날짜 함수 + CASE)
- 목표: 요일 | 판매수량 — 많이 팔린 요일부터
- 새로 쓸 것: `strftime('%w', day)` → 요일 번호(0 = 일요일, 1 = 월요일 … 6 = 토요일). 엑셀의 `WEEKDAY`.
- 번호를 '월', '화'로 바꾸려면 `CASE 값 WHEN '0' THEN '일' WHEN '1' THEN '월' ... END` (과제 1의 CASE WHEN과 비슷하지만, 같은 값을 여러 번 비교할 때 쓰는 짧은 모양)
- 정답 확인: 7줄, 1위 **금 13,467개**, 꼴찌 **일 11,392개**
- 생각해 볼 것: 주말에 덜 팔린다면 광고·행사를 어느 요일에 하는 게 좋을까?

<details><summary>힌트: GROUP BY는 무엇으로?</summary>

요일 번호로 묶는다. `GROUP BY 요일번호` (SELECT에서 `AS 요일번호`로 이름을 붙였다면)
</details>

<details><summary>정답</summary>

```sql
SELECT strftime('%w', day) AS 요일번호,
  CASE strftime('%w', day) WHEN '0' THEN '일' WHEN '1' THEN '월' WHEN '2' THEN '화' WHEN '3' THEN '수'
       WHEN '4' THEN '목' WHEN '5' THEN '금' ELSE '토' END AS 요일,
  SUM(qty) AS 판매수량
FROM sales_daily
GROUP BY 요일번호
ORDER BY 판매수량 DESC;
```
</details>

### 과제 6: 카테고리별 반품률 (정수 나눗셈 함정)
- 목표: 카테고리 | 판매 | 반품 | 반품률(%) — 반품률 높은 순
- 카테고리는 `skus` 표에 있다 → JOIN
- **함정**: `SUM(s.returned) / SUM(s.qty)`를 그대로 쓰면 반품률이 **전부 0**으로 나온다. 왜 그럴까? (먼저 직접 실행해서 확인해 볼 것)
- 정답 확인: 5줄, 1위 **glass(강화유리) 10.9%**, 꼴찌 **grip 2.9%**

<details><summary>힌트: 왜 0이 나오나</summary>

반품 수량도, 판매 수량도 **정수**(소수점 없는 수)다. SQLite는 정수 ÷ 정수를 **정수로** 계산해서 소수점 아래를 버린다(2277 ÷ 20984 = 0.108… → 0).
나누기 전에 한쪽을 소수로 만들면 된다: `100.0 * SUM(s.returned) / SUM(s.qty)` — `100.0`처럼 점을 찍으면 소수가 된다(퍼센트도 함께 구함).
</details>

<details><summary>정답</summary>

```sql
SELECT k.category AS 카테고리, SUM(s.qty) AS 판매, SUM(s.returned) AS 반품,
  ROUND(100.0 * SUM(s.returned) / SUM(s.qty), 1) AS 반품률_퍼센트
FROM sales_daily s
JOIN skus k ON k.sku = s.sku
GROUP BY k.category
ORDER BY 반품률_퍼센트 DESC;
```
강화유리 반품률이 유독 높은 이유: 데이터에 심어 둔 '갤럭시 S26 울트라 강화유리 불량 로트(반품률 40%)'가 섞여 있어서. 과제 6 보너스: `GROUP BY k.name`으로 바꿔 반품률 높은 강화유리 상품을 찾아보자.
</details>

### 과제 7 (도전): 채널마다 가장 많이 팔린 상품 1개 (WITH + 순위 매기기)
- 목표: 채널 | 상품 | 판매수량 — 채널마다 1등 상품 한 줄씩, 5줄
- 지금까지 배운 것만으로는 "채널 **안에서** 1등"을 고르기 어렵다. 두 가지 새 도구를 쓴다.
  1. `WITH 이름 AS (...)` — 중간 결과에 이름을 붙여 두고 다음 단계에서 표처럼 쓴다(엑셀의 보조 시트). `sku_channel_inputs.sql`에서 본 그것.
  2. `ROW_NUMBER() OVER (PARTITION BY 채널 ORDER BY 판매수량 DESC)` — **채널마다 따로** 1, 2, 3… 순위를 매긴다. 엑셀로 치면 채널별로 나눠 놓고 각각 `RANK`를 매기는 것.
- 단계: ① 채널 × 상품별 판매수량(WITH 상품별) → ② 거기에 채널 안 순위 붙이기(WITH 순위) → ③ 순위 = 1인 줄만
- 정답 확인: 5줄, 1위 **아마존 미국 · C형 스트랩 블랙 · 2,193개**. 스마트스토어·자사몰의 1위는 **링 그립 블랙**
  - C형 스트랩 블랙(아마존 미국)은 과제 3 보너스에서 ROAS가 낮았던 상품 — 가장 많이 팔리지만 광고비가 과한 상품이다.

<details><summary>힌트: 뼈대</summary>

```sql
WITH 상품별 AS (
  SELECT s.channel AS 채널, k.name AS 상품, SUM(s.qty) AS 판매수량
  FROM ...  -- 판매 표 + 상품 표 JOIN
  GROUP BY ...
),
순위 AS (
  SELECT 채널, 상품, 판매수량,
         ROW_NUMBER() OVER (PARTITION BY 채널 ORDER BY 판매수량 DESC) AS 순위
  FROM 상품별
)
SELECT ... FROM 순위 WHERE ...;
```
</details>

<details><summary>정답</summary>

```sql
WITH 상품별 AS (
  SELECT s.channel AS 채널, k.name AS 상품, SUM(s.qty) AS 판매수량
  FROM sales_daily s
  JOIN skus k ON k.sku = s.sku
  GROUP BY s.channel, k.name
),
순위 AS (
  SELECT 채널, 상품, 판매수량,
         ROW_NUMBER() OVER (PARTITION BY 채널 ORDER BY 판매수량 DESC) AS 순위
  FROM 상품별
)
SELECT 채널, 상품, 판매수량
FROM 순위
WHERE 순위 = 1
ORDER BY 판매수량 DESC;
```
`WHERE 순위 <= 3`으로 바꾸면 채널마다 TOP 3.
</details>

---

## 4. 내가 실제로 겪은 실수 모음

| 실수 | 내가 쓴 것 | 증상 | 고친 것 |
|---|---|---|---|
| SELECT 마지막 칸 뒤 쉼표 | `COUNT(*) AS 광고비,` 다음 줄 `FROM` | 'FROM' 근처 문법 오류 | 마지막 쉼표 삭제 |
| 다른 쿼리의 줄이 섞임 | 가로형인데 `GROUP BY 월, 채널` | '채널'이라는 칸이 없음 | `채널`은 다른 쿼리에서 `AS`로 만든 이름표 → `GROUP BY 월` |
| 이름표에 띄어쓰기 | `AS 아마존 일본` | '일본' 근처 문법 오류 | `AS 아마존일본_원화` (또는 `AS "아마존 일본"`) |
| 예시의 별명을 그대로 복사 | `substr(s.day, 1, 7)` (표 별명은 `a`) | 's.day'라는 칸이 없음 | 내 쿼리의 별명으로: `a.day` |
| 붙이기만 하고 안 씀 | JOIN으로 환율을 붙였지만 곱하지 않음 | 오류 없이 엔화 그대로 | `spend * f.krw` |
| 칸 사이 쉼표 빠뜨림 | `a.spend AS 광고비` 다음 줄 `ROUND(...)` | 'ROUND' 근처 문법 오류 | 오류 단어 **바로 앞**에 쉼표 |
| 묶었는데 SUM 없이 칸을 씀 | `GROUP BY s.channel` + `s.gross - s.discount AS 매출` | 오류 없이 **아무 한 줄의 값**(쿠팡 매출 24,900원) | `SUM(s.gross - s.discount)` |
| 비율을 줄마다 나눠서 더함 | `SUM(매출 / 광고비)` | ROAS 11만 같은 엉뚱한 큰 수 | **더한 다음 나누기** `SUM(매출) / SUM(광고비)` |
| 괄호 하나 덜 닫음 | `ROUND( SUM(...), 2) / ROUND(...)` 의 바깥 ROUND | 'AS' 근처 문법 오류 | `(` 개수 = `)` 개수, 괄호 짝부터 쓰고 안을 채우기 |
| `, 2`를 엉뚱한 함수에 줌 | `SUM(x, 2)` | 함수 인자 개수 오류 | `, 2`는 ROUND의 몫: `ROUND(값, 2)` |
| 나누기 전에 각각 반올림 | `ROUND(매출, 2) / ROUND(광고비, 2)` | 결과가 11.005096… (반올림 안 됨) | **결과 전체를** 반올림 `ROUND(매출 / 광고비, 2)` |

**습관으로 만들 것**
1. 칸 이름은 **표 둘러보기**에서 확인한다(지어낸 이름은 오류).
2. `AS`로 만든 이름표는 **그 쿼리 안에서만** 존재한다.
3. 표가 두 개 이상이면 **모든 칸에 별명**(`a.spend`, `f.krw`)을 붙인다.
4. 오류가 가리킨 단어의 **바로 앞**을 먼저 본다.
5. 결과는 정답의 한두 줄과 맞춰 **검산**한다. 합계가 정확히 2배면 JOIN 조건이 빠진 것.
6. **GROUP BY를 쓰면 SELECT의 각 칸은** GROUP BY에 적은 칸이거나 SUM·COUNT 같은 묶음 계산이어야 한다. 아니면 오류 없이 엉뚱한 값이 나온다.
7. 결과가 **말이 되는지** 본다(1년 매출이 2만 원? ROAS 11만?). 오류가 안 나도 틀릴 수 있다.

---

## 5. 처음부터 쓸 때: 처리 순서대로 만들기

SQL은 적는 순서(SELECT → FROM …)와 처리 순서(FROM → WHERE → GROUP BY → SELECT)가 다르다. **처리 순서대로 생각**하고, 처음엔 `SELECT *`로 자리만 잡아 **한 단계씩 실행하며** 확인한다.

**0. 질문을 문장으로 쪼개기** — "판매와 광고비를 / (조건) / 채널별로 묶어서 / 매출·광고비·ROAS를 보여 줘"

**템플릿** (복사해서 위에서부터 채우고, 필요한 줄의 `--`만 지운다. `--`로 시작하는 줄은 실행되지 않는 주석)
```sql
SELECT *          -- ④ 마지막에: 보여 줄 칸 (처음엔 * 로 두기)
FROM 표 별명      -- ① 어떤 표에서
-- JOIN 표 별명 ON ...   -- ② 붙일 표가 있으면
-- WHERE 조건            -- ③ 어떤 줄만
-- GROUP BY 칸           -- ④ 무엇끼리 묶어서
-- ORDER BY 칸           -- ⑤ 정렬
LIMIT 5;          -- 확인용, 마지막에 지우기
```

**과제 3을 이렇게 만들었다**
1. `SELECT * FROM sales_daily s LIMIT 5` → 칸 확인
2. `JOIN ad_spend_daily a ON (3개 조건)` 추가 → 왼쪽·오른쪽 day·sku·channel이 같은지 확인 (`SELECT *`로 붙이면 같은 이름 칸이 두 번 나와 화면에서 `day_2`처럼 보인다)
3. `GROUP BY s.channel` + SELECT에 `SUM(...)` 칸들 → 숫자가 말이 되는지 확인
4. `ORDER BY ROAS DESC`
