import pandas as pd

from app import costs

MARKET_LABELS = {"KR": "한국 주식", "US": "미국 주식", "CRYPTO": "암호화폐"}
DEFAULT_USDKRW = 1400.0
MAX_ACCOUNT_RISK_PCT = 6.0  # 모든 보유의 2×ATR 손실을 합친 계좌 총 리스크 상한
DEFAULT_TARGET_POSITIONS = (4, 7)  # 집중 투자 스타일의 목표 종목 수 (설정에서 변경 가능)
MIN_TRIM_CANDIDATES = 3  # 초과분이 1개여도 고를 여지를 남긴다


def position_rule(rows: list[dict], target_min: int, target_max: int) -> dict:
    """보유 종목 수가 목표 범위 안에 있는지, 벗어났다면 무엇을 덜어낼지.

    종목별 비중 상한(MAX_WEIGHT)과 계좌 총 리스크(MAX_ACCOUNT_RISK_PCT)는 이미
    보고 있지만, 둘 다 통과하면서 종목 수만 두 배가 되는 계좌는 아무 경고도
    받지 않는다. 12종목은 각각 8%씩이라 비중 위반이 아니고, 손절폭이 작으면
    총 리스크도 한도 안이다. 그런데 12종목을 매일 추적하지 못하면 손절 규율은
    비중과 무관하게 무너진다 — 그래서 개수 자체를 룰로 둔다.

    rows: [{symbol, name, weight_pct, swing_score}]
    """
    count = len(rows)
    status = "over" if count > target_max else "under" if count < target_min else "ok"
    # 후보 순서: ① 스윙 매도 신호 — 시그널이 이미 나가라고 말한 것,
    # ② 비중 하위 — 계좌 수익엔 기여 못 하면서 주의만 나눠 갖는 포지션.
    # 비중만으로 줄을 세우면 "비중 큰 강력매도"가 후보에서 빠진다.
    def order(r):
        score, weight = r.get("swing_score") or 0.0, r.get("weight_pct") or 0.0
        return (0, score) if score < 0 else (1, weight)

    excess = max(count - target_max, 0)
    candidates = []
    if status == "over":
        n = min(max(excess, MIN_TRIM_CANDIDATES), count)
        candidates = [{"symbol": r["symbol"], "name": r.get("name", r["symbol"]),
                       "weight_pct": r.get("weight_pct"),
                       "swing_score": r.get("swing_score"),
                       # 왜 이 종목이 목록에 올라왔는지 — 이유 없는 명단은 따르지 않는다
                       "reason": ("스윙 매도 신호" if (r.get("swing_score") or 0) < 0
                                  else "비중 하위")}
                      for r in sorted(rows, key=order)[:n]]
    return {"count": count, "min": target_min, "max": target_max, "status": status,
            "excess": excess, "shortfall": max(target_min - count, 0),
            "trim_candidates": candidates}


def _trade_costs(t: dict, info: dict) -> tuple[float, float, bool]:
    """(수수료, 세금, 추정여부) — 입력값이 있으면 그대로, 없으면 시장 요율로 추정."""
    fee, tax = t.get("fee"), t.get("tax")
    if fee is not None and tax is not None:
        return float(fee), float(tax), False
    est = costs.estimate(info.get("market", ""), t["side"],
                         t["price"] * t["quantity"], is_etf=info.get("is_etf", 0) or 0)
    return (float(fee) if fee is not None else est["fee"],
            float(tax) if tax is not None else est["tax"],
            fee is None or tax is None)


def _trade_fx(t: dict, info: dict, usdkrw) -> float:
    if info.get("currency", "KRW") != "USD":
        return 1.0
    return float(t.get("fx_rate") or usdkrw or DEFAULT_USDKRW)


# 평단 맞춤용 보정 로트의 메모 표식. exclude_from_stats 체크박스가 생기기 전에
# 임포트된 건은 플래그가 0이고 이 문구만 남아 있다 — 플래그만 보면 그런 계좌에서는
# 경고가 영원히 뜨지 않는다. 원장을 고치지 않고 읽는 쪽에서 같은 사실로 취급한다.
BASIS_ADJ_MARK = "보정 로트"


def _is_basis_adjusted(t: dict) -> bool:
    return bool(t.get("exclude_from_stats")) or BASIS_ADJ_MARK in (t.get("note") or "")


