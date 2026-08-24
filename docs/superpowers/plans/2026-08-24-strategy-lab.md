# 전략 연구실 (`/strategy`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 24종목 유니버스에서 시계열 모멘텀 전략의 계좌 단위 자본곡선을 백테스트하는 새 화면 `/strategy`를 만든다.

**Architecture:** 기존 `backtest.py`(등급 검증기)는 손대지 않는다. 순수 함수 모듈 `strategy.py`(일봉 → 진입/청산 시그널)와 `engine.py`(시그널 → 자본곡선)를 새로 만들고, 그 위에 API 2개와 화면 1개를 얹는다. 사이징·손절·비용은 앱이 이미 쓰는 1% 룰·2×ATR·`costs`를 그대로 재사용한다.

**Tech Stack:** Python 3.11 / FastAPI / pandas / pytest (백엔드), React 19 + TypeScript + Vite (프론트). 새 의존성 없음.

## Global Constraints

- **새 라이브러리 추가 금지.** 차트는 인라인 SVG로 직접 그린다.
- `backend/app/backtest.py`, `backend/app/scoring.py`는 **수정하지 않는다**. 상수만 import 한다.
- `strategy.py`는 **순수 함수만**. DB·네트워크·현재시각(`datetime.now()`) 접근 금지.
- 룩어헤드 금지. rolling 최고/최저는 반드시 `.shift(1)`을 건다.
- 진입가는 **신호 익일 시가**. 손절은 **2×ATR**(`backtest.STOP_ATR_MULT`).
- 수량 절삭은 `costs.round_to_lot` **내림**. 올림하면 리스크 한도를 넘는다.
- 주석·커밋 메시지·화면 문구는 한국어.
- 백엔드 테스트는 `backend/`에서 `python -m pytest`. 프론트는 `frontend/`에서 `npx tsc -b`.
- PowerShell 5.1 환경 — `&&` 사용 불가. 명령을 한 줄에 하나씩 쓴다.

## 파일 구조

| 파일 | 책임 | 신규/수정 |
|---|---|---|
| `backend/app/strategy.py` | 전략 프리셋. 일봉 → `enter`/`exit` 불리언 | 신규 |
| `backend/tests/test_strategy.py` | 시그널·룩어헤드 검증 | 신규 |
| `backend/app/engine.py` | 포트폴리오 백테스트. 자본곡선·거래·지표 | 신규 |
| `backend/tests/test_engine.py` | 사이징·청산·비용·상한 검증 | 신규 |
| `backend/app/service.py` | 조회 계층 (파일 끝에 추가) | 수정 |
| `backend/app/api.py` | 엔드포인트 2개 (파일 끝에 추가) | 수정 |
| `backend/tests/test_api.py` | 엔드포인트 계약 | 수정 |
| `frontend/src/types.ts` | `StrategyResult` 등 타입 | 수정 |
| `frontend/src/components/EquityCurve.tsx` | 자본곡선 SVG 꺾은선 | 신규 |
| `frontend/src/pages/Strategy.tsx` | 화면 본체 | 신규 |
| `frontend/src/App.tsx` | `/strategy` 라우트 | 수정 |
| `frontend/src/components/Layout.tsx` | 내비 탭 추가 | 수정 |

---

### Task 1: 절대 모멘텀 시그널

**Files:**
- Create: `backend/app/strategy.py`
- Test: `backend/tests/test_strategy.py`

**Interfaces:**
- Consumes: `pandas`. 입력 `df`는 `date` 인덱스에 `open/high/low/close/volume` 열을 가진 일봉.
- Produces:
  - `momentum(close: pd.Series, lookback: int, skip: int) -> pd.Series`
  - `abs_momentum(df: pd.DataFrame, params: dict) -> pd.DataFrame` — `enter`/`exit` bool 열
  - `PRESETS: dict` — Task 2에서 `donchian` 항목이 추가된다

- [ ] **Step 1: Write the failing test**

`backend/tests/test_strategy.py` 를 새로 만든다:

```python
import pandas as pd
import pytest

from app import strategy


def _series(values: list[float]) -> pd.Series:
    idx = pd.date_range("2024-01-01", periods=len(values), freq="D")
    return pd.Series(values, index=idx, dtype=float)


def _frame(closes: list[float]) -> pd.DataFrame:
    """종가만 의미 있는 최소 일봉. 고가·저가는 종가와 같게 둔다."""
    s = _series(closes)
    return pd.DataFrame({"open": s, "high": s, "low": s, "close": s,
                         "volume": 1000.0}, index=s.index)


def test_momentum_skips_recent_window():
    """12-1 모멘텀은 최근 skip일을 제외한다 — 단기 반전이 신호를 오염시킨다.

    lookback=5, skip=2 이면 i 시점 수익률은 close[i-2] / close[i-7] - 1 이다.
    """
    close = _series([100, 110, 120, 130, 140, 150, 160, 170, 180, 190])
    m = strategy.momentum(close, lookback=5, skip=2)
    # i=7: close[5]=150, close[0]=100 → 0.5
    assert m.iloc[7] == pytest.approx(0.5)
    # 앞쪽 lookback+skip 구간은 값이 없다
    assert m.iloc[:7].isna().all()


def test_abs_momentum_enters_on_positive_momentum_above_trend():
    """진입 조건 = 모멘텀 양(+) AND 종가 > 추세선."""
    df = _frame([100 + i for i in range(30)])
    out = strategy.abs_momentum(df, {"lookback": 10, "skip": 2, "trend_ma": 5})
    assert out["enter"].iloc[-1]
    assert not out["exit"].iloc[-1]


def test_abs_momentum_exits_when_momentum_turns_negative():
    """모멘텀이 음(-)으로 돌면 청산 신호."""
    df = _frame([100 + i for i in range(20)] + [120 - 4 * i for i in range(20)])
    out = strategy.abs_momentum(df, {"lookback": 10, "skip": 2, "trend_ma": 5})
    assert out["exit"].iloc[-1]
    assert not out["enter"].iloc[-1]


def test_signals_have_no_lookahead():
    """미래 봉을 붙여도 과거 시그널이 바뀌면 안 된다.

    이게 깨지면 백테스트 전체가 거짓이 된다 — 가장 중요한 테스트다.
    """
    full = _frame([100 + (i % 7) * 3 for i in range(60)])
    out_full = strategy.abs_momentum(full, {"lookback": 10, "skip": 2, "trend_ma": 5})
    cut = full.iloc[:40]
    out_cut = strategy.abs_momentum(cut, {"lookback": 10, "skip": 2, "trend_ma": 5})
    pd.testing.assert_frame_equal(out_full.iloc[:40], out_cut)
```

- [ ] **Step 2: Run test to verify it fails**

`backend/` 에서:

```bash
python -m pytest tests/test_strategy.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.strategy'`

- [ ] **Step 3: Write minimal implementation**

`backend/app/strategy.py` 를 새로 만든다:

```python
"""전략 프리셋 — 일봉을 받아 진입·청산 시점만 답한다.

여기는 **순수 함수만** 둔다(DB·네트워크·현재시각 없음). 자본이 얼마인지,
몇 주를 사는지는 engine.py의 몫이다. 경계를 섞으면 전략을 추가할 때마다
사이징 로직까지 손대게 된다.

룩어헤드 금지가 이 파일의 유일한 하드 규칙이다. rolling 최고/최저에는
반드시 .shift(1)을 건다 — 오늘 고가를 오늘 돌파 판정에 넣으면 그 백테스트는
전부 거짓이 된다.
"""
import pandas as pd


def momentum(close: pd.Series, lookback: int, skip: int) -> pd.Series:
    """12-1 모멘텀 — 최근 skip일을 제외한 lookback 기간 수익률(비율).

    최근 1개월을 빼는 이유는 단기 반전 효과다. 그대로 두면 막 급등한 종목이
    최고 점수를 받고, 그 급등은 다음 달에 되돌려지는 경향이 있다.
    """
    base = close.shift(skip)
    return base / base.shift(lookback) - 1


def abs_momentum(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """절대(시계열) 모멘텀 — 자기 과거 수익률의 부호를 본다.

    횡단면 랭킹과 달리 유니버스가 필요 없다. 종목 하나로 계산된다.

    진입: 모멘텀 > 0 AND 종가 > 추세선
    청산: 모멘텀 < 0
    """
    close = df["close"]
    mom = momentum(close, params["lookback"], params["skip"])
    trend = close.rolling(params["trend_ma"]).mean()
    enter = (mom > 0) & (close > trend)
    exit_ = mom < 0
    # NaN 구간(지표가 아직 안 찬 앞부분)은 신호 없음으로 확정한다 —
    # 결측을 그대로 두면 engine이 NaN을 참으로 읽을 여지가 남는다
    return pd.DataFrame({"enter": enter.fillna(False).astype(bool),
                         "exit": exit_.fillna(False).astype(bool)},
                        index=df.index)


PRESETS = {
    "abs_momentum": {
        "label": "절대 모멘텀",
        "fn": abs_momentum,
        "params": {
            "lookback": {"default": 252, "min": 20, "max": 504, "label": "룩백(일)"},
            "skip": {"default": 21, "min": 0, "max": 63, "label": "스킵(일)"},
            "trend_ma": {"default": 200, "min": 20, "max": 300, "label": "추세필터(일)"},
        },
    },
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_strategy.py -v
```

