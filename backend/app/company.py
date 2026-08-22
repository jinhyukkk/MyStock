"""회사 자료(프로필·스냅샷·재무·뉴스·컨센서스·내부자) 수집·캐시·조립.

설계 규칙 세 가지만 지키면 이 모듈은 안전하다.

1. **외부 호출은 `app.sources.*`에서만.** 여기서는 `requests`/`yfinance`를 직접 부르지
   않는다. 그래야 테스트가 sources만 monkeypatch해서 네트워크 없이 전부 돈다.
2. **요청 경로(`get_company`/`get_profile`/`get_snapshot`)는 `company_cache`만 읽는다.**
   yfinance `info` 한 번이 1~3초라, 화면이 직접 부르면 종목상세가 그만큼 멈춘다.
3. **실패해도 이전 캐시를 지우지 않는다.** `attempted_at`·`error`만 갱신한다. 값을 지우면
   "원래 데이터가 없는 종목"과 "이번에 못 받아온 종목"을 화면이 구분할 수 없다.

단위 규약(§5.1): 금액은 종목 통화 원단위 숫자, 비율은 퍼센트 숫자(`_pct`), 배수는 배수 그대로,
날짜는 `YYYY-MM-DD`, 일시는 ISO8601 로컬(KST).
"""

from __future__ import annotations

import html
import json
import math
import re
import time
from datetime import datetime, timedelta, timezone

from app import db
from app.sources import daum as src_daum
from app.sources import dart as src_dart
from app.sources import krx_desc as src_krx
from app.sources import naver as src_naver
from app.sources import yf as src_yf

BLOCKS = ("profile", "snapshot", "financials", "news", "ratings", "insiders")

# 블록별 TTL(초). 뉴스는 자주, 재무·프로필은 드물게 — 전부 같은 주기로 돌리면
# 7일이면 충분한 재무를 1시간마다 받느라 뉴스 갱신이 밀린다.
TTL_SEC = {
    "profile": 7 * 24 * 3600,
    "snapshot": 12 * 3600,
    "financials": 7 * 24 * 3600,
    "news": 3600,
    "ratings": 24 * 3600,
    "insiders": 24 * 3600,
    "perf10y": 7 * 24 * 3600,  # 10년 성과용 월봉 — 화면에 직접 나가지 않는 내부 캐시
}

# 한 번의 전체 갱신에서 회사 자료를 받아올 종목 수 상한. 종목이 늘어도 갱신 루프
# 시간이 선형으로 늘지 않게 막는다(8종목 × 최악 6콜 ≈ 20~40초).
COMPANY_MAX_SYMBOLS_PER_RUN = 8
# 실패한 블록을 곧바로 다시 때리지 않는다 — 차단된 비공식 API를 매 루프 두들기면
# 차단이 길어진다.
FAIL_BACKOFF_SEC = 30 * 60
# 네이버·다음은 비공식 API라 병렬·연타에 민감하다. 종목 사이에 숨을 준다.
SYMBOL_SLEEP_SEC = 0.3

RECOMMENDATION_SCALE = "1=strong_buy..5=strong_sell"

NOTE_PENDING = "회사 자료를 아직 받지 못했습니다 — 새로고침을 누르면 지금 가져옵니다."
NOTE_KR_RATINGS = ("국내 종목은 증권사별 투자의견 변경 이력을 제공하는 무료 소스가 없어 "
                   "최근 리포트 목록으로 대신합니다.")
NOTE_KR_INSIDERS = "국내 종목 내부자 거래는 OpenDART 키(무료)를 등록해야 표시됩니다."
NOTE_KR_SHARES = "발행주식수 이력은 OpenDART 키 등록 후 표시됩니다."

MAX_NEWS = 20
MAX_CHANGES = 20
MAX_REPORTS = 10
MAX_INSIDERS = 30
MAX_DESCRIPTION = 2000

# yfinance `exchange`는 코드로 온다. 화면에 'NMS'가 찍히면 사용자는 그게 나스닥인지 모른다.
EXCHANGE_NAMES = {"NMS": "NASDAQ", "NGM": "NASDAQ", "NCM": "NASDAQ", "NAS": "NASDAQ",
                  "NYQ": "NYSE", "ASE": "NYSE American", "PCX": "NYSE Arca",
                  "BTS": "Cboe BZX", "KSC": "KOSPI", "KOE": "KOSDAQ"}


# --------------------------------------------------------------------------- 값 정규화

def _num(v):
    """숫자 아니면 None. NaN/inf도 None — JSON에 실리면 화면에 'NaN'이 그대로 찍힌다."""
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _round(v, digits=4):
    f = _num(v)
    return None if f is None else round(f, digits)


def to_pct(v, digits=2):
    """0~1 비율을 퍼센트 숫자로. `returnOnEquity` 0.9268 → 92.68."""
    f = _num(v)
    return None if f is None else round(f * 100, digits)


def pct_to_ratio(v, digits=4):
    """퍼센트로 오는 배수를 배수로. yfinance `debtToEquity` 78.445 → 0.7845,
    네이버 부채비율 45.95(%) → 0.4595. 나누지 않으면 부채비율이 100배로 보인다."""
    f = _num(v)
    return None if f is None else round(f / 100, digits)


def dividend_yield_pct(raw, rate=None, price=None, digits=2):
    """배당수익률을 퍼센트 숫자로 맞춘다.

    yfinance `dividendYield`는 소스·시점에 따라 0.34(=0.34%)로도, 0.0034(=비율)로도 온다.
    스케일을 잘못 읽으면 배당수익률이 100배 틀린다 — 배당금/주가로 기대값을 만들 수 있으면
    그것과 가까운 쪽을 고르고, 만들 수 없으면 값을 그대로 퍼센트로 본다.
    """
    f = _num(raw)
    if f is None:
        return None
    expected = None
    r, p = _num(rate), _num(price)
    if r is not None and p:
        expected = r / p * 100
    if expected is None:
        return round(f, digits)
    if abs(f * 100 - expected) < abs(f - expected):
        return round(f * 100, digits)
    return round(f, digits)


def naver_recomm_to_scale(v):
    """네이버 `recommMean`을 '1=강력매수' 스케일로 뒤집는다.

    실측 2026-08-21: 000660 `recommMean`=4.00 / `priceTargetMean`=3,317,917 (전일가
    1,691,000 대비 +96% 상방), 같은 날 yfinance `000660.KS recommendationMean`=1.33(강력매수).
    005930·035420·034020도 전부 3.9~4.04 + 큰 상방. 즉 **네이버는 5=강력매수**이고
    yfinance와 방향이 반대다. 뒤집지 않으면 화면이 '강력매수'를 '매도'로 말한다.
    """
    f = _num(v)
    if f is None:
        return None
    return round(6.0 - f, 2)


def recommendation_label(mean) -> str | None:
    """1=강력매수 스케일 기준 한국어 라벨."""
    f = _num(mean)
    if f is None:
        return None
    if f <= 1.5:
        return "강력매수"
    if f <= 2.5:
        return "매수"
    if f <= 3.5:
        return "중립"
    if f <= 4.5:
        return "매도"
    return "강력매도"


_KR_UNITS = (("조", 10 ** 12), ("억", 10 ** 8), ("만", 10 ** 4))


