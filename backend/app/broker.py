"""CODEF 잔고 응답 → 이 앱의 보유·예수금 형태로 변환.

여기는 순수 변환만 한다(네트워크·DB 없음). 증권사마다 빈 문자열·콤마·부호가
제각각이라 파싱이 조용히 틀리면 총자산이 통째로 어긋나므로, 이 부분만 따로 두고
테스트로 고정한다.
"""

KR_CODE, US_CODE = "01", "04"  # resProductTypeCd


def num(v) -> float:
    """CODEF는 모든 숫자를 문자열로 준다 — 빈 값·콤마·공백을 0/실수로 흡수한다."""
    if v is None:
        return 0.0
    s = str(v).replace(",", "").strip()
    if not s or s in ("-", "+"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def normalize_code(raw: str, product_cd: str) -> str | None:
    """증권사 종목코드를 앱의 심볼로. 확신이 서지 않으면 None(=매핑 실패로 보고)."""
    s = (raw or "").strip().upper()
    if not s:
        return None
    if product_cd == KR_CODE:
        # 일부 증권사는 'A005930'처럼 앞에 한 글자를 붙인다
        if len(s) == 7 and s[0] == "A" and s[1:].isalnum():
            s = s[1:]
        # 2024년 이후 신형 코드는 다섯째 자리가 문자다('0167A0'). 숫자만 남기면
        # 실재하는 다른 종목('001670')이 되어 엉뚱한 시세로 평가손익이 계산된다.
        if len(s) == 6 and s.isalnum() and s[:4].isdigit():
            return s
        return s.zfill(6) if s.isdigit() and 1 <= len(s) <= 6 else None
    if product_cd == US_CODE:
        # 티커만 받는다. ISIN(US0378331005)·거래소 접미사가 붙은 코드는 앱의 심볼
        # 체계와 다르므로 억지로 맞추지 않고 매핑 실패로 올린다 — 잘못 맞추면
        # 엉뚱한 종목의 시세로 평가손익이 계산된다.
        base = s.split(".")[0]
        return base if base.isalpha() and 1 <= len(base) <= 5 else None
    return None


def parse_balance(data: dict, account: str | None = None) -> dict:
    """주식잔고조회 응답 1건 → {cash_krw, cash_usd, holdings, unmapped}.

    holdings 원소: {code, market, currency, name, quantity, avg_price, basis_missing}
    code는 아직 앱 심볼로 확정되기 전 값이며, 매핑 실패한 행은 unmapped로 넘긴다.
    """
    cash_krw = num(data.get("resDepositReceivedD2")) or num(data.get("resDepositReceived"))
    # 원화환산 외화예수금(resDepositReceivedF)이 아니라 통화별 원금액을 쓴다 —
    # 환산값을 달러 예수금으로 넣으면 총자산이 환율 배수만큼 부풀어 오른다.
    cash_usd = 0.0
    for f in data.get("resDepositReceivedFList") or []:
        if (f.get("resAccountCurrency") or "").upper() == "USD":
            # 미래에셋은 금액을 resProductType에 담아 보낸다 — 필드명이 증권사마다
            # 어긋난다. 못 읽으면 달러 예수금이 통째로 0이 되어 총자산이 그만큼
            # 작아지고, 비중·현금비중·계좌 리스크%가 전부 부풀려진다.
            cash_usd += num(f.get("resAmount")) or num(f.get("resProductType"))

    holdings, unmapped = [], []
    for item in data.get("resItemList") or []:
        product_cd = (item.get("resProductTypeCd") or "").strip()
        if product_cd not in (KR_CODE, US_CODE):
            continue  # 펀드·채권·RP 등은 이 앱이 다루는 종목이 아니다
        qty = num(item.get("resQuantity"))
        if qty <= 0:
            continue
        name = (item.get("resItemName") or "").strip()
        code = normalize_code(item.get("resItemCode"), product_cd)
        if not code:
            unmapped.append({"name": name, "raw_code": item.get("resItemCode"),
                             "quantity": qty})
            continue
        avg, basis_missing = _avg_price(item, qty)
        holdings.append({
            "code": code,
            "market": "KR" if product_cd == KR_CODE else "US",
            "currency": (item.get("resAccountCurrency") or
                         ("KRW" if product_cd == KR_CODE else "USD")).upper(),
            "name": name or code,
            "quantity": qty,
            "avg_price": avg,
            "basis_missing": basis_missing,
            "account": account,
        })
    return {"cash_krw": cash_krw, "cash_usd": cash_usd,
            "holdings": holdings, "unmapped": unmapped}


def _avg_price(item: dict, qty: float) -> tuple[float, bool]:
    """(평단, 미제공여부). 평균매입가는 필수 항목이 아니라 안 주는 증권사가 있다.

    평단을 0으로 두면 평가손익이 '평가액 전액이 이익'으로 찍힌다 — 그 화면을 보고
    익절하면 실제로는 손실일 수 있다. 그래서 매입금액에서 역산하고, 그것도 없으면
    현재가로 채운 뒤(손익 0) 미제공 사실을 함께 올린다.
    """
    avg = num(item.get("resAvgPresentAmt"))
    if avg > 0:
        return avg, False
    purchase = num(item.get("resPurchaseAmount"))
    if purchase > 0 and qty > 0:
        return purchase / qty, False
    return num(item.get("resPresentAmt")), True


def merge(parsed_list: list[dict]) -> dict:
    """여러 계좌의 파싱 결과를 합산한다. 같은 종목은 수량 가중 평균으로 평단을 합친다."""
    cash_krw = sum(p["cash_krw"] for p in parsed_list)
    cash_usd = sum(p["cash_usd"] for p in parsed_list)
    merged: dict[str, dict] = {}
    for p in parsed_list:
        for h in p["holdings"]:
            cur = merged.get(h["code"])
            if cur is None:
                merged[h["code"]] = dict(h)
                continue
            total = cur["quantity"] + h["quantity"]
            cur["avg_price"] = ((cur["avg_price"] * cur["quantity"] +
                                 h["avg_price"] * h["quantity"]) / total) if total else 0.0
            cur["quantity"] = total
            cur["basis_missing"] = cur["basis_missing"] or h["basis_missing"]
    return {"cash_krw": cash_krw, "cash_usd": cash_usd,
            "holdings": list(merged.values()),
            "unmapped": [u for p in parsed_list for u in p["unmapped"]]}


# ── 종합자산 (주식잔고조회가 주지 않는 자산) ──────────────────────────────────
ETC_CODE = "99"  # resProductTypeCd — 외화예수금이 이 칸으로 온다
ASSET_TYPE_NAMES = {"02": "펀드", "03": "CMA", "05": "신탁/퇴직연금", "06": "채권",
                    "07": "RP", "08": "CD/CP", "09": "ELS/DLS", "10": "해외뮤추얼펀드",
                    "11": "Wrap", "12": "외화RP", "13": "연금저축", "14": "선물옵션"}


def parse_assets(data: dict, account: str | None = None) -> tuple[list[dict], list[dict]]:
    """종합자산 응답 1건 → (더해야 할 자산, 이미 세고 있어서 뺀 행).

    주식(수량>0)·해외주식은 보유종목으로, '99: 기타'는 외화예수금으로 이미 세고
    있다 — 그대로 더하면 같은 돈이 두 번 잡힌다. 반대로 발행어음처럼 상품유형이
    '주식'인데 수량이 0이고 평가금액만 있는 행은 현금성 자산이라 남겨야 한다.

    평가액을 원화로 확신할 수 없는 행은 빼고 알린다 — 통화가 섞인 채 더하면
    총자산이 환율 배수만큼 어긋난다.
    """
    keep, skipped = [], []
    for it in data.get("resItemList") or []:
        cd = (it.get("resProductTypeCd") or "").strip()
        value = num(it.get("resValuationAmt"))
        if value <= 0:
            continue
        qty, name = num(it.get("resQuantity")), (it.get("resItemName") or "").strip()
        row = {"name": name, "type_cd": cd, "value_krw": value, "account": account}
        if cd == US_CODE or cd == ETC_CODE or (cd == KR_CODE and qty > 0):
            skipped.append({**row, "reason": "보유종목·외화예수금으로 이미 반영"})
            continue
        if (it.get("resAccountCurrency") or "KRW").upper() != "KRW":
            skipped.append({**row, "reason": "원화 평가액이 아님"})
            continue
        keep.append({**row,
                     # 발행어음을 '주식'으로 부르면 배분 화면에서 주식 비중에 섞인다
                     "type": ("현금성 상품" if cd == KR_CODE
                              else ASSET_TYPE_NAMES.get(cd, "기타 자산")),
                     "name": name or ASSET_TYPE_NAMES.get(cd, "기타 자산")})
    return keep, skipped


# ── 입출금내역 ────────────────────────────────────────────────────────────
# 증권사 거래내역에는 입출금·배당·이자뿐 아니라 매수/매도 대금까지 한 줄씩 섞여 있다.
# 적요는 자유 텍스트로 보이지만 실제로 오는 값은 증권사가 찍는 정형 문구뿐이다.
# 그래서 그 문구 자체를 보고, 확정할 수 없는 줄은 방향(입금/출금)만 인정한다.
#
# '매매'·'약정'·'장내'처럼 넓은 단어로 거르면 이체 적요에 그 글자가 우연히 섞였을 때
# 입출금이 조용히 사라진다. 매매 대금은 trades 원장이 진실이므로 버리되, 버리는
# 근거는 실제 관측된 문구로 좁힌다.
TRADE_WORDS = ("주식매수", "주식매도", "매수입고", "매도출고", "매수출금", "매도입금",
               "권리선반영", "액면분할")
# 계좌 밖으로 나간 돈이 아닌 줄 — 넣으면 원금 흐름이 양방향으로 부풀려진다.
#  - 계좌대체: 본인 계좌 간 이동. 양쪽 계좌를 다 동기화하므로 입금·출금에 두 번 잡힌다.
#  - 발행어음·RP·MMF: 예수금을 현금성 상품에 굴리는 스윕. 자동으로 반복되는 탓에
#    건수·금액이 실제 입출금보다 훨씬 커서, 넣으면 원금 흐름을 통째로 뒤덮는다.
TRANSFER_WORDS = ("계좌대체", "발행어음", "RP매수", "RP매도", "MMF", "MMW")
DIVIDEND_WORDS = ("배당", "분배금")
INTEREST_WORDS = ("이용료", "이자")


def parse_transactions(data: dict, account: str | None = None) -> list[dict]:
    """입출금내역 응답 1건 → [{date, desc, amount_in, amount_out, ext_key}].

    ext_key는 같은 기간을 다시 조회해도 같은 값이 나와야 한다(중복 적재 방지).
    금액·적요가 완전히 같은 거래가 하루에 두 번 있을 수 있으므로 그날 안에서의
    순번을 함께 넣는다 — 순번이 없으면 두 번째 입금이 영영 안 들어온다.
    """
    rows, seen = [], {}
    for h in data.get("resTrHistoryList") or []:
        date = (h.get("resAccountTrDate") or "").strip()
        if len(date) != 8 or not date.isdigit():
            continue  # 날짜 없는 줄은 합계·구분선이다
        amount_in, amount_out = num(h.get("resAccountIn")), num(h.get("resAccountOut"))
        if amount_in <= 0 and amount_out <= 0:
            continue
        desc = " ".join(s for s in ((h.get(f"resAccountDesc{i}") or "").strip()
                                    for i in (1, 2, 3, 4)) if s)
        base = f"codef:{account or ''}:{date}:{h.get('resAccountTrTime') or ''}:" \
               f"{amount_in:.0f}:{amount_out:.0f}:{desc}"
        seq = seen[base] = seen.get(base, 0) + 1
        rows.append({"date": f"{date[:4]}-{date[4:6]}-{date[6:]}", "desc": desc,
                     "amount_in": amount_in, "amount_out": amount_out,
                     "account": account, "ext_key": f"{base}#{seq}"})
    return rows


def classify_flow(row: dict) -> str | None:
    """거래 한 줄 → cash_flows의 flow_type. 매매·계좌대체·분류 불가면 None."""
    text = row.get("desc") or ""
    if any(w in text for w in TRADE_WORDS + TRANSFER_WORDS):
        return None
    if row["amount_in"] > 0:
        if any(w in text for w in DIVIDEND_WORDS):
            return "DIVIDEND"
        if any(w in text for w in INTEREST_WORDS):
            return "INTEREST"
        return "DEPOSIT"
    return "WITHDRAW" if row["amount_out"] > 0 else None
