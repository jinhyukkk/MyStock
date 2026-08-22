"""회사 자료 수집·정규화·캐시 테스트.

전부 네트워크 없이 돈다 — `conftest.no_network_sources`가 `app.sources.*`를 막고,
여기서 필요한 함수만 고정 페이로드로 다시 붙인다. 실측(2026-08-21) 응답 모양을 그대로
본떴으므로, 소스 스키마가 바뀌면 이 픽스처를 실측으로 다시 맞춰야 한다.
"""

import json
from datetime import datetime, timedelta

import pytest

from app import company, db
from app.sources import daum as src_daum
from app.sources import dart as src_dart
from app.sources import krx_desc as src_krx
from app.sources import naver as src_naver
from app.sources import yf as src_yf

# --------------------------------------------------------------------------- 픽스처 데이터

# yfinance `000660.KS` 실측: trailingPE·priceToBook·trailingEps·bookValue가 전부 None
KR_YF_INFO = {
    "sector": "Technology", "industry": "Semiconductors", "country": "South Korea",
    "exchange": "KSC", "fullTimeEmployees": 47639, "website": "https://www.skhynix.com",
    "longBusinessSummary": "SK hynix Inc. provides semiconductor products worldwide.",
    "marketCap": 1227339115528192, "enterpriseValue": 1131238014320640,
    "netIncomeToCommon": 162084281122816, "totalRevenue": 189170676924416,
    "bookValue": None, "totalCash": 87958002597888, "sharesOutstanding": 709854891,
    "floatShares": 566260500, "dividendRate": 1500.0,
    "trailingAnnualDividendRate": None, "exDividendDate": 1787875200,
    "payoutRatio": None, "trailingPE": None, "forwardPE": 3.7769692,
    "trailingPegRatio": 0.2093, "priceToSalesTrailing12Months": 6.487999,
    "priceToBook": None, "enterpriseToEbitda": 7.884, "enterpriseToRevenue": 5.98,
    "quickRatio": 15.254, "currentRatio": 17.544, "debtToEquity": 7.075,
    "trailingEps": None, "forwardEps": None, "heldPercentInsiders": 0.20212,
    "heldPercentInstitutions": 0.39676, "returnOnAssets": 0.33661,
    "returnOnEquity": 0.9268, "grossMargins": 0.70197, "operatingMargins": 0.76328003,
    "profitMargins": 0.85682, "beta": 2.413, "recommendationMean": 1.33333,
    "targetMeanPrice": 3166022.2, "numberOfAnalystOpinions": 40, "dividendYield": 0.09,
}

# yfinance `AAPL` 실측 (2026-08-21)
US_YF_INFO = {
    "sector": "Technology", "industry": "Consumer Electronics",
    "country": "United States", "exchange": "NMS", "fullTimeEmployees": 150000,
    "website": "https://www.apple.com", "longBusinessSummary": "Apple Inc. " + "설명 " * 800,
    "firstTradeDateEpochUtc": None,
    "marketCap": 4543167856640, "enterpriseValue": 4565112979456,
    "netIncomeToCommon": 128929996800, "totalRevenue": 466822987776, "bookValue": 7.36,
    "totalCash": 62399000576, "sharesOutstanding": 14594180000, "floatShares": 14569223952,
    "dividendRate": 1.08, "trailingAnnualDividendRate": 1.05, "exDividendDate": 1786320000,
    "payoutRatio": 0.1204, "trailingPE": 36.366817, "forwardPE": 32.63342,
    "trailingPegRatio": 2.5547, "priceToSalesTrailing12Months": 9.7321,
    "priceToBook": 42.296192, "freeCashflow": 107721875456, "enterpriseToEbitda": 27.18,
    "enterpriseToRevenue": 9.779, "quickRatio": 0.812, "currentRatio": 1.003,
    "debtToEquity": 78.445, "trailingEps": 8.56, "forwardEps": 9.5393,
    "heldPercentInsiders": 0.01648, "heldPercentInstitutions": 0.66482,
    "returnOnAssets": 0.27082002, "returnOnEquity": 1.4875101, "grossMargins": 0.48653,
    "operatingMargins": 0.32623002, "profitMargins": 0.27618998,
    "sharesShort": 141606163, "shortRatio": 2.58, "shortPercentOfFloat": 0.0097,
    "beta": 1.086, "recommendationMean": 2.11111, "targetMeanPrice": 326.3415,
    "numberOfAnalystOpinions": 40, "dividendYield": 0.34,
}

