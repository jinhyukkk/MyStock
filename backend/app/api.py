from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

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
    side: str
    quantity: float
    price: float
    trade_date: str


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
def refresh(request: Request):
    return service.refresh_all(_conn(request))


@router.get("/search")
def search(q: str, request: Request):
    return fetchers.search_symbols(q)


@router.get("/tickers/{symbol}")
def ticker_detail(symbol: str, request: Request):
    out = service.get_ticker_detail(_conn(request), symbol)
    if out is None:
        raise HTTPException(404, "ticker not found")
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
    if not db.get_ticker(conn, t.symbol):
        raise HTTPException(400, "unknown symbol — 워치리스트에 먼저 추가하세요")
    tid = db.insert_trade(conn, t.symbol, t.side, t.quantity, t.price, t.trade_date)
    return {"id": tid}


@router.delete("/trades/{trade_id}")
def remove_trade(trade_id: int, request: Request):
    db.delete_trade(_conn(request), trade_id)
    return {"ok": True}


@router.get("/portfolio")
def get_portfolio(request: Request):
    conn = _conn(request)
    from app.service import _holdings_map, _latest_close_and_change, get_sentiment_view
    holdings = _holdings_map(conn)
    prices = {}
    for s in holdings:
        close, _ = _latest_close_and_change(conn, s)
        if close is not None:
            prices[s] = close
    tickers_map = {t["symbol"]: dict(t) for t in db.list_tickers(conn)}
    from app import portfolio as pf
    return pf.build_portfolio(holdings, prices, tickers_map,
                              get_sentiment_view(conn).get("usdkrw"))


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
