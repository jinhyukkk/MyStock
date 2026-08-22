"""루트 .env / .env.local 로드. python-dotenv 없이 동작한다.

우선순위: 이미 설정된 환경 변수 > .env.local > .env. .env.local은 개인 키 파일이라
git에 올라가지 않고, .env.example을 복사해 만든 .env보다 우선한다.
"""
import os
from pathlib import Path

# .env.local은 CODEF_SERVICE_TYPE(demo|api|sandbox)을 쓰는데 앱은 CODEF_ENV(demo|prod)를
# 본다. sandbox는 고정 응답 서버라 실데이터 수집에 의미가 없으므로 demo로 취급한다.
_SERVICE_TYPE_TO_ENV = {"api": "prod", "demo": "demo", "sandbox": "demo"}


def _read(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip("'\"")
    return out


def load(root: Path) -> None:
    merged = {**_read(root / ".env"), **_read(root / ".env.local")}
    for k, v in merged.items():
        os.environ.setdefault(k, v)
    svc = os.environ.get("CODEF_SERVICE_TYPE")
    if svc and "CODEF_ENV" not in os.environ:
        os.environ["CODEF_ENV"] = _SERVICE_TYPE_TO_ENV.get(svc, "demo")