def _walk_trades(trades: list, tickers: dict | None = None,
                 usdkrw=None) -> tuple[dict, list]:
    """매매 내역을 시간순으로 재생해 (현재 보유, 실현손익 원장)을 만든다.

    평단은 매수 수수료를 포함한 **비용 기준**이고, 실현손익은 매도 수수료·세금을
    차감한 **net**이다. 외화 종목은 매수 환율을 비용 가중 이동평균으로 함께 추적해
    원금에 붙은 환차손익까지 정산한다(매도 환율만 쓰면 손익이 크게 어긋난다).
    """
    tickers = tickers or {}
    holdings: dict[str, dict] = {}
    realized: list[dict] = []
    for t in trades:
        s = t["symbol"]
        info = tickers.get(s, {})
        h = holdings.setdefault(s, {"quantity": 0.0, "avg_price": 0.0, "avg_fx": 1.0})
        fee, tax, estimated = _trade_costs(t, info)
        fx = _trade_fx(t, info, usdkrw)
        excluded = _is_basis_adjusted(t)
        if t["side"] == "BUY":
            if h["quantity"] == 0:  # 신규 진입 — 첫 매수 시점 등급이 복기 기준
                h["entry_grade"] = t.get("grade_at_trade")
                h["cost_estimated"] = False
                h["basis_adjusted"] = False
                h["fx_known"] = True
            h["cost_estimated"] = h.get("cost_estimated", False) or estimated
            # 평단 맞춤용 보정 로트는 평단에는 반영하되(그게 목적이다) 그 원가로
            # 만들어진 실현손익은 실제 체결이 아니라는 사실을 포지션에 남긴다
            h["basis_adjusted"] = h.get("basis_adjusted", False) or excluded
            # 매수 환율이 한 로트라도 비어 있으면 avg_fx는 현재 환율로 메운 값이다.
            # 그걸 근거로 낸 환 기여 0은 "영향 없음"이 아니라 "알 수 없음"이다.
            h["fx_known"] = h.get("fx_known", True) and t.get("fx_rate") is not None
            prev_cost = h["avg_price"] * h["quantity"]
            add_cost = t["price"] * t["quantity"] + fee + tax
            h["avg_fx"] = ((h["avg_fx"] * prev_cost + fx * add_cost) / (prev_cost + add_cost)
                           if prev_cost + add_cost else fx)
            h["quantity"] += t["quantity"]
            h["avg_price"] = (prev_cost + add_cost) / h["quantity"]
        else:
            qty = min(t["quantity"], h["quantity"])
            if qty > 0 and h["avg_price"] > 0:
                # 부분 매도면 이 체결의 비용도 체결 수량 비율만큼만 귀속시킨다
                ratio = qty / t["quantity"] if t["quantity"] else 1.0
                cost = (fee + tax) * ratio
                basis = h["avg_price"] * qty
                gross = (t["price"] - h["avg_price"]) * qty
                net = gross - cost
                buy_fx = h["avg_fx"]
                realized.append({
                    "symbol": s, "trade_date": t["trade_date"], "quantity": qty,
                    "buy_price": h["avg_price"], "sell_price": t["price"],
                    "pnl_gross": round(gross, 4),
                    "cost": round(cost, 4),
                    "cost_estimated": bool(estimated or h.get("cost_estimated")),
                    # 원가에 보정 로트가 섞였거나 이 매도 자체가 보정이면 복기 집계에서 뺀다
                    "basis_adjusted": bool(excluded or h.get("basis_adjusted")),
                    "pnl": round(net, 4),
                    "pnl_pct": round(net / basis * 100, 2),
                    # 원화 정산 — 가격 손익과 환 손익을 분리해야 KR/US 배분 판단이 선다
                    "buy_fx": round(buy_fx, 4), "sell_fx": round(fx, 4),
                    "pnl_krw": round(net * fx + basis * (fx - buy_fx), 4),
                    "price_pnl_krw": round(gross * fx, 4),
                    "fx_pnl_krw": round(basis * (fx - buy_fx), 4),
                    "cost_krw": round(cost * fx, 4),
                    "fx_rate": t.get("fx_rate"),
                    "entry_grade": h.get("entry_grade"),
                    "note": t.get("note"),
                })
            h["quantity"] -= t["quantity"]
        if h["quantity"] <= 1e-9:
            holdings.pop(s)
    return holdings, realized


def compute_holdings(trades: list, tickers: dict | None = None, usdkrw=None) -> dict:
    return _walk_trades(trades, tickers, usdkrw)[0]


def realized_pnl(trades: list, tickers: dict | None = None, usdkrw=None) -> list[dict]:
    return _walk_trades(trades, tickers, usdkrw)[1]


