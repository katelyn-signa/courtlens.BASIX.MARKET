import logging

import pytest

from tests.agents import SENTINEL, LeakyFailingAgent, full_registry


def audit(env, case_id, **params):
    return env.client.get(f"/api/v1/cases/{case_id}/audit-events", params={"limit": 200, **params}).json()


def test_audit_trail_for_case_lifecycle(env):
    c = env.case()
    env.client.patch(f"/api/v1/cases/{c['id']}", json={"court_name": "Court Z"}, headers={"X-Actor-Id": "clerk-7"})
    env.doc(c["id"])
    data = audit(env, c["id"])
    types = [e["event_type"] for e in data["items"]]
    assert types[:3] == ["CASE_CREATED", "CASE_UPDATED", "DOCUMENT_REGISTERED"]
    upd = data["items"][1]
    assert upd["actor"] == "clerk-7" and upd["metadata"] == {"changed_fields": ["court_name"], "previous_value": {"court_name": None}, "new_value": {"court_name": "Court Z"}}
    assert upd["resource_type"] == "case" and upd["resource_id"] == c["id"] and upd["correlation_id"]


def test_audit_filters_pagination_and_ordering(env):
    c = env.case(); env.doc(c["id"])
    run = env.run(c["id"]).json()
    all_events = audit(env, c["id"])
    assert all_events["total"] >= 10
    times = [e["occurred_at"] for e in all_events["items"]]
    assert times == sorted(times)
    newest = audit(env, c["id"], newest_first="true")["items"]
    assert [e["id"] for e in newest] == [e["id"] for e in reversed(all_events["items"])]
    only = audit(env, c["id"], event_type="EVIDENCE_STORED")
    assert only["total"] == 1 and only["items"][0]["analysis_run_id"] == run["id"]
    page = audit(env, c["id"], limit=3, offset=3)
    assert len(page["items"]) == 3 and page["items"][0]["id"] == all_events["items"][3]["id"]
    by_run = env.client.get(f"/api/v1/analysis-runs/{run['id']}/audit-events", params={"limit": 200}).json()
    assert by_run["total"] > 0 and {e["analysis_run_id"] for e in by_run["items"]} == {run["id"]}
    assert audit(env, c["id"], actor="nobody")["total"] == 0
    assert env.client.get(f"/api/v1/cases/{c['id']}/audit-events", params={"since": "not-a-date"}).status_code == 422
    assert env.client.get(f"/api/v1/cases/case_{'0'*21}/audit-events").status_code == 404
    assert env.client.get(f"/api/v1/analysis-runs/run_{'0'*21}/audit-events").status_code == 404


def test_no_api_can_modify_or_delete_audit_events(env):
    c = env.case()
    ev = audit(env, c["id"])["items"][0]
    for method in ("post", "put", "patch", "delete"):
        for url in (f"/api/v1/cases/{c['id']}/audit-events", f"/api/v1/cases/{c['id']}/audit-events/{ev['id']}",
                    "/api/v1/audit-events/" + ev["id"]):
            assert getattr(env.client, method)(url).status_code in (404, 405)
    assert audit(env, c["id"])["items"][0] == ev
    paths = env.client.get("/openapi.json").json()["paths"]
    for path, ops in paths.items():
        if "audit" in path:
            assert set(ops) == {"get"}


def test_audit_events_scoped_to_their_case(env):
    a, b = env.case(), env.case()
    env.doc(a["id"])
    assert {e["case_id"] for e in audit(env, b["id"])["items"]} == {b["id"]}


def test_sensitive_text_not_logged_or_audited(make_env, caplog):
    e = make_env(registry=full_registry(conflict=LeakyFailingAgent()))
    c = e.case(); e.doc(c["id"])
    with caplog.at_level(logging.DEBUG):
        run = e.run(c["id"]).json()
    assert run["status"] == "PARTIALLY_COMPLETED"
    st = {s["stage_name"]: s for s in run["stages"]}["conflict_detection"]
    assert st["error_code"] == "AGENT_UNEXPECTED_ERROR" and st["error_summary"] == "Unexpected error: RuntimeError"
    everything = caplog.text + str(run) + str(audit(e, c["id"]))
    assert SENTINEL not in everything


def test_document_quotes_never_reach_logs_or_audit(env, caplog):
    c = env.case(); env.doc(c["id"])
    with caplog.at_level(logging.DEBUG):
        env.run(c["id"])
    assert "synthetic arrest date" not in caplog.text
    assert "synthetic arrest date" not in str(audit(env, c["id"]))
    assert any("Run run_" in r.getMessage() for r in caplog.records)  # logging is active, ids only


def test_api_key_never_logged(make_env, caplog):
    e = make_env(api_key="TOPSECRETKEY123")
    with caplog.at_level(logging.DEBUG):
        e.client.get("/api/v1/cases", headers={"X-API-Key": "TOPSECRETKEY123"})
        e.client.get("/api/v1/cases", headers={"X-API-Key": "wrong-key-value"})
    assert "TOPSECRETKEY123" not in caplog.text and "wrong-key-value" not in caplog.text


def test_unhandled_errors_do_not_leak_details(make_env):
    e = make_env()
    from app.api.deps import get_case_service

    def boom():
        raise RuntimeError("secret-internal-detail")
    e.app.dependency_overrides[get_case_service] = boom
    r = e.client.get("/api/v1/cases")
    assert r.status_code == 500 and r.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "secret-internal-detail" not in r.text and "Traceback" not in r.text