Expected: PASS — 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/strategy.py backend/tests/test_strategy.py
```

```bash
git commit -m "feat: 전략 프리셋 모듈과 절대 모멘텀 시그널"
```

---

### Task 2: 돈치안 돌파 시그널

**Files:**
- Modify: `backend/app/strategy.py` (`donchian` 함수 추가, `PRESETS`에 항목 추가)
- Test: `backend/tests/test_strategy.py` (테스트 추가)

**Interfaces:**
- Consumes: Task 1의 `PRESETS` dict
- Produces: `donchian(df: pd.DataFrame, params: dict) -> pd.DataFrame` — `enter`/`exit` bool 열. `PRESETS["donchian"]`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_strategy.py` 끝에 추가한다:

```python
def _ohlc(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    """(open, high, low, close) 튜플 목록 → 일봉."""
    idx = pd.date_range("2024-01-01", periods=len(rows), freq="D")
    return pd.DataFrame(
        {"open": [r[0] for r in rows], "high": [r[1] for r in rows],
         "low": [r[2] for r in rows], "close": [r[3] for r in rows],
         "volume": 1000.0}, index=idx)


def test_donchian_enters_on_breakout_of_prior_high():
    """N일 최고가를 넘어서면 진입. 비교 대상은 **어제까지의** 최고가다."""
    rows = [(100, 110, 90, 100)] * 3 + [(100, 116, 95, 115)]
    out = strategy.donchian(_ohlc(rows), {"entry_n": 3, "exit_n": 2})
    assert out["enter"].iloc[3]


def test_donchian_does_not_use_todays_high_in_its_own_breakout():
    """오늘 고가를 오늘 돌파 판정에 넣으면 매일 진입 신호가 뜬다.

    .shift(1) 누락 회귀를 잡는 테스트다.
    """
    rows = [(100, 110, 90, 100), (100, 120, 90, 105),
            (100, 130, 90, 115), (100, 140, 90, 125)]
    out = strategy.donchian(_ohlc(rows), {"entry_n": 2, "exit_n": 2})
    assert not out["enter"].any()


def test_donchian_exits_below_prior_low():
    """M일 최저가를 이탈하면 청산."""
    rows = [(100, 110, 95, 100)] * 3 + [(100, 105, 80, 90)]
    out = strategy.donchian(_ohlc(rows), {"entry_n": 3, "exit_n": 3})
    assert out["exit"].iloc[3]


def test_donchian_registered_in_presets():
    assert "donchian" in strategy.PRESETS
    assert strategy.PRESETS["donchian"]["fn"] is strategy.donchian
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_strategy.py -v -k donchian
```

Expected: FAIL — `AttributeError: module 'app.strategy' has no attribute 'donchian'`

- [ ] **Step 3: Write minimal implementation**

`backend/app/strategy.py` 의 `PRESETS` **바로 위**에 추가한다:

```python
def donchian(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """돈치안 채널 돌파 — 가격 자체가 신호다.

    진입: 종가 > 직전 entry_n일 최고가
    청산: 종가 < 직전 exit_n일 최저가

    .shift(1)이 핵심이다. 빼면 오늘 고가가 오늘의 비교 대상에 들어가
    고가를 경신한 날마다 진입 신호가 뜬다.
    """
    hh = df["high"].rolling(params["entry_n"]).max().shift(1)
    ll = df["low"].rolling(params["exit_n"]).min().shift(1)
    enter = df["close"] > hh
    exit_ = df["close"] < ll
    return pd.DataFrame({"enter": enter.fillna(False).astype(bool),
                         "exit": exit_.fillna(False).astype(bool)},
                        index=df.index)
```

그리고 `PRESETS` dict 안, `abs_momentum` 항목 **뒤에** 추가한다:

```python
    "donchian": {
        "label": "돈치안 돌파",
        "fn": donchian,
        "params": {
            "entry_n": {"default": 55, "min": 5, "max": 200, "label": "진입 채널(일)"},
            "exit_n": {"default": 20, "min": 5, "max": 200, "label": "청산 채널(일)"},
        },
    },
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_strategy.py -v
```

Expected: PASS — 8 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/strategy.py backend/tests/test_strategy.py
```

```bash
git commit -m "feat: 돈치안 돌파 전략 프리셋"
```

---

### Task 3: 엔진 — 1% 룰 포지션 사이징

**Files:**
- Create: `backend/app/engine.py`
- Test: `backend/tests/test_engine.py`

**Interfaces:**
- Consumes: `costs.round_to_lot`, `backtest.STOP_ATR_MULT`
- Produces:
  - `position_size(equity_krw: float, entry: float, stop: float, fx: float, market: str, max_weight: float = MAX_WEIGHT) -> float`
  - 상수 `RISK_PCT = 0.01`, `MAX_WEIGHT = 0.20`, `MAX_POSITIONS = 7`, `STOP_ATR_MULT`

**주의:** `service.MAX_WEIGHT`를 import 하면 `service` → `engine` 순환이 생긴다. 같은 값 `0.20`을 `engine.MAX_WEIGHT`로 **다시 선언**하고 주석으로 묶는다.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_engine.py` 를 새로 만든다:

```python
import pandas as pd
import pytest

from app import engine


def test_position_size_risks_one_percent_of_equity():
    """진입가-손절가 거리가 계좌의 1%가 되도록 수량을 정한다.

    equity 10,000,000 → 리스크 100,000원. 진입 10,000 / 손절 9,000 → 주당 1,000원
    → 100주.
    """
    qty = engine.position_size(10_000_000, entry=10_000, stop=9_000,
                               fx=1.0, market="KR", max_weight=1.0)
    assert qty == 100


def test_position_size_rounds_down_to_lot():
    """국내 주식은 정수 주문만 가능하다. 올림하면 계산해 둔 리스크 한도를 넘는다.

    리스크 100,000 / 주당 950원 = 105.26주 → 105주.
    """
    qty = engine.position_size(10_000_000, entry=10_000, stop=9_050,
                               fx=1.0, market="KR", max_weight=1.0)
    assert qty == 105


def test_position_size_capped_by_max_weight():
    """저변동성 종목은 손절폭이 좁아 1% 룰 수량이 폭발한다 — 비중 상한으로 자른다.

    진입 10,000 / 손절 9,990 → 주당 10원 → 1% 룰로는 10,000주(계좌의 1000%).
    비중 상한 20%면 10,000,000 × 0.2 / 10,000 = 200주.
    """
    qty = engine.position_size(10_000_000, entry=10_000, stop=9_990,
                               fx=1.0, market="KR", max_weight=0.20)
    assert qty == 200


def test_position_size_zero_when_cannot_afford_one_share():
    """한 주도 못 사면 0. 1주로 올려주면 그 1주가 1% 룰을 넘는다."""
    qty = engine.position_size(100_000, entry=10_000_000, stop=9_000_000,
                               fx=1.0, market="KR", max_weight=1.0)
    assert qty == 0


def test_position_size_applies_fx_for_usd():
    """USD 종목의 진입가·손절가는 달러다 — 원화 리스크로 환산해야 수량이 맞는다.

    리스크 100,000원, 주당 손실 $10 × 1,300 = 13,000원 → 7.69주 → 7주.
    """
    qty = engine.position_size(10_000_000, entry=100, stop=90,
                               fx=1_300.0, market="US", max_weight=1.0)
    assert qty == 7


def test_position_size_zero_when_stop_above_entry():
    """손절선이 진입가 위면 손실 정의가 성립하지 않는다 — 0을 돌려준다."""
    qty = engine.position_size(10_000_000, entry=100, stop=110,
                               fx=1.0, market="KR", max_weight=1.0)
    assert qty == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_engine.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.engine'`