NAVER_INTEGRATION = {
    "stockName": "SK하이닉스",
    "totalInfos": [
        {"code": "marketValue", "key": "시총", "value": "1,262조 2,908억"},
        {"code": "foreignRate", "key": "외인소진율", "value": "51.05%"},
        {"code": "per", "key": "PER", "value": "7.70배"},
        {"code": "eps", "key": "EPS", "value": "224,313원"},
        {"code": "cnsPer", "key": "추정PER", "value": "4.94배"},
        {"code": "cnsEps", "key": "추정EPS", "value": "349,566원"},
        {"code": "pbr", "key": "PBR", "value": "4.66배"},
        {"code": "bps", "key": "BPS", "value": "370,432원"},
        {"code": "dividendYieldRatio", "key": "배당수익률", "value": "0.17%"},
        {"code": "dividend", "key": "주당배당금", "value": "3,000원"},
    ],
    # 실측: recommMean 4.00 + 목표주가가 현재가의 약 2배 = '매수'. 네이버는 5=강력매수.
    "consensusInfo": {"itemCode": "000660", "createDate": "2026-08-20",
                      "recommMean": "4.00", "priceTargetMean": "3,317,917"},
    "researches": [{"researchId": 95791, "title": "40조원은 시작", "brokerName": "한화투자증권",
                    "writeDate": "2026-08-20"}],
}

NAVER_RESEARCH = [
    {"researchId": 95791, "title": "40조원은 시작", "brokerName": "한화투자증권",
     "writeDate": "2026-08-20"},
    {"researchId": 95786, "title": "자기주식 취득 및 소각 공시", "brokerName": "하나증권",
     "writeDate": "2026-08-20"},
    {"researchId": 95700, "title": "HBM 증설 효과", "brokerName": "미래에셋증권",
     "writeDate": "2026-08-19"},
    {"researchId": 95611, "title": "목표주가 상향", "brokerName": "NH투자증권",
     "writeDate": "2026-08-18"},
]

NAVER_NEWS = [
    # 네이버는 제목을 HTML 조각으로 준다 — 실응답에 `&quot;`가 리터럴로 섞여 온다
    {"total": 1, "items": [{"officeName": "파이낸셜뉴스", "datetime": "202608211512",
                            "title": "카카오 인적분할",
                            "titleFull": "[오후장] &quot;반도체 빼면 설명 안돼&quot; &amp; 삼전닉스",
                            "mobileNewsUrl": "https://n.news.naver.com/1"}]},
    {"total": 1, "items": [{"officeName": "매일경제", "datetime": "202608211507",
                            "title": "레버리지", "titleFull": "해외로 향한 개미들",
                            "mobileNewsUrl": "https://n.news.naver.com/2"}]},
    {"total": 1, "items": [{"officeName": "한국경제", "datetime": "202608201130",
                            "title": "HBM", "titleFull": "HBM 공급 확대",
                            "mobileNewsUrl": "https://n.news.naver.com/3"}]},
    {"total": 1, "items": [{"officeName": "연합뉴스", "datetime": "202608200900",
                            "title": "반도체", "titleFull": "반도체 수출 증가",
                            "mobileNewsUrl": "https://n.news.naver.com/4"}]},
    {"total": 1, "items": [{"officeName": "머니투데이", "datetime": "202608191700",
                            "title": "자사주", "titleFull": "자사주 소각 결정",
                            "mobileNewsUrl": "https://n.news.naver.com/5"}]},
]

DAUM_QUOTE = {
    "market": "KOSPI", "wicsSectorName": "반도체와반도체장비",
    "companySummary": "동사는 1949년 설립되어 2012년 에스케이하이닉스로 상호를 변경하였으며, "
                      "경기도 이천 본사를 거점으로 운영하는 글로벌 반도체 기업임. "
                      "DRAM과 NAND Flash 중심의 메모리 반도체가 주력 제품이며, "
                      "Foundry 사업도 병행하고 있음. 세계 메모리 시장에서 상위 점유율을 유지함.",
    "marketCap": 1262290806720000, "foreignRatio": 0.5104987757,
    "listedShareCount": 730492365, "listingDate": "1996-12-26",
    "eps": 62044.0, "bps": 171751.0, "dps": 3000.0, "per": 27.25, "pbr": 9.85,
}

KRX_DESC = {"sector": None, "industry": "반도체 제조업", "market": "KOSPI",
            "listing_date": "1996-12-26", "homepage": "http://www.skhynix.com",
            "representative": "곽노정"}


def _naver_finance(periods, rows):
    """네이버 `finance/{annual|quarter}` 응답 모양으로 조립."""
    return {"itemCode": "000660", "financeInfo": {
        "trTitleList": [{"key": k, "title": k, "isConsensus": "Y" if est else "N"}
                        for k, est in periods],
        "rowList": [{"title": title,
                     "columns": {k: {"value": vals.get(k, "-")} for k, _ in periods}}
                    for title, vals in rows.items()]}}


