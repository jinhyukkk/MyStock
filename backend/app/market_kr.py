"""한국 시장 상수와 블록 빌더.

가격은 네이버(비공식 모바일 API), 캔들은 yfinance 로 받는다. 네이버에 5분봉이 없고
yfinance 에 국내 국채·투자자 수급이 없어 한쪽으로 통일할 수 없다.

빌더는 예외를 그대로 올린다 — 격리는 `market.py` 몫이다. 예외는 지수 블록으로,
네이버가 죽으면 캔들에서 값을 만들어 블록을 살린다(지수는 화면 최상단이라 빈 칸이 크다).
"""
from __future__ import annotations

import re

from app import market_fetch as fetch
from app.market import _chg, _pct
from app.sources import naver

SESSION = {"tz": "Asia/Seoul", "open": "09:00", "close": "15:30"}

# 미국판과 같은 기준: 장중 지수는 짧게, 구성종목 목록은 길게.
TTL_SEC = {
    "indices": 5 * 60,
    "forex_bonds": 5 * 60,
    "signals_up": 10 * 60,
    "signals_down": 10 * 60,
    "heatmap": 15 * 60,
    "investors": 30 * 60,   # 장 마감 후 하루 한 번 바뀐다
    "headlines": 15 * 60,
}

# (표시명, yfinance 심볼(5분봉), 네이버 코드(가격))
INDICES = [("코스피", "^KS11", "KOSPI"), ("코스닥", "^KQ11", "KOSDAQ"),
           ("코스피 200", "^KS200", "KPI200")]

# (표시명, 소스, 코드, 소수 자릿수). 소스 "yf" 는 market_fetch.daily_closes.
FOREX_BONDS = [("USD/KRW", "exchange", "FX_USDKRW", 2),
               ("JPY(100)/KRW", "exchange", "FX_JPYKRW", 2),
               ("국채 3년", "bond", "KR3YT=RR", 3),
               ("국채 10년", "bond", "KR10YT=RR", 3),
               ("미국채 10년", "yf", "^TNX", 3)]

# (naver ranking kind, 시장, 라벨, 개수)
SIGNALS_UP = [("up", "KOSPI", "상승 상위", 6), ("up", "KOSDAQ", "코스닥 상승", 5),
              ("searchTop", "KOSPI", "검색 상위", 4), ("marketValue", "KOSPI", "시총 상위", 4)]
SIGNALS_DOWN = [("down", "KOSPI", "하락 상위", 6), ("down", "KOSDAQ", "코스닥 하락", 5),
                ("searchTop", "KOSDAQ", "코스닥 검색", 4),
                ("marketValue", "KOSDAQ", "코스닥 시총", 4)]

HEATMAP_MARKET = "KOSPI"
HEATMAP_COUNT = 100          # 네이버 pageSize 상한. 걸러내면 87 종목쯤 남는다(실측 2026-08-22)
INVESTOR_MARKETS = ["KOSPI", "KOSDAQ"]
HEADLINES_SYMBOL = "^KS11"
HEADLINES_COUNT = 8
SECTOR_FALLBACK = "기타"

# 우선주 이름 규칙. 코드가 0 으로 끝나지 않는다는 조건과 **함께** 써야 한다 —
# 이름만 보면 '미래에셋대우'(006800, 보통주) 같은 회사가 걸린다.
_PREFERRED_NAME = re.compile(r"우[A-Z]?$")

# 시총 상위 100 종목의 섹터(2026-08-22 KOSPI 기준 수기 분류). 구성과 가중치는 네이버
# 실시간이고 여기 있는 건 섹터 이름뿐이라 유지 부담이 작다. 없는 코드는 "기타"로 떨어진다 —
# 그 칸이 커지면 매핑을 보탤 때다.
SECTOR_OF: dict[str, str] = {
    # 반도체·전자부품
    "005930": "반도체·전자부품", "000660": "반도체·전자부품", "402340": "반도체·전자부품",
    "009150": "반도체·전자부품", "042700": "반도체·전자부품", "007660": "반도체·전자부품",
    "011070": "반도체·전자부품",
    # 자동차
    "005380": "자동차", "000270": "자동차", "012330": "자동차", "086280": "자동차",
    "161390": "자동차",
    # 2차전지·소재
    "373220": "2차전지·소재", "006400": "2차전지·소재", "051910": "2차전지·소재",
    "003670": "2차전지·소재", "010130": "2차전지·소재", "005490": "2차전지·소재",
    "009830": "2차전지·소재",
    # 바이오·제약
    "207940": "바이오·제약", "068270": "바이오·제약", "0126Z0": "바이오·제약",
    "000100": "바이오·제약", "326030": "바이오·제약",
    # 금융
    "032830": "금융", "105560": "금융", "055550": "금융", "086790": "금융", "000810": "금융",
    "316140": "금융", "138040": "금융", "006800": "금융", "024110": "금융", "005830": "금융",
    "071050": "금융", "323410": "금융", "005940": "금융", "016360": "금융", "039490": "금융",
    # 조선·기계·방산
    "012450": "조선·기계·방산", "329180": "조선·기계·방산", "034020": "조선·기계·방산",
    "042660": "조선·기계·방산", "298040": "조선·기계·방산", "009540": "조선·기계·방산",
    "010140": "조선·기계·방산", "267250": "조선·기계·방산", "079550": "조선·기계·방산",
    "064350": "조선·기계·방산", "272210": "조선·기계·방산", "047810": "조선·기계·방산",
    "443060": "조선·기계·방산", "010120": "조선·기계·방산", "267260": "조선·기계·방산",
    "006260": "조선·기계·방산", "000150": "조선·기계·방산",
    # 인터넷·게임·콘텐츠
    "035420": "인터넷·게임·콘텐츠", "035720": "인터넷·게임·콘텐츠",
    "259960": "인터넷·게임·콘텐츠", "352820": "인터넷·게임·콘텐츠",
    # IT서비스·전자
    "066570": "IT서비스·전자", "018260": "IT서비스·전자", "064400": "IT서비스·전자",
    "307950": "IT서비스·전자",
    # 에너지·화학
    "096770": "에너지·화학", "010950": "에너지·화학", "047050": "에너지·화학",
    # 통신·유틸리티
    "017670": "통신·유틸리티", "030200": "통신·유틸리티", "032640": "통신·유틸리티",
    "015760": "통신·유틸리티",
    # 건설·운송
    "000720": "건설·운송", "028050": "건설·운송", "047040": "건설·운송", "011200": "건설·운송",
    "003490": "건설·운송", "180640": "건설·운송",
    # 소비재·유통
    "033780": "소비재·유통", "003230": "소비재·유통", "090430": "소비재·유통",
    "278470": "소비재·유통", "021240": "소비재·유통",
    # 지주
    "034730": "지주", "003550": "지주", "028260": "지주", "078930": "지주", "000880": "지주",
}