- [ ] **Step 3: Write minimal implementation**

`backend/app/engine.py` 를 새로 만든다:

```python
"""포트폴리오 백테스트 엔진 — 시그널을 자본곡선으로 바꾼다.

strategy.py가 "언제"를 답하면 여기가 "얼마나"를 답한다. 두 관심사를 섞지 않는
이유는 전략이 앞으로 늘어나기 때문이다 — 엔진은 전략을 몰라야 하고, 전략은
자본을 몰라야 한다.

사이징·손절·비용은 앱이 화면에서 권하는 규칙을 그대로 쓴다. 검증한 전략과
실행할 전략이 다르면 이 백테스트는 아무것도 증명하지 못한다.
"""
import math

import pandas as pd

from app import backtest, costs, indicators, strategy

RISK_PCT = 0.01  # 거래 1건이 계좌에서 잃을 수 있는 비율 — service._risk_block과 동일
# service.MAX_WEIGHT와 같은 값. import 하면 service → engine 순환이 생겨 다시 선언한다.
# 한쪽을 바꾸면 다른 쪽도 함께 바꿔야 한다.
MAX_WEIGHT = 0.20
MAX_POSITIONS = 7  # portfolio.DEFAULT_TARGET_POSITIONS[1]과 동일
# 모든 보유가 동시에 손절에 닿았을 때의 손실 합 상한 — portfolio.MAX_ACCOUNT_RISK_PCT와 동일.
# 종목별 1%만 지키면 7종목에서 총 7%가 되는데, 합산을 안 보면 그 사실이 어디에도 안 남는다.
MAX_ACCOUNT_RISK_PCT = 6.0
STOP_ATR_MULT = backtest.STOP_ATR_MULT
TRADING_DAYS = 252


def position_size(equity_krw: float, entry: float, stop: float, fx: float,
                  market: str, max_weight: float = MAX_WEIGHT) -> float:
    """1% 룰 수량 — 진입가에서 손절가까지 맞았을 때 계좌의 1%를 잃는 수량.

    entry·stop은 종목 통화 기준, fx로 원화 환산한다. 두 상한을 함께 건다:
      - 리스크 상한: 손실이 계좌의 RISK_PCT
      - 노셔널 상한: 한 종목이 계좌의 max_weight를 넘지 않게
    저변동성 종목은 손절폭이 좁아 리스크 상한만으로는 수량이 폭발한다.
    """
    per_share_loss = (entry - stop) * fx
    if per_share_loss <= 0 or entry <= 0 or equity_krw <= 0:
        return 0.0
    risk_qty = equity_krw * RISK_PCT / per_share_loss
    cap_qty = equity_krw * max_weight / (entry * fx)
    # 내림 — 올리면 계산해 둔 리스크 한도를 넘는다
    return costs.round_to_lot(min(risk_qty, cap_qty), market)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_engine.py -v
```

Expected: PASS — 6 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/engine.py backend/tests/test_engine.py
```

```bash
git commit -m "feat: 백테스트 엔진 1% 룰 포지션 사이징"
```

---

### Task 4: 엔진 — 청산가 결정

**Files:**
- Modify: `backend/app/engine.py` (파일 끝에 `resolve_exit` 추가)
- Test: `backend/tests/test_engine.py` (테스트 추가)

**Interfaces:**
- Consumes: Task 3의 `engine` 모듈
- Produces: `resolve_exit(bars: pd.DataFrame, entry_i: int, stop: float | None, exit_signal: list[bool]) -> tuple[int, float, str]` — `(청산봉 인덱스, 청산가, 사유)`. 사유는 `"stop"|"signal"|"end"`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_engine.py` 끝에 추가한다:

```python
def _bars(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(rows), freq="D")
    return pd.DataFrame(
        {"open": [r[0] for r in rows], "high": [r[1] for r in rows],
         "low": [r[2] for r in rows], "close": [r[3] for r in rows]}, index=idx)


def test_resolve_exit_stops_out_when_low_touches_stop():
    """저가가 손절선을 건드리면 그 자리에서 청산."""
    bars = _bars([(100, 105, 98, 102), (102, 106, 88, 95), (95, 99, 94, 97)])
    i, px, reason = engine.resolve_exit(bars, entry_i=0, stop=90.0,
                                        exit_signal=[False, False, False])
    assert (i, px, reason) == (1, 90.0, "stop")


def test_resolve_exit_uses_open_when_gap_below_stop():
    """갭 하락으로 시가가 이미 손절선 아래면 시가 체결.

    손절선 체결을 가정하면 갭 리스크만큼 성과가 낙관적으로 부풀려진다.
    """
    bars = _bars([(100, 105, 98, 102), (85, 88, 84, 86)])
    i, px, reason = engine.resolve_exit(bars, entry_i=0, stop=90.0,
                                        exit_signal=[False, False])
    assert (i, px, reason) == (1, 85.0, "stop")


def test_resolve_exit_on_signal_uses_next_open():
    """청산 신호는 그날 종가에 체결할 수 없다 — 익일 시가다."""
    bars = _bars([(100, 105, 98, 102), (103, 106, 101, 104), (99, 100, 97, 98)])
    i, px, reason = engine.resolve_exit(bars, entry_i=0, stop=50.0,
                                        exit_signal=[False, True, False])
    # 인덱스 1에서 청산 신호 → 인덱스 2 시가 99에 청산
    assert (i, px, reason) == (2, 99.0, "signal")


def test_resolve_exit_falls_back_to_last_close():
    """신호도 손절도 없이 데이터가 끝나면 마지막 종가로 평가 청산."""
    bars = _bars([(100, 105, 98, 102), (102, 106, 101, 104)])
    i, px, reason = engine.resolve_exit(bars, entry_i=0, stop=50.0,
                                        exit_signal=[False, False])
    assert (i, px, reason) == (1, 104.0, "end")


def test_resolve_exit_prefers_stop_when_stop_precedes_signal():
    """손절이 먼저 닿았으면 뒤에 오는 청산 신호는 의미가 없다."""
    bars = _bars([(100, 105, 98, 102), (100, 101, 85, 88), (88, 90, 87, 89)])
    i, px, reason = engine.resolve_exit(bars, entry_i=0, stop=90.0,
                                        exit_signal=[False, True, False])
    assert reason == "stop"
    assert i == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_engine.py -v -k resolve_exit
```

Expected: FAIL — `AttributeError: module 'app.engine' has no attribute 'resolve_exit'`

- [ ] **Step 3: Write minimal implementation**

`backend/app/engine.py` 끝에 추가한다:

```python
def resolve_exit(bars: pd.DataFrame, entry_i: int, stop: float | None,
                 exit_signal) -> tuple[int, float, str]:
    """진입봉(entry_i) 이후 언제·얼마에 나가는지. (인덱스, 가격, 사유)를 돌려준다.

    사유는 stop|signal|end. 손절로 끝난 비율이 안 보이면 전략이 규칙대로
    굴러간 것인지 알 수 없어서 사유를 함께 남긴다.

    우선순위는 시간순이다 — 손절이 먼저 닿았으면 뒤의 청산 신호는 무의미하다.
    """
    o = bars["open"].to_numpy(dtype=float)
    low = bars["low"].to_numpy(dtype=float)
    close = bars["close"].to_numpy(dtype=float)
    n = len(bars)
    for d in range(entry_i, n):
        # 손절 먼저 — 갭 하락이면 시가가 이미 손절선 아래다
        if stop is not None and low[d] <= stop:
            return d, min(o[d], stop), "stop"
        # 청산 신호는 그날 종가에 낼 수 없다 — 익일 시가
        if exit_signal[d] and d + 1 < n:
            return d + 1, o[d + 1], "signal"
    return n - 1, close[n - 1], "end"
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_engine.py -v
```

Expected: PASS — 11 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/engine.py backend/tests/test_engine.py
```

```bash
git commit -m "feat: 엔진 청산가 결정 — 손절·신호·기간종료"
```

---

### Task 5: 엔진 — 자본곡선과 성과 지표

**Files:**
- Modify: `backend/app/engine.py` (파일 끝에 `metrics`, `_cost_pct`, `run` 추가)
- Test: `backend/tests/test_engine.py` (테스트 추가)

**Interfaces:**
- Consumes: Task 3의 `position_size`, Task 4의 `resolve_exit`, `strategy.PRESETS`, `indicators.compute_indicators`, `costs.backtest_cost_pct`
- Produces:
  - `metrics(equity: list[float], trades: list[dict]) -> dict` — 키 `cagr/mdd/sharpe/win_rate/trade_count/final_equity_krw`
  - `run(price_frames: dict, tickers: dict, preset: str, params: dict, *, initial_capital_krw: float, fx: float) -> dict` — 키 `equity_curve/trades/metrics/max_concurrent/universe_size/preset/params`
  - 거래 dict 키: `symbol, name, entry_date, entry_price, exit_date, exit_price, exit_reason, qty, cost_krw, pnl_krw`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_engine.py` 끝에 추가한다:

```python
def test_metrics_mdd_measures_peak_to_trough():
    """MDD는 최고점 대비 최대 낙폭 — 시작점 대비가 아니다."""
    m = engine.metrics([100.0, 200.0, 150.0, 180.0], trades=[])
    assert m["mdd"] == pytest.approx(-25.0)  # 200 → 150


def test_metrics_win_rate_counts_positive_net_pnl_only():
    """비용 차감 후 손익이 양(+)인 거래만 승. 0원은 승이 아니다."""
    trades = [{"pnl_krw": 100.0}, {"pnl_krw": -50.0}, {"pnl_krw": 0.0}]
    m = engine.metrics([100.0, 110.0], trades=trades)
    assert m["win_rate"] == pytest.approx(33.3, abs=0.1)
    assert m["trade_count"] == 3


def test_metrics_flat_curve_has_zero_mdd_and_cagr():
    m = engine.metrics([1_000.0] * 300, trades=[])
    assert m["mdd"] == 0.0
    assert m["cagr"] == pytest.approx(0.0, abs=1e-9)


def test_metrics_no_trades_leaves_win_rate_none():
    """거래가 0건이면 승률은 0%가 아니라 '없음'이다."""
    m = engine.metrics([100.0, 100.0], trades=[])
    assert m["win_rate"] is None


def _rising(n: int) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    close = [100.0 + i * 0.5 for i in range(n)]
    return pd.DataFrame({"open": close, "high": [c + 1 for c in close],
                         "low": [c - 1 for c in close], "close": close,
                         "volume": 100_000.0}, index=idx)


def test_run_with_no_signals_returns_flat_equity():
    """신호가 하나도 없으면 자본곡선은 초기자본 평선이고 거래는 0건이다."""
    idx = pd.date_range("2024-01-01", periods=300, freq="D")
    flat = pd.DataFrame({"open": 100.0, "high": 100.0, "low": 100.0,
                         "close": 100.0, "volume": 1000.0}, index=idx)
    out = engine.run({"AAA": flat},
                     {"AAA": {"name": "가", "market": "KR", "currency": "KRW",
                              "is_etf": 0}},
                     preset="abs_momentum",
                     params={"lookback": 20, "skip": 2, "trend_ma": 10},
                     initial_capital_krw=10_000_000.0, fx=1_300.0)
    assert out["trades"] == []
    assert out["metrics"]["trade_count"] == 0
    equities = [p["equity_krw"] for p in out["equity_curve"]]
    assert all(e == pytest.approx(10_000_000.0) for e in equities)


def test_run_deducts_cost_from_trade_pnl():
    """왕복 비용이 실제로 빠지는지 — 총수익과 순손익이 비용만큼 달라야 한다."""
    out = engine.run({"AAA": _rising(260)},
                     {"AAA": {"name": "가", "market": "KR", "currency": "KRW",
                              "is_etf": 0}},
                     preset="abs_momentum",
                     params={"lookback": 60, "skip": 5, "trend_ma": 30},
                     initial_capital_krw=10_000_000.0, fx=1_300.0)
    assert out["trades"], "상승 추세에서 진입이 한 건도 없으면 시그널이 잘못됐다"
    t = out["trades"][0]
    assert t["cost_krw"] > 0
    gross = (t["exit_price"] - t["entry_price"]) * t["qty"]
    assert t["pnl_krw"] == pytest.approx(gross - t["cost_krw"], abs=1.0)


def test_run_respects_max_positions():
    """동시 보유는 MAX_POSITIONS를 넘지 않는다."""
    df = _rising(260)
    frames = {f"S{i}": df.copy() for i in range(12)}
    tickers = {f"S{i}": {"name": f"종목{i}", "market": "KR", "currency": "KRW",
                         "is_etf": 0} for i in range(12)}
    out = engine.run(frames, tickers, preset="abs_momentum",
                     params={"lookback": 60, "skip": 5, "trend_ma": 30},
                     initial_capital_krw=100_000_000.0, fx=1_300.0)
    assert out["max_concurrent"] <= engine.MAX_POSITIONS


def _volatile_rising(n: int) -> pd.DataFrame:
    """상승 추세 + 넓은 일중 변동.

    2×ATR이 가격의 5%를 넘어야 1% 룰이 비중 상한(20%)보다 먼저 묶인다
    (조건: 주당 손실 > 가격/20). 일중 ±5%면 2×ATR ≈ 가격의 20%다.
    저변동 fixture(_rising)를 쓰면 비중 상한이 먼저 걸려 이 테스트가 무의미해진다.
    """
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    close = [100.0 + i * 0.5 for i in range(n)]
    return pd.DataFrame({"open": close,
                         "high": [c * 1.05 for c in close],
                         "low": [c * 0.95 for c in close],
                         "close": close, "volume": 100_000.0}, index=idx)


def test_run_caps_total_account_risk():
    """종목별 1%만 지키면 7종목에서 총 7%가 된다 — 합산 상한 6%가 먼저 막아야 한다.

    각 포지션이 계좌의 정확히 1%를 걸므로 6건째까지만 들어간다.
    MAX_POSITIONS(7)가 아니라 MAX_ACCOUNT_RISK_PCT(6%)가 막는 것을 확인한다.
    """
    df = _volatile_rising(260)
    frames = {f"S{i}": df.copy() for i in range(12)}
    tickers = {f"S{i}": {"name": f"종목{i}", "market": "KR", "currency": "KRW",
                         "is_etf": 0} for i in range(12)}
    out = engine.run(frames, tickers, preset="abs_momentum",
                     params={"lookback": 60, "skip": 5, "trend_ma": 30},
                     initial_capital_krw=1_000_000_000.0, fx=1_300.0)
    # 자본이 충분해 비중 상한에는 안 걸린다 — 막는 것은 총 리스크 6%다
    assert out["max_concurrent"] == 6


def test_run_rejects_unknown_preset():
    """알 수 없는 전략은 ValueError — API 계층이 400으로 바꿔 준다."""
    with pytest.raises(ValueError):
        engine.run({}, {}, preset="없는전략", params={},
                   initial_capital_krw=1_000_000.0, fx=1_300.0)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_engine.py -v -k "metrics or run_"
```

Expected: FAIL — `AttributeError: module 'app.engine' has no attribute 'metrics'`

- [ ] **Step 3: Write minimal implementation**

`backend/app/engine.py` 끝에 추가한다:

