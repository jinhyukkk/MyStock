"""한국투자증권(KIS) REST 클라이언트 — 토큰·잔고·시세·현금주문.

모의(paper)/실전(live)은 도메인과 TR ID만 다르고 요청 형식은 같다. 전환은
.env의 KIS_MODE 하나로 한다 — 코드 경로가 갈라지면 모의로 검증한 것과
실전에서 도는 것이 다른 물건이 된다.

키는 .env(.env.local)에만 둔다. 이 파일 어디에서도 키 값을 로그·예외 메시지에
싣지 않는다 — 예외는 KIS가 준 응답 본문만 전달한다.
"""
import json
import os
import time

import requests

from app import db

DOMAIN = {
    "live": "https://openapi.koreainvestment.com:9443",
    "paper": "https://openapivts.koreainvestment.com:29443",
}
# TR ID — [모드][동작]. 모의는 실전 TR의 T를 V로 바꾼 것이다
TR = {
    "live": {"buy": "TTTC0802U", "sell": "TTTC0801U", "balance": "TTTC8434R"},
    "paper": {"buy": "VTTC0802U", "sell": "VTTC0801U", "balance": "VTTC8434R"},
}
TIMEOUT = 10


class KisError(Exception):
    """KIS 호출 실패 — 메시지는 그대로 화면(detail)까지 올라간다."""


def mode() -> str:
    return os.environ.get("KIS_MODE", "paper").lower()


def configured() -> bool:
    return all(os.environ.get(k) for k in
               ("KIS_APP_KEY", "KIS_APP_SECRET", "KIS_ACCOUNT"))


class Client:
    """conn은 토큰 캐시(meta 테이블)용 — KIS는 토큰 발급을 분당 1회로 제한해서
    서버 재시작마다 새로 받으면 바로 rate limit에 걸린다."""

    def __init__(self, conn):
        if not configured():
            raise KisError("KIS 키가 없습니다. .env에 KIS_APP_KEY / "
                           "KIS_APP_SECRET / KIS_ACCOUNT를 설정하세요.")
        self.conn = conn
        self.mode = mode()
        self.base = DOMAIN[self.mode]
        self.key = os.environ["KIS_APP_KEY"]
        self.secret = os.environ["KIS_APP_SECRET"]
        acct = os.environ["KIS_ACCOUNT"].replace("-", "")
        # 계좌는 "12345678-01" 또는 "1234567801" — 앞 8자리 + 상품코드 2자리
        self.cano, self.prdt = acct[:8], (acct[8:] or "01")

    # ── 토큰 ──────────────────────────────────────────────────────────────
    def _token(self) -> str:
        cached = db.get_meta(self.conn, f"kis_token_{self.mode}")
        if cached:
            tok = json.loads(cached)
            # 만료 10분 전부터 재발급 — 주문 도중 만료되는 창을 없앤다
            if tok.get("expires_at", 0) - 600 > time.time():
                return tok["token"]
        r = requests.post(f"{self.base}/oauth2/tokenP", timeout=TIMEOUT,
                          json={"grant_type": "client_credentials",
                                "appkey": self.key, "appsecret": self.secret})
        body = r.json()
        if "access_token" not in body:
            raise KisError(f"토큰 발급 실패: {body.get('error_description') or body}")
        db.set_meta(self.conn, f"kis_token_{self.mode}", json.dumps({
            "token": body["access_token"],
            "expires_at": time.time() + int(body.get("expires_in", 86400)),
        }))
        return body["access_token"]

    def _headers(self, tr_id: str) -> dict:
        return {"authorization": f"Bearer {self._token()}",
                "appkey": self.key, "appsecret": self.secret,
                "tr_id": tr_id, "custtype": "P"}

    def _check(self, r: requests.Response) -> dict:
        body = r.json()
        # rt_cd "0"이 성공 — HTTP 200이어도 rt_cd가 실패일 수 있다
        if body.get("rt_cd") != "0":
            raise KisError(f"KIS 오류: {body.get('msg1') or body}")
        return body

    # ── 조회 ──────────────────────────────────────────────────────────────
    def balance(self) -> dict:
        """예수금·보유 목록·총평가액. 사이징 분모와 보유 여부 판단에 쓴다."""
        r = requests.get(
            f"{self.base}/uapi/domestic-stock/v1/trading/inquire-balance",
            headers=self._headers(TR[self.mode]["balance"]), timeout=TIMEOUT,
            params={"CANO": self.cano, "ACNT_PRDT_CD": self.prdt,
                    "AFHR_FLPR_YN": "N", "OFL_YN": "", "INQR_DVSN": "02",
                    "UNPR_DVSN": "01", "FUND_STTL_ICLD_YN": "N",
                    "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "00",
                    "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""})
        body = self._check(r)
        holdings = [{"symbol": h["pdno"], "name": h.get("prdt_name", ""),
                     "qty": float(h.get("hldg_qty", 0) or 0),
                     "avg_price": float(h.get("pchs_avg_pric", 0) or 0)}
                    for h in body.get("output1", [])
                    if float(h.get("hldg_qty", 0) or 0) > 0]
        summary = (body.get("output2") or [{}])[0]
        return {
            "cash_krw": float(summary.get("dnca_tot_amt", 0) or 0),
            "total_eval_krw": float(summary.get("tot_evlu_amt", 0) or 0),
            "holdings": holdings,
        }

    def price(self, symbol: str) -> float:
        """현재가 — TR은 모의/실전 공통(FHKST01010100)."""
        r = requests.get(
            f"{self.base}/uapi/domestic-stock/v1/quotations/inquire-price",
            headers=self._headers("FHKST01010100"), timeout=TIMEOUT,
            params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": symbol})
        return float(self._check(r)["output"]["stck_prpr"])

    # ── 주문 ──────────────────────────────────────────────────────────────
    def order(self, symbol: str, side: str, qty: int) -> str:
        """국내주식 현금 시장가 주문. 주문번호를 돌려준다.

        시장가(ORD_DVSN 01)로 내는 이유 — 전략의 진입 규칙이 "신호 익일
        시가"라서 가격을 지정하는 순간 백테스트와 다른 전략이 된다. 미체결로
        신호를 흘려보내는 것이 불리한 체결가보다 더 큰 오차다.
        """
        if side not in ("BUY", "SELL"):
            raise KisError(f"알 수 없는 주문 방향: {side}")
        r = requests.post(
            f"{self.base}/uapi/domestic-stock/v1/trading/order-cash",
            headers=self._headers(TR[self.mode]["buy" if side == "BUY" else "sell"]),
            timeout=TIMEOUT,
            json={"CANO": self.cano, "ACNT_PRDT_CD": self.prdt,
                  "PDNO": symbol, "ORD_DVSN": "01",
                  "ORD_QTY": str(int(qty)), "ORD_UNPR": "0"})
        return self._check(r)["output"]["ODNO"]
