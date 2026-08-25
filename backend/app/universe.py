"""생존편향 없는 전략 검증 유니버스 — 후보 수집과 시점별 멤버십.

두 겹의 편향을 걷어내는 모듈이다:
- 선택편향: 사용자가 고른 관심종목이 아니라 거래대금 상위 전 종목을 쓴다.
- 생존편향: 상장폐지 종목을 폐지일까지 포함한다 — 망한 종목이 조용히
  빠지면 백테스트가 "살아남은 종목만의 과거"를 재게 된다.

멤버십 선정은 point-in-time이 하드 규칙이다. 시가총액 상위로 뽑으면 "지금 큰
회사"가 과거 유니버스에 들어가 미래 정보가 샌다 — 직전 window일 거래대금
중앙값은 그 시점에 실제로 알 수 있는 값이다.
"""
from datetime import datetime

import pandas as pd

from app import db

CANDIDATE_TOP = 600     # 수집 후보 — 상위 300 필터를 통과할 여지를 넉넉히
TOP_N = 300             # 시점별 멤버십 크기
TURNOVER_WINDOW = 60    # 거래대금 중앙값 창(거래일)
START_DATE = "2019-01-01"        # 2021년 이후 멤버십의 워밍업 확보
DELISTED_SINCE = "2021-01-01"    # 이보다 옛날 폐지 종목은 백테스트 구간 밖


def candidate_symbols() -> list[dict]:
    """수집 대상 후보 — 현재 상장 거래대금 상위 + 최근 폐지 주권. 네트워크 사용."""
    import FinanceDataReader as fdr
    listed = fdr.StockListing("KRX")
    listed = listed.dropna(subset=["Code", "Name"])
    # ETF·ETN·스팩·우선주가 아닌 보통주 위주로 고르는 정밀 분류는 KRX 목록에
    # 없다 — 거래대금 상위 절단이면 스팩·초저유동성은 자연히 걸러진다
    top = listed.sort_values("Amount", ascending=False).head(CANDIDATE_TOP)
    out = [{"symbol": str(r["Code"]), "name": str(r["Name"]),
            "listing_date": None, "delisting_date": None, "is_etf": 0}
           for _, r in top.iterrows()]
    seen = {c["symbol"] for c in out}
    dl = fdr.StockListing("KRX-DELISTING")
    dl = dl[dl["SecuGroup"] == "주권"].dropna(subset=["Symbol", "DelistingDate"])
    dl = dl[pd.to_datetime(dl["DelistingDate"]) >= DELISTED_SINCE]
    for _, r in dl.iterrows():
        sym = str(r["Symbol"])
        if sym in seen:
            continue
        seen.add(sym)
        ld = r.get("ListingDate")
        out.append({"symbol": sym, "name": str(r["Name"]),
                    "listing_date": str(pd.Timestamp(ld).date()) if pd.notna(ld) else None,
                    "delisting_date": str(pd.Timestamp(r["DelistingDate"]).date()),
                    "is_etf": 0})
    return out


def collect(conn, progress_cb=None) -> dict:
    """후보 전 종목 일봉을 수집해 universe_prices/meta에 저장. 네트워크 사용.

    실패 종목은 목록으로 돌려준다 — 조용히 빠뜨리면 그것이 곧 새로운
    생존편향이다. 한 번 실패는 즉시 1회 재시도한다(FDR 간헐 오류 흡수).
    """
    import FinanceDataReader as fdr
    cands = candidate_symbols()
    ok, failed = 0, []
    for i, c in enumerate(cands):
        df = None
        for _attempt in range(2):
            try:
                df = fdr.DataReader(c["symbol"], START_DATE)
                break
            except Exception:
                df = None
        if df is None or df.empty:
            failed.append(c["symbol"])
        else:
            df = df.rename(columns={"Open": "open", "High": "high", "Low": "low",
                                    "Close": "close", "Volume": "volume"})
            db.save_universe_prices(conn, c["symbol"],
                                    df[["open", "high", "low", "close", "volume"]])
            db.upsert_universe_meta(conn, c["symbol"], c["name"], "KR",
                                    c["listing_date"], c["delisting_date"], c["is_etf"])
            ok += 1
        if progress_cb:
            progress_cb(i + 1, len(cands))
    db.set_meta(conn, "universe_collected_at",
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    return {"ok": ok, "failed": failed}


def monthly_membership(frames: dict, top_n: int = TOP_N,
                       window: int = TURNOVER_WINDOW) -> dict:
    """심볼별 bool Series(인덱스=그 종목 거래일) — 그날 유니버스 멤버인가.

    매월 첫 거래일에 직전 window일 거래대금(close×volume) 중앙값 상위 top_n을
    재선정하고 다음 재선정까지 유지한다. 재선정일 판정 창은 shift(1)로 재선정일
    **이전** 봉만 담는다 — 그날 종가를 넣으면 그만큼 미래를 본 것이다.
    창이 안 찬 종목(상장 직후)은 후보가 아니다 — NaN 중앙값을 0으로 치면
    신규 상장이 전부 첫 달부터 들어와 실제로는 알 수 없던 순위가 된다.
    """
    turnover = {}
    for sym, df in frames.items():
        t = (df["close"] * df["volume"]).shift(1).rolling(window).median()
        turnover[sym] = t
    # 전 종목 거래일 합집합 달력에서 매월 첫 거래일을 재선정일로 잡는다
    calendar = sorted(set().union(*(set(df.index) for df in frames.values()))) \
        if frames else []
    if not calendar:
        return {}
    cal = pd.DatetimeIndex(calendar)
    months = pd.Series(cal.to_period("M"), index=cal)
    rebalance_days = months.groupby(months).apply(lambda s: s.index[0]).tolist()

    members_by_day: dict[pd.Timestamp, set] = {}
    current: set = set()
    ri = 0
    for day in cal:
        if ri < len(rebalance_days) and day == rebalance_days[ri]:
            ranks = []
            for sym, t in turnover.items():
                if day in t.index:
                    v = t.at[day]
                    if pd.notna(v):
                        ranks.append((sym, float(v)))
            ranks.sort(key=lambda x: x[1], reverse=True)
            current = {sym for sym, _ in ranks[:top_n]}
            ri += 1
        members_by_day[day] = current
    return {sym: pd.Series([sym in members_by_day[d] for d in df.index],
                           index=df.index, dtype=bool)
            for sym, df in frames.items()}


def load_frames(conn) -> tuple[dict, dict]:
    """universe 테이블 → engine.run이 받는 (frames, tickers). 네트워크 없음."""
    frames, tickers = {}, {}
    for row in db.list_universe_meta(conn):
        t = dict(row)
        df = db.load_universe_prices(conn, t["symbol"])
        if df.empty:
            continue
        frames[t["symbol"]] = df
        tickers[t["symbol"]] = {"symbol": t["symbol"], "name": t["name"],
                                "market": "KR", "currency": "KRW", "is_etf":
                                t["is_etf"], "delisting_date": t["delisting_date"]}
    return frames, tickers