```python
def metrics(equity: list[float], trades: list[dict]) -> dict:
    """자본곡선과 거래 목록에서 성과 지표.

    샤프의 무위험수익률은 0으로 둔다 — 화면에 그 가정을 함께 표시한다.
    승률은 비용 차감 후 손익 기준이다(0원은 승이 아니다).
    """
    n = len(equity)
    start, end = (equity[0], equity[-1]) if n else (0.0, 0.0)
    cagr = 0.0
    if n > 1 and start > 0:
        cagr = ((end / start) ** (TRADING_DAYS / (n - 1)) - 1) * 100
    # MDD — 최고점 대비 최대 낙폭. 시작점 대비로 재면 중간에 오른 뒤의 하락을 놓친다
    peak, mdd = start or 1.0, 0.0
    for v in equity:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, (v / peak - 1) * 100)
    rets = [equity[i] / equity[i - 1] - 1
            for i in range(1, n) if equity[i - 1] > 0]
    sharpe = None
    if len(rets) > 1:
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        sd = math.sqrt(var)
        sharpe = mean / sd * math.sqrt(TRADING_DAYS) if sd > 0 else None
    wins = sum(1 for t in trades if t["pnl_krw"] > 0)
    return {
        "cagr": round(cagr, 2),
        "mdd": round(mdd, 2),
        "sharpe": round(sharpe, 2) if sharpe is not None else None,
        "win_rate": round(wins / len(trades) * 100, 1) if trades else None,
        "trade_count": len(trades),
        "final_equity_krw": round(end, 0),
    }


def _one_way_cost(t: dict, df: pd.DataFrame, fx: float) -> float:
    """이 종목의 편도 비용(비율). 왕복값을 절반으로 나눠 진입·청산에 각각 건다."""
    recent = df.tail(60)
    turnover = float((recent["close"] * recent["volume"]).median()) if len(recent) else 0.0
    if t.get("currency") == "USD":
        turnover *= fx
    return costs.backtest_cost_pct(t.get("market", ""), t.get("is_etf", 0),
                                   turnover) / 2 / 100


def run(price_frames: dict, tickers: dict, preset: str, params: dict, *,
        initial_capital_krw: float, fx: float) -> dict:
    """포트폴리오 백테스트 — 시그널을 계좌 단위 자본곡선으로.

    진입은 신호 익일 시가, 손절은 2×ATR, 사이징은 1% 룰. 전부 앱이 화면에서
    권하는 규칙과 같다.
    """
    if preset not in strategy.PRESETS:
        raise ValueError(f"알 수 없는 전략: {preset}")
    fn = strategy.PRESETS[preset]["fn"]

    # 모든 종목의 거래일을 합집합으로 모아 하나의 달력을 만든다 —
    # 종목마다 다른 인덱스로 자본을 합산하면 어느 날의 자본인지 알 수 없다
    calendar = sorted(set().union(*(set(df.index) for df in price_frames.values()))) \
        if price_frames else []

    prepared = {}
    for sym, df in price_frames.items():
        if len(df) < 30:
            continue  # 지표가 안 차는 종목은 신호를 만들 수 없다
        enriched = indicators.compute_indicators(df)
        prepared[sym] = {
            "df": enriched, "sig": fn(enriched, params),
            "rate": fx if tickers.get(sym, {}).get("currency") == "USD" else 1.0,
            "cost": _one_way_cost(tickers.get(sym, {}), df, fx),
        }

    equity = initial_capital_krw
    open_pos: dict[str, dict] = {}
    trades: list[dict] = []
    curve: list[dict] = []
    max_concurrent = 0

    for day in calendar:
        # ① 청산 먼저 — 같은 날 나가고 들어오는 자리를 비워 준다
        for sym in list(open_pos):
            p = open_pos[sym]
            if day < p["exit_date"]:
                continue
            gross = (p["exit_price"] - p["entry_price"]) * p["qty"] * p["rate"]
            equity += gross - p["cost_krw"]
            trades.append({
                "symbol": sym, "name": tickers.get(sym, {}).get("name", sym),
                "entry_date": p["entry_date"].strftime("%Y-%m-%d"),
                "entry_price": round(p["entry_price"], 4),
                "exit_date": p["exit_date"].strftime("%Y-%m-%d"),
                "exit_price": round(p["exit_price"], 4),
                "exit_reason": p["exit_reason"], "qty": p["qty"],
                "cost_krw": round(p["cost_krw"], 0),
                "pnl_krw": round(gross - p["cost_krw"], 0),
            })
            del open_pos[sym]

        # ② 진입 — 자리가 남아 있고 계좌 총 리스크가 한도 안일 때만.
        # 미결 리스크 = 모든 보유가 동시에 손절에 닿았을 때의 손실 합
        open_risk = sum((p["entry_price"] - p["stop"]) * p["qty"] * p["rate"]
                        for p in open_pos.values())
        for sym, pr in prepared.items():
            if len(open_pos) >= MAX_POSITIONS:
                break
            if sym in open_pos or day not in pr["sig"].index:
                continue
            if not bool(pr["sig"].at[day, "enter"]):
                continue
            df = pr["df"]
            i = df.index.get_loc(day)
            if i + 1 >= len(df):
                continue  # 마지막 봉에서는 낼 수 있는 주문이 없다
            entry = float(df["open"].iloc[i + 1])
            atr = df["atr14"].iloc[i]
            if not entry or pd.isna(atr) or not atr:
                continue
            stop = entry - STOP_ATR_MULT * float(atr)
            market = tickers.get(sym, {}).get("market", "")
            qty = position_size(equity, entry, stop, pr["rate"], market)
            if qty <= 0:
                continue
            # 이 포지션을 더했을 때 계좌 총 리스크가 한도를 넘으면 진입하지 않는다
            add_risk = (entry - stop) * qty * pr["rate"]
            if equity > 0 and (open_risk + add_risk) / equity * 100 > MAX_ACCOUNT_RISK_PCT:
                continue
            open_risk += add_risk
            bars = df.iloc[i + 1:]
            exit_i, exit_px, reason = resolve_exit(
                bars, 0, stop, pr["sig"]["exit"].iloc[i + 1:].tolist())
            notional = entry * qty * pr["rate"]
            open_pos[sym] = {
                "entry_date": df.index[i + 1], "entry_price": entry,
                "exit_date": bars.index[exit_i], "exit_price": exit_px,
                "exit_reason": reason, "qty": qty, "rate": pr["rate"],
                "stop": stop,  # 계좌 총 리스크 합산에 필요하다
                # 진입·청산 각각 편도 비용. 청산 노셔널로 재계산하지 않는 것은
                # 근사지만, 왕복을 통째로 빼먹는 것보다 훨씬 정확하다
                "cost_krw": notional * pr["cost"] * 2,
            }
        max_concurrent = max(max_concurrent, len(open_pos))

        # ③ 그날의 자본 — 확정 자본 + 미결 포지션 평가손익
        unrealized = 0.0
        for sym, p in open_pos.items():
            df = prepared[sym]["df"]
            if day in df.index:
                unrealized += (float(df["close"].at[day]) - p["entry_price"]) \
                    * p["qty"] * p["rate"]
        curve.append({"date": day.strftime("%Y-%m-%d"),
                      "equity_krw": round(equity + unrealized, 0)})

    return {
        "equity_curve": curve,
        "trades": trades,
        "metrics": metrics([c["equity_krw"] for c in curve], trades),
        "max_concurrent": max_concurrent,
        "universe_size": len(price_frames),
        "preset": preset,
        "params": params,
    }
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_engine.py -v
```

Expected: PASS — 20 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/engine.py backend/tests/test_engine.py
```

```bash
git commit -m "feat: 엔진 자본곡선과 성과 지표"
```

---

### Task 6: 벤치마크·동일가중 비교선

**Files:**
- Modify: `backend/app/engine.py` (파일 끝에 `buy_and_hold` 추가)
- Test: `backend/tests/test_engine.py` (테스트 추가)

**Interfaces:**
- Consumes: Task 5의 `engine` 모듈
- Produces: `buy_and_hold(price_frames: dict, tickers: dict, initial_capital_krw: float, fx: float, calendar: list) -> list[dict]` — `[{"date": str, "equity_krw": float}]`

**왜 필요한가:** 전략 CAGR이 12%라도 그냥 들고 있었으면 18%였다면 그 전략은 실패다. 비교선이 없으면 그 사실이 화면 어디에도 안 나온다.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_engine.py` 끝에 추가한다:

```python
def test_buy_and_hold_equal_weights_the_universe():
    """동일가중 매수보유 — 초기자본을 종목 수로 나눠 첫날 사서 끝까지 든다."""
    idx = pd.date_range("2024-01-01", periods=5, freq="D")
    up = pd.DataFrame({"open": 100.0, "high": 100.0, "low": 100.0,
                       "close": [100.0, 110.0, 120.0, 130.0, 140.0],
                       "volume": 1000.0}, index=idx)
    flat = pd.DataFrame({"open": 100.0, "high": 100.0, "low": 100.0,
                         "close": 100.0, "volume": 1000.0}, index=idx)
    tickers = {s: {"market": "KR", "currency": "KRW", "is_etf": 0}
               for s in ("A", "B")}
    curve = engine.buy_and_hold({"A": up, "B": flat}, tickers,
                                initial_capital_krw=1_000_000.0,
                                fx=1_300.0, calendar=list(idx))
    # A에 50만(+40%), B에 50만(0%) → 마지막 120만
    assert curve[0]["equity_krw"] == pytest.approx(1_000_000.0)
    assert curve[-1]["equity_krw"] == pytest.approx(1_200_000.0)


def test_buy_and_hold_empty_universe_returns_empty():
    """종목이 없으면 빈 곡선. 화면이 빈 배열을 그대로 처리한다."""
    assert engine.buy_and_hold({}, {}, 1_000_000.0, 1_300.0, []) == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_engine.py -v -k buy_and_hold
```

Expected: FAIL — `AttributeError: module 'app.engine' has no attribute 'buy_and_hold'`

- [ ] **Step 3: Write minimal implementation**

`backend/app/engine.py` 끝에 추가한다:

```python
def buy_and_hold(price_frames: dict, tickers: dict, initial_capital_krw: float,
                 fx: float, calendar: list) -> list[dict]:
    """동일가중 매수보유 비교선.

    전략 CAGR이 12%라도 그냥 들고 있었으면 18%였다면 그 전략은 실패다.
    비교선이 없으면 그 사실이 화면 어디에도 안 나온다. 비용은 첫 진입 1회뿐이라
    생략한다 — 전략 쪽에 불리한 쪽(보수적)이다.
    """
    usable = {s: df for s, df in price_frames.items() if len(df)}
    if not usable or not calendar:
        return []
    slot = initial_capital_krw / len(usable)
    units = {}
    for s, df in usable.items():
        rate = fx if tickers.get(s, {}).get("currency") == "USD" else 1.0
        first = float(df["close"].iloc[0])
        units[s] = (slot / (first * rate) if first > 0 else 0.0, rate)
    out, last = [], {}
    for day in calendar:
        total = 0.0
        for s, df in usable.items():
            if day in df.index:
                last[s] = float(df["close"].at[day])
            qty, rate = units[s]
            total += qty * last.get(s, float(df["close"].iloc[0])) * rate
        out.append({"date": day.strftime("%Y-%m-%d"), "equity_krw": round(total, 0)})
    return out
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_engine.py -v
```

Expected: PASS — 22 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/engine.py backend/tests/test_engine.py
```

```bash
git commit -m "feat: 동일가중 매수보유 비교선"
```

---

### Task 7: API 엔드포인트

**Files:**
- Modify: `backend/app/service.py` (import 한 줄 + 파일 끝에 섹션 추가)
- Modify: `backend/app/api.py` (파일 끝에 섹션 추가)
- Test: `backend/tests/test_api.py` (테스트 추가)

**Interfaces:**
- Consumes: `engine.run`·`engine.buy_and_hold` (Task 5·6), `strategy.PRESETS` (Task 1·2), `db.list_tickers`, `db.load_prices`, `fetchers.BENCHMARKS`
- Produces:
  - `service.strategy_presets() -> list[dict]` — `[{key, label, params}]`
  - `service.run_strategy_backtest(conn, preset: str, params: dict | None, initial_capital_krw: float) -> dict`
  - `GET /api/strategy/presets`, `POST /api/strategy/backtest`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_api.py` 끝에 추가한다:

```python
def test_strategy_presets_lists_both_strategies(client):
    """화면이 파라미터 입력칸을 그리려면 각 전략의 파라미터 메타가 필요하다."""
    r = client.get("/api/strategy/presets")
    assert r.status_code == 200
    body = r.json()
    assert {p["key"] for p in body} == {"abs_momentum", "donchian"}
    mom = next(p for p in body if p["key"] == "abs_momentum")
    assert mom["label"] == "절대 모멘텀"
    assert mom["params"]["lookback"]["default"] == 252


def test_strategy_backtest_returns_curve_and_metrics(client):
    r = client.post("/api/strategy/backtest",
                    json={"preset": "abs_momentum",
                          "initial_capital_krw": 10_000_000})
    assert r.status_code == 200
    body = r.json()
    assert "equity_curve" in body
    assert "trades" in body
    assert set(body["metrics"]) >= {"cagr", "mdd", "sharpe", "win_rate",
                                    "trade_count", "final_equity_krw"}
    assert "buy_and_hold" in body
    assert "benchmark" in body
    # 유니버스 편향 경고는 화면이 문구를 지어내지 않도록 서버가 내려준다
    assert body["universe_warning"]
    assert body["fx_note"]


def test_strategy_backtest_rejects_unknown_preset(client):
    """알 수 없는 전략은 500이 아니라 400이어야 화면에 원인이 남는다."""
    r = client.post("/api/strategy/backtest", json={"preset": "없는전략"})
    assert r.status_code == 400


def test_strategy_backtest_fills_missing_params_with_defaults(client):
    """화면이 일부 파라미터만 보내도 나머지는 기본값으로 채운다."""
    r = client.post("/api/strategy/backtest",
                    json={"preset": "donchian", "params": {"entry_n": 20}})
    assert r.status_code == 200
    assert r.json()["params"] == {"entry_n": 20, "exit_n": 20}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_api.py -v -k strategy
```

Expected: FAIL — 404 (라우트가 없어 SPA 폴백이 걸린다)

- [ ] **Step 3: Write minimal implementation**

먼저 `backend/app/service.py` 의 import 줄을 바꾼다. 현재:

```python
from app import (backtest, company, costs, db, fetchers, indicators,
```

를 다음으로 바꾼다 (`engine` 추가):

```python
from app import (backtest, company, costs, db, engine, fetchers, indicators,
```

그리고 같은 import 문의 마지막 이름 뒤에 `strategy` 를 추가한다 (알파벳 순서 유지).

`backend/app/service.py` **파일 끝**에 추가한다:

```python
# ── 전략 연구실 ────────────────────────────────────────────────────────────
# 등급 검증(backtest.py)과 목적이 다르다. 여기는 "이 매매 규칙이 계좌 단위로
# 돈을 버는가"에 답한다 — 자본곡선·사이징·동시보유가 전부 들어간다.

STRATEGY_DAYS = 1500  # 약 6년 — price_cache가 가진 만큼 다 쓴다
UNIVERSE_WARNING = (
    "유니버스는 등록된 보유·관심 종목입니다. 직접 고른 종목이라 전략의 알파와 "
    "종목 선택 효과를 분리할 수 없습니다. 이 수치를 실전 기대값으로 쓰지 마세요.")


def strategy_presets() -> list[dict]:
    return [{"key": k, "label": v["label"], "params": v["params"]}
            for k, v in strategy.PRESETS.items()]


def run_strategy_backtest(conn, preset: str, params: dict | None = None,
                          initial_capital_krw: float = 10_000_000.0) -> dict:
    """등록 종목 전체를 유니버스로 전략 백테스트를 돌린다."""
    if preset not in strategy.PRESETS:
        raise ValueError(f"알 수 없는 전략: {preset}")
    # 화면이 일부 파라미터만 보내도 나머지는 기본값으로 채운다
    merged = {k: v["default"] for k, v in strategy.PRESETS[preset]["params"].items()}
    merged.update(params or {})

    frames, tickers = {}, {}
    for row in db.list_tickers(conn):
        t = dict(row)
        df = db.load_prices(conn, t["symbol"], limit=STRATEGY_DAYS)
        if df.empty:
            continue
        frames[t["symbol"]] = df
        tickers[t["symbol"]] = t
    fx = get_sentiment_view(conn).get("usdkrw") or portfolio.DEFAULT_USDKRW

    out = engine.run(frames, tickers, preset, merged,
                     initial_capital_krw=initial_capital_krw, fx=fx)

    calendar = sorted(set().union(*(set(df.index) for df in frames.values()))) \
        if frames else []
    out["buy_and_hold"] = engine.buy_and_hold(
        frames, tickers, initial_capital_krw, fx, calendar)
    # 벤치마크는 KOSPI. _refresh_benchmark가 BENCH:KR로 저장해 둔다
    bdf = db.load_prices(conn, "BENCH:KR", limit=STRATEGY_DAYS)
    out["benchmark"] = engine.buy_and_hold(
        {"BENCH:KR": bdf},
        {"BENCH:KR": {"market": "KR", "currency": "KRW", "is_etf": 0}},
        initial_capital_krw, fx, calendar) if not bdf.empty else []
    out["benchmark_label"] = fetchers.BENCHMARKS["KR"][1] if not bdf.empty else None

    out["universe_warning"] = UNIVERSE_WARNING
    out["fx_note"] = f"USD 종목은 현재 환율 {fx:,.0f}원 고정 근사입니다."
    out["initial_capital_krw"] = initial_capital_krw
    return out
```

`backend/app/api.py` **파일 끝**에 추가한다:

```python
# ── 전략 연구실 ────────────────────────────────────────────────────────────

class StrategyBacktestIn(BaseModel):
    preset: str = Field(min_length=1)
    params: dict[str, int] | None = None
    initial_capital_krw: float = Field(default=10_000_000.0, gt=0)


@router.get("/strategy/presets")
def strategy_presets():
    return service.strategy_presets()


@router.post("/strategy/backtest")
def strategy_backtest(body: StrategyBacktestIn, request: Request):
    try:
        return service.run_strategy_backtest(
            _conn(request), body.preset, body.params, body.initial_capital_krw)
    except ValueError as e:
        # 알 수 없는 전략이 500이 되면 화면에 원인이 안 남는다
        raise HTTPException(400, str(e))
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_api.py -v -k strategy
```

