-- 과거 기종 출시 후 주차별 판매 (전 색상·전 채널 합계). 초도 발주 모형의 학습 데이터
SELECT l.device, l.name, l.brand, l.launch_date, l.interest,
       w.week, w.category, SUM(w.qty) AS qty
FROM launch_weekly w
JOIN launches l ON l.device = w.device
GROUP BY l.device, w.week, w.category
ORDER BY l.launch_date, w.category, w.week;
