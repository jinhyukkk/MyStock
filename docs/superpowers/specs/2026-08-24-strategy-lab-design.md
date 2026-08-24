# 전략 연구실 설계 (`/strategy`)

작성일: 2026-08-24

## 배경

이 앱에는 이미 백테스트가 있지만([`backtest.py`](../../../backend/app/backtest.py)), 그것은
**등급 검증기**다. `scoring.score_ticker`가 매긴 5등급(강력매수~강력매도)이 미래 수익률과
상관있는지를 종목별로 따로 확인한다.

```python
# backtest.py — 종목 하나를 받아 등급별 forward 수익률을 집계
def backtest_ticker(df, bench=None, bench_label=None, cost_pct=None) -> dict | None:
    for i in range(start, n - 1 - min(all_horizons)):
        res = scoring.score_ticker(enriched.iloc[:i + 1])
```

알고리즘 매매에 필요한 것은 여기 없다:

| | 기존 `backtest.py` | 알고리즘 매매에 필요한 것 |
|---|---|---|
| 대상 | 이미 만들어진 등급의 예측력 | 임의 진입/청산 규칙의 손익 |
| 포지션 사이징 | 없음 (종목 1개, 진입 1회) | 자본 대비 수량 결정 필수 |
| 계좌 단위 | 없음 (종목별 독립) | 동시 보유 합산 자본곡선 필수 |
| 산출물 | 등급별 평균 수익률·판별력 | CAGR·MDD·샤프 |

`scoring.py`에 팩터를 더 얹는 방식은 세 가지 이유로 택하지 않았다.

1. `score_ticker(df)`는 종목 하나만 받는 **단일 종목 절대평가**다. 횡단면 랭킹 팩터가
   구조적으로 안 들어간다.
2. 절대화해서 넣으면 이미 있는 `_score_trend_slope`·`_score_alignment`와 중복된다.
   `SWING_WEIGHTS` 주석이 세운 규율(상관 0.70 이상이면 합성 대상)에 걸린다.
3. `SWING_CUTS`/`LONGTERM_CUTS`가 실측 분위수로 캘리브레이션돼 있어, 팩터를 추가하면
   `scripts/calibrate_grades.py` 재실행이 강제된다.

→ 기존 스코어링을 건드리지 않고 별도 화면·별도 모듈로 분리한다.

## 목표

1. 전략 규칙을 코드 프리셋으로 정의하고, 화면에서 파라미터만 조절해 백테스트한다.
2. **계좌 단위 자본곡선**을 만든다 — 동시 보유·사이징·비용을 합산한 하나의 곡선.
3. 사이징·손절·비용 규칙을 **앱이 화면에서 권하는 규칙과 일치**시킨다.
4. 결과를 CAGR·MDD·샤프·승률과 벤치마크 대비로 제시한다.

**목표가 아닌 것**

- 횡단면 랭킹 전략. 유니버스가 24종목(KR 13 / US 11)뿐이라 상위 10분위가 2.4종목이다.
  KOSPI200 벌크 수집은 별도 작업으로 끊는다.
- 파라미터 스윕·자동 최적화. 과최적화 위험이 있고 walk-forward가 짝으로 필요하다.
- 자동 주문 실행. CODEF 제거(`7598c79`)로 증권사 연동 경로 자체가 없다.
- 화면에서 규칙을 조립하는 전략 빌더 UI.
- `backtest.py` 수정. 등급 검증기로 그대로 둔다.

## 유니버스와 그 한계

현재 `tickers` 24종목, `price_cache` 26심볼 × 2021-10-19 ~ 2026-08-24 (약 5년).

이 24종목은 **사용자가 직접 고른 보유·관심 종목**이다. 자본곡선이 좋게 나와도 그것이
전략의 알파인지 종목 선택의 결과인지 이 유니버스로는 분리할 수 없다.
**화면에 이 한계를 상시 문구로 표시한다** — 숫자만 크게 보이고 전제가 사라지면
검증했다고 믿는 상태가 검증 안 한 상태보다 위험하다.

## 모듈 구조

새 파일 2개. 경계는 "언제"와 "얼마나"로 가른다.

| 파일 | 책임 | 의존 | 금지 |
|---|---|---|---|
| `backend/app/strategy.py` | 전략 프리셋. 일봉 → 진입/청산 불리언 시리즈 | `pandas`, `indicators` | DB·네트워크 접근 |
| `backend/app/engine.py` | 포트폴리오 백테스트. 시그널 → 자본곡선·거래·지표 | `strategy`, `costs`, `portfolio` | 전략 규칙을 여기 두지 않음 |

