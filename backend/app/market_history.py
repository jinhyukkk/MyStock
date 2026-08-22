"""breadth·차트패턴·실적·인사이더가 함께 쓰는 **유니버스와 일봉 행렬**.

왜 따로 있나: 이 네 블록은 같은 종목 목록과 같은 일봉 자료를 본다. 블록마다 받으면
같은 500 종목 1년치를 네 번 내려받는다. `market.py` 의 블록 캐시는 블록별이라 이걸
공유해 주지 못해서, 여기서 시장별로 한 번만 받고 짧은 TTL 로 들고 있는다.

유니버스 크기의 근거:
- KR: fdr KRX 스냅샷의 시총 상위 200(코넥스·우선주 제외). 네이버 랭킹은 pageSize 100 상한.
- US: S&P 500 전 종목. 야후·fdr 어디에도 미국 시총 필드가 없어 '상위 200'을 자를 근거가
  없다 — 임의로 200개를 고르는 것보다 지수 구성 전체가 설명 가능한 범위다. 대신 1년치
  일봉이 24초쯤 걸려(실측 2026-08-22) TTL 을 길게 잡는다.
"""
from __future__ import annotations

import re
import threading
import time

from app import market_fetch as fetch

# 한 번 받으면 이만큼은 그대로 쓴다. 일봉 기반이라 장중에 자주 바뀌지 않는다.
TTL_SEC = 30 * 60
KR_UNIVERSE_N = 200
KR_MARKETS = ("KOSPI", "KOSDAQ")     # 코넥스는 거래가 거의 없어 breadth 를 왜곡한다

# 우선주 이름 규칙. **코드가 0 으로 끝나지 않는다는 조건과 함께** 써야 한다 —
# 이름만 보면 '미래에셋대우'(006800, 보통주) 같은 회사가 걸린다.
_PREFERRED_NAME = re.compile(r"우[A-Z]?$")


def is_preferred(code: str, name: str) -> bool:
    """우선주인가. 보통주와 같은 회사라 유니버스에 둘 다 들어가면 한 회사가 두 번 세진다."""
    code, name = code or "", name or ""
    return bool(not code.endswith("0") and _PREFERRED_NAME.search(name))


def _kr_universe() -> list[dict]:
    rows = [r for r in fetch.krx_listing()
            if r.get("market") in KR_MARKETS
            and not is_preferred(r.get("symbol", ""), r.get("name") or "")]
    # yfinance 심볼은 시장별 접미사가 다르다. 화면 링크는 6자리 코드를 쓰므로 둘 다 들고 간다.
    return [{"symbol": r["symbol"], "name": r["name"],
             "yf": r["symbol"] + (".KS" if r["market"] == "KOSPI" else ".KQ")}
            for r in rows[:KR_UNIVERSE_N]]


def _us_universe() -> list[dict]:
    """S&P 500 전 종목을 **대형주 먼저** 정렬해서 준다.

    fdr·야후 어디에도 미국 시총 필드가 없어 정렬 기준이 없다. 그대로 두면 알파벳순이라
    실적·인사이더가 보는 상위 N 이 'A, AOS, ABT…' 가 되고, 패턴 표에도 큰 종목이 아니라
    이름이 빠른 종목이 뜬다. 히트맵이 이미 들고 있는 대형주 가중치(시총 근사)를 정렬
    힌트로 재사용한다 — 새 소스를 붙이지 않고 순서만 고친다.
    `market_us` 는 이 모듈을 import 하므로 순환을 피해 **함수 안에서** 가져온다."""
    from app.market_us import HEATMAP_SECTORS

    weight = {sym: w for rows in HEATMAP_SECTORS.values() for sym, w in rows}
    rows = [{"symbol": r["symbol"], "name": r["name"], "yf": r["symbol"]}
            for r in fetch.sp500_listing()]
    rows.sort(key=lambda r: -weight.get(r["symbol"], 0.0))
    return rows


UNIVERSES = {
    "KR": (_kr_universe, f"코스피·코스닥 시총 {KR_UNIVERSE_N}"),
    "US": (_us_universe, "S&P 500"),
}

_lock = threading.Lock()
_memo: dict[str, tuple[float, dict]] = {}


def reset_cache() -> None:
    """테스트용."""
    with _lock:
        _memo.clear()


def history(market: str, now: float | None = None) -> dict:
    """{label, as_of, closes(DataFrame), names, rows}. 시장별로 TTL 안에서는 한 번만 받는다.

    실패는 그대로 올린다 — 부르는 쪽(블록 빌더)이 `market.py` 의 실패 격리에 얹힌다.
    빈 결과를 캐시하지 않는 이유: 소스가 잠깐 막힌 날 30분 동안 빈 화면이 굳는다.
    """
    now = time.time() if now is None else now
    with _lock:
        hit = _memo.get(market)
        if hit and now - hit[0] < TTL_SEC:
            return hit[1]

    build, label = UNIVERSES[market]
    rows = build()
    closes = fetch.daily_closes_matrix([r["yf"] for r in rows])
    # 열 이름을 야후 심볼 → 화면 심볼로 바꾼다. 종목 링크가 `/ticker/005930` 이라
    # `005930.KS` 를 그대로 내보내면 클릭이 깨진다.
    by_yf = {r["yf"]: r for r in rows}
    closes = closes.rename(columns={c: by_yf[c]["symbol"] for c in closes.columns if c in by_yf})
    # 유니버스 순서(시총 순)를 유지한다 — 패턴 표에 큰 종목이 먼저 오게 하는 근거다
    order = [r["symbol"] for r in rows if r["symbol"] in closes.columns]
    closes = closes[order]
    out = {
        "label": label,
        "rows": rows,
        "names": {r["symbol"]: r["name"] for r in rows},
        "closes": closes,
        "as_of": str(closes.index[-1])[:10] if len(closes.index) else None,
    }
    if not closes.empty:
        with _lock:
            _memo[market] = (now, out)
    return out
