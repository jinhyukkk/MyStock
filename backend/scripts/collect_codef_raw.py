"""CODEF 응답을 가공 없이 파일로 떠 둔다 — API 사용 기간이 끝나기 전에 원본을 남기는 용도.

    python -m scripts.collect_codef_raw --dry-run   # 호출 계획만
    python -m scripts.collect_codef_raw             # 수집
    python -m scripts.collect_codef_raw --force     # 지난 달 파일도 전부 다시

CODEF가 과거분을 주는 건 입출금내역(transaction-list)뿐이다. 잔고조회·종합자산은
"지금" 스냅샷이라 실행 당일 것 한 벌만 남는다. 입출금내역은 증권사별 조회 한도
(키움 3개월 등)에 걸리면 CODEF가 시작일을 조용히 당겨 버리므로 월 단위로 끊어 받는다.

저장 위치: backend/raw/codef/<연도>/<계좌 라벨>/
  transactions_YYYYMM.json / balance_YYYYMMDD.json / financial_assets_YYYYMMDD.json
파일 하나 = 호출 하나. 요청 본문은 accountPassword를 뺀 채로 같이 적는다.

끝난 달의 파일은 다시 부르지 않는다 — 일 100회 한도를 넘겨 중간에 끊겨도 다음 날
그대로 이어 돌리면 된다. 진행 중인 달과 스냅샷은 매번 새로 받는다.
"""
import argparse
import calendar
import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import codef, db, env, service

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_OUT = ROOT / "backend" / "raw" / "codef"
QUOTA_EXCEEDED = "CF-00012"


def month_ranges(year: int, today: date) -> list[tuple[str, str]]:
    """1월부터 today가 속한 달까지 (시작일, 종료일) — 마지막 달은 today까지."""
    out = []
    for m in range(1, 13):
        first = date(year, m, 1)
        if first > today:
            break
        last = min(date(year, m, calendar.monthrange(year, m)[1]), today)
        out.append((first.strftime("%Y%m%d"), last.strftime("%Y%m%d")))
    return out


def _safe_label(label: str) -> str:
    return "".join(c if c.isalnum() or c in " _-" else "_" for c in label).strip() or "account"


def _plan(cid: str, accounts: list[dict], year: int, today: date) -> list[dict]:
    """호출 목록. 파일명이 곧 중복 판단 키다."""
    stamp = today.strftime("%Y%m%d")
    jobs = []
    for a in accounts:
        label = _safe_label(a.get("display") or a["account"])
        base = {"connectedId": cid, "organization": a["organization"],
                "account": "".join(c for c in a["account"] if c.isdigit())}
        for start, end in month_ranges(year, today):
            jobs.append({"label": label, "file": f"transactions_{start[:6]}.json",
                         "endpoint": codef.TRANSACTION_LIST,
                         "body": {**base, "startDate": start, "endDate": end, "orderBy": "1"},
                         # 진행 중인 달은 끝나지 않았으니 기존 파일이 있어도 다시 받는다
                         "final": end != stamp,
                         "password_enc": a.get("password_enc")})
        jobs.append({"label": label, "file": f"balance_{stamp}.json",
                     "endpoint": codef.BALANCE_INQUIRY, "body": dict(base),
                     "final": False, "password_enc": a.get("password_enc")})
        jobs.append({"label": label, "file": f"financial_assets_{stamp}.json",
                     "endpoint": codef.FINANCIAL_ASSETS,
                     "body": {**base, "inquiryType": "0"},
                     "final": False, "password_enc": a.get("password_enc")})
    return jobs


def _call(job: dict) -> dict:
    body = dict(job["body"])
    if job["password_enc"]:
        body["accountPassword"] = job["password_enc"]
    payload = codef.post_raw(job["endpoint"], body)
    result = payload.get("result") or {}
    if result.get("code") != codef.SUCCESS:
        raise codef.CodefError(result.get("code", "CF-LOCAL"),
                               result.get("message") or result.get("extraMessage") or "알 수 없는 오류")
    return payload


def collect(conn, out: Path, year: int, today: date | None = None,
            force: bool = False, dry_run: bool = False) -> dict:
    today = today or date.today()
    cid = db.get_meta(conn, service.BROKER_CID)
    accounts = service.broker_accounts(conn)
    if not cid or not accounts:
        raise codef.CodefError("CF-LOCAL", "연결된 증권사 계좌가 없습니다 — 앱에서 먼저 연동하세요")

    jobs = _plan(cid, accounts, year, today)
    todo, skipped = [], []
    for j in jobs:
        path = out / str(year) / j["label"] / j["file"]
        (skipped if j["final"] and path.exists() and not force else todo).append((j, path))

    summary = {"calls": len(todo), "skipped": len(skipped), "saved": [], "failed": [],
               "stopped": None, "dry_run": dry_run}
    if dry_run:
        summary["plan"] = [str(p.relative_to(out)) for _, p in todo]
        return summary

    # 시도 자체가 한도를 쓴다 — 앱의 자동 동기화가 같은 날 또 부르지 않게 시계를 민다
    db.set_meta(conn, service.BROKER_LAST_ATTEMPT,
                datetime.now().isoformat(timespec="seconds"))
    for j, path in todo:
        rel = str(path.relative_to(out))
        try:
            payload = _call(j)
        except codef.CodefError as e:
            summary["failed"].append({"file": rel, "error": str(e)})
            if e.code == QUOTA_EXCEEDED:
                summary["stopped"] = e.code
                break
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "endpoint": j["endpoint"], "request": j["body"],  # 암호는 body에 없다
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "payload": payload}, ensure_ascii=False, indent=1), encoding="utf-8")
        summary["saved"].append(rel)
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--db", default=None, help="기본값: backend/mystock.db")
    ap.add_argument("--force", action="store_true", help="끝난 달 파일도 다시 받는다")
    ap.add_argument("--dry-run", action="store_true", help="호출하지 않고 계획만 출력")
    args = ap.parse_args(argv)

    env.load(ROOT)
    if not codef.is_configured():
        print("CODEF 키가 없습니다 — .env 또는 .env.local을 확인하세요", file=sys.stderr)
        return 2
    conn = db.get_conn(args.db)
    try:
        s = collect(conn, args.out, args.year, force=args.force, dry_run=args.dry_run)
    except codef.CodefError as e:
        print(e, file=sys.stderr)
        return 2
    finally:
        conn.close()

    print(f"host={codef.host()}  호출 {s['calls']}건, 건너뜀 {s['skipped']}건")
    if s["dry_run"]:
        for p in s["plan"]:
            print("  ", p)
        return 0
    for p in s["saved"]:
        print("  저장", p)
    for f in s["failed"]:
        print("  실패", f["file"], "—", f["error"])
    if s["stopped"]:
        print(f"일일 한도({s['stopped']})에 걸려 중단 — 내일 같은 명령으로 이어서 받으세요")
        return 1
    return 0 if not s["failed"] else 1


if __name__ == "__main__":
    sys.exit(main())
