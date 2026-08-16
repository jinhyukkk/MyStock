from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app import db, fetchers, service

router = APIRouter(prefix="/api")


class WatchItem(BaseModel):
    symbol: str
    name: str
    market: str
    is_etf: int = 0
    yf_symbol: str | None = None
    currency: str = "KRW"


class TradeIn(BaseModel):
    symbol: str
    side: Literal["BUY", "SELL"]
    quantity: float = Field(gt=0)
    price: float = Field(gt=0)
    trade_date: str
    # 같은 날 매도 후 재매수를 정확한 순서로 재생하려면 시각이 필요하다.
    # 순서가 뒤바뀌면 매도가 무시되거나 평단이 잘못 만들어진다.
    executed_at: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    note: str | None = None
    # 미전송(None) = 시장 요율로 추정. 실제 체결 비용을 넣으면 그 값이 원장에 그대로 쓰인다.
    fee: float | None = Field(default=None, ge=0)
    tax: float | None = Field(default=None, ge=0)
    # 평단 맞춤용 보정 로트 — 체결가가 인위적이므로 승률·실현손익 집계에서 제외한다
    exclude_from_stats: bool = False


class RuleIn(BaseModel):
    symbol: str
    rule_type: str
    value: float


def _conn(request: Request):
    """요청을 처리 중인 스레드의 연결. 스레드 간 공유는 세그폴트를 부른다."""
    return request.app.state.db.conn()


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/dashboard")
def dashboard(request: Request):
    return service.get_dashboard(_conn(request))


@router.post("/refresh")
def refresh(request: Request, symbol: str | None = None):
    return service.refresh_all(_conn(request), symbol)


@router.get("/search")
def search(q: str, request: Request):
    return fetchers.search_symbols(q)


@router.get("/tickers/{symbol}")
def ticker_detail(symbol: str, request: Request):
    out = service.get_ticker_detail(_conn(request), symbol)
    if out is None:
        raise HTTPException(404, "ticker not found")
    return out


@router.get("/tickers/{symbol}/backtest")
def ticker_backtest(symbol: str, request: Request):
    conn = _conn(request)
    if not db.get_ticker(conn, symbol):
        raise HTTPException(404, "ticker not found")
    out = service.get_backtest(conn, symbol)
    if out is None:
        raise HTTPException(404, "가격 데이터 부족 — 새로고침 후 다시 시도")
    return out


@router.post("/watchlist")
def add_watch(item: WatchItem, request: Request):
    conn = _conn(request)
    db.upsert_ticker(conn, item.symbol, item.market, item.name,
                     is_etf=item.is_etf, in_watchlist=1,
                     yf_symbol=item.yf_symbol, currency=item.currency)
    return {"ok": True}


@router.delete("/watchlist/{symbol}")
def remove_watch(symbol: str, request: Request):
    db.remove_from_watchlist(_conn(request), symbol)
    return {"ok": True}


@router.get("/trades")
def get_trades(request: Request, symbol: str | None = None):
    return [dict(r) for r in db.list_trades(_conn(request), symbol)]


@router.post("/trades")
def add_trade(t: TradeIn, request: Request):
    conn = _conn(request)
    ticker = db.get_ticker(conn, t.symbol)
    if not ticker:
        raise HTTPException(400, "unknown symbol — 워치리스트에 먼저 추가하세요")
    # 보유보다 많이 파는 입력은 거부한다. 통과시키면 수량이 음수가 되면서
    # 종목이 원장에서 통째로 사라진다 — 오타 한 번에 보유가 조용히 없어진다.
    if t.side == "SELL":
        held = service._holdings_map(conn).get(t.symbol, {}).get("quantity", 0.0)
        if t.quantity > held + 1e-9:
            raise HTTPException(400, f"보유 수량({held:g})보다 많이 매도할 수 없습니다")
    # 체결 시점 환율 스냅샷 — 실현손익 원화 환산이 과거 환율로 왜곡되지 않게
    fx_rate = 1.0
    if ticker["currency"] == "USD":
        fx_rate = service.get_sentiment_view(conn).get("usdkrw")  # 미수집이면 NULL → 현재 환율 폴백
    sig = db.get_latest_signal(conn, t.symbol)
    tid = db.insert_trade(conn, t.symbol, t.side, t.quantity, t.price, t.trade_date,
                          fx_rate=fx_rate, note=t.note,
                          grade_at_trade=sig["grade"] if sig else None,
                          fee=t.fee, tax=t.tax, executed_at=t.executed_at,
                          exclude_from_stats=int(t.exclude_from_stats))
    # 예수금은 매매와 연동돼야 한다 — 수동 입력값만 쓰면 매수할수록 총자산이
    # 과대 계상되고, 그 총자산을 분모로 쓰는 1% 리스크 사이징까지 오염된다.
    cash = service.apply_trade_to_cash(conn, {
        "symbol": t.symbol, "side": t.side, "quantity": t.quantity, "price": t.price,
        "fee": t.fee, "tax": t.tax}, ticker)
    return {"id": tid, "cash": cash}


@router.delete("/trades/{trade_id}")
def remove_trade(trade_id: int, request: Request):
    conn = _conn(request)
    row = db.get_trade(conn, trade_id)
    db.delete_trade(conn, trade_id)
    cash = None
    if row is not None:
        ticker = db.get_ticker(conn, row["symbol"])
        if ticker is not None:  # 삭제는 예수금 증감도 함께 되돌린다
            cash = service.apply_trade_to_cash(conn, dict(row), ticker, reverse=True)
    return {"ok": True, "cash": cash}


@router.get("/portfolio")
def get_portfolio(request: Request):
    return service.get_portfolio_view(_conn(request))


class CashIn(BaseModel):
    # 미전송(None) = 기존 값 유지. 0은 "비웠다"는 명시적 의사이므로 구분해서 저장한다.
    # 프론트의 빈 입력이 0으로 변환되어 예수금을 날리면 총자산이 줄고,
    # 그것을 분모로 쓰는 1% 리스크 포지션 사이징까지 오염된다.
    amount: float | None = Field(default=None, ge=0)
    amount_usd: float | None = Field(default=None, ge=0)


@router.put("/cash")
def set_cash(c: CashIn, request: Request):
    conn = _conn(request)
    if c.amount is not None:
        db.set_meta(conn, "cash_krw", str(c.amount))
    if c.amount_usd is not None:
        db.set_meta(conn, "cash_usd", str(c.amount_usd))
    return {"cash_krw": service.get_cash_krw(conn), "cash_usd": service.get_cash_usd(conn)}


@router.get("/rules")
def get_rules(request: Request, symbol: str | None = None):
    return [dict(r) for r in db.list_rules(_conn(request), symbol)]


@router.post("/rules")
def add_rule(r: RuleIn, request: Request):
    rid = db.insert_rule(_conn(request), r.symbol, r.rule_type, r.value)
    return {"id": rid}


@router.delete("/rules/{rule_id}")
def remove_rule(rule_id: int, request: Request):
    db.delete_rule(_conn(request), rule_id)
    return {"ok": True}
