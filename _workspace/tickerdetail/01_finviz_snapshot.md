# finviz 스냅샷 표 — 실페이지 추출 (NFLX, 2026-08-21)

12열(라벨·값 6쌍) × 14행 = 84칸. 아래는 **열 단위**(finviz DOM 순서) 라벨과 NFLX 예시값.
각 행은 6개 열의 같은 인덱스를 가로로 놓는다 (예: 1행 = Index · P/E · EPS (ttm) · Insider Own · Shs Outstand · Perf Week).

| # | 열1 | 열2 | 열3 | 열4 | 열5 | 열6 |
|---|---|---|---|---|---|---|
| 1 | Index `NDX, S&P 500` | P/E `25.25` | EPS (ttm) `3.17` | Insider Own `0.72%` | Shs Outstand `4.16B` | Perf Week `2.43%` |
| 2 | Market Cap `333.70B` | Forward P/E `21.00` | EPS next Y `3.82` | Insider Trans `-6.32%` | Shs Float `4.13B` | Perf Month `16.94%` |
| 3 | Enterprise Value `341.21B` | PEG `0.96` | EPS next Q `0.82` | Inst Own `83.45%` | Short Float `2.23%` | Perf Quarter `-9.02%` |
| 4 | Income `13.65B` | P/S `6.84` | EPS this Y `42.21%` | Inst Trans `-1.51%` | Short Ratio `2.16` | Perf Half Y `4.08%` |
| 5 | Sales `48.77B` | P/B `11.07` | EPS next Y `6.05%` | ROA `24.47%` | Short Interest `92.20M` | Perf YTD `-14.53%` |
| 6 | Book/sh `7.24` | P/C `36.54` | EPS next 5Y `21.80%` | ROE `49.54%` | 52W High `126.71 -36.75%` | Perf Year `-33.98%` |
| 7 | Cash/sh `2.19` | P/FCF `29.92` | EPS past 3/5Y `36.44% 32.98%` | ROIC `31.11%` | 52W Low `65.08 23.14%` | Perf 3Y `98.11%` |
| 8 | Dividend Est. `-` | EV/EBITDA `10.52` | Sales past 3/5Y `12.72% 12.61%` | Gross Margin `49.53%` | Volatility `2.94% 2.90%` | Perf 5Y `46.54%` |
| 9 | Dividend TTM `-` | EV/Sales `7.00` | EPS Y/Y TTM `34.80%` | Oper. Margin `30.25%` | ATR (14) `2.43` | Perf 10Y `735.92%` |
| 10 | Dividend Ex-Date `-` | Quick Ratio `1.14` | Sales Y/Y TTM `17.62%` | Profit Margin `27.99%` | RSI (14) `63.61` | Recom `1.70` |
| 11 | Dividend Gr. 3/5Y `- -` | Current Ratio `1.14` | EPS Q/Q `11.06%` | SMA20 `7.13%` | Beta `1.53` | Target Price `94.07` |
| 12 | Payout `0.00%` | Debt/Eq `0.55` | Sales Q/Q `13.41%` | SMA50 `7.47%` | Rel Volume `0.64` | Prev Close `80.22` |
| 13 | Employees `16000` | LT Debt/Eq `0.46` | Earnings `Jul 16 AMC` | SMA200 `-9.52%` | Avg Volume `42.65M` | Price `80.14` |
| 14 | IPO `May 23, 2002` | Option/Short `Yes / Yes` | EPS/Sales Surpr. `1.73% -0.17%` | Trades `` | Volume `27,118,417` | Change % `-0.10%` |

## 표기 규칙 (finviz)
- 양수 초록·음수 빨강은 **변화율·이격·성과** 칸에만. 절대값(P/E, Market Cap 등)은 무채색. 단, P/E 등 밸류 지표는 finviz가 수준에 따라 색을 바꾸지만(낮으면 초록) 1차 범위에서는 생략 가능.
- 큰 수는 `333.70B` / `92.20M` 축약. 원화는 `조`/`억` 축약으로 대응.
- 두 값 한 칸: `52W High 126.71 -36.75%`(값 + 현재가와의 거리), `Volatility 주간 월간`, `EPS past 3/5Y`, `Dividend Gr. 3/5Y`, `EPS/Sales Surpr.`.
- `Option/Short`, `Trades`(Elite 전용), `Index`는 MyStock에선 대체/생략 후보 (architect 판단).

## 하단 블록 스키마 (실페이지)
- 뉴스: `시각(MMM-DD-YY hh:mmAM) · 제목(링크) · 출처`, 날짜 바뀔 때만 날짜 표기, 같은 날은 시각만.
- 애널리스트: `Date · Action(Upgrade/Downgrade/Reiterated/Initiated/Resumed) · Analyst · Rating Change(A → B) · Price Target Change($120 → $100)`, 기본 10건 + "Show Previous Ratings".
- 재무 차트: `Timeframe: Annual | Quarterly` 토글, 3개 막대 차트 `GAAP EPS` / `Sales ($bln)` / `Shares Outstanding (bln)`, x축 연도(2019…2025, TTM/MRQ), 막대 위 값 라벨.
- 회사 설명: 한 단락 텍스트.
- 내부자: `Insider Trading · Relationship · Date · Transaction(Buy/Sale/Option Exercise) · Cost · #Shares · Value ($) · #Shares Total · SEC Form 4(일시)`.
