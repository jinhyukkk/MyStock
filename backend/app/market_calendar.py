"""대시보드 캘린더 두 칸 — 경제지표(econ)와 실적 발표(earnings).

`status` 규약은 company.py 와 같다: `ok` | `unavailable`(+`note`). 키가 필요한 소스가
없을 때 빈 표를 내보내면 "오늘 일정이 없다"로 읽히므로, 왜 비었는지를 화면까지 올린다.
"""
from __future__ import annotations

from datetime import date, timedelta

from app import market_fetch as fetch
from app.sources import ecos, fred

NOTE_FRED = ("미국 경제지표 일정은 FRED 무료 키가 필요합니다. "
             "https://fred.stlouisfed.org/docs/api/api_key.html 에서 발급 후 "
             ".env.local 에 FRED_API_KEY=... 를 넣으세요.")
NOTE_ECOS = ("국내 경제지표는 한국은행 ECOS 무료 키가 필요합니다. "
             "https://ecos.bok.or.kr/api 에서 발급 후 "
             ".env.local 에 ECOS_API_KEY=... 를 넣으세요.")

ECON_ROWS = 10
# ECOS 100대 지표 중 화면에 먼저 올릴 것들. 이름이 조금씩 바뀌어도 걸리도록 **부분 문자열**로
# 찾고, 이 목록으로 6줄을 못 채우면 ECOS 가 준 순서대로 뒤를 채운다.
ECON_KEYWORDS = ("기준금리", "국고채", "소비자물가", "생산자물가", "실업률", "취업자",
                 "경제성장", "경상수지", "수출", "수입", "환율", "M2")

EARNINGS_SYMBOLS = 40      # 종목당 야후 1회 호출 — 유니버스 전체를 돌면 분 단위가 된다
# 며칠 안으로 창을 좁히면 실적 시즌이 아닌 달에는 칸이 늘 비어 있다(국내는 분기 발표가
# 1·4·7·10월에 몰린다). 그래서 "다가오는 발표일 앞에서부터 N일"로 잡는다.
EARNINGS_DAYS = 120
EARNINGS_DATES = 6


def econ(market: str, today: date | None = None) -> dict:
    """경제지표 칸. 미국은 '발표 예정일', 국내는 '주요 지표 최신값' — 소스가 주는 것이
    다르다. 없는 칸(예상치·실제치)을 지어내지 않으려고 시장별로 성격을 달리 둔다."""
    if market == "US":
        if not fred.available():
            return {"status": "unavailable", "note": NOTE_FRED, "kind": "release", "rows": []}
        rows = [{"date": r["date"], "name": r["name"], "value": None, "unit": None}
                for r in fred.release_dates(today=today)][:ECON_ROWS]
        return {"status": "ok", "note": None, "kind": "release", "rows": rows}

    if not ecos.available():
        return {"status": "unavailable", "note": NOTE_ECOS, "kind": "indicator", "rows": []}
    stats = ecos.key_statistics()
    picked: list[dict] = []
    seen: set[str] = set()
    for kw in ECON_KEYWORDS:
        for s in stats:
            name = s.get("name") or ""
            if kw in name and name not in seen:
                seen.add(name)
                picked.append(s)
                break
    for s in stats:                      # 키워드로 못 채운 자리는 ECOS 순서대로
        if len(picked) >= ECON_ROWS:
            break
        if (s.get("name") or "") not in seen:
            seen.add(s["name"])
            picked.append(s)
    rows = [{"date": _period(s.get("period")), "name": s.get("name"),
             "value": s.get("value"), "unit": s.get("unit")} for s in picked[:ECON_ROWS]]
    return {"status": "ok", "note": None, "kind": "indicator", "rows": rows}


def _period(cycle: str | None) -> str | None:
    """ECOS CYCLE(20260814 / 202608 / 2026)을 사람이 읽는 기준시점으로."""
    c = (cycle or "").strip()
    if len(c) == 8:
        return f"{c[:4]}-{c[4:6]}-{c[6:8]}"
    if len(c) == 6:
        return f"{c[:4]}-{c[4:6]}"
    return c or None


def earnings(rows: list[dict], today: date | None = None) -> dict:
    """유니버스 상위 종목의 다음 실적 발표일을 날짜별로 묶어 가까운 순으로 준다.

    상위 `EARNINGS_SYMBOLS` 개만 보는 이유: 야후 `calendar` 는 종목당 한 번 호출이라
    200~500 종목을 돌면 갱신이 분 단위가 된다. 시총 큰 종목의 발표일이 시장을 흔든다.
    """
    today = today or date.today()
    end = today + timedelta(days=EARNINGS_DAYS)
    scanned = rows[:EARNINGS_SYMBOLS]
    by_date: dict[str, list[dict]] = {}
    for r in scanned:
        try:
            when = fetch.earnings_date(r["yf"])
        except Exception:  # noqa: BLE001 — 한 종목이 막혀도 나머지 일정은 보여준다
            continue
        if not when:
            continue
        try:
            d = date.fromisoformat(when)
        except ValueError:
            continue
        if not (today <= d <= end):
            continue
        by_date.setdefault(when, []).append({"symbol": r["symbol"], "name": r["name"]})
    # 훑은 범위를 같이 준다 — 유니버스 전체가 아니라 상위 N 만 본 목록이라,
    # 화면이 "이게 전부"로 보이면 안 나온 종목이 발표를 안 하는 것으로 읽힌다.
    return {"status": "ok", "note": None, "scope": f"상위 {len(scanned)}종목",
            "rows": [{"date": d, "tickers": by_date[d]}
                     for d in sorted(by_date)[:EARNINGS_DATES]]}
