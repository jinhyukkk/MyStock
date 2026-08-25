"""universe.monthly_membership — 시점 기준(point-in-time) 선정의 룩어헤드 금지가 핵심."""
import numpy as np
import pandas as pd
import pytest

from app import universe


def _frame(dates, close, volume):
    close = np.asarray(close, dtype=float)
    return pd.DataFrame({"open": close, "high": close, "low": close,
                         "close": close, "volume": np.asarray(volume, float)},
                        index=pd.to_datetime(dates))


def test_membership_excludes_symbol_before_volume_surge():
    """나중에만 거래대금이 커진 종목이 이른 시점 멤버십에 들어가면 룩어헤드다."""
    days = pd.bdate_range("2024-01-01", periods=200)
    frames = {
        "BIG": _frame(days, [100] * 200, [1_000_000] * 200),   # 내내 거래대금 큼
        "LATE": _frame(days, [100] * 200, [10] * 150 + [10_000_000] * 50),  # 후반에만 급증
    }
    mem = universe.monthly_membership(frames, top_n=1, window=60)
    # 전반부: BIG만 멤버 — LATE의 후반 거래대금이 새어들면 안 된다
    early = days[80]
    assert bool(mem["BIG"].loc[early]) is True
    assert bool(mem["LATE"].loc[early]) is False
    # 급증이 60일 창에 다 담긴 마지막 재선정 이후에는 LATE가 밀어낸다
    late_day = days[-1]
    assert bool(mem["LATE"].loc[late_day]) is True


def test_membership_rebalances_monthly_not_daily():
    """재선정은 매월 첫 거래일 — 그 사이 순위가 뒤집혀도 멤버십은 유지된다."""
    days = pd.bdate_range("2024-01-01", periods=80)
    # A가 근소하게 앞서다 2월 중순부터 B가 역전
    vol_a = [110] * 25 + [100] * 55
    vol_b = [100] * 25 + [120] * 55
    frames = {"A": _frame(days, [100] * 80, vol_a),
              "B": _frame(days, [100] * 80, vol_b)}
    mem = universe.monthly_membership(frames, top_n=1, window=20)
    feb = [d for d in days if d.month == 2]
    # 2월 재선정 시점(2/1)의 직전 20일 창에는 역전이 아직 안 담겼다 → 2월 내내 A
    assert all(bool(mem["A"].loc[d]) for d in feb)
    mar = [d for d in days if d.month == 3]
    # 3월 재선정에는 역전이 담긴다 → B로 교체
    assert all(bool(mem["B"].loc[d]) for d in mar)


def test_membership_needs_full_window():
    """상장 직후(창 미달) 종목은 멤버가 아니다 — NaN 중앙값으로 뽑으면 안 된다."""
    days = pd.bdate_range("2024-01-01", periods=100)
    frames = {
        "OLD": _frame(days, [100] * 100, [100] * 100),
        "NEW": _frame(days[70:], [100] * 30, [999_999] * 30),  # 30일 전 상장
    }
    mem = universe.monthly_membership(frames, top_n=2, window=60)
    assert bool(mem["NEW"].loc[days[75]]) is False  # 창이 안 찼다
    assert bool(mem["OLD"].loc[days[75]]) is True


@pytest.mark.smoke
def test_candidate_symbols_live():
    cands = universe.candidate_symbols()
    assert len(cands) > 300
    assert any(c["delisting_date"] for c in cands)
    assert {"symbol", "name", "listing_date", "delisting_date", "is_etf"} <= set(cands[0])
