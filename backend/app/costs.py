"""체결 비용 — 수수료·세금 요율.

원장의 실현손익이 gross면 "내 매매가 비용을 이기는가"에 답할 수 없다.
사용자가 실제 비용을 입력하지 않은 행(과거 데이터 포함)은 여기 요율로 추정하고,
추정분은 `cost_estimated` 플래그로 표시해 실측과 구분한다.

요율은 국내 증권사 온라인 기준 근사이며 계좌마다 다르다 — 정확한 복기를 원하면
매매 입력에서 실제 수수료·세금을 직접 넣으면 추정값 대신 그 값이 쓰인다.
"""

# 편도 위탁수수료율
FEE_RATES = {"KR": 0.00015, "US": 0.0007, "CRYPTO": 0.0005}
# 매도 시에만 붙는 세금·부과금 (KR 증권거래세, US SEC fee)
SELL_TAX_RATES = {"KR": 0.0015, "US": 0.0000278, "CRYPTO": 0.0}
_FALLBACK_FEE = 0.0007
_FALLBACK_TAX = 0.0015


def fee_rate(market: str) -> float:
    return FEE_RATES.get(market, _FALLBACK_FEE)


def sell_tax_rate(market: str, is_etf: int = 0) -> float:
    if market == "KR" and is_etf:
        return 0.0  # 국내 상장 ETF는 증권거래세 면제
    return SELL_TAX_RATES.get(market, _FALLBACK_TAX)


def estimate(market: str, side: str, notional: float, is_etf: int = 0) -> dict:
    """체결 금액(수량×단가, 종목 통화 기준)에 대한 수수료·세금 추정."""
    notional = abs(notional)
    fee = round(notional * fee_rate(market), 6)
    tax = round(notional * sell_tax_rate(market, is_etf), 6) if side == "SELL" else 0.0
    return {"fee": fee, "tax": tax}


def roundtrip_pct(market: str, is_etf: int = 0) -> float:
    """왕복 수수료·세금(%p) — 스프레드는 뺀 값."""
    return round((fee_rate(market) * 2 + sell_tax_rate(market, is_etf)) * 100, 4)


# 일평균 거래대금(원) 구간별 왕복 스프레드·시장충격 근사(%p).
# 유동성이 낮을수록 호가 간격이 벌어져 체결가가 밀린다. 정밀한 값이 아니라
# "소형주에 0.3%p 단일 상수를 쓰면 부족하다"를 반영하기 위한 계단식 근사다.
SPREAD_TIERS = ((100e8, 0.05), (10e8, 0.15), (1e8, 0.35), (0.0, 0.60))
_DEFAULT_SPREAD = 0.15


def spread_pct(avg_turnover_krw: float | None) -> float:
    """왕복 스프레드 추정(%p). 거래대금을 모르면 중간 구간으로 가정."""
    if not avg_turnover_krw or avg_turnover_krw <= 0:
        return _DEFAULT_SPREAD
    for floor, pct in SPREAD_TIERS:
        if avg_turnover_krw >= floor:
            return pct
    return _DEFAULT_SPREAD


def backtest_cost_pct(market: str, is_etf: int = 0,
                      avg_turnover_krw: float | None = None) -> float:
    """백테스트 순수익률에서 뺄 왕복 비용(%p) = 수수료·세금 + 스프레드.

    시장 무관 단일 0.3%p는 두 방향으로 틀렸다 — 업비트 왕복은 그보다 훨씬 싸서
    코인 신호의 순수익이 과소 표기되고, 유동성 낮은 국내 소형주는 증권거래세에
    호가 스프레드까지 얹혀 0.3%p로는 크게 모자란다.
    """
    return round(roundtrip_pct(market, is_etf) + spread_pct(avg_turnover_krw), 4)
