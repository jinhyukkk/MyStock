from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

from app import codef, db, fetchers, service

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


class PositionRuleIn(BaseModel):
    # 뒤집힌 범위(min>max)는 어떤 개수든 위반으로 만든다. 늘 빨간 화면은
    # 며칠 만에 무시되고, 그러면 진짜 위반도 함께 지나친다.
    min: int = Field(ge=1, le=50)
    max: int = Field(ge=1, le=50)

    @model_validator(mode="after")
    def _ordered(self):
        if self.min > self.max:
            raise ValueError("최소 종목 수가 최대보다 클 수 없습니다")
        return self


@router.get("/position-rule")
def get_position_rule(request: Request):
    lo, hi = service.get_target_positions(_conn(request))
    return {"min": lo, "max": hi}


@router.put("/position-rule")
def set_position_rule(r: PositionRuleIn, request: Request):
    lo, hi = service.set_target_positions(_conn(request), r.min, r.max)
    return {"min": lo, "max": hi}


class CashFlowIn(BaseModel):
    flow_type: Literal["DIVIDEND", "DEPOSIT", "WITHDRAW", "INTEREST"]
    amount: float = Field(gt=0)  # 세전 금액
    flow_date: str
    symbol: str | None = None
    currency: Literal["KRW", "USD"] = "KRW"
    # 원천징수액. 배당은 입금 시점에 이미 떼이므로 순액과 세전을 모두 원장에 남긴다.
    tax: float = Field(default=0.0, ge=0)
    note: str | None = None


@router.get("/cash-flows")
def get_cash_flows(request: Request, symbol: str | None = None,
                   flow_type: str | None = None):
    return [dict(r) for r in db.list_cash_flows(_conn(request), symbol, flow_type)]


@router.post("/cash-flows")
def add_cash_flow(f: CashFlowIn, request: Request):
    conn = _conn(request)
    if f.flow_type in ("DIVIDEND", "INTEREST") and not f.symbol:
        raise HTTPException(400, "배당·이자는 종목을 지정해야 합니다")
    currency = f.currency
    if f.symbol:
        ticker = db.get_ticker(conn, f.symbol)
        if not ticker:
            raise HTTPException(400, "unknown symbol — 워치리스트에 먼저 추가하세요")
        currency = ticker["currency"]  # 통화는 종목이 정한다 — 어긋나면 환산이 통째로 틀린다
    if f.tax > f.amount:
        raise HTTPException(400, "원천징수액이 세전 금액보다 클 수 없습니다")
    # 입금 시점 환율 스냅샷 — 없으면 작년 배당이 오늘 환율로 다시 계산된다
    fx_rate = 1.0
    if currency == "USD":
        fx_rate = service.get_sentiment_view(conn).get("usdkrw")
    fid = db.insert_cash_flow(conn, f.flow_type, f.amount, f.flow_date, symbol=f.symbol,
                              currency=currency, tax=f.tax, fx_rate=fx_rate, note=f.note)
    cash = service.apply_flow_to_cash(conn, {
        "flow_type": f.flow_type, "amount": f.amount, "tax": f.tax, "currency": currency})
    return {"id": fid, "cash": cash}


class CashFlowPatch(BaseModel):
    symbol: str | None = None  # 빈 값이면 '미지정'으로 되돌린다


@router.patch("/cash-flows/{flow_id}")
def set_cash_flow_symbol(flow_id: int, body: CashFlowPatch, request: Request):
    """배당의 귀속 종목을 나중에 지정한다.

    증권사 입출금내역에는 종목 정보가 없다(적요가 '배당금입금'뿐이다). 그래서
    가져온 배당은 미지정으로 쌓이고, 고칠 방법이 없으면 종목별 배당수익률에
    영원히 안 잡힌다. 예수금은 건드리지 않는다 — 이미 반영된 입금이고 귀속만 바뀐다.
    """
    conn = _conn(request)
    if db.get_cash_flow(conn, flow_id) is None:
        raise HTTPException(404, "없는 현금흐름입니다")
    symbol = (body.symbol or "").strip().upper() or None
    if symbol and db.get_ticker(conn, symbol) is None:
        raise HTTPException(400, "unknown symbol — 워치리스트에 먼저 추가하세요")
    db.update_cash_flow_symbol(conn, flow_id, symbol)
    return {"ok": True, "symbol": symbol}


