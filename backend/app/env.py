"""루트 .env / .env.local 로드. python-dotenv 없이 동작한다.

우선순위: 이미 설정된 환경 변수 > .env.local > .env. .env.local은 개인 키 파일이라
git에 올라가지 않고, .env.example을 복사해 만든 .env보다 우선한다.
"""
import os
from pathlib import Path

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