def open_risk(holdings: dict, atrs: dict, tickers: dict, usdkrw,
              total_asset_krw: float, prices: dict | None = None,
              stops: dict | None = None) -> dict | None:
    """계좌 전체 미결 리스크 — 모든 보유가 동시에 손절에 닿았을 때의 손실 합.

    종목별 1% 룰만 지키면 5종목에 "총 5%"라고 믿게 되지만, 합산해서 보지 않으면
    그 5%가 실제로 몇 %인지 화면 어디에도 없다.

    손절선은 **등록된 STOP 룰이 있으면 그것**을, 없으면 2×ATR을 쓴다. 알림을
    울리는 것은 등록된 룰뿐인데(check_rules) 합산은 매일 재계산되는 2×ATR로
    하면, 화면의 '총 3.5%'는 어떤 시나리오에서도 실현되지 않는 숫자가 된다.
    룰이 없는 종목은 2×ATR '가정'이므로 몇 건이 가정인지 함께 내려보낸다.
    """
    fx_now = usdkrw or DEFAULT_USDKRW
    prices, stops = prices or {}, stops or {}
    rows, unregistered = [], 0
    for s, h in holdings.items():
        atr = atrs.get(s)
        close, stop = prices.get(s), stops.get(s)
        info = tickers.get(s, {})
        rate = fx_now if info.get("currency") == "USD" else 1.0
        if stop is not None and close is not None:
            # 손절선이 현재가 위면 더 잃을 것이 없다 — 음수 리스크는 총합을 깎아
            # 다른 종목의 위험을 상쇄해버리므로 0으로 바닥을 친다
            per_share, source = max(close - stop, 0.0), "rule"
        elif atr:
            per_share, source = 2 * float(atr), "atr"
            unregistered += 1
        else:
            continue
        risk = per_share * h["quantity"] * rate
        rows.append({"symbol": s, "name": info.get("name", s),
                     "stop_source": source,
                     "risk_krw": round(risk, 0),
                     "risk_pct": round(risk / total_asset_krw * 100, 2)
                     if total_asset_krw else None})
    if not rows:
        return None
    rows.sort(key=lambda r: -r["risk_krw"])
    total = sum(r["risk_krw"] for r in rows)
    total_pct = round(total / total_asset_krw * 100, 2) if total_asset_krw else None
    return {"rows": rows, "total_risk_krw": round(total, 0),
            "total_risk_pct": total_pct, "limit_pct": MAX_ACCOUNT_RISK_PCT,
            "unregistered_count": unregistered,
            "over_limit": bool(total_pct is not None and total_pct > MAX_ACCOUNT_RISK_PCT)}


def overseas_tax_view(realized: list, tickers: dict, year: int) -> dict:
    """해당 연도 해외주식 양도소득세 추정.

    체결 시점에 떼이지 않고 이듬해 5월에 신고·납부하기 때문에, 화면이 실현손익을
    '세금 차감 후'라고 부르면서 이걸 빼면 사용자는 이미 낸 돈을 또 쓸 수 있다고
    믿는다. 종목별이 아니라 **연간 통산** 후 250만원 공제라, 손실 종목이 세금을
    줄여준다는 사실도 합산하지 않으면 화면에 나타나지 않는다.
    """
    gain = 0.0
    for r in realized:
        info = tickers.get(r["symbol"], {})
        if not costs.taxable_overseas(info.get("market", "")):
            continue
        if not str(r.get("trade_date", "")).startswith(str(year)):
            continue
        # 과세표준은 원화 양도차익 — 환차익도 과세 대상에 포함된다
        gain += float(r.get("pnl_krw") or 0.0)
    tax = costs.overseas_capital_gains_tax(gain)
    return {
        "year": year,
        "gain_krw": round(gain, 0),
        "deduction_krw": costs.OVERSEAS_DEDUCTION_KRW,
        "deduction_left_krw": round(max(costs.OVERSEAS_DEDUCTION_KRW - gain, 0.0), 0),
        "taxable_krw": round(max(gain - costs.OVERSEAS_DEDUCTION_KRW, 0.0), 0),
        "tax_krw": tax,
        "rate_pct": round(costs.OVERSEAS_TAX_RATE * 100, 1),
    }


