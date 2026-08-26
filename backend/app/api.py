from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

from app import autotrade, db, fetchers, jobs, kis, preview, service, universe

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
    # 종목 지정 새로고침 = 사용자가 버튼을 눌렀고 이미 스피너가 돌고 있다는 뜻이라,
    # 회사 자료도 TTL을 무시하고 지금 받아온다(§6.3 요청 경로 외부 호출 금지의 유일한 예외).
    return service.refresh_all(_conn(request), symbol, force_company=symbol is not None)


@router.get("/search")
def search(q: str, request: Request):
    return fetchers.search_symbols(q)


@router.get("/tickers/{symbol}")
def ticker_detail(symbol: str, request: Request, bg: BackgroundTasks):
    """미등록 심볼도 연다 — 없으면 백그라운드로 해석·수집하고 pending을 준다.

    404를 주지 않는 이유는 `/company`와 같다. `refresh_all`의 시세·시그널·재무 수집이
    수 초 걸려 요청 경로에서 할 수 없고, 그러면 첫 응답 시점에 존재 여부를 아직 모른다."""
    conn = _conn(request)
    t = db.get_ticker(conn, symbol)
    if not t:
        return preview.poll(symbol, bg, request.app.state.db)
    # 행이 있어도 그 심볼의 preview job이 아직 진행 중이면(=시세가 아직 안 붙었으면)
    # ready를 주면 안 된다. `db.upsert_ticker`는 job 초반에 즉시 commit되고
    # `refresh_all`(시세·시그널·재무)은 그 뒤 수 초 더 걸린다 — 그 창에 도착한
    # 폴링이 candles=[]/signal=null인 "ready"를 받으면 훅이 폴링을 영구 중단해버린다.
    # 등록된(워치리스트/보유) 종목은 preview job이 절대 돌지 않으므로 이 분기를 타지 않는다.
    if preview.is_inflight(symbol):
        return {"status": "pending", "symbol": symbol}
    out = service.get_ticker_detail(conn, symbol)
    if out is None:
        raise HTTPException(404, "ticker not found")
    # 추가 필드만 얹는다. 기존 필드를 건드리면 구버전 빌드본이 깨진다.
    return {**out, "status": "ready", "tracked": bool(t["in_watchlist"])}


@router.get("/tickers/{symbol}/company")
def ticker_company(symbol: str, request: Request):
    """회사 자료 4블록. 캐시가 비어도 200 + status:"pending" — 404를 주면 화면이
    '없는 종목'과 '아직 수집 전'을 구분하지 못한다."""
    conn = _conn(request)
    if not db.get_ticker(conn, symbol):
        raise HTTPException(404, "ticker not found")
    return service.get_company(conn, symbol)


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


@router.put("/watchlist/{symbol}")
def track_watch(symbol: str, request: Request):
    """이미 있는 행의 플래그만 세운다.

    `POST /api/watchlist`는 yf_symbol·currency까지 본문으로 받는데, 임시 조회로 만들어진
    행은 그 값이 이미 정확하다. 프론트가 메타데이터를 되돌려 보내면 틀릴 여지만 생긴다."""
    conn = _conn(request)
    if not db.get_ticker(conn, symbol):
        raise HTTPException(404, "ticker not found")
    db.set_watchlist(conn, symbol, 1)
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


class NotifyIn(BaseModel):
    # 미전송(None) = 변경 없음, "" = 해제. 토큰을 매번 다시 넣게 하면 채팅 ID만
    # 고치려다 알림이 통째로 꺼진다.
    bot_token: str | None = None
    chat_id: str | None = None


@router.get("/notify")
def get_notify(request: Request):
    return service.notify_status(_conn(request))


@router.put("/notify")
def set_notify(body: NotifyIn, request: Request):
    return service.set_notify(_conn(request), body.bot_token, body.chat_id)


@router.post("/notify/test")
def test_notify(request: Request):
    try:
        return service.notify_test(_conn(request))
    except Exception as e:
        raise HTTPException(400, str(e))


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


# ── 전략 연구실 ────────────────────────────────────────────────────────────

class StrategyBacktestIn(BaseModel):
    preset: str = Field(min_length=1)
    params: dict[str, int] | None = None
    initial_capital_krw: float = Field(default=10_000_000.0, gt=0)


@router.get("/strategy/presets")
def strategy_presets():
    return service.strategy_presets()


@router.post("/strategy/backtest")
def strategy_backtest(body: StrategyBacktestIn, request: Request):
    try:
        return service.run_strategy_backtest(
            _conn(request), body.preset, body.params, body.initial_capital_krw)
    except ValueError as e:
        # 알 수 없는 전략이 500이 되면 화면에 원인이 안 남는다
        raise HTTPException(400, str(e))


