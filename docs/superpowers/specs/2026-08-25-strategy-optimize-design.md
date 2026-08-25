# 전략 파라미터 최적화 (홀드아웃 그리드 서치) — 설계

2026-08-25. "자동 매매로 수익 극대화" 요청의 1단계 — 자동화 전에 전략 수익률부터
검증 구간 분리로 개선한다. 승인된 접근: A안(홀드아웃 그리드 서치).

## 목표

기존 전략 프리셋(절대모멘텀·돈치안)의 파라미터를 그리드 탐색하되, **학습/검증
구간을 날짜로 분리**해 오버피팅 조합을 눈으로 걸러낼 수 있게 한다. 백테스트
CAGR 맹목 최대화는 하지 않는다 — 정렬 기준은 검증 구간 샤프.

## 백엔드

- `strategy.PRESETS` 각 파라미터에 `grid: [값…]` 추가 (조합 수는 프리셋당 12~15개로 유지)
  - donchian: entry_n [20,40,55,80,120] × exit_n [10,20,40]
  - abs_momentum: lookback [63,126,252] × skip [0,21] × trend_ma [100,200]
- `engine.run(..., trade_start=None)` 옵션 추가 — 달력을 `day >= trade_start`로
  필터. 시그널·지표는 전체 이력으로 계산되므로 검증 구간도 워밍업이 완전하다.
- `engine.optimize(price_frames, tickers, preset, *, initial_capital_krw, fx)`
  - 전 종목 합집합 달력의 70% 지점 날짜를 split으로 잡는다
  - 학습 = frames를 split 이하로 절단해 `run()`, 검증 = 전체 frames로
    `run(trade_start=split 다음 날)`
  - 조합별 `{params, train: metrics, valid: metrics}` — 검증 샤프 내림차순(None 최하)
- `service.run_strategy_optimize(conn, preset, initial_capital_krw)` — 기존
  `run_strategy_backtest`와 같은 방식으로 frames·fx 로드 후 `engine.optimize` 호출
- `POST /api/strategy/optimize` `{preset, initial_capital_krw?}` →
  `{split_date, train_days, valid_days, results: [...]}` (동기, 수 초~수십 초)

## 프론트 (Strategy.tsx)

- "파라미터 최적화" 버튼 → 결과 표: 파라미터 | 학습 CAGR/샤프/MDD | 검증
  CAGR/샤프/MDD | 거래수. 검증 샤프 순 정렬, null은 `—`
- 행 클릭 → 해당 파라미터를 입력 폼에 적용하고 즉시 백테스트 실행
- 표 상단에 split 날짜와 "검증 성과가 학습보다 크게 낮으면 과최적화 의심" 안내 1줄

## 테스트

- `trade_start`가 달력을 자르고 그 이전 거래가 없는지
- `optimize`가 조합 수·정렬·split 날짜를 옳게 내는지 (합성 일봉)
- API 스모크: presets grid 노출, optimize 응답 형태

## 하지 않는 것

- 워크포워드(B안) — A안 토대 위에 나중에
- 실주문 연동·모의매매 — 별도 단계