NAVER_ANNUAL = _naver_finance(
    [("202312", False), ("202412", False), ("202512", False), ("202612", True)],
    {"매출액": {"202312": "327,657", "202412": "661,930", "202512": "971,467",
              "202612": "3,458,039"},
     "당기순이익": {"202312": "-91,375", "202412": "197,969", "202512": "429,479"},
     "영업이익률": {"202312": "-23.59", "202412": "35.45", "202512": "48.59"},
     "순이익률": {"202312": "-27.89", "202412": "29.91", "202512": "44.21"},
     "ROE": {"202312": "-15.61", "202412": "31.06", "202512": "44.15"},
     "부채비율": {"202312": "87.52", "202412": "62.15", "202512": "45.95"},
     "당좌비율": {"202312": "75.97", "202412": "113.24", "202512": "132.97"},
     "EPS": {"202312": "-12,517", "202412": "27,182", "202512": "58,955",
             "202612": "349,566"},
     "주당배당금": {"202312": "1,200", "202412": "2,204", "202512": "3,000",
                "202612": "9,794"}})

NAVER_QUARTER = _naver_finance(
    [("202506", False), ("202509", False), ("202512", False), ("202603", False),
     ("202606", False), ("202609", True)],
    {"매출액": {"202506": "200,000", "202509": "240,000", "202512": "280,000",
              "202603": "320,000", "202606": "360,000", "202609": "400,000"},
     "당기순이익": {"202506": "80,000", "202509": "96,000", "202512": "112,000",
                "202603": "128,000", "202606": "144,000"},
     "EPS": {"202506": "10,000", "202509": "15,000", "202512": "20,000",
             "202603": "25,000", "202606": "30,000", "202609": "35,000"}})

US_FINANCIALS = {
    "annual": [
        {"end_date": "2021-09-30", "eps": 5.61, "sales": 365817000000,
         "shares": 16864919000, "operating_income": 108949000000,
         "pretax_income": 109207000000, "tax_provision": 14527000000},
        {"end_date": "2022-09-30", "eps": 6.11, "sales": 394328000000,
         "shares": 16325819000},
        {"end_date": "2023-09-30", "eps": 6.13, "sales": 383285000000,
         "shares": 15812547000},
        {"end_date": "2024-09-30", "eps": 6.08, "sales": 391035000000,
         "shares": 15408095000},
        {"end_date": "2025-09-30", "eps": 8.56, "sales": 416161000000,
         "shares": 14994082000, "operating_income": 127364000000,
         "pretax_income": 148000000000, "tax_provision": 29600000000},
    ],
    "quarterly": [
        {"end_date": "2025-06-30", "eps": 1.57, "sales": 94036000000, "shares": 15000000000},
        {"end_date": "2025-09-30", "eps": 1.85, "sales": 102466000000, "shares": 14980000000},
        {"end_date": "2025-12-31", "eps": 2.84, "sales": 140000000000, "shares": 14900000000},
        {"end_date": "2026-03-31", "eps": 2.01, "sales": 98000000000, "shares": 14850000000},
        {"end_date": "2026-06-30", "eps": 2.02, "sales": 96000000000, "shares": 14800000000},
    ],
    "balance": {"long_term_debt": 78000000000, "equity": 60000000000,
                "invested_capital": 200000000000},
}

US_ESTIMATES = {"eps_trend": {"0q": 1.97656, "+1q": 2.91256, "0y": 8.80532, "+1y": 9.53224},
                "growth": {"0q": 0.0703, "0y": 0.1819, "+1y": 0.0819, "LTG": 0.122},
                "earnings": [{"date": "2026-10-29", "eps_estimate": 1.98,
                              "eps_reported": None, "surprise_pct": None},
                             {"date": "2026-07-30", "eps_estimate": 1.89,
                              "eps_reported": 2.02, "surprise_pct": 6.74}]}

US_NEWS = [{"title": f"Apple story {i}", "url": f"https://finance.yahoo.com/{i}",
            "published_at": f"2026-08-2{i}T19:43:18Z", "source": "Yahoo Finance"}
           for i in range(1, 7)]

US_UPGRADES = [{"date": f"2026-08-1{i}", "firm": f"Firm {i}", "action": "up",
                "from_grade": "Hold", "to_grade": "Buy", "from_target": 0.0,
                "to_target": 300.0 + i} for i in range(1, 7)]

US_INSIDERS = [{"name": f"INSIDER {i}", "relation": "Officer",
                "date": (datetime.now() - timedelta(days=10 * i)).date().isoformat(),
                "transaction": "", "text": "Sale at price 307.75 per share.",
                "shares": 1000 * i, "value": 307750.0 * i, "url": ""}
               for i in range(1, 7)]


@pytest.fixture
def conn(tmp_path, ohlcv_up):
    c = db.get_conn(str(tmp_path / "t.db"))
    db.upsert_ticker(c, "000660", "KR", "SK하이닉스", in_watchlist=1,
                     yf_symbol="000660.KS")
    db.upsert_ticker(c, "AAPL", "US", "Apple", in_watchlist=1, yf_symbol="AAPL",
                     currency="USD")
    db.save_prices(c, "000660", ohlcv_up)
    db.save_prices(c, "AAPL", ohlcv_up)
    yield c
    c.close()