def _is_company(row: dict) -> bool:
    """히트맵에 그릴 대상인가. ETF 는 회사가 아니고, 우선주는 보통주와 같은 회사라
    큰 칸이 둘로 중복된다."""
    if row.get("is_etf"):
        return False
    code, name = row.get("symbol") or "", row.get("name") or ""
    return not (not code.endswith("0") and _PREFERRED_NAME.search(name))


def _build_indices() -> list[dict]:
    out = []
    for name, yf_sym, naver_code in INDICES:
        d = fetch.intraday(yf_sym)      # 실패하면 블록 전체가 실패한다 — 캔들이 없으면 그릴 게 없다
        try:
            q = naver.index_basic(naver_code)
        except Exception:  # noqa: BLE001 — 네이버가 막혀도 캔들로 지수는 그린다
            q = {}
        last = q.get("last") if q.get("last") is not None else d["last"]
        prev = q.get("prev_close") if q.get("prev_close") is not None else d["prev_close"]
        change = q.get("change") if q.get("change") is not None else _chg(last, prev)
        pct = q.get("change_pct") if q.get("change_pct") is not None else _pct(last, prev)
        out.append({"name": name, "symbol": yf_sym, "last": last, "prev_close": prev,
                    "change": change, "change_pct": pct, "candles": d["candles"]})
    return out


def _build_forex_bonds() -> list[dict]:
    yf_syms = [code for _, src, code, _ in FOREX_BONDS if src == "yf"]
    q = fetch.daily_closes(yf_syms) if yf_syms else {}
    out = []
    for name, src, code, dec in FOREX_BONDS:
        if src == "yf":
            v = q.get(code) or {}
            last, prev = v.get("last"), v.get("prev_close")
            row = {"last": last, "change": _chg(last, prev), "change_pct": _pct(last, prev)}
        else:
            row = naver.market_index(src, code)
        out.append({"name": name, "symbol": code, "last": row.get("last"),
                    "change": row.get("change"), "change_pct": row.get("change_pct"),
                    "decimals": dec})
    return out


def _build_signals(spec: list[tuple[str, str, str, int]]) -> list[dict]:
    out = []
    for kind, mkt, label, n in spec:
        for row in naver.ranking(kind, mkt, n):
            out.append({"symbol": row["symbol"], "name": row["name"], "last": row["last"],
                        "change_pct": row["change_pct"], "volume": row["volume"],
                        "signal": label})
    return out


def _build_heatmap() -> list[dict]:
    rows = [r for r in naver.ranking("marketValue", HEATMAP_MARKET, HEATMAP_COUNT)
            if _is_company(r)]
    buckets: dict[str, list[dict]] = {}
    for r in rows:
        sector = SECTOR_OF.get(r["symbol"], SECTOR_FALLBACK)
        buckets.setdefault(sector, []).append(
            {"symbol": r["symbol"], "name": r["name"],
             "weight": r["market_value"] or 0.0, "change_pct": r["change_pct"]})
    # 섹터는 시총 합이 큰 것부터 — 트리맵이 큰 덩어리를 왼쪽 위에 놓는다
    return [{"name": s, "tickers": t} for s, t in
            sorted(buckets.items(), key=lambda kv: -sum(x["weight"] for x in kv[1]))]


def _build_investors() -> list[dict]:
    out = []
    for m in INVESTOR_MARKETS:
        d = naver.investor_trend(m)
        out.append({"market": m, **d})
    return out


def _build_headlines() -> list[dict]:
    return fetch.news(HEADLINES_SYMBOL, limit=HEADLINES_COUNT)


BUILDERS = {
    "indices": _build_indices,
    "forex_bonds": _build_forex_bonds,
    "signals_up": lambda: _build_signals(SIGNALS_UP),
    "signals_down": lambda: _build_signals(SIGNALS_DOWN),
    "heatmap": _build_heatmap,
    "investors": _build_investors,
    "headlines": _build_headlines,
}