def dividend_view(flows: list, tickers: dict, usdkrw=None, year: int | None = None,
                  cost_krw: dict | None = None,
                  traded_this_year: set | None = None) -> dict:
    """배당·분배금 집계.

    주가만 보는 화면은 커버드콜·고배당 종목을 실제보다 나쁘게 보여준다 —
    분배금으로 받은 현금이 어디에도 없으니 총수익이 하락분만큼만 남는다.

    세 가지를 분리해서 낸다.
    - **순액**: 배당소득세는 입금 시점에 이미 떼인다. 세전 금액을 수익이라 부르면
      실제로 쓸 수 있는 돈보다 15% 많은 숫자를 보고 판단하게 된다.
    - **올해 / 누적**: 합치면 오래 보유한 종목이 무조건 높은 수익률로 보인다.
    - **환율**: 입금 시점 환율로 고정한다. 현재 환율로 환산하면 작년에 받은
      배당이 오늘 환율 변동만으로 늘었다 줄었다 한다.
    """
    fx_now = usdkrw or DEFAULT_USDKRW
    cost_krw, traded_this_year = cost_krw or {}, traded_this_year or set()
    by: dict[str, dict] = {}
    gross = tax = net = ytd_net = ytd_gross = 0.0
    count = ytd_count = fx_estimated = 0
    for f in flows:
        if f.get("flow_type") != "DIVIDEND":
            continue  # 입출금은 현금흐름이지 수익이 아니다
        s = f.get("symbol") or "미지정"
        info = tickers.get(s, {})
        cur = f.get("currency") or info.get("currency", "KRW")
        if cur == "USD":
            rate = f.get("fx_rate")
            if rate is None:
                rate, fx_estimated = fx_now, 1
            rate = float(rate)
        else:
            rate = 1.0
        g, t = float(f.get("amount") or 0.0), float(f.get("tax") or 0.0)
        n = g - t
        this_year = year is not None and str(f.get("flow_date", "")).startswith(str(year))
        gross += g * rate; tax += t * rate; net += n * rate; count += 1
        if this_year:
            ytd_net += n * rate; ytd_gross += g * rate; ytd_count += 1
        r = by.setdefault(s, {"symbol": s, "name": info.get("name", s), "currency": cur,
                              "count": 0, "gross": 0.0, "tax": 0.0, "net": 0.0,
                              "net_krw": 0.0, "ytd_net_krw": 0.0,
                              "first_date": None, "last_date": None})
        r["count"] += 1
        r["gross"] += g; r["tax"] += t; r["net"] += n
        r["net_krw"] += n * rate
        if this_year:
            r["ytd_net_krw"] += n * rate
        d = str(f.get("flow_date") or "")
        r["first_date"] = min(r["first_date"] or d, d)
        r["last_date"] = max(r["last_date"] or d, d)
    rows = []
    for r in sorted(by.values(), key=lambda x: -x["net_krw"]):
        basis = cost_krw.get(r["symbol"])
        # 중간에 사고 판 종목의 '올해 배당 ÷ 현재 원가'는 수익률이 아니다.
        # 반년만 보유하고 받은 배당을 연간 수익률처럼 읽으면 비중을 잘못 늘린다.
        changed = r["symbol"] in traded_this_year
        rows.append({**r,
                     # 종목 통화 금액은 소수까지, 원화 환산은 원 단위로 — 원화에
                     # 소수점이 붙으면 화면에서 달러 금액과 구분이 흐려진다
                     "gross": round(r["gross"], 4), "tax": round(r["tax"], 4),
                     "net": round(r["net"], 4),
                     "net_krw": round(r["net_krw"], 0),
                     "ytd_net_krw": round(r["ytd_net_krw"], 0),
                     "held": basis is not None,
                     "position_changed": changed,
                     "yield_on_cost_pct": round(r["ytd_net_krw"] / basis * 100, 2)
                     if basis and not changed else None})
    # 계좌 수익률도 종목별과 같은 기준으로 만든다. 종목마다 "기간 불일치"라며
    # 수익률을 감춰놓고 그 종목들만으로 계좌 수익률을 내면, 화면이 한쪽에서
    # 못 낸다고 말한 숫자를 다른 쪽에서 합계로 내놓는 셈이 된다.
    ok = [r for r in rows if r["yield_on_cost_pct"] is not None]
    total_basis = sum(cost_krw.get(r["symbol"], 0.0) for r in ok)
    ytd_ok = sum(r["ytd_net_krw"] for r in ok)
    any_changed = len(ok) < len(rows)
    return {
        "by_symbol": rows,
        "year": year, "count": count, "ytd_count": ytd_count,
        "total_gross_krw": round(gross, 0), "total_tax_krw": round(tax, 0),
        "total_net_krw": round(net, 0),
        "ytd_gross_krw": round(ytd_gross, 0), "ytd_net_krw": round(ytd_net, 0),
        # 배당을 받은 종목들의 현재 원가 대비 — 분모에 배당 없는 종목까지 넣으면
        # 커버드콜 비중이 낮은 계좌에서 수익률이 0에 가깝게 희석된다
        "yield_on_cost_pct": round(ytd_ok / total_basis * 100, 2) if total_basis else None,
        "yield_basis_krw": round(total_basis, 0),
        "yield_partial": any_changed,
        "fx_estimated": bool(fx_estimated),
    }


# 부분청산 비율 — 전량이냐 아니냐의 이분법만 있으면 물린 포지션에서 결정이 멈춘다
EXIT_SLICES = (("1/3", 1 / 3), ("1/2", 0.5), ("전량", 1.0))


