-- 채널별 월 판매 요약 (금액은 채널 통화: 국내 원, 아마존 미국 달러, 아마존 일본 엔)
SELECT
    substr(day, 1, 7)  AS month,
    channel,
    SUM(qty)           AS qty,
    SUM(gross)         AS gross,      -- 정가 × 수량
    SUM(discount)      AS discount,
    SUM(returned)      AS returned
FROM sales_daily
WHERE day BETWEEN :start AND :end
GROUP BY month, channel
ORDER BY month, channel;
