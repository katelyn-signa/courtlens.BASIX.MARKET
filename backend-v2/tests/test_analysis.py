"""Analysis-run API behaviour: creation, querying, listing, filtering, pagination."""


def test_run_can_be_created_and_queried(env):
    c = env.case(); env.doc(c["id"])
    created = env.run(c["id"]).json()
    got = env.client.get(f"/api/v1/analysis-runs/{created['id']}").json()
    assert got["id"] == created["id"] and got["status"] == "COMPLETED"
    assert got["pipeline_version"] == "1.0" and got["requested_modules"] == [
        "document_intelligence", "conflict_detection", "reasoning"]
    assert got["agent_versions"]["reasoning"]["simulated"] is True
    assert set(got["output_refs"]) >= {"evidence_ids", "conflict_ids", "rule_result_ids"}
    stages = env.client.get(f"/api/v1/analysis-runs/{created['id']}/stages").json()
    assert [s["sequence"] for s in stages] == [1, 2, 3]
    assert all(s["started_at"] and s["completed_at"] for s in stages)


def test_run_listing_filter_and_pagination(env):
    c = env.case(); env.doc(c["id"])
    ids = [env.run(c["id"], force=True).json()["id"] for _ in range(3)]
    url = f"/api/v1/cases/{c['id']}/analysis-runs"
    page = env.client.get(url, params={"limit": 2}).json()
    assert page["total"] == 3 and len(page["items"]) == 2
    assert [r["id"] for r in page["items"]] == list(reversed(ids))[:2]  # newest first
    assert env.client.get(url, params={"status": "FAILED"}).json()["total"] == 0
    assert env.client.get(url, params={"status": "COMPLETED"}).json()["total"] == 3
    assert env.client.get(url, params={"status": "BOGUS"}).status_code == 422


def test_findings_filters(env):
    c = env.case()
    env.doc(c["id"], "a.pdf", "aaa"); env.doc(c["id"], "b.pdf", "bbb")
    run = env.run(c["id"]).json()
    base = f"/api/v1/cases/{c['id']}"
    ev = env.client.get(f"{base}/evidence", params={"fact_type": "ARREST_DATE"}).json()
    assert ev["total"] == 2
    one_doc = env.client.get(f"{base}/evidence", params={"document_id": run["input_documents"][0]["document_id"]}).json()
    assert one_doc["total"] == 2
    assert env.client.get(f"{base}/evidence", params={"document_id": "bad"}).status_code == 422
    cf = env.client.get(f"{base}/conflicts", params={"conflict_type": "MISSING_EVIDENCE"}).json()
    assert cf["total"] == 1 and cf["items"][0]["resolution_status"] == "UNRESOLVED"
    assert env.client.get(f"{base}/conflicts", params={"resolution_status": "RESOLVED"}).json()["total"] == 0
    rr = env.client.get(f"{base}/rule-results", params={"review_signal": "CONFLICTS_DETECTED"}).json()
    assert rr["total"] == 1 and rr["items"][0]["rule_id"] == "DEMO-PROCESS-CHECK"
    assert env.client.get(f"{base}/rule-results", params={"analysis_run_id": run["id"], "limit": 1}).json()["total"] == 1


def test_evidence_retrieval_is_scoped_to_case(env):
    a, b = env.case(), env.case()
    env.doc(a["id"]); env.doc(b["id"])
    env.run(a["id"])
    assert env.client.get(f"/api/v1/cases/{b['id']}/evidence").json()["total"] == 0
    assert env.client.get(f"/api/v1/cases/{a['id']}/evidence").json()["total"] == 2


def test_rule_results_use_only_neutral_signals(env):
    c = env.case(); env.doc(c["id"])
    env.run(c["id"])
    allowed = {"POTENTIAL_REVIEW_SIGNAL", "NEEDS_HUMAN_REVIEW", "INSUFFICIENT_INFORMATION",
               "CONFLICTS_DETECTED", "ANALYSIS_INCOMPLETE"}
    for r in env.client.get(f"/api/v1/cases/{c['id']}/rule-results").json()["items"]:
        assert r["review_signal"] in allowed


def test_agent_output_cannot_carry_a_decision_signal():
    import pytest
    from pydantic import ValidationError
    from app.orchestration.contracts import RuleEvaluation
    with pytest.raises(ValidationError):
        RuleEvaluation(rule_id="R", rule_version="1", evaluation_status="EVALUATED",
                       review_signal="GRANT_BAIL", explanation="x")
    with pytest.raises(ValidationError):  # EVALUATED without any signal
        RuleEvaluation(rule_id="R", rule_version="1", evaluation_status="EVALUATED", explanation="x")