전략은 앞으로 늘어난다. 엔진은 전략을 몰라야 하고, 전략은 자본을 몰라야 한다.

### `strategy.py` 인터페이스

```python
def signals(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """일봉 → 진입/청산 불리언. df는 indicators.compute_indicators 적용본.

    반환: index=df.index, columns=["enter", "exit"] (bool)
    순수 함수 — 같은 입력이면 항상 같은 출력. DB·네트워크·현재시각 접근 없음.
    """

PRESETS = {
    "abs_momentum": {
        "label": "절대 모멘텀",
        "fn": _abs_momentum,
        "params": {"lookback": 252, "skip": 21, "trend_ma": 200},
    },
    "donchian": {
        "label": "돈치안 돌파",
        "fn": _donchian,
        "params": {"entry_n": 55, "exit_n": 20},
    },
}
```

### 프리셋 ① 절대 모멘텀

원래 검토했던 12-1 모멘텀의 **시계열 버전**. 횡단면 랭킹 대신 자기 과거 수익률의
부호를 본다 — 유니버스 없이 종목 하나로 계산된다.

- 진입: `close / close.shift(lookback) - 1 > 0` (단, 최근 `skip`일 제외) **AND** `close > SMA(trend_ma)`
- 청산: 위 모멘텀이 음(-)으로 전환 **OR** 2×ATR 손절
- 최근 1개월을 빼는 이유: 단기 반전 효과가 모멘텀 신호를 오염시킨다(Jegadeesh-Titman 1993의 표준 설계)

`trend_ma=200`은 `indicators.compute_indicators`가 만들지 않는다(sma20/60/120만).
`strategy.py`에서 필요한 기간을 직접 계산한다 — 지표 모듈에 200일선을 추가하면
`score_ticker`가 쓰지도 않는 열을 매번 계산하게 된다.

### 프리셋 ② 돈치안 돌파

- 진입: `close > high.rolling(entry_n).max().shift(1)`
- 청산: `close < low.rolling(exit_n).min().shift(1)` **OR** 2×ATR 손절
- `.shift(1)` 필수 — 오늘 고가를 오늘 돌파 판정에 넣으면 룩어헤드다

## 엔진 규칙

전부 기존 자산을 재사용한다. 백테스트가 화면이 권하는 규칙과 **같은 규칙**을 써야
검증한 전략과 실행할 전략이 같아진다.

| 항목 | 규칙 | 출처 |
|---|---|---|
| 진입가 | 신호 익일 시가 | `backtest.py` 동일 |
| 손절 | `진입가 - 2 × ATR14` | `backtest.STOP_ATR_MULT` |
| 갭 하락 | 시가가 이미 손절선 아래면 시가 체결 | `backtest._exit_price` 동일 |
| 사이징 | `risk_krw = equity × 0.01`<br>`qty = risk_krw / ((진입가 - 손절가) × fx)` | `service._risk_block` |
| 수량 절삭 | `costs.round_to_lot` 내림 | 올림하면 리스크 한도를 넘는다 |
| 노셔널 상한 | `qty ≤ equity × 0.20 / (진입가 × fx)` | `service.MAX_WEIGHT = 0.20`. 저변동성 종목에서 1% 룰 수량이 폭발한다 |
| 동시 보유 | 최대 7종목 | `portfolio.DEFAULT_TARGET_POSITIONS[1]` |
| 총 리스크 | 6% 초과 시 신규 진입 스킵 | `portfolio.MAX_ACCOUNT_RISK_PCT` |
| 비용 | 진입·청산 각각 차감 | `costs.backtest_cost_pct(market, is_etf, turnover)` |
| 환율 | 현재 환율 고정 근사 | `portfolio.account_risk`와 동일 철학. 화면에 명시 |

동시 진입 후보가 상한을 넘으면 **모멘텀 강도 내림차순**으로 자른다. 임의 순서(심볼
알파벳순 등)로 자르면 결과가 종목 이름에 의존하게 된다.

### 엔진 인터페이스

```python
def run(price_frames: dict[str, pd.DataFrame], tickers: dict[str, dict],
        preset: str, params: dict, *, start: str, end: str,
        initial_capital_krw: float, fx: float) -> dict:
    """반환:
    {
      "equity_curve": [{"date": "2021-10-19", "equity_krw": 10000000.0}, ...],
      "benchmark":    [{"date": ..., "equity_krw": ...}],   # KOSPI 매수보유
      "buy_and_hold": [{"date": ..., "equity_krw": ...}],   # 24종목 동일가중
      "trades": [{"symbol","name","entry_date","entry_price","exit_date",
                  "exit_price","exit_reason","qty","pnl_krw","cost_krw"}],
      "metrics": {"cagr","mdd","sharpe","win_rate","trade_count",
                  "excess_vs_bench","final_equity_krw"},
      "universe_size": 24, "universe_warning": "...",
    }
    """
```

