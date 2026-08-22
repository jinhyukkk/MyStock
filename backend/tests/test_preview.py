import pytest

from app import preview


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
