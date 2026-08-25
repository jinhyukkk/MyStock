"""벡터화 전후 engine.run 결과 불변을 증명하는 골든 회귀 테스트.

실 DB가 아니라 합성 일봉을 쓴다 — 실 시세는 개인 데이터인 데다 갱신될 때마다
테스트가 깨진다. 시드 고정 랜덤워크에 거래정지(NaN 행)·휴장(캘린더 어긋남)을
심어, 벡터화가 깨뜨리기 쉬운 경로(휴장일 매핑, NaN 봉 건너뛰기)를 픽스처에
가둔다. 픽스처 재생성은 이 파일을 직접 실행한다: python tests/test_engine_golden.py
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from app import engine

FIXTURE = Path(__file__).parent / "fixtures" / "engine_golden.json"

# 프리셋별 대표 파라미터 — 기본값이 아니라 거래가 충분히 발생하는 조합으로 고른다.
# 거래 0건 픽스처는 회귀를 못 잡는다.
CASES = [
    ("abs_momentum", {"lookback": 63, "skip": 0, "trend_ma": 100}),
    ("donchian", {"entry_n": 20, "exit_n": 10}),
]


def _synth_frames(n_symbols=8, n_days=700, seed=7):
    """시드 고정 합성 일봉. 종목마다 추세·변동성이 다르고,
    짝수 종목은 중간에 NaN 행(거래정지), 3의 배수 종목은 격주 금요일 휴장."""
    rng = np.random.default_rng(seed)
    base = pd.bdate_range("2021-01-04", periods=n_days)
    frames, tickers = {}, {}
    for k in range(n_symbols):
        drift = rng.normal(0.0004, 0.0006)
        vol = rng.uniform(0.01, 0.03)
        rets = rng.normal(drift, vol, n_days)
        close = 10_000 * np.exp(np.cumsum(rets))
        spread = np.abs(rng.normal(0, vol, n_days)) * close
        df = pd.DataFrame({
            "open": close * (1 + rng.normal(0, vol / 2, n_days)),
            "high": close + spread,
            "low": close - spread,
            "close": close,
            "volume": rng.integers(10_000, 500_000, n_days).astype(float),
        }, index=base)
        df["low"] = df[["open", "low", "close"]].min(axis=1)
        df["high"] = df[["open", "high", "close"]].max(axis=1)
        if k % 2 == 0:  # 거래정지 구간
            df.iloc[200 + k * 10:205 + k * 10,
                    df.columns.get_indexer(["open", "high", "low", "close"])] = np.nan
        if k % 3 == 0:  # 격주 금요일 휴장 — 종목 간 캘린더를 어긋나게 한다
            fridays = [d for i, d in enumerate(base) if d.weekday() == 4 and i % 2]
            df = df.drop(index=fridays)
        sym = f"SYN{k:02d}"
        frames[sym] = df
        tickers[sym] = {"symbol": sym, "name": f"합성{k}", "market": "KR",
                        "currency": "KRW", "is_etf": 0}
    return frames, tickers


def _run_case(preset, params):
    frames, tickers = _synth_frames()
    out = engine.run(frames, tickers, preset, params,
                     initial_capital_krw=10_000_000.0, fx=1400.0)
    out.pop("_used")
    curve = out.pop("equity_curve")
    # 곡선 전체는 픽스처가 비대해져 앞뒤 5점 + 길이로 요약한다 — 중간이 틀어지면
    # metrics(MDD·샤프)가 반드시 같이 틀어지므로 회귀 검출력은 유지된다
    out["curve_len"] = len(curve)
    out["curve_head"] = curve[:5]
    out["curve_tail"] = curve[-5:]
    return json.loads(json.dumps(out))  # 튜플→리스트 등 JSON 정규화


def test_golden_unchanged():
    golden = json.loads(FIXTURE.read_text())
    for preset, params in CASES:
        got = _run_case(preset, params)
        assert got == golden[preset], f"{preset} 결과가 골든 픽스처와 다릅니다"


def test_fixture_has_trades():
    # 거래 없는 픽스처는 아무것도 증명하지 못한다
    golden = json.loads(FIXTURE.read_text())
    for preset, _ in CASES:
        assert golden[preset]["metrics"]["trade_count"] > 5


if __name__ == "__main__":
    FIXTURE.parent.mkdir(exist_ok=True)
    FIXTURE.write_text(json.dumps(
        {preset: _run_case(preset, params) for preset, params in CASES},
        ensure_ascii=False, indent=1))
    print("fixture written:", FIXTURE)
