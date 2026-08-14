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
    note: str | None = None


class RuleIn(BaseModel):
    symbol: str
    rule_type: str
    value: float


def _conn(request: Request):
    return request.app.state.conn


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
    # 체결 시점 환율 스냅샷 — 실현손익 원화 환산이 과거 환율로 왜곡되지 않게
    fx_rate = 1.0
    if ticker["currency"] == "USD":
        fx_rate = service.get_sentiment_view(conn).get("usdkrw")  # 미수집이면 NULL → 현재 환율 폴백
    sig = db.get_latest_signal(conn, t.symbol)
    tid = db.insert_trade(conn, t.symbol, t.side, t.quantity, t.price, t.trade_date,
                          fx_rate=fx_rate, note=t.note,
                          grade_at_trade=sig["grade"] if sig else None)
    return {"id": tid}


@router.delete("/trades/{trade_id}")
def remove_trade(trade_id: int, request: Request):
    db.delete_trade(_conn(request), trade_id)
    return {"ok": True}


@router.get("/portfolio")
def get_portfolio(request: Request):
    return service.get_portfolio_view(_conn(request))


class CashIn(BaseModel):
    amount: float = Field(ge=0)


@router.put("/cash")
def set_cash(c: CashIn, request: Request):
    db.set_meta(_conn(request), "cash_krw", str(c.amount))
    return {"cash_krw": c.amount}


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