@pytest.fixture
def kr_sources(monkeypatch):
    monkeypatch.setattr(src_yf, "quote_info",
                        lambda s: {"info": dict(KR_YF_INFO), "first_trade_date": None,
                                   "calendar": {"Earnings Date": ["2026-10-27"]}})
    monkeypatch.setattr(src_yf, "estimates", lambda s: {"eps_trend": {}, "growth": {},
                                                        "earnings": []})
    monkeypatch.setattr(src_yf, "financials",
                        lambda s: {"annual": [], "quarterly": [], "balance": {}})
    monkeypatch.setattr(src_yf, "dividend_history", lambda s: [])
    monkeypatch.setattr(src_yf, "monthly_closes", lambda s, **k: [])
    monkeypatch.setattr(src_naver, "integration", lambda c: dict(NAVER_INTEGRATION))
    monkeypatch.setattr(src_naver, "finance",
                        lambda c, p="annual": NAVER_ANNUAL if p == "annual" else NAVER_QUARTER)
    monkeypatch.setattr(src_naver, "news", lambda c, n=20: list(NAVER_NEWS))
    monkeypatch.setattr(src_naver, "research", lambda c, n=20: list(NAVER_RESEARCH))
    monkeypatch.setattr(src_daum, "quote", lambda c: dict(DAUM_QUOTE))
    monkeypatch.setattr(src_krx, "describe", lambda c: dict(KRX_DESC))
    monkeypatch.setattr(src_dart, "available", lambda: False)


@pytest.fixture
def us_sources(monkeypatch):
    monkeypatch.setattr(src_yf, "quote_info",
                        lambda s: {"info": dict(US_YF_INFO),
                                   "first_trade_date": "1980-12-12",
                                   "calendar": {"Earnings Date": ["2026-10-30"]}})
    monkeypatch.setattr(src_yf, "estimates", lambda s: json.loads(json.dumps(US_ESTIMATES)))
    monkeypatch.setattr(src_yf, "financials",
                        lambda s: json.loads(json.dumps(US_FINANCIALS)))
    monkeypatch.setattr(src_yf, "dividend_history",
                        lambda s: [{"date": f"{y}-{m:02d}-10", "amount": 0.20 + 0.02 * (y - 2019)}
                                   for y in range(2019, 2026) for m in (2, 5, 8, 11)])
    monkeypatch.setattr(src_yf, "monthly_closes",
                        lambda s, **k: [{"date": "2015-08-01", "close": 25.0},
                                        {"date": "2026-08-01", "close": 311.3}])
    monkeypatch.setattr(src_yf, "news", lambda s, limit=10: list(US_NEWS))
    monkeypatch.setattr(src_yf, "upgrades_downgrades",
                        lambda s, limit=20: json.loads(json.dumps(US_UPGRADES)))
    monkeypatch.setattr(src_yf, "insider_transactions",
                        lambda s, limit=30: json.loads(json.dumps(US_INSIDERS)))


# --------------------------------------------------------------------------- AC-12 정규화

def test_ratio_to_percent():
    """0~1 비율로 오는 수익성 지표는 퍼센트 숫자로 나가야 한다."""
    assert company.to_pct(0.9268) == 92.68
    assert company.to_pct(0.27618998) == 27.62
    assert company.to_pct(None) is None


def test_debt_to_equity_divided_by_100():
    """yfinance·네이버 부채비율은 %다. 안 나누면 화면이 0.78배를 78배로 말한다."""
    assert company.pct_to_ratio(78.445, 2) == 0.78
    assert company.pct_to_ratio(45.95, 2) == 0.46
    assert company.pct_to_ratio(None) is None


def test_dividend_yield_scale_guard():
    """0.34(=0.34%)와 0.0034(=비율)를 배당금/주가 기대값으로 갈라낸다."""
    assert company.dividend_yield_pct(0.34, rate=1.08, price=311.3) == 0.34
    assert company.dividend_yield_pct(0.00347, rate=1.08, price=311.3) == 0.35
    # 기대값을 못 만들면 값을 그대로 퍼센트로 본다(100배 부풀리는 쪽으로 틀리지 않는다)
    assert company.dividend_yield_pct(0.17) == 0.17
    assert company.dividend_yield_pct(None) is None


def test_naver_recomm_normalized():
    """네이버 recommMean은 5=강력매수. 뒤집지 않으면 매수를 매도로 표시한다."""
    assert company.naver_recomm_to_scale("4.00") == 2.0
    assert company.naver_recomm_to_scale(5.0) == 1.0
    assert company.naver_recomm_to_scale(1.0) == 5.0
    assert company.recommendation_label(company.naver_recomm_to_scale("4.00")) == "매수"
    assert company.recommendation_label(1.2) == "강력매수"
    assert company.recommendation_label(4.8) == "강력매도"
    assert company.naver_recomm_to_scale(None) is None


