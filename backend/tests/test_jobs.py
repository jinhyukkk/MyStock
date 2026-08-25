"""jobs — 백그라운드 잡 스토어. 워크포워드(수 분)를 동기 API로 못 돌린다."""
import time

from app import jobs


def test_job_lifecycle():
    def work(progress_cb):
        progress_cb(1, 2)
        progress_cb(2, 2)
        return {"answer": 42}

    jid = jobs.start(work)
    for _ in range(100):
        st = jobs.get(jid)
        if st["status"] == "done":
            break
        time.sleep(0.02)
    assert st["status"] == "done"
    assert st["result"] == {"answer": 42}
    assert st["progress"]["done"] == 2 and st["progress"]["total"] == 2


def test_job_error_is_captured():
    def boom(progress_cb):
        raise RuntimeError("터짐")

    jid = jobs.start(boom)
    for _ in range(100):
        st = jobs.get(jid)
        if st["status"] == "error":
            break
        time.sleep(0.02)
    assert st["status"] == "error"
    assert "터짐" in st["error"]


def test_unknown_job():
    assert jobs.get("없음") is None
