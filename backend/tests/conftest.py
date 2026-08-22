import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import numpy as np
import pandas as pd
import pytest

from app import preview


@pytest.fixture(autouse=True)
def clean_preview_state():
    """모듈 레벨 상태는 프로세스 수명 동안 남는다 — 테스트끼리 새게 두면
    앞 테스트의 인플라이트가 뒤 테스트를 pending으로 붙잡는다.
    (test_api.py 등 preview를 직접 다루지 않는 테스트도 순서·추가 테스트에 따라
    깨질 수 있어 conftest에서 전체 테스트에 적용한다.)"""
    preview.reset()
    yield
    preview.reset()

@pytest.fixture
def ohlcv_up():
    """300일 완만한 상승 추세 + 노이즈 (결정적)."""
    rng = np.random.default_rng(42)
    n = 300
    close = 100 + np.arange(n) * 0.5 + rng.normal(0, 1.5, n).cumsum() * 0.3
    close = np.maximum(close, 10)
    high = close * (1 + rng.uniform(0.001, 0.02, n))
    low = close * (1 - rng.uniform(0.001, 0.02, n))
    open_ = (high + low) / 2
    volume = rng.uniform(1e5, 3e5, n)
    idx = pd.bdate_range("2025-05-01", periods=n)
    return pd.DataFrame({"open": open_, "high": high, "low": low,
                         "close": close, "volume": volume}, index=idx)

@pytest.fixture
def ohlcv_down(ohlcv_up):
    """상승 픽스처를 뒤집은 하락 추세."""
    df = ohlcv_up.copy()
    for col in ["open", "high", "low", "close"]:
        df[col] = df[col].values[::-1]
    df[["high", "low"]] = df[["low", "high"]].values  # 뒤집으면 high/low가 바뀜
    return df


# --- 테스트에서 회사 자료 소스는 기본적으로 막는다 -------------------------------
# `refresh_all`이 시세뿐 아니라 회사 자료(yfinance·네이버·다음·FDR)까지 갱신하므로,
# 막지 않으면 `pytest`가 네트워크에 붙어 버린다(느려지고, 야후가 죽는 날 같이 죽는다).
# 회사 자료를 검증하는 테스트는 필요한 함수만 골라 다시 monkeypatch한다.
_SOURCE_FUNCS = {
    "app.sources.yf": ["quote_info", "estimates", "financials", "news",
                       "upgrades_downgrades", "insider_transactions",
                       "dividend_history", "monthly_closes"],
    "app.sources.naver": ["integration", "finance", "news", "research",
                          "index_basic", "ranking", "investor_trend", "market_index"],
    "app.sources.daum": ["quote"],
    "app.sources.krx_desc": ["describe"],
    "app.sources.dart": ["elestock", "stock_total", "corp_code", "available"],
}


@pytest.fixture(autouse=True)
def no_network_sources(monkeypatch):
    import importlib

    def _blocked(name):
        def _raise(*a, **k):
            raise AssertionError(f"테스트에서 외부 호출 금지: {name}")
        return _raise

    for module_name, funcs in _SOURCE_FUNCS.items():
        mod = importlib.import_module(module_name)
        for fn in funcs:
            monkeypatch.setattr(mod, fn, _blocked(f"{module_name}.{fn}"), raising=False)
    # `available()`만 예외 — 키 유무 판정이라 호출돼도 네트워크를 타지 않는다.
    monkeypatch.setattr(importlib.import_module("app.sources.dart"),
                        "available", lambda: False)
    # 회사 자료 갱신의 종목 간 sleep은 테스트에서 의미가 없다(8종목이면 2.4초).
    monkeypatch.setattr(importlib.import_module("app.company"), "SYMBOL_SLEEP_SEC", 0)