def test_parse_kr_number():
    assert company.parse_kr_number("7.70배") == 7.7
    assert company.parse_kr_number("224,313원") == 224313
    assert company.parse_kr_number("0.17%") == 0.17
    assert company.parse_kr_number("1,262조 2,908억") == 1_262_290_800_000_000
    assert company.parse_kr_number("-") is None
    assert company.parse_kr_number("-12,517") == -12517


def test_cagr_refuses_sign_flip():
    """적자에서 흑자로 돌아선 구간에 CAGR을 찍으면 그건 성장률이 아니라 거짓말이다."""
    assert company._cagr_pct(-12517, 58955, 3) is None
    assert company._cagr_pct(327657, 971467, 3) == 43.66


def test_kr_per_pbr_falls_back_to_naver(conn, kr_sources):
    """yfinance가 KR에서 None으로 주는 PER/PBR/EPS/BPS를 네이버가 메운다."""
    t = dict(db.get_ticker(conn, "000660"))
    assert company.refresh_symbol(conn, t, force=True) == []
    snap = company.get_snapshot(conn, "000660")
    assert KR_YF_INFO["trailingPE"] is None and KR_YF_INFO["priceToBook"] is None
    assert snap["pe"] == 7.7
    assert snap["pb"] == 4.66
    assert snap["eps_ttm"] == 224313
    assert snap["book_per_share"] == 370432
    assert snap["forward_pe"] == 4.94
    # 네이버 재무비율(%) → 배수. yfinance 값(quickRatio 15.254, debtToEquity 7.075)이
    # 있어도 국내 라벨과 정의가 맞는 네이버 쪽으로 덮는다.
    assert snap["quick_ratio"] == 1.3297
    assert snap["debt_eq"] == 0.4595
    # 컨센서스는 1=강력매수로 뒤집힌 값
    assert snap["recommendation_mean"] == 2.0
    assert snap["recommendation_scale"] == "1=strong_buy..5=strong_sell"
    assert snap["target_price"] == 3317917


# --------------------------------------------------------------------------- 블록 조립

def test_kr_snapshot_fills_required_cells(conn, kr_sources):
    company.refresh_symbol(conn, dict(db.get_ticker(conn, "000660")), force=True)
    snap = company.get_snapshot(conn, "000660")
    for key in ["market_cap", "pe", "pb", "eps_ttm", "book_per_share",
                "dividend_yield_pct", "roe_pct", "oper_margin_pct",
                "shares_outstanding", "beta", "target_price", "recommendation_mean"]:
        assert snap[key] is not None, key
    # 공매도 3칸은 pykrx(로그인 필요)만 주는 값 — 국내는 비어 있어야 한다
    assert snap["short_float_pct"] is None
    assert snap["short_ratio"] is None
    assert snap["short_interest"] is None
    assert snap["market_cap"] == 1_262_290_800_000_000
    assert snap["foreign_own_pct"] == 51.05
    assert snap["dividend_yield_pct"] == 0.17
    assert snap["roe_pct"] == 92.68  # yfinance 우선
    assert snap["dividend_est"] == 9794  # 네이버 연간 컨센서스 DPS
    # 네이버 연간은 실적 3개(=2년 구간)뿐이라 3년 성장률을 만들 수 없다.
    # 2년치를 3년 성장률로 내보내면 화면이 없는 성장을 말한다.
    assert snap["sales_past_3y_pct"] is None
    assert snap["eps_past_3y_pct"] is None
    assert set(snap["perf"]) == set(company.PERF_KEYS)
    assert snap["status"] == "ok"
    assert "naver" in snap["sources"]


def test_us_snapshot_normalizes_units(conn, us_sources):
    company.refresh_symbol(conn, dict(db.get_ticker(conn, "AAPL")), force=True)
    snap = company.get_snapshot(conn, "AAPL")
    assert snap["debt_eq"] == 0.7844        # 78.445% → 0.7844배 (US·KR 같은 단위)
    assert snap["quick_ratio"] == 0.812
    assert snap["roe_pct"] == 148.75        # 1.4875 → %
    assert snap["profit_margin_pct"] == 27.62
    assert snap["insider_own_pct"] == 1.65
    assert snap["short_float_pct"] == 0.97
    assert snap["dividend_yield_pct"] == 0.34
    assert snap["cash_per_share"] == round(62399000576 / 14594180000, 4)
    assert snap["float_pct"] == 99.83
    assert snap["eps_this_y_pct"] == 18.19
    assert snap["eps_next_5y_pct"] == 12.2
    assert snap["eps_qoq_pct"] == 0.5       # 2.01 → 2.02
    assert snap["eps_surprise_pct"] == 6.74
    assert snap["earnings_date"] == "2026-10-30"
    assert snap["lt_debt_eq"] == 1.3
    assert snap["roic_pct"] is not None
    assert snap["perf"]["y10"] is not None   # 월봉 10년
    assert snap["recommendation_mean"] == 2.11


