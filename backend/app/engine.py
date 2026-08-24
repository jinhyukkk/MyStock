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
