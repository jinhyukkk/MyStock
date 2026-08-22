import pytest
from fastapi.testclient import TestClient

from app import fetchers, preview, sentiment
from app.main import create_app


@pytest.fixture(autouse=True)
def clean_preview_state():
    """모듈 레벨 상태는 프로세스 수명 동안 남는다 — 테스트끼리 새게 두면
    앞 테스트의 인플라이트가 뒤 테스트를 pending으로 붙잡는다."""
    preview.reset()
    yield
    preview.reset()


def test_acquire_is_exclusive_until_released():
    assert preview._acquire("005930") is True
    assert preview._acquire("005930") is False
    assert preview._acquire("005930") is False
    preview._release("005930")
    assert preview._acquire("005930") is True


def test_acquire_is_per_symbol():
    assert preview._acquire("005930") is True
    assert preview._acquire("AAPL") is True


def test_failure_is_remembered_then_expires(monkeypatch):
    preview._fail("NOPE", "알 수 없는 심볼입니다 — 종목 코드를 확인하세요.")
    assert preview._recent_failure("NOPE") == "알 수 없는 심볼입니다 — 종목 코드를 확인하세요."
    # TTL이 지나면 잊는다 — 일시적 네트워크 장애 한 번이 영구 실패로 굳으면
    # 사용자가 새로고침을 눌러도 계속 같은 에러만 본다.
    monkeypatch.setattr(preview, "FAILURE_TTL_SEC", 0)
    assert preview._recent_failure("NOPE") is None


def test_unknown_symbol_has_no_failure():
    assert preview._recent_failure("005930") is None


SAMSUNG = {"symbol": "005930", "name": "삼성전자", "market": "KR",
           "is_etf": 0, "yf_symbol": "005930.KS", "currency": "KRW"}

FAKE_SENTI = {"vix": 18.0, "vkospi": None, "cnn_fg": 60, "crypto_fg": 50,
              "usdkrw": 1300.0, "failed": []}


def test_resolve_takes_exact_symbol_match(monkeypatch):
    monkeypatch.setattr(fetchers, "search_symbols", lambda q, conn=None: [SAMSUNG])
    assert preview._resolve("005930") == SAMSUNG


def test_resolve_rejects_partial_match(monkeypatch):
    # 부분 일치를 받아들이면 사용자가 요청하지 않은 종목이 그 URL에 눌러앉는다.
    monkeypatch.setattr(fetchers, "search_symbols", lambda q, conn=None: [SAMSUNG])
    assert preview._resolve("NOPE") is None


def test_resolve_survives_search_failure(monkeypatch):
    def boom(q, conn=None):
        raise RuntimeError("network down")
    monkeypatch.setattr(fetchers, "search_symbols", boom)
    assert preview._resolve("005930") is None


@pytest.fixture
def client(tmp_path, ohlcv_up, monkeypatch):
    monkeypatch.setattr(fetchers, "fetch_ohlcv", lambda *a, **k: ohlcv_up)
    monkeypatch.setattr(fetchers, "fetch_fundamentals", lambda *a, **k: None)
    monkeypatch.setattr(fetchers, "search_symbols", lambda q, conn=None: [SAMSUNG])
    monkeypatch.setattr(sentiment, "fetch_sentiment", lambda: dict(FAKE_SENTI))
    app = create_app(db_path=str(tmp_path / "t.db"), refresh_on_start=False)
    with TestClient(app) as c:
        yield c


def test_unregistered_symbol_is_pending_then_ready(client):
    first = client.get("/api/tickers/005930")
    assert first.status_code == 200
    assert first.json() == {"status": "pending", "symbol": "005930"}

    second = client.get("/api/tickers/005930").json()
    assert second["status"] == "ready"
    assert second["tracked"] is False
    # 기존 필드가 그대로 나가야 한다 — 구버전 빌드본도 계속 동작해야 하므로.
    assert len(second["candles"]) > 0
    assert second["signal"]["swing_grade"]
    assert second["cost_rates"]["fee_pct"] >= 0


def test_preview_row_stays_out_of_the_refresh_loop(client):
    client.get("/api/tickers/005930")
    assert client.get("/api/tickers/005930").json()["status"] == "ready"
    # in_watchlist=0 + 미보유라 `_active_tickers`에 안 들어간다.
    # 들어가면 한 번 열어본 종목 수만큼 매시간 외부 호출이 늘어난다.
    assert client.get("/api/dashboard").json()["signals"] == []


def test_unresolvable_symbol_reports_failed(client):
    assert client.get("/api/tickers/NOPE").json()["status"] == "pending"
    out = client.get("/api/tickers/NOPE").json()
    assert out["status"] == "failed"
    assert out["message"] == "알 수 없는 심볼입니다 — 종목 코드를 확인하세요."


def test_registered_ticker_is_ready_and_tracked(client):
    client.post("/api/watchlist", json=SAMSUNG)
    client.post("/api/refresh")
    out = client.get("/api/tickers/005930").json()
    assert out["status"] == "ready"
    assert out["tracked"] is True


def test_track_flips_preview_row_into_watchlist(client):
    client.get("/api/tickers/005930")
    assert client.get("/api/tickers/005930").json()["tracked"] is False

    assert client.put("/api/watchlist/005930").status_code == 200
    assert client.get("/api/tickers/005930").json()["tracked"] is True
    # 등록했으니 이제 대시보드(=시간당 갱신 대상)에도 나타난다.
    assert len(client.get("/api/dashboard").json()["signals"]) == 1


def test_track_unknown_symbol_is_404(client):
    assert client.put("/api/watchlist/NOPE").status_code == 404