def test_perf_10y_tolerates_first_monthly_bar(conn):
    """yfinance `period=10y` 월봉의 첫 봉은 정확히 10년 전이 아니라 그 직후 달이다.
    엄격히 자르면 10Y 칸이 영원히 빈다."""
    df = db.load_prices(conn, "AAPL", limit=1)
    last = df.index[-1].date()
    just_after = (last - timedelta(days=3640)).isoformat()
    perf = company.compute_perf(conn, "AAPL",
                                [{"date": just_after, "close": 50.0}])
    assert perf["y10"] is not None
    # 그렇다고 5년치를 10년 성과로 부르지는 않는다
    too_recent = (last - timedelta(days=1800)).isoformat()
    assert company.compute_perf(conn, "AAPL",
                                [{"date": too_recent, "close": 50.0}])["y10"] is None


def test_perf_keys_always_present_and_bounded(conn):
    """가격이 200일치뿐이면 1년·3년 성과는 값이 아니라 null이어야 한다 —
    짧은 구간을 긴 성과로 내보내면 사용자가 없는 수익률을 믿는다."""
    perf = company.compute_perf(conn, "AAPL")
    assert set(perf) == set(company.PERF_KEYS)
    assert perf["m1"] is not None
    assert perf["y3"] is None and perf["y5"] is None and perf["y10"] is None


def test_kr_profile_is_korean(conn, kr_sources):
    company.refresh_symbol(conn, dict(db.get_ticker(conn, "000660")), force=True)
    prof = company.get_profile(conn, "000660")
    assert prof["description_lang"] == "ko"
    assert len(prof["description"]) >= 100
    assert prof["sector"] == "반도체와반도체장비"
    assert prof["industry"] == "반도체 제조업"
    assert prof["country"] == "South Korea"
    assert prof["exchange"] == "KOSPI"
    assert prof["employees"] == 47639
    assert prof["ipo_date"] == "1996-12-26"
    assert prof["fetched_at"]


def test_kr_debt_eq_is_ratio_not_percent(conn, kr_sources):
    """B3 — 네이버가 %(45.95)로 주는 부채비율·당좌비율은 배수로 나가야 한다.

    US(0.7845)와 KR(0.4595)이 같은 이름·다른 단위로 나가면, 화면은 국내 종목만
    부채비율을 100배로 말한다. 이 프로젝트에서 실제로 화면을 깨뜨려 온 버그 유형이다.
    """
    assert company.pct_to_ratio(45.95, 4) == 0.4595
    assert company.pct_to_ratio(132.97, 4) == 1.3297
    company.refresh_symbol(conn, dict(db.get_ticker(conn, "000660")), force=True)
    kr = company.get_snapshot(conn, "000660")
    assert kr["debt_eq"] == 0.4595
    assert kr["quick_ratio"] == 1.3297
    # 배수 칸은 어느 시장이든 1 근처의 작은 수여야 한다 — 퍼센트가 새어 들어오면 여기서 걸린다
    for key in ("debt_eq", "quick_ratio"):
        assert 0 < kr[key] < 20, (key, kr[key])


def test_profile_status_ok_when_cached(conn, kr_sources):
    """B1 — 캐시가 있으면 status는 ok이고 note는 null이다."""
    company.refresh_symbol(conn, dict(db.get_ticker(conn, "000660")), force=True)
    prof = company.get_profile(conn, "000660")
    assert prof["status"] == "ok"
    assert prof["note"] is None
    assert prof["source"] and prof["fetched_at"]


def test_dividend_yield_stays_in_plausible_range(conn, kr_sources, us_sources):
    """B4 — 배당수익률은 퍼센트 숫자다. 스케일을 놓치면 0.17%가 17%로 보인다.
    (현실의 배당수익률이 30%를 넘는 상장사는 사실상 없다 — 넘으면 단위 사고다)"""
    for scale_broken in (0.0017, 0.17):
        assert 0 <= company.dividend_yield_pct(
            scale_broken, rate=3000, price=1_691_000) <= 30
    for symbol in ("000660", "AAPL"):
        company.refresh_symbol(conn, dict(db.get_ticker(conn, symbol)), force=True)
        dy = company.get_snapshot(conn, symbol)["dividend_yield_pct"]
        assert dy is not None and 0 <= dy <= 30, (symbol, dy)


def test_perf_y5_uses_monthly_cache(conn):
    """B2 — `price_cache`는 4.8년뿐이라 y5를 못 만든다. 10Y용으로 이미 받아둔 월봉으로
    추가 호출 없이 채운다. y3·y10은 있는데 y5만 비는 화면을 없앤다."""
    last = db.load_prices(conn, "AAPL", limit=1).index[-1].date()
    monthly = [{"date": (last - timedelta(days=30 * i)).replace(day=1).isoformat(),
                "close": 100.0} for i in range(130, -1, -1)]
    perf = company.compute_perf(conn, "AAPL", monthly)
    assert perf["y5"] is not None
    assert perf["y10"] is not None
    # 월봉이 5년을 못 덮는 신규 상장 종목은 그대로 null
    short = [{"date": (last - timedelta(days=30 * i)).replace(day=1).isoformat(),
              "close": 100.0} for i in range(20, -1, -1)]
    assert company.compute_perf(conn, "AAPL", short)["y5"] is None