def exit_plan(held: float, avg_price: float, close: float, stop_price: float,
              market: str, is_etf: int = 0, fx: float = 1.0,
              taxable_overseas: bool = False,
              deduction_left_krw: float = 0.0) -> dict | None:
    """보유 포지션의 청산 플랜 — 지금 나가면 얼마를 회수하고 얼마를 확정하는가.

    진입 화면(손절·목표·수량)만 있으면 나가는 판단은 매번 즉흥이 된다. 특히
    매도 등급이 뜬 보유 종목에서 화면이 '추가 매수 가능 수량'만 보여주면
    물타기를 권하는 꼴이 된다. 회수액은 매도 수수료·세금을 뺀 순액이다.
    """
    if held <= 0 or avg_price <= 0:
        return None
    slices = []
    for label, ratio in EXIT_SLICES:
        qty = held * ratio
        notional = close * qty
        est = costs.estimate(market, "SELL", notional, is_etf=is_etf)
        cost = est["fee"] + est["tax"]
        pnl_krw = ((close - avg_price) * qty - cost) * fx
        # 해외 양도세는 체결 시점에 떼이지 않고 이듬해 5월에 낸다. 올해 남은
        # 250만원 공제를 반영한 '이 청산을 지금 하면 추가로 내는' 한계 세액이라야
        # 판단에 쓸 수 있다 — 공제가 남아 있으면 세금 0이라는 사실도 결정을 바꾼다.
        tax_krw = (costs.OVERSEAS_TAX_RATE
                   * max(pnl_krw - max(deduction_left_krw, 0.0), 0.0)
                   if taxable_overseas else 0.0)
        slices.append({
            "label": label,
            "quantity": round(qty, 4),
            "proceeds_krw": round((notional - cost) * fx, 2),
            "realized_pnl_krw": round(pnl_krw, 2),
            "tax_krw": round(tax_krw, 0),
            "realized_pnl_after_tax_krw": round(pnl_krw - tax_krw, 2),
        })
    # 1R = 현재가에서 손절선까지(2×ATR) — 이 앱이 포지션 사이징에 쓰는 리스크 단위.
    # 손익을 %가 아니라 "감수하는 리스크의 몇 배"로 재면 익절·추격 판단이 직접 나온다
    # (+27%보다 +2.1R이 행동에 가깝다). '평단 − 손절선'으로 재면 손절선이 평단 위로
    # 올라간 수익 포지션에서 값이 사라지는데, 익절 판단이 가장 필요한 순간이 그때다.
    r_unit = close - stop_price
    return {
        "held_quantity": round(held, 4),
        "avg_price": round(avg_price, 4),
        "r_unit": round(r_unit, 4) if r_unit > 0 else None,
        "r_multiple": round((close - avg_price) / r_unit, 2) if r_unit > 0 else None,
        "unrealized_pnl_pct": round((close / avg_price - 1) * 100, 2),
        "unrealized_pnl_krw": round((close - avg_price) * held * fx, 2),
        # 손절선이 평단 대비 어디인지 — 현재가 대비만 보면 이미 물린 폭이 안 보인다
        "stop_from_avg_pct": round((stop_price / avg_price - 1) * 100, 2),
        # 손절선이 평단 위면 그 손절은 손실 확정이 아니라 이익 확정이다 —
        # 같은 숫자를 붉게 칠하면 좋은 소식이 나쁜 소식으로 읽힌다
        "stop_locks_profit": stop_price > avg_price,
        "risk_to_stop_krw": round(max(close - stop_price, 0.0) * held * fx, 2),
        "taxable_overseas": bool(taxable_overseas),
        "deduction_left_krw": round(max(deduction_left_krw, 0.0), 0) if taxable_overseas else None,
        "slices": slices,
    }