Expected: PASS — 4 passed

전체도 확인한다:

```bash
python -m pytest -q
```

Expected: 실패 0건

- [ ] **Step 5: Commit**

```bash
git add backend/app/service.py backend/app/api.py backend/tests/test_api.py
```

```bash
git commit -m "feat: 전략 백테스트 API 2개"
```

---

### Task 8: 타입과 자본곡선 차트

**Files:**
- Modify: `frontend/src/types.ts` (파일 끝에 추가)
- Create: `frontend/src/components/EquityCurve.tsx`

**Interfaces:**
- Consumes: Task 7의 API 응답 형태
- Produces:
  - `types.ts`: `EquityPoint`, `StrategyTrade`, `StrategyMetrics`, `StrategyResult`, `StrategyParamMeta`, `StrategyPreset`
  - `EquityCurve.tsx`: `export interface Series { label: string; color: string; points: EquityPoint[] }` 와 `export default function EquityCurve({ series }: { series: Series[] })`

- [ ] **Step 1: 타입 추가**

`frontend/src/types.ts` **파일 끝**에 추가한다:

```typescript
/** 전략 연구실 — 계좌 단위 백테스트 (등급 검증용 Backtest와 다른 것) */
export interface EquityPoint { date: string; equity_krw: number }
export interface StrategyTrade {
  symbol: string; name: string;
  entry_date: string; entry_price: number;
  exit_date: string; exit_price: number;
  /** stop=손절 터치, signal=청산 신호, end=데이터 끝 평가청산 */
  exit_reason: 'stop' | 'signal' | 'end';
  qty: number; cost_krw: number; pnl_krw: number;
}
export interface StrategyMetrics {
  cagr: number; mdd: number;
  /** 무위험수익률 0 가정. 변동성이 0이면 null */
  sharpe: number | null;
  /** 비용 차감 후 손익이 양(+)인 거래 비율. 거래가 없으면 null */
  win_rate: number | null;
  trade_count: number; final_equity_krw: number;
}
export interface StrategyResult {
  equity_curve: EquityPoint[];
  buy_and_hold: EquityPoint[];
  benchmark: EquityPoint[];
  benchmark_label: string | null;
  trades: StrategyTrade[];
  metrics: StrategyMetrics;
  max_concurrent: number; universe_size: number;
  preset: string; params: Record<string, number>;
  /** 서버가 내려주는 유니버스 편향 경고 — 화면이 문구를 지어내지 않는다 */
  universe_warning: string;
  fx_note: string;
  initial_capital_krw: number;
}
export interface StrategyParamMeta {
  default: number; min: number; max: number; label: string;
}
export interface StrategyPreset {
  key: string; label: string; params: Record<string, StrategyParamMeta>;
}
```

- [ ] **Step 2: 차트 컴포넌트 작성**

`frontend/src/components/EquityCurve.tsx` 를 새로 만든다:

```tsx
import { useLayoutEffect, useRef, useState } from 'react'
import type { EquityPoint } from '../types'

// 자본곡선은 5분봉 캔들(finviz/IndexChart)과 형태가 달라 재사용하지 않는다.
// 차트 라이브러리를 넣는 대신 꺾은선 하나를 직접 그린다.
const PAD = { top: 12, right: 68, bottom: 22, left: 12 }
const PLOT_H = 220
const H = PAD.top + PLOT_H + PAD.bottom

export interface Series { label: string; color: string; points: EquityPoint[] }

export default function EquityCurve({ series }: { series: Series[] }) {
  const box = useRef<HTMLDivElement>(null)
  const [w, setW] = useState(720)
  // 카드 실폭을 재서 좌표계로 쓴다 — viewBox를 고정폭으로 두면 넓은 화면에서 늘어진다
  useLayoutEffect(() => {
    const el = box.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setW(Math.max(320, e.contentRect.width)))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const drawn = series.filter(s => s.points.length > 1)
  if (drawn.length === 0)
    return <div className="empty">표시할 자본곡선이 없습니다.</div>

  const all = drawn.flatMap(s => s.points.map(p => p.equity_krw))
  const lo = Math.min(...all), hi = Math.max(...all)
  const span = hi - lo || 1
  const plotW = w - PAD.left - PAD.right
  const x = (i: number, len: number) =>
    PAD.left + (len > 1 ? (i / (len - 1)) * plotW : 0)
  const y = (v: number) => PAD.top + PLOT_H - ((v - lo) / span) * PLOT_H
  const fmtKrw = (v: number) => `₩${Math.round(v / 10_000).toLocaleString()}만`
  const first = drawn[0].points

  return (
    <div ref={box}>
      <svg width={w} height={H} role="img" aria-label="전략 자본곡선">
        {/* 가로 격자 3줄 — 없으면 곡선의 기울기를 눈으로 못 잰다 */}
        {[0, 0.5, 1].map(f => {
          const v = lo + span * f
          return (
            <g key={f}>
              <line x1={PAD.left} x2={PAD.left + plotW} y1={y(v)} y2={y(v)}
                    stroke="var(--border)" strokeWidth={1} />
              <text x={PAD.left + plotW + 6} y={y(v) + 4} fontSize={11}
                    fill="var(--text-dim)">{fmtKrw(v)}</text>
            </g>
          )
        })}
        {drawn.map(s => (
          <polyline key={s.label} fill="none" stroke={s.color} strokeWidth={1.6}
            points={s.points
              .map((p, i) => `${x(i, s.points.length)},${y(p.equity_krw)}`)
              .join(' ')} />
        ))}
        <text x={PAD.left} y={H - 6} fontSize={11} fill="var(--text-dim)">
          {first[0].date}</text>
        <text x={PAD.left + plotW} y={H - 6} fontSize={11}
              fill="var(--text-dim)" textAnchor="end">
          {first[first.length - 1].date}</text>
      </svg>
      <div style={{ display: 'flex', gap: 14, fontSize: 12, marginTop: 4,
                    flexWrap: 'wrap' }}>
        {drawn.map(s => (
          <span key={s.label} style={{ color: 'var(--text-dim)' }}>
            <span style={{ display: 'inline-block', width: 10, height: 2,
                           background: s.color, marginRight: 5,
                           verticalAlign: 'middle' }} />
            {s.label}</span>
        ))}
      </div>
    </div>
  )
}
```

- [ ] **Step 3: 타입체크**

`frontend/` 에서:

```bash
npx tsc -b
```

Expected: 출력 없음(통과)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types.ts frontend/src/components/EquityCurve.tsx
```

```bash
git commit -m "feat: 자본곡선 SVG 차트 컴포넌트"
```

---

### Task 9: 전략 화면과 라우트

**Files:**
- Create: `frontend/src/pages/Strategy.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Layout.tsx`

**Interfaces:**
- Consumes: Task 7의 API, Task 8의 `EquityCurve`·`Series`·타입, `api.ts`의 `get`/`post`
- Produces: 라우트 `/strategy`, 내비 탭 "전략"

- [ ] **Step 1: 화면 작성**

`frontend/src/pages/Strategy.tsx` 를 새로 만든다:

```tsx
import { useEffect, useState } from 'react'
import { get, post } from '../api'
import EquityCurve from '../components/EquityCurve'
import type { StrategyPreset, StrategyResult } from '../types'

const fmt = (n: number) => Math.round(n).toLocaleString()
const signed = (n: number) => `${n >= 0 ? '+' : ''}${n}%`
const REASON_LABEL = { stop: '손절', signal: '신호', end: '기간종료' } as const

