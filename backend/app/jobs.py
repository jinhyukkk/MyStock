"""백그라운드 잡 스토어 — 워크포워드처럼 수 분 걸리는 작업의 진행률·결과 보관.

모듈 레벨 dict + threading으로 충분하다(로컬 단일 사용자, 단일 프로세스).
잡 함수는 progress_cb(done, total)를 받고 결과 dict를 반환한다.
DB가 필요한 잡은 함수 안에서 자기 스레드의 연결을 얻어야 한다 —
요청 스레드의 연결을 넘겨받으면 동시 접근으로 프로세스가 죽는다(db.py 주석).
"""
import threading
import uuid
from datetime import datetime

_jobs: dict[str, dict] = {}
_lock = threading.Lock()
_MAX_KEEP = 20  # 끝난 잡을 무한정 들고 있으면 결과(수 MB)가 메모리에 쌓인다


def start(fn, *args, **kwargs) -> str:
    job_id = uuid.uuid4().hex[:12]
    with _lock:
        _jobs[job_id] = {"status": "running",
                         "progress": {"done": 0, "total": None},
                         "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        # 오래된 완료 잡 정리 — running은 지우면 안 된다
        finished = [k for k, v in _jobs.items() if v["status"] != "running"]
        for k in finished[:-_MAX_KEEP]:
            del _jobs[k]

    def progress_cb(done, total):
        with _lock:
            _jobs[job_id]["progress"] = {"done": done, "total": total}

    def runner():
        try:
            result = fn(progress_cb, *args, **kwargs)
            with _lock:
                _jobs[job_id].update(status="done", result=result)
        except Exception as e:  # 잡 실패가 서버를 죽이면 안 된다 — 상태로 남긴다
            with _lock:
                _jobs[job_id].update(status="error", error=str(e))

    threading.Thread(target=runner, daemon=True).start()
    return job_id


def get(job_id: str) -> dict | None:
    with _lock:
        st = _jobs.get(job_id)
        return dict(st) if st else None
