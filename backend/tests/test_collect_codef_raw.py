import json
from datetime import date

import pytest

from app import codef, db, env, service
from scripts import collect_codef_raw as col


@pytest.fixture
def conn(tmp_path):
    c = db.get_conn(str(tmp_path / "t.db"))
    db.set_meta(c, service.BROKER_CID, "cid-1")
    db.set_meta(c, service.BROKER_ACCOUNTS, json.dumps([
        {"organization": "0264", "account": "123-45-678", "display": "키움 위탁",
         "password_enc": "SECRET-ENC"},
    ]))
    yield c
    c.close()


@pytest.fixture
def calls(monkeypatch):
    """post_raw를 가로채 (path, body) 기록 — 실제 CODEF는 호출하지 않는다."""
    seen = []

    def fake(path, body):
        seen.append((path, body))
        return {"result": {"code": "CF-00000"}, "data": [{"resAccountTrDate": "20260102"}]}
    monkeypatch.setattr(codef, "post_raw", fake)
    return seen


def test_month_ranges_cover_year_to_today():
    assert col.month_ranges(2026, date(2026, 3, 15)) == [
        ("20260101", "20260131"), ("20260201", "20260228"), ("20260301", "20260315")]


def test_collect_writes_one_file_per_call_without_password(conn, calls, tmp_path):
    out = tmp_path / "raw"
    summary = col.collect(conn, out, year=2026, today=date(2026, 2, 10))

    acct = out / "2026" / "키움 위탁"
    assert sorted(p.name for p in acct.iterdir()) == [
        "balance_20260210.json", "financial_assets_20260210.json",
        "transactions_202601.json", "transactions_202602.json"]
    assert summary["calls"] == 4 and summary["failed"] == []

    doc = json.loads((acct / "transactions_202601.json").read_text(encoding="utf-8"))
    assert doc["endpoint"] == codef.TRANSACTION_LIST
    assert doc["request"]["startDate"] == "20260101" and doc["request"]["endDate"] == "20260131"
    assert doc["payload"]["result"]["code"] == "CF-00000"
    assert "SECRET" not in (acct / "transactions_202601.json").read_text(encoding="utf-8")
    # 실제 요청에는 암호가 들어간다 — 파일에만 빠져야 한다
    assert all(b.get("accountPassword") == "SECRET-ENC" for _, b in calls)


def test_completed_months_are_skipped_on_rerun(conn, calls, tmp_path):
    out = tmp_path / "raw"
    col.collect(conn, out, year=2026, today=date(2026, 2, 10))
    calls.clear()
    col.collect(conn, out, year=2026, today=date(2026, 2, 10))
    # 1월은 끝난 달이라 재호출 없음. 2월(진행 중)·잔고·자산은 다시 받는다.
    paths = [p for p, _ in calls]
    assert paths.count(codef.TRANSACTION_LIST) == 1
    assert codef.BALANCE_INQUIRY in paths and codef.FINANCIAL_ASSETS in paths


def test_force_refetches_everything(conn, calls, tmp_path):
    out = tmp_path / "raw"
    col.collect(conn, out, year=2026, today=date(2026, 2, 10))
    calls.clear()
    col.collect(conn, out, year=2026, today=date(2026, 2, 10), force=True)
    assert len(calls) == 4


def test_quota_error_stops_immediately(conn, monkeypatch, tmp_path):
    n = {"calls": 0}

    def fake(path, body):
        n["calls"] += 1
        raise codef.CodefError("CF-00012", "일일 한도 초과")
    monkeypatch.setattr(codef, "post_raw", fake)
    summary = col.collect(conn, tmp_path / "raw", year=2026, today=date(2026, 3, 1))
    assert n["calls"] == 1 and summary["stopped"] == "CF-00012"


def test_other_errors_continue_and_are_reported(conn, monkeypatch, tmp_path):
    def fake(path, body):
        if body.get("startDate") == "20260101":
            raise codef.CodefError("CF-12100", "조회 기간 초과")
        return {"result": {"code": "CF-00000"}, "data": []}
    monkeypatch.setattr(codef, "post_raw", fake)
    summary = col.collect(conn, tmp_path / "raw", year=2026, today=date(2026, 2, 10))
    assert [f["file"] for f in summary["failed"]] == ["2026/키움 위탁/transactions_202601.json"]
    assert not (tmp_path / "raw/2026/키움 위탁/transactions_202601.json").exists()


def test_collect_marks_sync_attempt_so_auto_loop_waits(conn, calls, tmp_path):
    col.collect(conn, tmp_path / "raw", year=2026, today=date(2026, 2, 10))
    assert db.get_meta(conn, service.BROKER_LAST_ATTEMPT)


def test_dry_run_makes_no_calls_and_no_files(conn, calls, tmp_path):
    plan = col.collect(conn, tmp_path / "raw", year=2026, today=date(2026, 3, 1), dry_run=True)
    assert plan["calls"] == 5 and calls == [] and not (tmp_path / "raw").exists()


def test_env_local_overrides_and_maps_service_type(tmp_path, monkeypatch):
    for k in ("CODEF_ENV", "CODEF_SERVICE_TYPE", "CODEF_CLIENT_ID"):
        monkeypatch.delenv(k, raising=False)
    (tmp_path / ".env").write_text("CODEF_CLIENT_ID=from-env\n", encoding="utf-8")
    (tmp_path / ".env.local").write_text(
        "CODEF_CLIENT_ID=from-local\nCODEF_SERVICE_TYPE=api\n", encoding="utf-8")
    env.load(tmp_path)
    import os
    assert os.environ["CODEF_CLIENT_ID"] == "from-local"
    assert os.environ["CODEF_ENV"] == "prod"
