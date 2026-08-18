"""CODEF(헥토데이터) 증권사 오픈API 클라이언트.

증권사 계좌를 직접 붙는 대신 CODEF가 스크래핑해 준 잔고를 받아온다.
쓰는 엔드포인트는 셋뿐이다:
  - POST /v1/account/create              계정 등록 → connectedId 발급 (1회)
  - POST /v1/kr/stock/a/account/account-list   전계좌 목록
  - POST /v1/kr/stock/a/account/balance-inquiry 주식잔고 (예수금 + 보유종목)
  - POST /v1/kr/stock/a/account/transaction-list  입출금내역 (기간별 거래)

주의: CODEF는 응답 본문을 URL 인코딩해서 준다. 디코딩 없이 json.loads 하면 깨진다.
"""
import base64
import json
import os
import threading
import time
import urllib.parse

import requests
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_der_public_key

TOKEN_URL = "https://oauth.codef.io/oauth/token"
DEMO_HOST = "https://development.codef.io"
PROD_HOST = "https://api.codef.io"

ACCOUNT_CREATE = "/v1/account/create"
ACCOUNT_LIST = "/v1/kr/stock/a/account/account-list"
BALANCE_INQUIRY = "/v1/kr/stock/a/account/balance-inquiry"
TRANSACTION_LIST = "/v1/kr/stock/a/account/transaction-list"
FINANCIAL_ASSETS = "/v1/kr/stock/a/account/financial-assets"

SUCCESS = "CF-00000"
TIMEOUT = 120  # 잔고조회는 대상 증권사 사이트를 실제로 긁는다 — 문서상 timeout 100초


class CodefError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(f"[{code}] {message}")
        self.code, self.message = code, message


def host() -> str:
    return DEMO_HOST if os.environ.get("CODEF_ENV", "demo") == "demo" else PROD_HOST


def is_configured() -> bool:
    return all(os.environ.get(k) for k in
               ("CODEF_CLIENT_ID", "CODEF_CLIENT_SECRET", "CODEF_PUBLIC_KEY"))


# accessToken은 일주일 유효하므로 재사용한다. 호출마다 발급받으면 느릴 뿐 아니라
# CODEF가 비정상 호출로 보고 서비스를 제한할 수 있다.
_token: dict = {"value": None, "exp": 0.0}
_token_lock = threading.Lock()


def _access_token() -> str:
    with _token_lock:
        if _token["value"] and time.time() < _token["exp"]:
            return _token["value"]
        cid, secret = os.environ.get("CODEF_CLIENT_ID"), os.environ.get("CODEF_CLIENT_SECRET")
        if not cid or not secret:
            raise CodefError("CF-LOCAL", "CODEF_CLIENT_ID/SECRET 미설정 — .env를 확인하세요")
        auth = base64.b64encode(f"{cid}:{secret}".encode()).decode()
        try:
            res = requests.post(TOKEN_URL, data="grant_type=client_credentials&scope=read",
                                headers={"Authorization": f"Basic {auth}",
                                         "Content-Type": "application/x-www-form-urlencoded"},
                                timeout=30)
        except requests.RequestException as e:
            raise CodefError("CF-LOCAL", f"CODEF 연결 실패 — {e}") from e
        if res.status_code != 200:
            raise CodefError("CF-LOCAL",
                             f"토큰 발급 실패 (HTTP {res.status_code}) — CODEF_CLIENT_ID/SECRET와 "
                             f"CODEF_ENV(demo/prod)가 서로 맞는지 확인하세요")
        body = _decode(res.text)
        _token["value"] = body["access_token"]
        # 만료 1시간 전에 미리 버린다 — 경계에서 401을 맞고 동기화가 통째로 실패하지 않게
        _token["exp"] = time.time() + max(int(body.get("expires_in", 604800)) - 3600, 60)
        return _token["value"]


def encrypt(plain: str) -> str:
    """CODEF 공개키로 RSA 암호화(PKCS#1 v1.5) 후 base64.

    비밀번호류는 평문으로 보낼 수 없다. 암호문은 CODEF만 풀 수 있으므로
    계좌비밀번호는 이 결과만 저장해 두고 재사용한다(우리 DB에는 평문이 남지 않는다).
    """
    pub = os.environ.get("CODEF_PUBLIC_KEY")
    if not pub:
        raise CodefError("CF-LOCAL", "CODEF_PUBLIC_KEY 미설정 — .env를 확인하세요")
    # 키가 잘못 붙여넣어진 경우가 흔하다. 원본 예외가 그대로 500이 되면 화면에는
    # "Internal Server Error"만 남아 사용자가 무엇을 고쳐야 할지 알 수 없다.
    try:
        key = load_der_public_key(base64.b64decode(pub))
    except Exception as e:
        raise CodefError("CF-LOCAL",
                         "CODEF_PUBLIC_KEY 형식이 올바르지 않습니다 — 키 관리의 publicKey를 "
                         "줄바꿈 없이 그대로 넣으세요") from e
    return base64.b64encode(key.encrypt(plain.encode(), padding.PKCS1v15())).decode()