`exit_reason`은 `"stop"|"signal"|"end"` 셋. 손절로 끝난 비율이 안 보이면 전략이
규칙대로 굴러간 것인지 알 수 없다.

## 지표 정의

- **CAGR**: `(final/initial) ** (252/거래일수) - 1`
- **MDD**: 자본곡선 최고점 대비 최대 낙폭
- **샤프**: 일간 수익률 평균/표준편차 × √252. 무위험수익률 0 가정 — 화면에 명시
- **승률**: 비용 차감 후 손익이 양(+)인 거래 비율. `backtest.py`와 동일하게
  비용 넘긴 것만 승으로 센다
- **초과수익**: 전략 CAGR − 벤치마크 CAGR

벤치마크는 `fetchers.BENCHMARKS["KR"]` = KOSPI(`KS11`). `BENCH:KR` 심볼로 이미
`price_cache`에 저장되는 경로가 있다(`service._refresh_benchmark`).

## API

```
POST /api/strategy/backtest
  body: {preset, params, start, end, initial_capital_krw}
  resp: engine.run() 반환값 그대로

GET  /api/strategy/presets
  resp: [{key, label, params: {name: {default, min, max, label}}}]
```

캐시하지 않는다. 24종목 × 5년은 벡터 연산이라 빠르고, 파라미터가 매번 바뀌어
캐시 적중률이 사실상 0이다. `backtest.py`의 meta 캐시 패턴을 따르지 않는다.

## 화면

새 최상위 라우트 `/strategy`. `Layout.tsx` 내비게이션에 항목 추가.

```
┌ 전략 [절대 모멘텀 ▾] 룩백[252] 스킵[21] 필터[200] 기간[2021-10 ~ 2026-08] [실행]
├ ⚠ 유니버스 24종목은 직접 고른 보유·관심 종목입니다. 전략의 알파와
│   종목 선택 효과를 분리할 수 없습니다.
├ 자본곡선 — 전략 / KOSPI / 24종목 동일가중 보유 (3선)
├ CAGR 12.3% │ MDD -18.4% │ 샤프 0.71 │ 승률 48% │ 거래 63회 │ 손절종료 31%
└ 거래 내역 표 — 종목·진입일·청산일·종료사유·수량·손익·비용
```

컴포넌트: `pages/Strategy.tsx` + `components/EquityCurve.tsx`.

차트는 **인라인 SVG를 직접 그린다** — `finviz/IndexChart.tsx`가 이미 그 방식이고
(`useLayoutEffect`로 카드 실폭을 재서 좌표계로 쓴다), 새 차트 라이브러리를 넣지 않는다.
`IndexChart`는 5분봉 캔들 전용이라 재사용하지 않고, 자본곡선용 꺾은선을 따로 만든다.

## 검증

`tests/test_strategy.py`
- 절대 모멘텀·돈치안 각각의 진입/청산 시점을 손계산 가능한 짧은 시리즈로 고정
- **룩어헤드 없음**: `signals(df[:i])`의 마지막 값이 `signals(df)[i-1]`과 같아야 한다.
  미래 봉을 붙여도 과거 신호가 바뀌면 안 된다
- `.shift(1)` 누락 회귀를 잡는 케이스

`tests/test_engine.py`
- 3봉짜리 케이스로 사이징 수식 고정 (`qty = risk / (진입-손절)`, 내림)
- 손절 터치 시 청산가·`exit_reason="stop"`
- 갭 하락 시 시가 체결
- 진입·청산 비용이 자본곡선에서 실제로 빠지는지
- 동시 보유 7종목 상한, 총 리스크 6% 상한에서 신규 진입 스킵
- 신호가 하나도 없으면 자본곡선이 초기자본 평선

## 구현 순서

1. `strategy.py` + `test_strategy.py` — 시그널만. 자본 개념 없음
2. `engine.py` + `test_engine.py` — 사이징·손절·비용·자본곡선
3. `api.py` 엔드포인트 2개 + `service` 조회 계층
4. `Strategy.tsx` + `EquityCurve.tsx` + 라우트·내비 추가

1·2는 순수 함수라 화면 없이 테스트로 완결된다. 3·4는 그 위에 얹는다.

## 이후 작업 (이 스펙 범위 밖)

- KOSPI200 벌크 일봉 수집 → 횡단면 12-1 모멘텀
- walk-forward 검증 자동화
- 확정 전략의 오늘 시그널을 보여주는 실행 콘솔