def realized_stats(realized: list, tickers: dict, usdkrw) -> dict:
    """승률·평균 손익비 — 전부 비용 차감 후(net) 기준.
    KRW 환산은 매수/매도 환율을 각각 반영한 완전 정산값(pnl_krw)을 우선 사용한다."""
    fx = usdkrw or DEFAULT_USDKRW
    # 평단 맞춤용 보정 로트가 원가에 섞인 건은 체결가가 인위적이라 손익·승률이
    # 통째로 거짓이 된다. 집계에서 빼되 몇 건을 뺐는지는 화면에 알린다.
    excluded_count = sum(bool(r.get("basis_adjusted")) for r in realized)
    realized = [r for r in realized if not r.get("basis_adjusted")]
    total_krw = fx_krw = cost_krw = 0.0
    for r in realized:
        if r.get("pnl_krw") is not None:
            total_krw += r["pnl_krw"]
            fx_krw += r.get("fx_pnl_krw") or 0.0
            cost_krw += r.get("cost_krw") or 0.0
            continue
        cur = tickers.get(r["symbol"], {}).get("currency", "KRW")
        rate = r.get("fx_rate") or (fx if cur == "USD" else 1.0)
        total_krw += r["pnl"] * rate
    wins = [r["pnl_pct"] for r in realized if r["pnl"] > 0]
    losses = [r["pnl_pct"] for r in realized if r["pnl"] <= 0]
    avg_win = sum(wins) / len(wins) if wins else None
    avg_loss = sum(losses) / len(losses) if losses else None
    payoff = round(avg_win / abs(avg_loss), 2) if avg_win and avg_loss else None
    # 진입 등급별 성과 — "시그널 따른 매매 vs 뇌동매매"를 분리해서 본다
    by_grade: dict[str, list] = {}
    for r in realized:
        by_grade.setdefault(r.get("entry_grade") or "미기록", []).append(r)
    grade_stats = [
        {"grade": g, "count": len(rows),
         "win_rate": round(sum(r["pnl"] > 0 for r in rows) / len(rows) * 100, 1),
         "avg_pnl_pct": round(sum(r["pnl_pct"] for r in rows) / len(rows), 2)}
        for g, rows in sorted(by_grade.items(), key=lambda x: -len(x[1]))]
    return {
        "count": len(realized),
        "excluded_count": excluded_count,
        "total_pnl_krw": round(total_krw, 0),
        "fx_pnl_krw": round(fx_krw, 0),
        "cost_krw": round(cost_krw, 0),
        "cost_estimated": any(r.get("cost_estimated") for r in realized),
        "win_rate": round(len(wins) / len(realized) * 100, 1) if realized else None,
        "avg_win_pct": round(avg_win, 2) if avg_win is not None else None,
        "avg_loss_pct": round(avg_loss, 2) if avg_loss is not None else None,
        "payoff_ratio": payoff,
        "by_entry_grade": grade_stats,
    }