export default function Strategy() {
  const [presets, setPresets] = useState<StrategyPreset[]>([])
  const [key, setKey] = useState('')
  const [params, setParams] = useState<Record<string, number>>({})
  const [capital, setCapital] = useState(10_000_000)
  const [result, setResult] = useState<StrategyResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    get<StrategyPreset[]>('/api/strategy/presets')
      .then(ps => {
        setPresets(ps)
        if (ps.length) applyPreset(ps[0])
      })
      .catch(e => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  function applyPreset(p: StrategyPreset) {
    setKey(p.key)
    setParams(Object.fromEntries(
      Object.entries(p.params).map(([k, meta]) => [k, meta.default])))
    setResult(null)
  }

  const current = presets.find(p => p.key === key)

  async function run() {
    setBusy(true); setError('')
    try {
      setResult(await post<StrategyResult>('/api/strategy/backtest', {
        preset: key, params, initial_capital_krw: capital,
      }))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const m = result?.metrics
  const stopped = result
    ? result.trades.filter(t => t.exit_reason === 'stop').length : 0

  return (
    <>
      <div className="card">
        <strong>전략 연구실</strong>
        <div style={{ color: 'var(--text-dim)', fontSize: 12, marginTop: 4 }}>
          매매 규칙을 계좌 단위로 돌려 자본곡선을 만듭니다. 종목별 등급 검증은
          종목 상세의 백테스트 표에 있습니다.
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap',
                      alignItems: 'center', marginTop: 10 }}>
          <select value={key} onChange={e => {
            const p = presets.find(x => x.key === e.target.value)
            if (p) applyPreset(p)
          }}>
            {presets.map(p => <option key={p.key} value={p.key}>{p.label}</option>)}
          </select>
          {current && Object.entries(current.params).map(([k, meta]) => (
            <label key={k} style={{ fontSize: 12, color: 'var(--text-dim)' }}>
              {meta.label}{' '}
              <input type="number" value={params[k] ?? meta.default}
                     min={meta.min} max={meta.max} style={{ width: 78 }}
                     onChange={e => setParams(
                       { ...params, [k]: Number(e.target.value) })} />
            </label>
          ))}
          <label style={{ fontSize: 12, color: 'var(--text-dim)' }}>
            초기자본{' '}
            <input type="number" value={capital} step={1_000_000}
                   style={{ width: 130 }}
                   onChange={e => setCapital(Number(e.target.value))} />
          </label>
          <button onClick={run} disabled={busy || !key}>
            {busy ? '계산 중…' : '실행'}</button>
        </div>
        {error && <div className="warn" style={{ marginTop: 8 }}>⚠ {error}</div>}
      </div>

      {result && (
        <>
          {/* 이 경고를 지우면 숫자만 남고 전제가 사라진다 —
              검증했다고 믿는 상태가 검증 안 한 상태보다 위험하다 */}
          <div className="card warn" style={{ fontSize: 12 }}>
            ⚠ {result.universe_warning} (유니버스 {result.universe_size}종목,
            동시 보유 최대 {result.max_concurrent}종목)
            <div style={{ color: 'var(--text-dim)', marginTop: 4 }}>
              {result.fx_note} 샤프는 무위험수익률 0 가정입니다.</div>
          </div>

          <div className="card">
            <strong>자본곡선</strong>
            <EquityCurve series={[
              { label: '전략', color: 'var(--buy)', points: result.equity_curve },
              { label: `${result.benchmark_label ?? '벤치마크'} 매수보유`,
                color: 'var(--text-dim)', points: result.benchmark },
              { label: `${result.universe_size}종목 동일가중 보유`,
                color: 'var(--sell)', points: result.buy_and_hold },
            ]} />
          </div>

          <div className="card">
            <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
              {m && ([
                ['CAGR', signed(m.cagr)],
                ['MDD', `${m.mdd}%`],
                ['샤프', m.sharpe === null ? '—' : String(m.sharpe)],
                ['승률', m.win_rate === null ? '—' : `${m.win_rate}%`],
                ['거래', `${m.trade_count}회`],
                ['손절종료', m.trade_count
                  ? `${Math.round(stopped / m.trade_count * 100)}%` : '—'],
                ['최종자본', `₩${fmt(m.final_equity_krw)}`],
              ] as const).map(([label, value]) => (
                <div key={label}>
                  <div style={{ color: 'var(--text-dim)', fontSize: 12 }}>{label}</div>
                  <div style={{ fontSize: 18, fontWeight: 700 }}>{value}</div>
                </div>
              ))}
            </div>
          </div>

          <div className="card">
            <strong>거래 내역 ({result.trades.length}건)</strong>
            {result.trades.length === 0
              ? <div className="empty">이 파라미터에서는 진입 신호가 없었습니다.</div>
              : <table>
                  <thead><tr>
                    <th>종목</th><th>진입</th><th>청산</th><th>사유</th>
                    <th>수량</th><th>비용</th><th>손익</th>
                  </tr></thead>
                  <tbody>
                    {result.trades.map((t, i) => (
                      <tr key={`${t.symbol}-${t.entry_date}-${i}`}>
                        <td>{t.name}</td>
                        <td>{t.entry_date}</td>
                        <td>{t.exit_date}</td>
                        <td>{REASON_LABEL[t.exit_reason]}</td>
                        <td>{fmt(t.qty)}</td>
                        <td style={{ color: 'var(--text-dim)' }}>
                          ₩{fmt(t.cost_krw)}</td>
                        <td className={t.pnl_krw >= 0 ? 'pos' : 'neg'}>
                          ₩{fmt(t.pnl_krw)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>}
          </div>
        </>
      )}
    </>
  )
}
```

- [ ] **Step 2: 라우트 등록**

`frontend/src/App.tsx` 의 lazy import 블록을 바꾼다. 현재:

```tsx
const Watchlist = lazy(() => import('./pages/Watchlist'))
```

뒤에 한 줄 추가한다:

```tsx
const Strategy = lazy(() => import('./pages/Strategy'))
```

그리고 `/watchlist` 라우트 바로 뒤에 추가한다:

```tsx
          <Route path="/strategy" element={
            <Suspense fallback={fallback}><Strategy /></Suspense>} />
```

- [ ] **Step 3: 내비 탭 추가**

`frontend/src/components/Layout.tsx` 의 `tabs` 배열을 바꾼다. 현재:

```tsx
const tabs = [
  { to: '/', label: '대시보드' }, { to: '/portfolio', label: '포트폴리오' },
  { to: '/watchlist', label: '워치리스트' },
]
```

를 다음으로 바꾼다:

```tsx
const tabs = [
  { to: '/', label: '대시보드' }, { to: '/portfolio', label: '포트폴리오' },
  { to: '/watchlist', label: '워치리스트' }, { to: '/strategy', label: '전략' },
]
```

- [ ] **Step 4: 타입체크와 빌드**

```bash
npx tsc -b
```

Expected: 출력 없음(통과)

```bash
npm run build
```

Expected: `✓ built in ...`

- [ ] **Step 5: 브라우저 실측**

`preview_start` 로 앱을 띄우고 `/strategy` 로 이동해 확인한다:

- 전략 드롭다운에 "절대 모멘텀", "돈치안 돌파" 2개가 있다
- 전략을 바꾸면 파라미터 입력칸이 바뀐다 (모멘텀 3개 ↔ 돈치안 2개)
- [실행] 후 자본곡선 3선·지표 카드·거래 내역이 렌더된다
- 유니버스 경고 문구가 보인다
- `read_console_messages` 에 에러가 0건이다

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/Strategy.tsx frontend/src/App.tsx frontend/src/components/Layout.tsx
```

```bash
git commit -m "feat: 전략 연구실 화면과 /strategy 라우트"
```

---

### Task 10: 개발 규약 갱신과 최종 검증

**Files:**
- Modify: `.claude/skills/mystock-dev/SKILL.md`

**Interfaces:**
- Consumes: Task 1~9의 결과물 전체

- [ ] **Step 1: 화면·모듈 지도에 반영**

`.claude/skills/mystock-dev/SKILL.md` 의 화면 표(`| Settings | ...` 행이 있는 표)에 행을 추가한다:

```markdown
| 전략 연구실 | `/strategy` | `pages/Strategy.tsx`, `components/EquityCurve.tsx` | `GET /api/strategy/presets`, `POST /api/strategy/backtest` |
```

백엔드 모듈 표에도 두 행을 추가한다:

```markdown
| `strategy.py` | 전략 프리셋 — 일봉 → 진입/청산 시그널 (순수 함수) |
| `engine.py` | 포트폴리오 백테스트 — 시그널 → 자본곡선·지표 |
```

- [ ] **Step 2: 백엔드 전체 테스트**

`backend/` 에서:

```bash
python -m pytest -q
```

Expected: 실패 0건

- [ ] **Step 3: 프론트 타입체크와 빌드**

`frontend/` 에서:

```bash
npx tsc -b
```

Expected: 출력 없음

```bash
npm run build
```

Expected: `✓ built in ...`

- [ ] **Step 4: 브라우저 최종 확인**

`preview_start` 후 `/strategy` 에서:

- 두 전략 모두 실행되어 자본곡선 3선이 그려진다
- 파라미터를 바꾸면 결과 숫자가 달라진다
- 극단 파라미터(룩백 504, 돈치안 진입 200)에서도 500이 나지 않는다
- `read_console_messages` 에러 0건

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/mystock-dev/SKILL.md
```

```bash
git commit -m "docs: 개발 규약에 전략 연구실 화면·모듈 반영"
```
