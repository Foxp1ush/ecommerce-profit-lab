-- SKU × 채널 × 월 단위로, 공헌이익 계산에 필요한 값을 모은다.
-- 월 단위로 나누는 이유: 아마존 매출·비용을 그달 환율로 원화 환산하기 위해서.
-- 판매와 광고비를 먼저 따로 집계한 뒤 합친다(바로 JOIN하면 행이 중복돼 합계가 부풀려짐).
WITH sales AS (
    SELECT sku, channel, substr(day, 1, 7) AS month,
           SUM(qty) AS qty, SUM(gross) AS gross, SUM(discount) AS discount, SUM(returned) AS returned
    FROM sales_daily
    WHERE day BETWEEN :start AND :end
    GROUP BY sku, channel, month
),
ads AS (
    SELECT sku, channel, substr(day, 1, 7) AS month, SUM(spend) AS ad_spend
    FROM ad_spend_daily
    WHERE day BETWEEN :start AND :end
    GROUP BY sku, channel, month
)
SELECT s.sku, s.channel, s.month, s.qty, s.gross, s.discount, s.returned,
       COALESCE(a.ad_spend, 0) AS ad_spend,
       k.name, k.category, k.device, k.cost_usd
FROM sales s
LEFT JOIN ads a ON a.sku = s.sku AND a.channel = s.channel AND a.month = s.month
JOIN skus k ON k.sku = s.sku
ORDER BY s.sku, s.channel, s.month;