class StrategyOptimizeIn(BaseModel):
    preset: str = Field(min_length=1)
    initial_capital_krw: float = Field(default=10_000_000.0, gt=0)


@router.post("/strategy/optimize")
def strategy_optimize(body: StrategyOptimizeIn, request: Request):
    """홀드아웃 그리드 서치 — 조합 수 × 2회 백테스트라 수 초~수십 초 걸린다."""
    try:
        return service.run_strategy_optimize(
            _conn(request), body.preset, body.initial_capital_krw)
    except ValueError as e:
        raise HTTPException(400, str(e))


class WalkforwardIn(BaseModel):
    preset: str = Field(min_length=1)
    initial_capital_krw: float = Field(default=10_000_000.0, gt=0)
    universe: str = Field(default="watchlist", pattern="^(watchlist|krx300)$")
    regime_filter: bool = False


@router.post("/strategy/walkforward")
def strategy_walkforward(body: WalkforwardIn, request: Request):
    """워크포워드 검증 — 수 분 걸리는 작업이라 잡으로 돌리고 job_id를 돌려준다."""
    from app import strategy as strategy_mod
    if body.preset not in strategy_mod.PRESETS:
        raise HTTPException(400, f"알 수 없는 전략: {body.preset}")
    state_db = request.app.state.db
    # 잡 스레드가 자기 연결을 얻도록 conn()을 잡 함수 안에서 부른다 —
    # 요청 스레드의 연결을 넘기면 동시 접근으로 프로세스가 죽는다
    job_id = jobs.start(lambda cb: service.run_walkforward(
        state_db.conn(), body.preset, body.initial_capital_krw,
        body.universe, body.regime_filter, progress_cb=cb))
    return {"job_id": job_id}


@router.get("/strategy/walkforward/{job_id}")
def strategy_walkforward_status(job_id: str):
    st = jobs.get(job_id)
    if st is None:
        raise HTTPException(404, "해당 작업을 찾을 수 없습니다.")
    return st


# ── 검증 유니버스 ────────────────────────────────────────────────────────────

@router.post("/universe/collect")
def universe_collect(request: Request):
    """KRX 거래대금 상위 + 폐지 종목 시세 수집 — 약 2~3분, 잡으로 돌린다."""
    state_db = request.app.state.db
    job_id = jobs.start(lambda cb: universe.collect(state_db.conn(), progress_cb=cb))
    return {"job_id": job_id}


@router.get("/universe/collect/{job_id}")
def universe_collect_status(job_id: str):
    st = jobs.get(job_id)
    if st is None:
        raise HTTPException(404, "해당 작업을 찾을 수 없습니다.")
    return st


@router.get("/universe/status")
def universe_status(request: Request):
    return service.universe_status(_conn(request))


# ── 자동매매 ────────────────────────────────────────────────────────────────

class AutotradeSettingsIn(BaseModel):
    preset: str = Field(min_length=1)
    params: dict[str, int] | None = None
    # 생략하면 ON — 워크포워드에서 유효성이 확인된 유일한 구성이다
    regime_filter: bool = True


class AutotradeExecuteIn(BaseModel):
    # 실수 클릭 한 번이 실제 주문이 되면 안 된다 — 화면이 명시적으로 보낸다
    confirm: bool = False


@router.get("/autotrade/status")
def autotrade_status(request: Request):
    """설정·포지션·주문 이력 — KIS를 부르지 않아 키가 없어도 뜬다."""
    conn = _conn(request)
    return {
        "configured": kis.configured(),
        "mode": kis.mode(),
        "settings": autotrade.settings(conn),
        "positions": [dict(r) for r in db.list_auto_positions(conn)],
        "orders": [dict(r) for r in db.list_auto_orders(conn)],
    }


@router.put("/autotrade/settings")
def autotrade_settings(body: AutotradeSettingsIn, request: Request):
    try:
        autotrade.save_settings(_conn(request), body.preset, body.params or {},
                                body.regime_filter)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@router.post("/autotrade/plan")
def autotrade_plan(request: Request):
    """오늘 낼 주문 미리보기 — 주문은 발송하지 않는다."""
    conn = _conn(request)
    try:
        client = kis.Client(conn)
        return autotrade.plan(conn, client.balance())
    except kis.KisError as e:
        raise HTTPException(400, str(e))


@router.post("/autotrade/execute")
def autotrade_execute(body: AutotradeExecuteIn, request: Request):
    if not body.confirm:
        raise HTTPException(400, "confirm=true 없이 주문을 실행할 수 없습니다.")
    conn = _conn(request)
    try:
        return autotrade.execute(conn, kis.Client(conn))
    except kis.KisError as e:
        raise HTTPException(400, str(e))
