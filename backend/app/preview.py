"""미등록 종목의 임시 조회(preview).

종목 상세는 `tickers` 행이 있어야 열린다. 이 모듈은 행이 없는 심볼을 요청받았을 때
백그라운드에서 해석·수집해 행을 만든다. 요청 경로에서 하지 않는 이유는 두 가지다 —
심볼 해석(`fetchers.search_symbols`)이 캐시 없는 FinanceDataReader 호출이고,
`refresh_all`의 시세·시그널·재무 수집이 수 초 걸린다.

여기서 만든 행은 `in_watchlist=0`이라 `service._active_tickers`의 시간당 갱신 대상에
들어가지 않는다. 한 번 열어본 것만으로 매시간 외부 호출이 늘어나면 안 된다.
"""
import threading
import time

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