def parse_kr_number(text):
    """네이버 표시 문자열을 숫자로. '7.70배'→7.7, '224,313원'→224313,
    '0.17%'→0.17, '1,262조 2,908억'→1.2622908e15, '-'→None."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return _num(text)
    s = str(text).strip().replace(",", "")
    if not s or s in ("-", "N/A"):
        return None
    total, matched = 0.0, False
    for unit, mult in _KR_UNITS:
        m = re.search(rf"(-?\d+(?:\.\d+)?)\s*{unit}", s)
        if m:
            total += float(m.group(1)) * mult
            matched = True
            s = s.replace(m.group(0), "")
    if matched:
        rest = re.search(r"(-?\d+(?:\.\d+)?)", s)
        if rest:
            total += float(rest.group(1))
        return total
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group(0)) if m else None


def _cagr_pct(first, last, years):
    """연평균 성장률(%). 부호가 바뀌거나 시작이 0/음수면 CAGR이 의미를 잃으므로 None.
    (적자→흑자에 '연 300% 성장'을 찍으면 그건 사실이 아니라 계산 실수다)"""
    f, l = _num(first), _num(last)
    if f is None or l is None or years <= 0 or f <= 0 or l <= 0:
        return None
    return round(((l / f) ** (1 / years) - 1) * 100, 2)


def _change_pct(prev, cur):
    p, c = _num(prev), _num(cur)
    if p is None or c is None or p == 0:
        return None
    return round((c - p) / abs(p) * 100, 2)


def _iso_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _epoch_to_date(v) -> str | None:
    f = _num(v)
    if f is None:
        return None
    try:
        return datetime.fromtimestamp(f, tz=timezone.utc).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return None


# --------------------------------------------------------------------------- 캐시

def read_block(conn, symbol: str, block: str):
    return conn.execute(
        "SELECT * FROM company_cache WHERE symbol=? AND block=?",
        (symbol, block)).fetchone()


def read_payload(conn, symbol: str, block: str) -> tuple[dict | None, str | None, str | None]:
    row = read_block(conn, symbol, block)
    if row is None:
        return None, None, None
    try:
        return json.loads(row["payload"]), row["source"], row["fetched_at"]
    except (ValueError, TypeError):
        return None, row["source"], row["fetched_at"]


def save_success(conn, symbol: str, block: str, payload: dict,
                 source: str | None, now: str | None = None) -> None:
    now = now or _iso_now()
    conn.execute(
        """INSERT INTO company_cache (symbol, block, payload, source, fetched_at,
                                      attempted_at, error)
             VALUES (?,?,?,?,?,?,NULL)
           ON CONFLICT(symbol, block) DO UPDATE SET
             payload=excluded.payload, source=excluded.source,
             fetched_at=excluded.fetched_at, attempted_at=excluded.attempted_at,
             error=NULL""",
        (symbol, block, json.dumps(payload, ensure_ascii=False), source, now, now))
    conn.commit()


def save_failure(conn, symbol: str, block: str, error: str,
                 now: str | None = None) -> None:
    """실패 기록. **payload·fetched_at은 절대 건드리지 않는다**(§6.1).

    행이 아예 없으면 payload를 만들 게 없으므로 `fetched_at`을 빈 문자열로 둔 껍데기만
    남긴다 — 이게 있어야 30분 backoff가 걸려 죽은 소스를 매 루프 두들기지 않는다.
    """
    now = now or _iso_now()
    cur = conn.execute(
        "UPDATE company_cache SET attempted_at=?, error=? WHERE symbol=? AND block=?",
        (now, error[:500], symbol, block))
    if cur.rowcount == 0:
        conn.execute(
            """INSERT INTO company_cache (symbol, block, payload, source, fetched_at,
                                          attempted_at, error)
               VALUES (?,?,'null',NULL,'',?,?)""",
            (symbol, block, now, error[:500]))
    conn.commit()


def _parse_iso(text) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(str(text))
    except ValueError:
        return None


def block_due(conn, symbol: str, block: str, now: datetime | None = None) -> bool:
    """TTL이 지났고 실패 backoff 중이 아니면 True."""
    now = now or datetime.now()
    row = read_block(conn, symbol, block)
    if row is None:
        return True
    attempted = _parse_iso(row["attempted_at"])
    if attempted and now - attempted < timedelta(seconds=FAIL_BACKOFF_SEC) \
            and row["error"]:
        return False
    fetched = _parse_iso(row["fetched_at"])
    if fetched is None:
        return True
    return now - fetched >= timedelta(seconds=TTL_SEC.get(block, 3600))


# --------------------------------------------------------------------------- 소스 묶음

class _Bundle:
    """종목 하나를 갱신하는 동안의 소스 호출 메모.

    프로필과 스냅샷이 같은 yfinance `info`를 쓰는데, 메모하지 않으면 블록 수만큼
    1~3초짜리 호출이 반복된다. 실패도 함께 기억한다 — 죽은 엔드포인트를 한 종목
    갱신에서 세 번 때리는 걸 막는다.
    """

    def __init__(self, ticker: dict):
        self.t = ticker
        self.symbol = ticker["symbol"]
        self.yf_symbol = ticker.get("yf_symbol") or ticker["symbol"]
        self.is_kr = ticker.get("market") == "KR"
        self._memo: dict[str, tuple[bool, object]] = {}
        self.used: set[str] = set()

    def _once(self, key: str, fn, source_name: str | None = None):
        if key not in self._memo:
            try:
                self._memo[key] = (True, fn())
                if source_name:
                    self.used.add(source_name)
            except Exception as e:  # 폴백 경로가 있으므로 여기서 죽이지 않는다
                self._memo[key] = (False, e)
        ok, val = self._memo[key]
        return val if ok else None

    # -- yfinance
    def yf_quote(self):
        return self._once("yf_quote", lambda: src_yf.quote_info(self.yf_symbol), "yfinance")

    def yf_info(self) -> dict:
        q = self.yf_quote()
        return (q or {}).get("info") or {}

    def yf_estimates(self) -> dict:
        return self._once("yf_est", lambda: src_yf.estimates(self.yf_symbol),
                          "yfinance") or {}

    def yf_financials(self) -> dict:
        return self._once("yf_fin", lambda: src_yf.financials(self.yf_symbol),
                          "yfinance") or {}

    def yf_news(self) -> list:
        return self._once("yf_news", lambda: src_yf.news(self.yf_symbol), "yfinance") or []

    def yf_upgrades(self) -> list:
        return self._once("yf_up", lambda: src_yf.upgrades_downgrades(self.yf_symbol),
                          "yfinance") or []

    def yf_insiders(self) -> list:
        return self._once("yf_ins", lambda: src_yf.insider_transactions(self.yf_symbol),
                          "yfinance") or []

    def yf_dividends(self) -> list:
        return self._once("yf_div", lambda: src_yf.dividend_history(self.yf_symbol),
                          "yfinance") or []

    def yf_monthly(self) -> list:
        return self._once("yf_mon", lambda: src_yf.monthly_closes(self.yf_symbol),
                          "yfinance") or []

    # -- 국내 1차
    def naver_integration(self) -> dict:
        if not self.is_kr:
            return {}
        return self._once("nv_int", lambda: src_naver.integration(self.symbol),
                          "naver") or {}

    def naver_annual(self) -> dict:
        if not self.is_kr:
            return {}
        return self._once("nv_a", lambda: src_naver.finance(self.symbol, "annual"),
                          "naver") or {}

    def naver_quarter(self) -> dict:
        if not self.is_kr:
            return {}
        return self._once("nv_q", lambda: src_naver.finance(self.symbol, "quarter"),
                          "naver") or {}

    def naver_news(self) -> list:
        if not self.is_kr:
            return []
        return self._once("nv_news", lambda: src_naver.news(self.symbol, MAX_NEWS),
                          "naver") or []

    def naver_research(self) -> list:
        if not self.is_kr:
            return []
        return self._once("nv_res", lambda: src_naver.research(self.symbol, MAX_NEWS),
                          "naver") or []

    def daum_quote(self) -> dict:
        if not self.is_kr:
            return {}
        return self._once("daum", lambda: src_daum.quote(self.symbol), "daum") or {}

    def krx_desc(self) -> dict:
        if not self.is_kr:
            return {}
        return self._once("krx", lambda: src_krx.describe(self.symbol), "fdr") or {}

    def dart_insiders(self) -> list | None:
        if not self.is_kr or not src_dart.available():
            return None
        return self._once("dart_ins", lambda: src_dart.elestock(self.symbol), "dart")


def _source_str(bundle: _Bundle, *names: str) -> str:
    """실제로 성공한 소스만 이어 붙인다 — 화면의 '출처: yfinance · 네이버'가 거짓이면
    사용자가 낡은 값의 출처를 오해한다."""
    used = [n for n in names if n in bundle.used]
    return "+".join(used) if used else "none"


def _naver_totals(integration: dict) -> dict:
    return {row.get("code"): row.get("value")
            for row in (integration.get("totalInfos") or []) if row.get("code")}


def _naver_rows(finance: dict) -> tuple[dict, list[dict]]:
    """(행제목 → {기간키: 값}, 기간 목록)."""
    info = (finance or {}).get("financeInfo") or {}
    rows = {r.get("title"): {k: (v or {}).get("value")
                             for k, v in (r.get("columns") or {}).items()}
            for r in (info.get("rowList") or [])}
    periods = [{"key": p.get("key"), "title": p.get("title"),
                "estimate": p.get("isConsensus") == "Y"}
               for p in (info.get("trTitleList") or []) if p.get("key")]
    periods.sort(key=lambda p: p["key"])
    return rows, periods


# --------------------------------------------------------------------------- 성과(perf)

PERF_WINDOWS = (("w1", 7, 5), ("m1", 30, 10), ("m3", 91, 15), ("m6", 182, 20),
                ("y1", 365, 30), ("y3", 1095, 45), ("y5", 1825, 60))
PERF_KEYS = ("w1", "m1", "m3", "m6", "ytd", "y1", "y3", "y5", "y10")


def compute_perf(conn, symbol: str, monthly: list | None = None) -> dict:
    """기간별 가격 성과(%). `price_cache`(≈1100영업일)로 5Y까지, 10Y는 월봉으로.

    캔들 200봉만 내려주는 상세 응답으로는 프론트가 1Y조차 만들 수 없어서 백엔드가 낸다.
    보정 없는 종가 기준(배당 재투자 제외)이다.
    """
    out = {k: None for k in PERF_KEYS}
    df = db.load_prices(conn, symbol, limit=1400)
    if df.empty:
        return out
    closes = [(idx.date(), float(c)) for idx, c in zip(df.index, df["close"])
              if _num(c) is not None]
    if not closes:
        return out
    last_date, last_close = closes[-1]
    first_date = closes[0][0]
    if last_close <= 0:
        return out

    def _close_on_or_before(target):
        prev = None
        for d, c in closes:
            if d <= target:
                prev = c
            else:
                break
        return prev

    for key, days, slack in PERF_WINDOWS:
        target = last_date - timedelta(days=days)
        if first_date > target + timedelta(days=slack):
            continue  # 데이터가 그 기간을 못 덮는다 — 짧은 구간을 긴 성과로 속이지 않는다
        base = _close_on_or_before(target)
        if base:
            out[key] = round((last_close / base - 1) * 100, 2)

    dec31 = _close_on_or_before(datetime(last_date.year, 1, 1).date() - timedelta(days=1))
    if dec31:
        out["ytd"] = round((last_close / dec31 - 1) * 100, 2)

    if monthly:
        rows = []
        for row in monthly:
            try:
                dd = datetime.fromisoformat(str(row.get("date"))).date()
            except (TypeError, ValueError):
                continue
            close = _num(row.get("close"))
            if close:
                rows.append((dd, close))
        rows.sort()
        # `price_cache`는 1100영업일(≈4.8년)이라 5년 구간을 못 덮는다. 10년 성과용으로
        # 이미 받아둔 월봉이 있으니 5Y도 **추가 호출 없이** 여기서 채운다 —
        # y3·y10은 있는데 y5만 '—'인 화면은 데이터 한계가 아니라 구현 누락으로 읽힌다.
        for key, days in (("y5", 1825), ("y10", 3650)):
            if out[key] is not None:
                continue
            base = _monthly_close_before(rows, last_date - timedelta(days=days))
            if base:
                out[key] = round((last_close / base - 1) * 100, 2)
    return out


def _monthly_close_before(rows: list, target) -> float | None:
    """`target` 이전 마지막 월봉 종가. yfinance `period=10y` 월봉의 첫 봉은 정확히
    10년 전이 아니라 그 직후 달이라, 엄격히 자르면 10Y 칸이 영원히 빈다 — 100일 여유를 준다.
    그래도 시리즈가 그 기간을 못 덮으면(신규 상장) None으로 남긴다."""
    base = None
    for dd, close in rows:
        if dd <= target:
            base = close
    if base is None and rows and rows[0][0] <= target + timedelta(days=100):
        base = rows[0][1]
    return base


def _last_close(conn, symbol: str):
    df = db.load_prices(conn, symbol, limit=1)
    if df.empty:
        return None
    return _num(df["close"].iloc[-1])


# --------------------------------------------------------------------------- profile

def build_profile(conn, b: _Bundle) -> tuple[dict, str]:
    info = b.yf_info()
    daum = b.daum_quote()
    krx = b.krx_desc()
    if not info and not daum and not krx:
        raise RuntimeError("프로필 소스 전부 실패")

    if b.is_kr:
        sector = daum.get("wicsSectorName") or krx.get("sector") or info.get("sector")
        industry = krx.get("industry") or info.get("industry")
        country = "South Korea"
        exchange = daum.get("market") or krx.get("market") or b.t.get("market")
        ipo = krx.get("listing_date") or _date_only(daum.get("listingDate"))
        website = krx.get("homepage") or info.get("website")
        desc_ko = (daum.get("companySummary") or "").strip()
        description = desc_ko or (info.get("longBusinessSummary") or "").strip() or None
        lang = "ko" if desc_ko else ("en" if description else None)
    else:
        sector = info.get("sector")
        industry = info.get("industry")
        country = info.get("country")
        exchange = info.get("exchange")
        ipo = _epoch_to_date(info.get("firstTradeDateEpochUtc")) \
            or (b.yf_quote() or {}).get("first_trade_date")
        website = info.get("website")
        description = (info.get("longBusinessSummary") or "").strip() or None
        lang = "en" if description else None

    truncated = False
    if description and len(description) > MAX_DESCRIPTION:
        description = description[:MAX_DESCRIPTION]
        truncated = True

    payload = {
        "status": "ok",
        "note": None,
        "sector": sector or None,
        "industry": industry or None,
        "country": country or None,
        "exchange": EXCHANGE_NAMES.get(exchange, exchange) or None,
        "employees": int(info["fullTimeEmployees"])
        if _num(info.get("fullTimeEmployees")) else None,
        "ipo_date": ipo,
        "website": website or None,
        "description": description,
        "description_lang": lang,
        "description_truncated": truncated,
    }
    return payload, _source_str(b, "yfinance", "daum", "fdr", "naver")


def _date_only(v) -> str | None:
    if not v:
        return None
    s = str(v)[:10]
    return s if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) else None


# --------------------------------------------------------------------------- snapshot

PROFILE_KEYS = ("sector", "industry", "country", "exchange", "employees",
                "ipo_date", "website", "description", "description_lang",
                "description_truncated")


def empty_profile(status: str = "pending") -> dict:
    """비어 있는 프로필 골격. `snapshot`과 같은 규칙으로 `status`/`note`를 준다 —
    사용자에게 보일 문구가 BE(4블록·snapshot)와 FE(회사 설명)로 갈라지면
    나중에 문구를 고칠 때 한쪽을 반드시 빠뜨린다."""
    payload = {k: None for k in PROFILE_KEYS}
    payload["description_truncated"] = False
    payload.update({"status": status, "note": None})
    return payload


SNAPSHOT_KEYS = (
    "market_cap", "enterprise_value", "income_ttm", "sales_ttm", "book_per_share",
    "cash_per_share", "dividend_est", "dividend_ttm", "dividend_ex_date",
    "dividend_growth_3y_pct", "dividend_growth_5y_pct", "payout_pct",
    "dividend_yield_pct",
    "pe", "forward_pe", "peg", "ps", "pb", "pc", "p_fcf", "ev_ebitda", "ev_sales",
    "quick_ratio", "current_ratio", "debt_eq", "lt_debt_eq", "float_pct",
    "eps_ttm", "eps_next_y", "eps_next_q", "eps_this_y_pct", "eps_next_y_pct",
    "eps_next_5y_pct", "eps_past_3y_pct", "eps_past_5y_pct", "sales_past_3y_pct",
    "sales_past_5y_pct", "eps_yoy_ttm_pct", "sales_yoy_ttm_pct", "eps_qoq_pct",
    "sales_qoq_pct", "earnings_date", "earnings_timing", "eps_surprise_pct",
    "sales_surprise_pct",
    "insider_own_pct", "insider_trans_pct", "inst_own_pct", "inst_trans_pct",
    "foreign_own_pct", "roa_pct", "roe_pct", "roic_pct", "gross_margin_pct",
    "oper_margin_pct", "profit_margin_pct",
    "shares_outstanding", "shares_float", "short_float_pct", "short_ratio",
    "short_interest", "beta", "recommendation_mean", "target_price",
)


def empty_snapshot(status: str = "pending") -> dict:
    """모든 칸이 비어 있는 스냅샷 골격. **키 자체는 항상 존재해야 한다**(§5.2) —
    키가 없으면 프론트가 84칸 표를 못 그리고 `undefined`가 화면에 뜬다."""
    payload = {k: None for k in SNAPSHOT_KEYS}
    payload.update({"status": status, "note": None,
                    "perf": {k: None for k in PERF_KEYS},
                    "recommendation_scale": RECOMMENDATION_SCALE,
                    "sources": []})
    return payload


def _dividend_growth(history: list) -> tuple[float | None, float | None]:
    """배당 이력에서 3년·5년 연평균 성장률(%). 올해는 아직 다 지급되지 않았으므로 뺀다."""
    by_year: dict[int, float] = {}
    for row in history or []:
        d = _date_only(row.get("date"))
        amt = _num(row.get("amount"))
        if not d or amt is None:
            continue
        by_year[int(d[:4])] = by_year.get(int(d[:4]), 0.0) + amt
    this_year = datetime.now().year
    years = sorted(y for y in by_year if y < this_year)
    if len(years) < 2:
        return None, None
    out = []
    for span in (3, 5):
        if len(years) >= span + 1:
            out.append(_cagr_pct(by_year[years[-1 - span]], by_year[years[-1]], span))
        else:
            out.append(None)
    return out[0], out[1]


def _stmt_series(rows: list, key: str) -> list:
    """연/분기 재무를 옛날→최근 순으로 정렬한 값 목록."""
    items = [(r.get("end_date"), _num(r.get(key))) for r in rows or []]
    items = [(d, v) for d, v in items if d]
    items.sort(key=lambda x: x[0])
    return [v for _, v in items]


def _snapshot_from_yf(b: _Bundle, price) -> dict:
    info = b.yf_info()
    est = b.yf_estimates()
    fin = b.yf_financials()
    snap = empty_snapshot("ok")

    shares = _num(info.get("sharesOutstanding"))
    total_cash = _num(info.get("totalCash"))
    cash_ps = round(total_cash / shares, 4) if total_cash and shares else None
    mcap = _num(info.get("marketCap"))
    fcf = _num(info.get("freeCashflow"))

    snap.update({
        "market_cap": mcap,
        "enterprise_value": _num(info.get("enterpriseValue")),
        "income_ttm": _num(info.get("netIncomeToCommon")),
        "sales_ttm": _num(info.get("totalRevenue")),
        "book_per_share": _num(info.get("bookValue")),
        "cash_per_share": cash_ps,
        "dividend_est": _num(info.get("dividendRate")),
        "dividend_ttm": _num(info.get("trailingAnnualDividendRate")),
        "dividend_ex_date": _epoch_to_date(info.get("exDividendDate")),
        "payout_pct": to_pct(info.get("payoutRatio")),
        "dividend_yield_pct": dividend_yield_pct(
            info.get("dividendYield"), info.get("dividendRate"), price),
        "pe": _round(info.get("trailingPE"), 2),
        "forward_pe": _round(info.get("forwardPE"), 2),
        "peg": _round(info.get("trailingPegRatio"), 2),
        "ps": _round(info.get("priceToSalesTrailing12Months"), 2),
        "pb": _round(info.get("priceToBook"), 2),
        "pc": round(price / cash_ps, 2) if price and cash_ps else None,
        "p_fcf": round(mcap / fcf, 2) if mcap and fcf else None,
        "ev_ebitda": _round(info.get("enterpriseToEbitda"), 2),
        "ev_sales": _round(info.get("enterpriseToRevenue"), 2),
        "quick_ratio": _round(info.get("quickRatio"), 4),
        "current_ratio": _round(info.get("currentRatio"), 2),
        # yfinance는 %로 준다(AAPL 78.445 = 0.7845배). 안 나누면 부채비율이 100배가 된다.
        # 자릿수는 4 — 2자리로 자르면 네이버 45.95%가 0.46이 되어, 계약이 요구하는
        # 0.4595와 다른 값이 나간다(US·KR이 같은 단위·같은 정밀도여야 한다).
        "debt_eq": pct_to_ratio(info.get("debtToEquity"), 4),
        "eps_ttm": _round(info.get("trailingEps"), 4),
        "eps_next_y": _round(info.get("forwardEps"), 4),
        "insider_own_pct": to_pct(info.get("heldPercentInsiders")),
        "inst_own_pct": to_pct(info.get("heldPercentInstitutions")),
        "roa_pct": to_pct(info.get("returnOnAssets")),
        "roe_pct": to_pct(info.get("returnOnEquity")),
        "gross_margin_pct": to_pct(info.get("grossMargins")),
        "oper_margin_pct": to_pct(info.get("operatingMargins")),
        "profit_margin_pct": to_pct(info.get("profitMargins")),
        "shares_outstanding": shares,
        "shares_float": _num(info.get("floatShares")),
        "short_float_pct": to_pct(info.get("shortPercentOfFloat")),
        "short_ratio": _round(info.get("shortRatio"), 2),
        "short_interest": _num(info.get("sharesShort")),
        "beta": _round(info.get("beta"), 3),
        "recommendation_mean": _round(info.get("recommendationMean"), 2),
        "target_price": _round(info.get("targetMeanPrice"), 4),
    })

    float_shares = snap["shares_float"]
    if float_shares and shares:
        snap["float_pct"] = round(float_shares / shares * 100, 2)

    balance = fin.get("balance") or {}
    ltd, equity = _num(balance.get("long_term_debt")), _num(balance.get("equity"))
    if ltd is not None and equity:
        snap["lt_debt_eq"] = round(ltd / equity, 2)

    # 추정치
    trend, growth = est.get("eps_trend") or {}, est.get("growth") or {}
    snap["eps_next_q"] = _round(trend.get("0q"), 4)
    snap["eps_this_y_pct"] = to_pct(growth.get("0y"))
    snap["eps_next_y_pct"] = to_pct(growth.get("+1y"))
    snap["eps_next_5y_pct"] = to_pct(growth.get("LTG"))

    # 과거 성장 — 연간 손익계산서
    annual = fin.get("annual") or []
    eps_series = _stmt_series(annual, "eps")
    sales_series = _stmt_series(annual, "sales")
    for span in (3, 5):
        if len(eps_series) >= span + 1:
            snap[f"eps_past_{span}y_pct"] = _cagr_pct(
                eps_series[-1 - span], eps_series[-1], span)
        if len(sales_series) >= span + 1:
            snap[f"sales_past_{span}y_pct"] = _cagr_pct(
                sales_series[-1 - span], sales_series[-1], span)

    quarterly = fin.get("quarterly") or []
    q_eps = _stmt_series(quarterly, "eps")
    q_sales = _stmt_series(quarterly, "sales")
    if len(q_eps) >= 5:
        snap["eps_yoy_ttm_pct"] = _change_pct(q_eps[-5], q_eps[-1])
    if len(q_sales) >= 5:
        snap["sales_yoy_ttm_pct"] = _change_pct(q_sales[-5], q_sales[-1])
    if len(q_eps) >= 2:
        snap["eps_qoq_pct"] = _change_pct(q_eps[-2], q_eps[-1])
    if len(q_sales) >= 2:
        snap["sales_qoq_pct"] = _change_pct(q_sales[-2], q_sales[-1])

    # ROIC — 실효세율을 손익계산서에서 뽑아 NOPAT을 만든다. 세율을 임의 상수로
    # 가정하면 그건 계산이 아니라 추측이라, 값이 없으면 칸을 비워 둔다.
    if annual:
        latest = sorted([r for r in annual if r.get("end_date")],
                        key=lambda r: r["end_date"])[-1]
        op = _num(latest.get("operating_income"))
        pretax, tax = _num(latest.get("pretax_income")), _num(latest.get("tax_provision"))
        invested = _num(balance.get("invested_capital"))
        if op and invested and pretax and tax is not None and pretax > 0:
            snap["roic_pct"] = round(op * (1 - tax / pretax) / invested * 100, 2)

    cal = (b.yf_quote() or {}).get("calendar") or {}
    dates = cal.get("Earnings Date")
    if isinstance(dates, list) and dates:
        snap["earnings_date"] = _date_only(dates[0])
    for row in est.get("earnings") or []:
        if _num(row.get("surprise_pct")) is not None:
            snap["eps_surprise_pct"] = _round(row.get("surprise_pct"), 2)
            break

    snap["dividend_growth_3y_pct"], snap["dividend_growth_5y_pct"] = \
        _dividend_growth(b.yf_dividends())

    # 내부자 순매수 비율(6개월) — 내부자 보유 주식수 대비 순취득 주식수.
    # yfinance가 KR에 이 표를 안 주므로 값이 없으면 그대로 비운다.
    insiders = b.yf_insiders() if not b.is_kr else []
    if insiders and snap["insider_own_pct"] and shares:
        cutoff = (datetime.now() - timedelta(days=182)).date().isoformat()
        net = 0.0
        for row in insiders:
            d = _date_only(row.get("date"))
            qty = _num(row.get("shares")) or 0
            if not d or d < cutoff or not qty:
                continue
            text = f"{row.get('transaction') or ''} {row.get('text') or ''}".lower()
            net += -qty if ("sale" in text or "sold" in text) else qty
        held = shares * snap["insider_own_pct"] / 100
        if held:
            snap["insider_trans_pct"] = round(net / held * 100, 2)
    return snap


def _apply_kr_sources(snap: dict, b: _Bundle, price) -> dict:
    """국내 종목의 빈 칸을 네이버·다음으로 메운다.

    yfinance는 `.KS` 종목에서 trailingPE·priceToBook·trailingEps·bookValue를 전부
    None으로 준다(실측 2026-08-21, 000660.KS). 여기서 채우지 않으면 국내 종목 스냅샷의
    핵심 4칸이 영구히 빈다.
    """
    tot = _naver_totals(b.naver_integration())
    daum = b.daum_quote()

    def _put(key, value, digits=None):
        v = _num(value)
        if v is None:
            return
        snap[key] = round(v, digits) if digits is not None else v

    _put("pe", parse_kr_number(tot.get("per")), 2)
    _put("pb", parse_kr_number(tot.get("pbr")), 2)
    _put("eps_ttm", parse_kr_number(tot.get("eps")), 2)
    _put("book_per_share", parse_kr_number(tot.get("bps")), 2)
    _put("forward_pe", parse_kr_number(tot.get("cnsPer")), 2)
    _put("eps_next_y", parse_kr_number(tot.get("cnsEps")), 2)
    _put("dividend_ttm", parse_kr_number(tot.get("dividend")), 2)
    _put("dividend_yield_pct", parse_kr_number(tot.get("dividendYieldRatio")), 2)
    _put("market_cap", parse_kr_number(tot.get("marketValue")))
    # 외인소진율: 네이버는 "51.05%"(퍼센트 문자열), 다음은 0.5105(비율) — 단위가 다르다
    _put("foreign_own_pct", parse_kr_number(tot.get("foreignRate")), 2)
    if snap["foreign_own_pct"] is None:
        _put("foreign_own_pct", to_pct(daum.get("foreignRatio")), 2)
    if snap["market_cap"] is None:
        _put("market_cap", daum.get("marketCap"))
    if snap["pe"] is None:
        _put("pe", daum.get("per"), 2)
    if snap["pb"] is None:
        _put("pb", daum.get("pbr"), 2)
    if snap["eps_ttm"] is None:
        _put("eps_ttm", daum.get("eps"), 2)
    if snap["book_per_share"] is None:
        _put("book_per_share", daum.get("bps"), 2)

    if snap["market_cap"] and snap["sales_ttm"] and snap["ps"] is None:
        snap["ps"] = round(snap["market_cap"] / snap["sales_ttm"], 2)

    a_rows, a_periods = _naver_rows(b.naver_annual())
    q_rows, q_periods = _naver_rows(b.naver_quarter())

    def _row_val(rows, title, period_key):
        return parse_kr_number((rows.get(title) or {}).get(period_key))

    actual_a = [p for p in a_periods if not p["estimate"]]
    est_a = [p for p in a_periods if p["estimate"]]

    if actual_a:
        last = actual_a[-1]["key"]
        # 네이버 재무비율은 전부 % — 배수 칸에 그대로 넣으면 100배가 된다.
        # 당좌비율·부채비율은 **yfinance 값이 있어도 네이버로 덮는다**: yfinance의
        # `debtToEquity`는 차입금 기준이라 국내 공시 부채비율(총부채/자본)과 정의가
        # 다르고(000660 실측 7.08 vs 45.95), 화면 라벨은 국내 기준을 말한다.
        for key, title in (("quick_ratio", "당좌비율"), ("debt_eq", "부채비율")):
            v = pct_to_ratio(_row_val(a_rows, title, last), 4)
            if v is not None:
                snap[key] = v
        if snap["roe_pct"] is None:
            snap["roe_pct"] = _round(_row_val(a_rows, "ROE", last), 2)
        if snap["oper_margin_pct"] is None:
            snap["oper_margin_pct"] = _round(_row_val(a_rows, "영업이익률", last), 2)
        if snap["profit_margin_pct"] is None:
            snap["profit_margin_pct"] = _round(_row_val(a_rows, "순이익률", last), 2)

    if est_a:
        _put("dividend_est", _row_val(a_rows, "주당배당금", est_a[-1]["key"]), 2)
    if snap["payout_pct"] is None and snap["eps_ttm"] and snap["dividend_ttm"]:
        snap["payout_pct"] = round(snap["dividend_ttm"] / snap["eps_ttm"] * 100, 2)

    # 국내 매출·순이익 TTM: yfinance가 비었을 때만 분기 4개를 더한다(억원 → 원)
    def _q_sum(title, keys):
        vals = [_row_val(q_rows, title, k) for k in keys]
        return sum(v for v in vals if v is not None) * 10 ** 8 \
            if all(v is not None for v in vals) else None

    actual_q = [p["key"] for p in q_periods if not p["estimate"]]
    if len(actual_q) >= 4:
        if snap["sales_ttm"] is None:
            snap["sales_ttm"] = _q_sum("매출액", actual_q[-4:])
        if snap["income_ttm"] is None:
            snap["income_ttm"] = _q_sum("당기순이익", actual_q[-4:])

    # 성장률 — 네이버 연간 3년/분기 5개. 5년치는 DART(2차)가 있어야 한다.
    # 과거 3년 성장률은 기준연도 + 3년 = 연간 실적 4개가 있어야 만들어진다.
    # 네이버는 연간 실적을 3개(=2년 구간)만 주므로 국내 1차에서는 대개 null이다 —
    # 2년치를 3년 성장률로 내보내면 화면이 없는 성장을 말하게 된다(DART 2차 과제).
    a_actual_keys = [p["key"] for p in actual_a]
    if len(a_actual_keys) >= 4:
        snap["eps_past_3y_pct"] = _cagr_pct(_row_val(a_rows, "EPS", a_actual_keys[-4]),
                                            _row_val(a_rows, "EPS", a_actual_keys[-1]), 3)
        snap["sales_past_3y_pct"] = _cagr_pct(
            _row_val(a_rows, "매출액", a_actual_keys[-4]),
            _row_val(a_rows, "매출액", a_actual_keys[-1]), 3)
    if est_a and a_actual_keys:
        snap["eps_this_y_pct"] = _change_pct(
            _row_val(a_rows, "EPS", a_actual_keys[-1]),
            _row_val(a_rows, "EPS", est_a[-1]["key"]))
    if len(actual_q) >= 5:
        snap["eps_yoy_ttm_pct"] = _change_pct(_row_val(q_rows, "EPS", actual_q[-5]),
                                              _row_val(q_rows, "EPS", actual_q[-1]))
        snap["sales_yoy_ttm_pct"] = _change_pct(_row_val(q_rows, "매출액", actual_q[-5]),
                                                _row_val(q_rows, "매출액", actual_q[-1]))
    if len(actual_q) >= 2:
        snap["eps_qoq_pct"] = _change_pct(_row_val(q_rows, "EPS", actual_q[-2]),
                                          _row_val(q_rows, "EPS", actual_q[-1]))
        snap["sales_qoq_pct"] = _change_pct(_row_val(q_rows, "매출액", actual_q[-2]),
                                            _row_val(q_rows, "매출액", actual_q[-1]))

    # 공매도 3칸은 pykrx(로그인 필요)만 주는 값이라 국내는 비운다(§3 보류)
    snap["short_float_pct"] = None
    snap["short_ratio"] = None
    snap["short_interest"] = None

    # 컨센서스: 네이버가 있으면 1=강력매수로 뒤집어 쓴다(방향이 yfinance와 반대다)
    cons = (b.naver_integration() or {}).get("consensusInfo") or {}
    naver_mean = naver_recomm_to_scale(parse_kr_number(cons.get("recommMean")))
    if naver_mean is not None:
        snap["recommendation_mean"] = naver_mean
    target = parse_kr_number(cons.get("priceTargetMean"))
    if target is not None:
        snap["target_price"] = target
    return snap


def build_snapshot(conn, b: _Bundle) -> tuple[dict, str]:
    price = _last_close(conn, b.symbol)
    if not b.yf_info() and not b.is_kr:
        raise RuntimeError("yfinance info 없음")
    snap = _snapshot_from_yf(b, price)
    if b.is_kr:
        if not b.naver_integration() and not b.daum_quote() and not b.yf_info():
            raise RuntimeError("국내 스냅샷 소스 전부 실패")
        snap = _apply_kr_sources(snap, b, price)

    monthly = None
    if block_due(conn, b.symbol, "perf10y"):
        monthly = b.yf_monthly()
        if monthly:
            save_success(conn, b.symbol, "perf10y", {"monthly": monthly}, "yfinance")
    if monthly is None:
        cached, _, _ = read_payload(conn, b.symbol, "perf10y")
        monthly = (cached or {}).get("monthly")
    snap["perf"] = compute_perf(conn, b.symbol, monthly)
    source = _source_str(b, "yfinance", "naver", "daum")
    snap["sources"] = [s for s in source.split("+") if s != "none"]
    return snap, source


# --------------------------------------------------------------------------- financials

def _fin_item(period, end_date, eps, sales, shares, estimate) -> dict:
    return {"period": period, "end_date": end_date, "eps": _round(eps, 4),
            "sales": _round(sales, 2), "shares_outstanding": _round(shares, 0),
            "estimate": bool(estimate)}


def _month_end(key: str) -> str:
    """'202512' → '2025-12-31'."""
    y, m = int(key[:4]), int(key[4:6])
    nxt = datetime(y + (m == 12), 1 if m == 12 else m + 1, 1)
    return (nxt - timedelta(days=1)).date().isoformat()


def _drop_empty(items: list) -> list:
    """EPS·매출·주식수가 전부 빈 기간은 뺀다 — 차트에 빈 막대만 남는다.
    (yfinance 손익계산서의 가장 오래된 열은 값이 통째로 비는 경우가 있다)"""
    return [i for i in items
            if any(i[k] is not None for k in ("eps", "sales", "shares_outstanding"))]


def _quarter_label(end_date: str) -> str:
    y, m = int(end_date[:4]), int(end_date[5:7])
    return f"{y}Q{(m - 1) // 3 + 1}"


def build_financials(conn, b: _Bundle) -> tuple[dict, str]:
    if b.is_kr:
        a_rows, a_periods = _naver_rows(b.naver_annual())
        q_rows, q_periods = _naver_rows(b.naver_quarter())
        if not a_periods and not q_periods:
            raise RuntimeError("네이버 재무 없음")

        def _items(rows, periods, quarterly):
            out = []
            for p in periods:
                key = p["key"]
                # 네이버는 '2025.12.'처럼 결산 월만 준다. 말일로 맞추지 않으면
                # 화면이 12월 결산을 12월 1일 실적으로 읽는다.
                end = _month_end(key)
                # 네이버 매출은 억원 단위 — 원단위로 올리지 않으면 US와 축이 안 맞는다
                sales = parse_kr_number((rows.get("매출액") or {}).get(key))
                out.append(_fin_item(
                    _quarter_label(end) if quarterly else key[:4],
                    end,
                    parse_kr_number((rows.get("EPS") or {}).get(key)),
                    sales * 10 ** 8 if sales is not None else None,
                    None, p["estimate"]))
            return out

        payload = {"status": "ok", "note": None,
                   "annual": _items(a_rows, a_periods, False),
                   "quarterly": _items(q_rows, q_periods, True),
                   "shares_note": None if src_dart.available() else NOTE_KR_SHARES}
        return payload, _source_str(b, "naver")

    fin = b.yf_financials()
    annual_rows = sorted([r for r in fin.get("annual") or [] if r.get("end_date")],
                         key=lambda r: r["end_date"])
    quarter_rows = sorted([r for r in fin.get("quarterly") or [] if r.get("end_date")],
                          key=lambda r: r["end_date"])
    if not annual_rows and not quarter_rows:
        raise RuntimeError("yfinance 손익계산서 없음")
    payload = {
        "status": "ok", "note": None,
        "annual": _drop_empty([_fin_item(r["end_date"][:4], r["end_date"], r.get("eps"),
                                         r.get("sales"), r.get("shares"), False)
                               for r in annual_rows]),
        "quarterly": _drop_empty([_fin_item(_quarter_label(r["end_date"]), r["end_date"],
                                            r.get("eps"), r.get("sales"), r.get("shares"),
                                            False) for r in quarter_rows]),
        "shares_note": None,
    }
    return payload, _source_str(b, "yfinance")


# --------------------------------------------------------------------------- news

def unescape_text(v):
    """HTML 엔티티를 실제 문자로 되돌린다.

    네이버 뉴스 API는 제목을 HTML 조각 그대로 준다 — `&quot;`·`&amp;`·`&#39;`가
    리터럴로 섞여 온다(2026-08-21 000660 20건 중 2건). 프론트는 React라 문자열을
    이스케이프해서 렌더하므로, 여기서 풀지 않으면 화면에 `&quot;`가 그대로 찍힌다.
    """
    if not isinstance(v, str):
        return v
    return html.unescape(v).strip() or None


def _naver_news_time(v) -> str | None:
    """'202608211512' → '2026-08-21T15:12:00' (KST 로컬)."""
    s = re.sub(r"\D", "", str(v or ""))
    if len(s) < 12:
        return None
    return f"{s[0:4]}-{s[4:6]}-{s[6:8]}T{s[8:10]}:{s[10:12]}:00"


def _yf_news_time(v) -> str | None:
    """야후는 UTC ISO(`2026-08-20T19:43:18Z`)로 준다. 화면은 KST를 보여줘야 하므로
    로컬 시각으로 옮긴다 — 안 그러면 '9시간 전 뉴스'가 방금 뉴스로 보인다."""
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().replace(tzinfo=None).isoformat(timespec="seconds")


def build_news(conn, b: _Bundle) -> tuple[dict, str]:
    items = []
    source = None
    if b.is_kr:
        for group in b.naver_news() or []:
            for row in (group.get("items") or []) if isinstance(group, dict) else []:
                url = row.get("mobileNewsUrl")
                title = row.get("titleFull") or row.get("title")
                published = _naver_news_time(row.get("datetime"))
                if not url or not title or not published:
                    continue
                items.append({"published_at": published,
                              "title": unescape_text(title),
                              "source": unescape_text(row.get("officeName")),
                              "url": url, "lang": "ko"})
        if items:
            source = "naver"
    if not items:
        for row in b.yf_news() or []:
            published = _yf_news_time(row.get("published_at"))
            if not published or not row.get("url"):
                continue
            items.append({"published_at": published,
                          "title": unescape_text(row.get("title")),
                          "source": unescape_text(row.get("source")),
                          "url": row.get("url"), "lang": "en"})
        if items:
            source = "yfinance"
    if not items:
        raise RuntimeError("뉴스 소스 전부 실패")
    items.sort(key=lambda x: x["published_at"], reverse=True)
    return {"status": "ok", "note": None, "items": items[:MAX_NEWS]}, source


# --------------------------------------------------------------------------- ratings

# 야후 `upgrades_downgrades.Action`은 축약 코드로 온다(실측 2026-08-21 AAPL:
# up/down/main/reit/init). 계약(§5.3)이 요구하는 표기로 옮긴다 — 화면에 'reit'이
# 찍히면 사용자는 그게 '의견 유지'라는 걸 모른다.
ACTION_LABELS = {"up": "Upgrade", "down": "Downgrade", "main": "Reiterated",
                 "reit": "Reiterated", "init": "Initiated", "resume": "Resumed"}


def build_ratings(conn, b: _Bundle) -> tuple[dict, str]:
    price = _last_close(conn, b.symbol)
    info = b.yf_info()
    mean = _round(info.get("recommendationMean"), 2)
    target = _round(info.get("targetMeanPrice"), 4)
    count = _num(info.get("numberOfAnalystOpinions"))
    as_of = None
    changes, reports = [], []
    source = "yfinance" if info else None

    if b.is_kr:
        cons = (b.naver_integration() or {}).get("consensusInfo") or {}
        naver_mean = naver_recomm_to_scale(parse_kr_number(cons.get("recommMean")))
        naver_target = parse_kr_number(cons.get("priceTargetMean"))
        if naver_mean is not None or naver_target is not None:
            source = "naver"
            as_of = _date_only(cons.get("createDate"))
            if naver_mean is not None:
                mean = naver_mean
            if naver_target is not None:
                target = naver_target
        seen = set()
        for row in (b.naver_research() or []) + \
                ((b.naver_integration() or {}).get("researches") or []):
            date = _date_only(row.get("writeDate"))
            title = row.get("title")
            if not date or not title or (date, title) in seen:
                continue
            seen.add((date, title))
            reports.append({"date": date,
                            "firm": unescape_text(row.get("brokerName")) or "",
                            "title": unescape_text(title),
                            "url": src_naver.research_url(row.get("researchId"))})
        reports.sort(key=lambda r: r["date"], reverse=True)
        reports = reports[:MAX_REPORTS]
        if reports:
            source = "naver"
        note = NOTE_KR_RATINGS
    else:
        changes = [c for c in (b.yf_upgrades() or []) if c.get("date")][:MAX_CHANGES]
        for c in changes:
            raw = (c.get("action") or "").strip().lower()
            c["action"] = ACTION_LABELS.get(raw, raw.title() or "기타")
            c["firm"] = c.get("firm") or ""
            # 야후는 '이전 목표가 없음'을 0.0으로 준다 — 0원 목표가는 사실이 아니다
            for key in ("from_target", "to_target"):
                if c.get(key) == 0:
                    c[key] = None
        note = None

    consensus = None
    if mean is not None or target is not None or count is not None:
        consensus = {
            "recommendation_mean": mean,
            "recommendation_label": recommendation_label(mean),
            "target_mean": target,
            "target_upside_pct": round((target / price - 1) * 100, 2)
            if target and price else None,
            "analyst_count": int(count) if count else None,
            "as_of": as_of,
        }
    if consensus is None and not changes and not reports:
        raise RuntimeError("컨센서스 소스 전부 실패")
    payload = {"status": "ok", "note": note, "consensus": consensus,
               "changes": changes, "reports": reports}
    return payload, source or "none"


# --------------------------------------------------------------------------- insiders

_PRICE_IN_TEXT = re.compile(r"at price\s+([\d,.]+)", re.I)


def build_insiders(conn, b: _Bundle) -> tuple[dict, str]:
    if b.is_kr:
        rows = b.dart_insiders()
        if rows is None:
            return {"status": "unavailable", "note": NOTE_KR_INSIDERS,
                    "items": []}, None
        items = []
        for r in rows[:MAX_INSIDERS]:
            date = _date_only(str(r.get("rcept_dt") or "").replace(".", "-")) \
                or _dart_date(r.get("rcept_dt"))
            if not date:
                continue
            items.append({
                "name": r.get("repror") or r.get("nm") or "",
                "relation": r.get("isu_exctv_ofcps") or r.get("isu_exctv_rgist_at"),
                "date": date,
                "transaction": r.get("chnge_rsn") or r.get("sp_stock_lmp_cnt") or "변동",
                "price": None,
                "shares": _num(str(r.get("chnge_qy") or "").replace(",", "")),
                "value": None,
                "shares_total": _num(str(r.get("sp_stock_lmp_cnt") or "").replace(",", "")),
                "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={r.get('rcept_no')}"
                if r.get("rcept_no") else None,
            })
        return {"status": "ok", "note": None, "items": items}, "dart"

    rows = b.yf_insiders()
    if not rows:
        # 미국 종목인데 표가 비면 '제공되지 않는다'가 아니라 '이번엔 못 받았다'일 수
        # 있으므로 실패로 남긴다 — 캐시가 있으면 이전 값이 그대로 유지된다.
        raise RuntimeError("내부자 거래 없음")
    items = []
    for r in rows[:MAX_INSIDERS]:
        text = r.get("text") or ""
        price = None
        m = _PRICE_IN_TEXT.search(text)
        if m:
            price = _num(m.group(1).replace(",", ""))
        transaction = r.get("transaction") or (text.split(" at ")[0] if text else None)
        items.append({
            "name": r.get("name") or "",
            "relation": r.get("relation"),
            "date": r.get("date"),
            "transaction": (transaction or "기타").strip(),
            "price": _round(price, 4),
            "shares": _round(r.get("shares"), 0),
            "value": _round(r.get("value"), 2),
            "shares_total": None,
            "url": r.get("url") or None,
        })
    items = [i for i in items if i["date"]]
    return {"status": "ok", "note": None, "items": items}, "yfinance"


def _dart_date(v) -> str | None:
    s = re.sub(r"\D", "", str(v or ""))
    return f"{s[0:4]}-{s[4:6]}-{s[6:8]}" if len(s) >= 8 else None


BUILDERS = {
    "profile": build_profile,
    "snapshot": build_snapshot,
    "financials": build_financials,
    "news": build_news,
    "ratings": build_ratings,
    "insiders": build_insiders,
}


# --------------------------------------------------------------------------- 갱신

def _due_blocks(conn, symbol: str, force: bool, now=None) -> list[str]:
    if force:
        return list(BLOCKS)
    return [b for b in BLOCKS if block_due(conn, symbol, b, now)]


def _oldest_fetch(conn, symbol: str) -> str:
    row = conn.execute("SELECT MIN(fetched_at) AS m FROM company_cache WHERE symbol=?",
                       (symbol,)).fetchone()
    return (row["m"] if row and row["m"] else "")


def select_symbols(conn, tickers: list, held: set | None = None,
                   limit: int = COMPANY_MAX_SYMBOLS_PER_RUN, now=None) -> list:
    """이번 루프에서 회사 자료를 받아올 종목. TTL이 지난 것 중 오래된 순, 동률이면
    보유 > 관심 > 기타. 상한을 두지 않으면 종목 수에 비례해 갱신 루프가 길어져
    시세·알림이 뒤로 밀린다."""
    held = held or set()
    cands = []
    for t in tickers:
        t = dict(t)
        if t.get("market") not in ("KR", "US"):
            continue  # 암호화폐는 회사 자료 자체가 없다
        if not _due_blocks(conn, t["symbol"], False, now):
            continue
        rank = 0 if t["symbol"] in held else (1 if t.get("in_watchlist") else 2)
        cands.append((rank, _oldest_fetch(conn, t["symbol"]), t["symbol"], t))
    cands.sort(key=lambda x: (x[0], x[1], x[2]))
    return [c[3] for c in cands[:limit]]


def refresh_symbol(conn, ticker: dict, force: bool = False, now=None) -> list[str]:
    """한 종목의 만료된(또는 force면 전체) 블록을 갱신. 실패한 블록명을 돌려준다."""
    blocks = _due_blocks(conn, ticker["symbol"], force, now)
    if not blocks:
        return []
    b = _Bundle(dict(ticker))
    failed = []
    for block in blocks:
        try:
            payload, source = BUILDERS[block](conn, b)
            save_success(conn, ticker["symbol"], block, payload, source)
        except Exception as e:
            save_failure(conn, ticker["symbol"], block, f"{type(e).__name__}: {e}")
            failed.append(block)
    return failed


def refresh_company_blocks(conn, tickers: list, force: bool = False,
                           held: set | None = None) -> list[str]:
    """회사 자료 갱신 진입점. 실패한 **종목** 목록을 돌려준다.

    시세 갱신이 끝난 뒤에 부른다. 여기서 예외가 새어 나가면 비공식 API 하나가 죽는 날
    시세·시그널 갱신까지 같이 멈춘다 — 호출부에서 반드시 try/except로 감싼다.
    """
    targets = [dict(t) for t in tickers] if force else \
        select_symbols(conn, tickers, held)
    failed = []
    for i, t in enumerate(targets):
        if i and SYMBOL_SLEEP_SEC:
            time.sleep(SYMBOL_SLEEP_SEC)  # 비공식 API 연타 방지
        if refresh_symbol(conn, t, force=force):
            failed.append(t["symbol"])
    return failed


# --------------------------------------------------------------------------- 조회

def _wrap(conn, symbol: str, block: str, defaults: dict) -> dict:
    payload, source, fetched_at = read_payload(conn, symbol, block)
    if not payload:
        return {"status": "pending", "note": NOTE_PENDING, "source": None,
                "fetched_at": None, **defaults}
    out = {**defaults, **payload}
    out["status"] = payload.get("status", "ok")
    out["note"] = payload.get("note")
    out["source"] = source
    out["fetched_at"] = fetched_at or None
    return out


def get_profile(conn, symbol: str) -> dict:
    """캐시가 없으면 `status:"pending"` + 안내 문구가 담긴 골격(계약 v2 §4-B1).

    v1에서는 null이었다. null이면 화면이 "회사 자료를 아직 못 받았다"는 문구를 스스로
    지어내야 하고, 그 문구가 BE의 4블록 문구와 갈라진다. 요청 경로에서 외부 호출은 없다.
    """
    payload, source, fetched_at = read_payload(conn, symbol, "profile")
    if not payload:
        out = empty_profile("pending")
        out["note"] = NOTE_PENDING
        out["source"] = None
        out["fetched_at"] = None
        return out
    out = empty_profile("ok")
    out.update(payload)
    out["status"] = payload.get("status", "ok")
    out["note"] = payload.get("note")
    out["source"] = source
    out["fetched_at"] = fetched_at or None
    return out


def get_snapshot(conn, symbol: str) -> dict:
    """캐시가 없으면 `status:"pending"` 골격. 84칸 키는 항상 존재한다."""
    payload, source, fetched_at = read_payload(conn, symbol, "snapshot")
    if not payload:
        out = empty_snapshot("pending")
        out["note"] = NOTE_PENDING
        out["fetched_at"] = None
        return out
    out = empty_snapshot("ok")
    out.update(payload)
    out["status"] = payload.get("status", "ok")
    out["recommendation_scale"] = RECOMMENDATION_SCALE
    out["sources"] = payload.get("sources") or (
        [s for s in (source or "").split("+") if s and s != "none"])
    out["fetched_at"] = fetched_at or None
    perf = dict(out.get("perf") or {})
    out["perf"] = {k: perf.get(k) for k in PERF_KEYS}
    return out


def get_company(conn, symbol: str) -> dict:
    """종목상세 하단 4블록. **캐시가 비어도 200**(전부 pending) — 404를 주면 화면이
    '없는 종목'과 '아직 안 받은 종목'을 구분하지 못한다."""
    return {
        "symbol": symbol,
        "financials": _wrap(conn, symbol, "financials",
                            {"annual": [], "quarterly": [], "shares_note": None}),
        "news": _wrap(conn, symbol, "news", {"items": []}),
        "ratings": _wrap(conn, symbol, "ratings",
                         {"consensus": None, "changes": [], "reports": []}),
        "insiders": _wrap(conn, symbol, "insiders", {"items": []}),
    }