def build_portfolio(holdings: dict, prices: dict, tickers: dict, usdkrw,
                    cash_krw: float = 0.0, cash_usd: float = 0.0,
                    dividends: dict | None = None) -> dict:
    fx = usdkrw or DEFAULT_USDKRW
    dividends = dividends or {}
    total_div = total_return_basis = 0.0
    cash_usd_krw = cash_usd * fx
    cash_total_krw = cash_krw + cash_usd_krw
    rows, alloc = [], {}
    total_value = total_cost = 0.0
    for symbol, h in holdings.items():
        info = tickers.get(symbol, {})
        currency = info.get("currency", "KRW")
        close = prices.get(symbol)
        rate = fx if currency == "USD" else 1.0
        value = pnl = pnl_pct = None
        exit_cost = net_proceeds = net_pnl = None
        price_pnl_krw = fx_pnl_krw = pnl_krw = None
        if close is not None:
            value = close * h["quantity"]
            pnl = (close - h["avg_price"]) * h["quantity"]
            pnl_pct = round((close / h["avg_price"] - 1) * 100, 2) if h["avg_price"] else None
            total_value += value * rate
            total_cost += h["avg_price"] * h["quantity"] * rate
            label = MARKET_LABELS.get(info.get("market"), "기타")
            alloc[label] = alloc.get(label, 0.0) + value * rate
            # "수익률 -0.13%"를 본전으로 읽고 청산하면 거래세·수수료 차감 후엔
            # 손실이 확정된다. 지금 팔면 실제로 얼마가 들어오는지를 함께 낸다.
            est = costs.estimate(info.get("market", ""), "SELL", value,
                                 is_etf=info.get("is_etf", 0) or 0)
            exit_cost = round(est["fee"] + est["tax"], 4)
            net_proceeds = round(value - exit_cost, 4)
            net_pnl = round(pnl - exit_cost, 4)
            # 원화 손익을 주가 기여와 환 기여로 나눈다 — 미국주식 비중이 큰 계좌는
            # 원화 손익의 상당 부분이 환이라 배분 판단이 통째로 어긋난다.
            buy_fx = float(h.get("avg_fx", 1.0)) if currency == "USD" else 1.0
            basis = h["avg_price"] * h["quantity"]
            price_pnl_krw = round(pnl * rate, 0)
            if currency != "USD":
                fx_pnl_krw = 0.0
            elif h.get("fx_known", False):
                fx_pnl_krw = round(basis * (rate - buy_fx), 0)
            else:
                fx_pnl_krw = None  # 매수 환율 미기록 — 0으로 쓰면 "영향 없음"으로 읽힌다
            pnl_krw = (round(price_pnl_krw + fx_pnl_krw, 0)
                       if fx_pnl_krw is not None else None)
        # 배당은 주가 손익과 다른 계정에서 들어온다 — 더하지 않으면 커버드콜이
        # "-5%짜리 실패한 포지션"으로만 보이고, 그 화면은 팔라고 말하는 셈이다.
        # 매도분에 대해 받은 배당도 이 종목이 준 현금이므로 누적 전액을 쓴다.
        div_krw = round(float(dividends.get(symbol, 0.0)), 0)
        cost_row = h["avg_price"] * h["quantity"] * rate
        tr_krw = tr_pct = None
        if div_krw and pnl_krw is not None:
            tr_krw = round(pnl_krw + div_krw, 0)
            tr_pct = round(tr_krw / cost_row * 100, 2) if cost_row else None
        total_div += div_krw
        if close is not None:
            total_return_basis += cost_row
        rows.append({"symbol": symbol, "name": info.get("name", symbol),
                     "dividend_krw": div_krw,
                     "total_return_krw": tr_krw, "total_return_pct": tr_pct,
                     "market": info.get("market"), "currency": currency,
                     # 원가에 평단 보정 로트가 섞였으면 평단 기반 숫자 전체가
                     # 실거래 산물이 아니다 — 그 사실을 숫자 옆에 남긴다
                     "basis_adjusted": bool(h.get("basis_adjusted", False)),
                     "quantity": h["quantity"], "avg_price": h["avg_price"],
                     "close": close, "value": value, "pnl": pnl, "pnl_pct": pnl_pct,
                     "exit_cost": exit_cost, "net_proceeds": net_proceeds,
                     "net_pnl": net_pnl,
                     "price_pnl_krw": price_pnl_krw, "fx_pnl_krw": fx_pnl_krw,
                     "pnl_krw": pnl_krw,
                     # 통화가 섞이면 종목 통화 표시만으로는 크기를 나란히 못 본다
                     "value_krw": round(value * rate, 0) if value is not None else None,
                     "weight_pct": None})
    total_asset = total_value + cash_total_krw
    for r in rows:  # 비중 분모는 현금 포함 총자산 — 평가액만 쓰면 현금 비중만큼 부풀려진다
        if r["value_krw"] is not None and total_asset:
            r["weight_pct"] = round(r["value_krw"] / total_asset * 100, 1)
    totals = {"total_value_krw": round(total_value, 0),
              "total_cost_krw": round(total_cost, 0),
              "total_pnl_krw": round(total_value - total_cost, 0),
              "total_pnl_pct": round((total_value / total_cost - 1) * 100, 2) if total_cost else 0.0,
              # 같은 손익을 총자산으로도 나눠 함께 내려보낸다. 분모가 하나뿐이면
              # 현금 비중이 큰 계좌에서 체감 손실이 몇 배로 부풀려 읽힌다.
              "total_pnl_pct_of_asset": round((total_value - total_cost) / total_asset * 100, 2)
              if total_asset else 0.0,
              "cash_krw": round(cash_krw, 0),
              "cash_usd": round(cash_usd, 2),
              "cash_usd_krw": round(cash_usd_krw, 0),
              "total_asset_krw": round(total_asset, 0),
              "cash_pct": round(cash_total_krw / total_asset * 100, 1) if total_asset else 0.0,
              # 원화 환산에 실제로 쓴 환율. 화면에 없으면 사용자가 KRW 숫자에서
              # 역산해야 하고, 수집 실패로 기본값을 쓴 경우와 구분할 방법도 없다.
              "usdkrw": round(fx, 2),
              "usdkrw_estimated": usdkrw is None,
              # 평가손익 + 누적 배당. 배당을 세지 않는 총수익은 배당주 계좌에서
              # 실제보다 낮게 나오고, 그 숫자로 비중을 줄이면 배당까지 함께 준다.
              "dividend_krw": round(total_div, 0),
              "total_return_krw": round(total_value - total_cost + total_div, 0)
              if total_div else None,
              "total_return_pct": round((total_value - total_cost + total_div)
                                        / total_return_basis * 100, 2)
              if total_div and total_return_basis else None}
    allocation = [{"label": k, "value_krw": round(v, 0)} for k, v in
                  sorted(alloc.items(), key=lambda x: -x[1])]
    if cash_total_krw > 0:
        allocation.append({"label": "현금", "value_krw": round(cash_total_krw, 0)})
    return {"holdings": rows, "totals": totals, "allocation": allocation}


def _periods_per_year(index) -> float:
    """관측 인덱스에서 연간 관측 수를 실측 — 주식 252, 코인 365를 상수로 박으면
    혼합 계좌에서 어긋난다. 거래일 교집합을 쓰면 그 수 자체가 자산 구성에 따라 달라진다."""
    span_days = (index[-1] - index[0]).days
    if span_days <= 0:
        return 252.0
    return max(len(index) - 1, 1) / (span_days / 365.25)


CLUSTER_CORR = 0.7  # 이 이상 동행하면 사실상 같은 포지션으로 본다


