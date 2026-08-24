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
