"""FDR `KRX-DESC` 상장기업 개요 — 업종·상장일·홈페이지.

KRX Data Marketplace 로그인이 필요한 pykrx와 달리 이 목록은 키 없이 받아진다(실측 2026-08-21).
전체 목록을 한 번 받아 프로세스 캐시에 둔다 — 종목마다 받으면 8종목 갱신에 8번 내려받는다.
"""

from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=1)
def _listing():
    import FinanceDataReader as fdr
    return fdr.StockListing("KRX-DESC")


def describe(code: str) -> dict:
    """{sector, industry, market, listing_date, homepage, representative} — 없으면 빈 dict."""
    df = _listing()
    hit = df[df["Code"] == code]
    if hit.empty:
        return {}
    row = hit.iloc[0]

    def _s(key):
        v = row.get(key)
        if v is None:
            return None
        s = str(v).strip()
        return s if s and s.lower() != "nan" else None

    listing = row.get("ListingDate")
    try:
        listing = listing.date().isoformat()
    except AttributeError:
        listing = _s("ListingDate")
    return {"sector": _s("Sector"), "industry": _s("Industry"),
            "market": _s("Market"),
            "listing_date": listing, "homepage": _s("HomePage"),
            "representative": _s("Representative")}