def _corr_clusters(frame, weights: list, tickers: dict) -> list[dict]:
    """상관 CLUSTER_CORR 이상으로 이어진 종목들을 한 묶음으로 합친다.

    "최대 종목 비중 9.3%"는 안전해 보이지만 반도체 5종목이 0.7 이상으로 묶여
    있으면 실제로 걸린 베팅은 그 합이다. 동반 하락 때 계좌가 맞는 타격은
    종목별 비중이 아니라 이 묶음 크기에 가깝다.

    이어짐(transitive)으로 묶는다 — A-B가 0.8, B-C가 0.8이면 A와 C가 직접
    높지 않아도 같은 흐름을 타는 하나의 덩어리다.
    """
    m = frame.pct_change().corr()
    symbols = list(m.columns)
    parent = {s: s for s in symbols}

    def find(s):
        while parent[s] != s:
            parent[s] = parent[parent[s]]
            s = parent[s]
        return s

    for i, a in enumerate(symbols):
        for b in symbols[i + 1:]:
            v = float(m.loc[a, b])
            if v >= CLUSTER_CORR:
                parent[find(a)] = find(b)

    w = {x["symbol"]: x["weight_pct"] for x in weights}
    groups: dict[str, list] = {}
    for s in symbols:
        groups.setdefault(find(s), []).append(s)
    out = [{"symbols": g,
            "names": [tickers.get(s, {}).get("name", s) for s in g],
            "weight_pct": round(sum(w.get(s, 0.0) for s in g), 1)}
           for g in groups.values() if len(g) >= 2]
    out.sort(key=lambda c: -c["weight_pct"])
    return out


def account_risk(holdings: dict, closes: dict, tickers: dict, usdkrw,
                 cash_krw: float = 0.0) -> dict | None:
    """계좌 단위 리스크 — 종목 비중(집중도), 상관계수, 변동성/MDD.

    현재 보유 수량을 과거 종가에 그대로 적용한 근사이며 환율은 현재 값 고정.
    달력은 **거래일 교집합**으로 맞춘다. 주말까지 포함한 합집합에 ffill을 걸면
    주식은 수익률 0인 행이 대량으로 끼어 변동성이 눌리고(√(252/365) ≈ -17%),
    상관계수는 0 쪽으로 밀려 분산 효과가 실제보다 커 보인다.
    """
    fx = usdkrw or DEFAULT_USDKRW
    series = {s: closes[s] for s in holdings
              if s in closes and closes[s] is not None and len(closes[s]) > 1}
    if not series:
        return None
    frame = pd.DataFrame(series).dropna()
    if len(frame) < 20:
        return None
    ppy = _periods_per_year(frame.index)
    rates = {s: (fx if tickers.get(s, {}).get("currency") == "USD" else 1.0)
             for s in frame.columns}
    qty = {s: holdings[s]["quantity"] for s in frame.columns}
    port = sum(frame[s] * qty[s] * rates[s] for s in frame.columns)
    rets = port.pct_change().dropna()
    mdd = float(((port / port.cummax()) - 1).min() * 100)

    last_vals = {s: float(frame[s].iloc[-1]) * qty[s] * rates[s] for s in frame.columns}
    total_asset = sum(last_vals.values()) + max(cash_krw, 0.0)
    weights = sorted(
        [{"symbol": s, "name": tickers.get(s, {}).get("name", s),
          "weight_pct": round(v / total_asset * 100, 1)} for s, v in last_vals.items()],
        key=lambda w: -w["weight_pct"])

    clusters = _corr_clusters(frame, weights, tickers) if len(frame.columns) >= 2 else []
    corr = None
    if len(frame.columns) >= 2:
        m = frame.pct_change().corr()
        symbols = list(m.columns)
        corr = {"symbols": symbols,
                "names": [tickers.get(s, {}).get("name", s) for s in symbols],
                "matrix": [[round(float(m.iloc[i, j]), 2) for j in range(len(symbols))]
                           for i in range(len(symbols))]}
    return {
        "days": len(frame),
        "weights": weights,
        "max_weight_pct": weights[0]["weight_pct"] if weights else None,
        # 종목별 비중이 낮아도 상관 높은 묶음의 합산이 실제로 걸린 베팅 크기다
        "clusters": clusters,
        "max_cluster_pct": clusters[0]["weight_pct"] if clusters else None,
        "cluster_threshold": CLUSTER_CORR,
        "volatility_pct": round(float(rets.std() * (ppy ** 0.5) * 100), 1),
        "periods_per_year": round(ppy, 1),
        "mdd_pct": round(mdd, 2),
        # 이 MDD는 "지금 포지션을 이 구간 내내 들고 있었다면"의 값이지 실제 계좌 낙폭이 아니다
        "mdd_note": "현 보유 수량을 과거 전 구간에 소급 적용한 가상 낙폭",
        "calendar_note": (f"보유 종목이 모두 거래된 날만 사용 (교집합 {len(frame)}일, "
                          f"연 {round(ppy)}회 기준 연율화)"),
        "corr": corr,
    }