def test_us_profile_truncates_description(conn, us_sources):
    company.refresh_symbol(conn, dict(db.get_ticker(conn, "AAPL")), force=True)
    prof = company.get_profile(conn, "AAPL")
    assert len(prof["description"]) == company.MAX_DESCRIPTION
    assert prof["description_truncated"] is True
    assert prof["description_lang"] == "en"
    assert prof["exchange"] == "NASDAQ"   # NMS 코드를 그대로 보여주지 않는다
    assert prof["ipo_date"] == "1980-12-12"


def test_news_title_html_entities_unescaped(conn, kr_sources):
    """D6 — 네이버 뉴스 제목의 `&quot;`가 화면에 리터럴로 찍히면 안 된다.

    프론트는 React라 문자열을 이스케이프해서 렌더한다 — BE가 풀지 않으면
    사용자가 기사 제목 대신 HTML 조각을 읽는다.
    """
    assert company.unescape_text("&quot;A&quot;") == '"A"'
    assert company.unescape_text("B &amp; C &#39;D&#39;") == "B & C 'D'"
    assert company.unescape_text(None) is None

    company.refresh_symbol(conn, dict(db.get_ticker(conn, "000660")), force=True)
    out = company.get_company(conn, "000660")
    titles = [i["title"] for i in out["news"]["items"]]
    assert titles[0] == '[오후장] "반도체 빼면 설명 안돼" & 삼전닉스'
    for text in titles + [r["title"] for r in out["ratings"]["reports"]]:
        assert "&quot;" not in text and "&amp;" not in text and "&#39;" not in text


def test_kr_company_blocks(conn, kr_sources):
    company.refresh_symbol(conn, dict(db.get_ticker(conn, "000660")), force=True)
    out = company.get_company(conn, "000660")
    assert out["symbol"] == "000660"

    news = out["news"]
    assert news["status"] == "ok" and len(news["items"]) >= 5
    assert all(i["lang"] == "ko" for i in news["items"])
    assert news["items"][0]["published_at"] == "2026-08-21T15:12:00"

    fin = out["financials"]
    assert len(fin["annual"]) >= 3
    assert fin["annual"][0]["period"] == "2023"
    # 네이버는 결산 '월'만 준다 — 말일로 맞추지 않으면 12월 결산이 12월 1일로 읽힌다
    assert fin["annual"][0]["end_date"] == "2023-12-31"
    assert fin["quarterly"][0]["end_date"] == "2025-06-30"
    assert fin["annual"][-1]["estimate"] is True       # 컨센서스 칸은 표시가 남아야 한다
    assert fin["annual"][2]["sales"] == 971467 * 10 ** 8   # 억원 → 원
    assert fin["quarterly"][0]["period"] == "2025Q2"
    assert fin["annual"][0]["shares_outstanding"] is None
    assert fin["shares_note"] == company.NOTE_KR_SHARES

    ratings = out["ratings"]
    assert ratings["status"] == "ok"
    assert ratings["changes"] == []
    assert ratings["note"]
    assert len(ratings["reports"]) >= 3
    assert ratings["consensus"]["recommendation_mean"] == 2.0
    assert ratings["consensus"]["recommendation_label"] == "매수"
    assert ratings["consensus"]["target_upside_pct"] is not None
    assert ratings["consensus"]["as_of"] == "2026-08-20"

    ins = out["insiders"]
    assert ins["status"] == "unavailable"
    assert ins["note"] == company.NOTE_KR_INSIDERS
    assert ins["items"] == []


def test_us_company_blocks(conn, us_sources):
    company.refresh_symbol(conn, dict(db.get_ticker(conn, "AAPL")), force=True)
    out = company.get_company(conn, "AAPL")
    assert len(out["news"]["items"]) >= 5
    assert all(i["lang"] == "en" for i in out["news"]["items"])
    assert len(out["ratings"]["changes"]) >= 5
    # 야후는 '이전 목표가 없음'을 0.0으로 준다 — 0달러 목표가는 사실이 아니다
    assert out["ratings"]["changes"][0]["from_target"] is None
    # 야후 축약 코드(up/down/main/reit)를 계약 표기로 옮긴다 — 'reit'은 화면에서 못 읽는다
    assert out["ratings"]["changes"][0]["action"] == "Upgrade"
    assert out["ratings"]["reports"] == []
    assert len(out["insiders"]["items"]) >= 5
    assert out["insiders"]["items"][0]["price"] == 307.75
    assert len(out["financials"]["annual"]) >= 4
    assert len(out["financials"]["quarterly"]) >= 4
    assert out["financials"]["annual"][-1]["shares_outstanding"] == 14994082000


