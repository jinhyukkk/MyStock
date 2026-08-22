"""미등록 종목의 임시 조회(preview).

종목 상세는 `tickers` 행이 있어야 열린다. 이 모듈은 행이 없는 심볼을 요청받았을 때
백그라운드에서 해석·수집해 행을 만든다. 요청 경로에서 하지 않는 이유는
`refresh_all`의 시세·시그널·재무 수집이 수 초 걸리기 때문이다 — 심볼 해석
자체(`fetchers.search_symbols`)는 `_krx_listing`이 `@lru_cache(maxsize=1)`라
프로세스 첫 호출 이후로는 빠르다.

여기서 만든 행은 `in_watchlist=0`이라 `service._active_tickers`의 시간당 갱신 대상에
들어가지 않는다. 한 번 열어본 것만으로 매시간 외부 호출이 늘어나면 안 된다.
"""
import threading
import time

from app import db, fetchers, service

# 일시적 네트워크 장애 한 번이 그 심볼을 영구 실패로 굳히면, 사용자가 새로고침을
# 눌러도 계속 같은 에러만 본다. 5분 뒤에는 다시 시도하게 한다.
FAILURE_TTL_SEC = 300

_lock = threading.Lock()
_inflight: set[str] = set()
_failures: dict[str, tuple[float, str]] = {}   # symbol -> (기록 시각, 메시지)


def reset() -> None:
    """테스트 격리용 — 모듈 레벨 상태는 프로세스 수명 동안 남는다."""
    with _lock:
        _inflight.clear()
        _failures.clear()


def _acquire(symbol: str) -> bool:
    """이 호출이 수집을 시작해야 하면 True.

    프론트가 2초마다 같은 URL을 다시 부르므로, 이게 없으면 폴링 한 번마다
    외부 수집 job이 새로 뜬다."""
    with _lock:
        if symbol in _inflight:
            return False
        _inflight.add(symbol)
        return True


def _release(symbol: str) -> None:
    with _lock:
        _inflight.discard(symbol)


def is_inflight(symbol: str) -> bool:
    """이 심볼의 수집 job이 아직 돌고 있으면 True.

    `_job`은 `db.upsert_ticker`를 먼저 commit하고 나서(행이 생김) `refresh_all`로
    시세를 채운다(수 초). 그 사이에는 행이 있어도 candles/signal/risk가 비어 있다 —
    `api.ticker_detail`이 행의 존재만 보고 ready를 주면 폴링이 그 창에서 멈춰버린다."""
    with _lock:
        return symbol in _inflight


def _fail(symbol: str, message: str) -> None:
    with _lock:
        _failures[symbol] = (time.monotonic(), message)


def _recent_failure(symbol: str) -> str | None:
    with _lock:
        hit = _failures.get(symbol)
        if hit is None:
            return None
        at, message = hit
        if time.monotonic() - at >= FAILURE_TTL_SEC:
            del _failures[symbol]
            return None
        return message


def _resolve(symbol: str) -> dict | None:
    """검색 결과에서 심볼이 **정확히** 일치하는 1건.

    부분 일치를 받아들이면 사용자가 요청하지 않은 종목이 그 URL에 눌러앉는다 —
    `/ticker/00593`이 삼성전자로 열리면 그 화면의 손절가·수량을 믿고 주문하게 된다."""
    try:
        hits = fetchers.search_symbols(symbol)
    except Exception:
        # 해석 실패와 "없는 종목"을 여기서 구분할 방법이 없다. 둘 다 None으로 보내고
        # 실패 TTL이 만료되면 다시 시도하게 한다.
        return None
    for hit in hits:
        if hit.get("symbol") == symbol:
            return hit
    return None


def _job(symbol: str, thread_db) -> None:
    """응답이 나간 뒤 스레드풀 워커에서 돈다."""
    try:
        # 요청 스레드의 연결을 넘겨받아 쓰면 동시 접근으로 프로세스가 죽는다.
        # 이 스레드의 연결을 여기서 직접 얻는다.
        conn = thread_db.conn()
        meta = _resolve(symbol)
        if meta is None:
            _fail(symbol, "알 수 없는 심볼입니다 — 종목 코드를 확인하세요.")
            return
        # in_watchlist=0 — 조회가 워치리스트를 오염시키지 않고, 시간당 전체 갱신
        # 대상(`service._active_tickers`)에도 들어가지 않는다.
        db.upsert_ticker(conn, meta["symbol"], meta["market"], meta["name"],
                         is_etf=meta.get("is_etf", 0), in_watchlist=0,
                         yf_symbol=meta.get("yf_symbol"),
                         currency=meta.get("currency", "KRW"))
        service.refresh_all(conn, symbol)
    except Exception as e:
        _fail(symbol, f"조회 실패: {e}")
    finally:
        # 해제를 빠뜨리면 그 심볼이 프로세스가 살아 있는 동안 영원히 pending으로 굳는다.
        _release(symbol)


def poll(symbol: str, bg, thread_db) -> dict:
    """미등록 심볼에 대한 응답. 첫 호출이 수집을 시작하고, 이후 폴링은 상태만 읽는다."""
    failed = _recent_failure(symbol)
    if failed:
        return {"status": "failed", "symbol": symbol, "message": failed}
    if _acquire(symbol):
        bg.add_task(_job, symbol, thread_db)
    return {"status": "pending", "symbol": symbol}