@router.delete("/cash-flows/{flow_id}")
def remove_cash_flow(flow_id: int, request: Request):
    conn = _conn(request)
    row = db.get_cash_flow(conn, flow_id)
    db.delete_cash_flow(conn, flow_id)
    cash = None
    if row is not None:  # 삭제는 예수금 증감도 함께 되돌린다
        cash = service.apply_flow_to_cash(conn, dict(row), reverse=True)
    return {"ok": True, "cash": cash}


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


# ── 증권사 연동 (CODEF) ────────────────────────────────────────────────────

class BrokerConnectIn(BaseModel):
    organization: str = Field(pattern=r"^\d{4}$")  # CODEF 기관코드 (예: 키움 0264)
    login_type: Literal["0", "1"] = "0"  # 0: 인증서, 1: 아이디/패스워드
    # 인증서 방식이면 인증서 암호, 아이디 방식이면 로그인 비밀번호.
    # 여기서 CODEF로 한 번 보내고 끝이며 서버에는 저장하지 않는다.
    password: str = Field(min_length=1)
    user_id: str | None = None
    der_file: str | None = None  # base64
    key_file: str | None = None  # base64

    @model_validator(mode="after")
    def _cert_files(self):
        if self.login_type == "0" and not (self.der_file and self.key_file):
            raise ValueError("인증서 로그인은 der/key 파일이 필요합니다")
        if self.login_type == "1" and not self.user_id:
            raise ValueError("아이디 로그인은 아이디가 필요합니다")
        return self


class BrokerAccountIn(BaseModel):
    organization: str = Field(pattern=r"^\d{4}$")
    account: str = Field(min_length=1)
    display: str | None = None
    name: str | None = None
    # 계좌비밀번호를 요구하는 증권사만. 즉시 RSA 암호화해 암호문만 저장한다.
    account_password: str | None = None


class BrokerFlowsIn(BaseModel):
    # YYYYMMDD. 증권사마다 조회 가능 기간이 달라 CODEF가 한도를 넘으면 알아서 줄인다.
    start_date: str | None = Field(default=None, pattern=r"^\d{8}$")
    end_date: str | None = Field(default=None, pattern=r"^\d{8}$")


class BrokerAccountsIn(BaseModel):
    accounts: list[BrokerAccountIn] = Field(min_length=1)


def _codef_guard(fn):
    """CODEF 오류는 그대로 500이 되면 화면에 원인이 안 남는다 — 메시지를 그대로 올린다."""
    try:
        return fn()
    except codef.CodefError as e:
        raise HTTPException(400, str(e))


@router.get("/broker/status")
def broker_status(request: Request):
    return service.broker_status(_conn(request))


@router.post("/broker/connect")
def broker_connect(body: BrokerConnectIn, request: Request):
    conn = _conn(request)
    return _codef_guard(lambda: service.broker_connect(
        conn, body.organization, body.login_type, body.password,
        user_id=body.user_id, der_file=body.der_file, key_file=body.key_file))


@router.put("/broker/accounts")
def broker_accounts(body: BrokerAccountsIn, request: Request):
    conn = _conn(request)
    return _codef_guard(lambda: service.broker_select_accounts(
        conn, [a.model_dump() for a in body.accounts]))


@router.post("/broker/sync")
def broker_sync(request: Request):
    conn = _conn(request)
    out = _codef_guard(lambda: service.sync_broker(conn))
    # 새로 편입된 종목은 시세가 없어 화면에서 평가액이 비어 보인다 — 바로 채운다
    for row in db.list_broker_holdings(conn):
        if db.load_prices(conn, row["symbol"], limit=1).empty:
            try:
                service.refresh_all(conn, row["symbol"])
            except Exception:
                pass
    return out


@router.post("/broker/flows")
def broker_flows(body: BrokerFlowsIn, request: Request):
    conn = _conn(request)
    return _codef_guard(lambda: service.sync_broker_flows(
        conn, start_date=body.start_date, end_date=body.end_date))


@router.delete("/broker")
def broker_disconnect(request: Request):
    return service.broker_disconnect(_conn(request))
