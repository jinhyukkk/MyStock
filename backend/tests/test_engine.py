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