def test_company_pending_when_no_cache(conn):
    """캐시가 비어도 200 + pending. 여기서 404를 주면 화면이 '없는 종목'과 헷갈린다."""
    out = company.get_company(conn, "AAPL")
    for block in ("financials", "news", "ratings", "insiders"):
        assert out[block]["status"] == "pending"
        assert out[block]["note"] == company.NOTE_PENDING
        assert out[block]["fetched_at"] is None
    assert out["news"]["items"] == []
    assert out["ratings"]["changes"] == [] and out["ratings"]["consensus"] is None
    prof = company.get_profile(conn, "AAPL")
    assert prof["status"] == "pending"
    assert prof["note"] == company.NOTE_PENDING
    assert all(prof[k] is None for k in company.PROFILE_KEYS
               if k != "description_truncated")
    snap = company.get_snapshot(conn, "AAPL")
    assert snap["status"] == "pending"
    assert set(snap["perf"]) == set(company.PERF_KEYS)
    assert all(snap[k] is None for k in company.SNAPSHOT_KEYS)


# --------------------------------------------------------------------------- AC-14 캐시 보존

def test_cache_kept_on_failure(conn, kr_sources, monkeypatch):
    t = dict(db.get_ticker(conn, "000660"))
    company.refresh_symbol(conn, t, force=True)
    before = company.read_block(conn, "000660", "snapshot")
    assert before["error"] is None

    def _boom(*a, **k):
        raise RuntimeError("naver 502")

    for name in ("integration", "finance", "news", "research"):
        monkeypatch.setattr(src_naver, name, _boom)
    monkeypatch.setattr(src_daum, "quote", _boom)
    monkeypatch.setattr(src_yf, "quote_info", _boom)
    monkeypatch.setattr(src_krx, "describe", _boom)

    failed = company.refresh_symbol(conn, t, force=True)
    assert "snapshot" in failed
    after = company.read_block(conn, "000660", "snapshot")
    assert after["payload"] == before["payload"]      # 값은 그대로
    assert after["fetched_at"] == before["fetched_at"]  # 성공 시각도 그대로
    assert after["error"] and "실패" in after["error"]
    assert after["attempted_at"] >= before["attempted_at"]
    # 화면은 낡은 값을 계속 보여준다 — 지우면 '원래 없는 종목'과 구분이 안 된다
    assert company.get_snapshot(conn, "000660")["pe"] == 7.7


def test_failed_block_backs_off_for_30min(conn, monkeypatch):
    """죽은 비공식 API를 매 루프 다시 때리면 차단이 길어진다."""
    company.save_failure(conn, "AAPL", "news", "boom")
    assert company.block_due(conn, "AAPL", "news") is False
    later = datetime.now() + timedelta(seconds=company.FAIL_BACKOFF_SEC + 60)
    assert company.block_due(conn, "AAPL", "news", now=later) is True


# --------------------------------------------------------------------------- AC-15 TTL·상한

def test_refresh_respects_ttl_and_cap(conn, monkeypatch):
    for i in range(12):
        db.upsert_ticker(conn, f"T{i:02d}", "US", f"Test {i}", in_watchlist=1,
                         yf_symbol=f"T{i:02d}")
    # 이미 방금 받아둔 종목은 TTL 안이라 다시 부르면 안 된다
    for block in company.BLOCKS:
        company.save_success(conn, "T00", block, {"status": "ok"}, "yfinance")

    called = []
    monkeypatch.setattr(company, "refresh_symbol",
                        lambda conn, t, force=False, now=None: called.append(t["symbol"]) or [])
    tickers = [dict(r) for r in db.list_tickers(conn)]
    company.refresh_company_blocks(conn, tickers)
    assert len(called) == company.COMPANY_MAX_SYMBOLS_PER_RUN == 8
    assert "T00" not in called


def test_refresh_prefers_holdings_then_watchlist(conn):
    db.upsert_ticker(conn, "OTHER", "US", "Other", in_watchlist=0, yf_symbol="OTHER")
    db.upsert_ticker(conn, "HELD", "US", "Held", in_watchlist=0, yf_symbol="HELD")
    tickers = [dict(r) for r in db.list_tickers(conn)]
    picked = [t["symbol"] for t in
              company.select_symbols(conn, tickers, held={"HELD"}, limit=2)]
    assert picked[0] == "HELD"
    assert "OTHER" not in picked  # 보유·관심이 먼저다


def test_crypto_is_skipped(conn):
    db.upsert_ticker(conn, "KRW-BTC", "CRYPTO", "비트코인", in_watchlist=1)
    tickers = [dict(r) for r in db.list_tickers(conn)]
    assert "KRW-BTC" not in [t["symbol"] for t in company.select_symbols(conn, tickers)]