def _decode(text: str) -> dict:
    """CODEF 응답은 URL 인코딩된 JSON이다 — 디코딩 없이 파싱하면 깨진다."""
    try:
        return json.loads(urllib.parse.unquote_plus(text))
    except ValueError as e:
        raise CodefError("CF-LOCAL", f"CODEF 응답을 해석하지 못했습니다 — {text[:120]}") from e


def _post(path: str, body: dict) -> dict:
    try:
        res = requests.post(host() + path, json=body, timeout=TIMEOUT,
                            headers={"Authorization": f"Bearer {_access_token()}",
                                     "Content-Type": "application/json"})
    except requests.RequestException as e:
        raise CodefError("CF-LOCAL", f"CODEF 연결 실패 — {e}") from e
    if res.status_code != 200:
        raise CodefError("CF-LOCAL", f"{path} 실패 (HTTP {res.status_code})")
    payload = _decode(res.text)
    result = payload.get("result") or {}
    if result.get("code") != SUCCESS:
        raise CodefError(result.get("code", "CF-LOCAL"),
                         result.get("message") or result.get("extraMessage") or "알 수 없는 오류")
    return payload.get("data") or {}


def create_account(organization: str, login_type: str, password: str,
                   user_id: str | None = None, der_file: str | None = None,
                   key_file: str | None = None) -> str:
    """계정 등록 → connectedId. login_type "0"=인증서, "1"=아이디/패스워드.

    password는 인증서 방식이면 인증서 암호, 아이디 방식이면 로그인 비밀번호.
    증권(businessType=ST)의 clientType은 통합(A)이다.
    """
    entry = {"countryCode": "KR", "businessType": "ST", "clientType": "A",
             "organization": organization, "loginType": login_type,
             "password": encrypt(password)}
    if login_type == "0":
        entry.update({"certType": "1", "derFile": der_file or "", "keyFile": key_file or ""})
        if user_id:  # 키움·대신 복수 아이디 계정은 인증서에 아이디를 함께 요구한다
            entry["id"] = user_id
    else:
        entry["id"] = user_id or ""
    data = _post(ACCOUNT_CREATE, {"accountList": [entry]})
    cid = data.get("connectedId")
    if not cid:
        errors = data.get("errorList") or [{}]
        raise CodefError(errors[0].get("code", "CF-LOCAL"),
                         errors[0].get("message", "커넥티드 아이디 발급 실패"))
    return cid


def account_list(connected_id: str, organization: str) -> list[dict]:
    data = _post(ACCOUNT_LIST, {"connectedId": connected_id, "organization": organization})
    return _as_list(data)


def balance(connected_id: str, organization: str, account: str,
            account_password_enc: str | None = None) -> dict:
    """주식잔고조회 — 예수금·외화예수금·종목별 보유. account_password_enc는 RSA 암호문."""
    body = {"connectedId": connected_id, "organization": organization,
            "account": "".join(c for c in account if c.isdigit())}
    if account_password_enc:
        body["accountPassword"] = account_password_enc
    data = _post(BALANCE_INQUIRY, body)
    rows = _as_list(data)
    return rows[0] if rows else {}


def financial_assets(connected_id: str, organization: str, account: str,
                     account_password_enc: str | None = None) -> list[dict]:
    """종합자산 — 계좌의 모든 상품(발행어음·펀드·채권 등)을 원화 평가액으로 준다.

    주식잔고조회는 주식만 주기 때문에 발행어음·펀드에 들어있는 돈이 총자산에서
    통째로 빠진다. 종목별 평단·통화는 잔고조회가 정확하므로 이 응답은 '잔고조회가
    주지 않는 자산'을 채우는 데만 쓴다.
    """
    body = {"connectedId": connected_id, "organization": organization,
            "account": "".join(c for c in account if c.isdigit()),
            "inquiryType": "0"}  # 0 = 결제기준. 2는 금융상품이 빠져 이 API를 쓰는 뜻이 없다
    if account_password_enc:
        body["accountPassword"] = account_password_enc
    return _as_list(_post(FINANCIAL_ASSETS, body))


def transactions(connected_id: str, organization: str, account: str,
                 start_date: str, end_date: str,
                 account_password_enc: str | None = None) -> list[dict]:
    """입출금내역 — 기간(YYYYMMDD) 안의 계좌 거래내역.

    조회 가능 기간은 증권사마다 다르다(키움 3개월, 삼성 CMA 3개월 등). CODEF가
    요청 시작일이 한도를 넘으면 가능한 날짜까지 자동으로 줄여서 처리한다.
    """
    body = {"connectedId": connected_id, "organization": organization,
            "account": "".join(c for c in account if c.isdigit()),
            "startDate": start_date, "endDate": end_date,
            "orderBy": "1"}  # 과거순 — 같은 날 중복 거래의 순번이 재조회에도 안 흔들린다
    if account_password_enc:
        body["accountPassword"] = account_password_enc
    return _as_list(_post(TRANSACTION_LIST, body))


def _as_list(data) -> list[dict]:
    """CODEF는 단건이면 객체, 다건이면 리스트로 준다 — 항상 리스트로 맞춘다."""
    if isinstance(data, list):
        return [d for d in data if isinstance(d, dict)]
    return [data] if isinstance(data, dict) and data else []
