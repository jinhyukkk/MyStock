"""대시보드 인사이더(내부자 거래) 칸.

미국은 야후가 종목별 표를 주고, 국내는 DART 임원·주요주주 소유보고(`elestock`)가 같은
역할을 한다. 국내는 **무료 키가 필요**하고, 키가 없으면 빈 표 대신 안내를 올린다
(company.py 의 `unavailable` 규약과 같다).

국내에는 체결 단가·거래대금이 없다 — 소유보고는 수량 변동만 신고한다. 그래서 두 번째
표의 정렬 기준이 시장마다 다르고, 그 기준을 `top_label` 로 화면까지 올린다. 라벨 없이
정렬만 다르면 같은 표가 두 시장에서 다른 뜻이 된다.
"""
from __future__ import annotations

from app import market_fetch as fetch
from app.sources import dart

NOTE_DART = ("국내 내부자 거래(임원·주요주주 소유보고)는 OpenDART 무료 키가 필요합니다. "
             "https://opendart.fss.or.kr 에서 발급 후 .env.local 에 DART_API_KEY=... 를 넣으세요.")

SYMBOLS = 25       # 종목당 1회 호출 — 유니버스 전체를 돌면 갱신이 분 단위가 된다
PER_SYMBOL = 3
LATEST_ROWS = 8
TOP_ROWS = 6


def insider(market: str, rows: list[dict]) -> dict:
    if market == "KR":
        if not dart.available():
            return {"status": "unavailable", "note": NOTE_DART, "top_label": "변동 수량 상위",
                    "scope": None, "latest": [], "top": []}
        items = _kr_items(rows)
        top_key, top_label = "shares", "변동 수량 상위"
    else:
        items = _us_items(rows)
        top_key, top_label = "value", "거래대금 상위"

    latest = sorted([i for i in items if i["date"]], key=lambda i: i["date"], reverse=True)
    top = sorted([i for i in items if i.get(top_key)],
                 key=lambda i: -abs(i[top_key]))
    # 실적 칸과 같은 이유로 훑은 범위를 남긴다(market_calendar.earnings 주석 참고)
    return {"status": "ok", "note": None, "top_label": top_label,
            "scope": f"상위 {min(len(rows), SYMBOLS)}종목",
            "latest": latest[:LATEST_ROWS], "top": top[:TOP_ROWS]}


def _us_items(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows[:SYMBOLS]:
        try:
            trades = fetch.insider_transactions(r["yf"], limit=PER_SYMBOL)
        except Exception:  # noqa: BLE001 — 한 종목이 막혀도 나머지는 보여준다
            continue
        for t in trades:
            out.append({"symbol": r["symbol"], "name": r["name"], **t})
    return out


def _kr_items(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows[:SYMBOLS]:
        try:
            reports = dart.elestock(r["symbol"])
        except Exception:  # noqa: BLE001
            continue
        for d in reports[:PER_SYMBOL]:
            out.append({
                "symbol": r["symbol"], "name": r["name"],
                "owner": d.get("repror") or d.get("nm") or "",
                "relation": d.get("isu_exctv_ofcps") or "",
                "date": _dart_date(d.get("rcept_dt")),
                "transaction": d.get("chnge_rsn") or "변동",
                "shares": _num(d.get("sp_stock_lmp_irds_cnt")),
                # 소유보고에는 체결 단가·금액이 없다. 0 으로 채우면 '무상'으로 읽힌다
                "value": None, "price": None,
                "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={d['rcept_no']}"
                       if d.get("rcept_no") else None,
            })
    return out


def _dart_date(v) -> str | None:
    s = str(v or "").replace(".", "").replace("-", "").strip()
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 and s.isdigit() else None


def _num(v) -> float | None:
    try:
        return float(str(v or "").replace(",", "").replace("+", ""))
    except ValueError:
        return None
