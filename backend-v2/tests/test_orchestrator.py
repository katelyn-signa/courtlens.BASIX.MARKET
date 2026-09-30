from tests.agents import (FailingConflictAgent, FlakyRuleAgent, InvalidOutputConflictAgent,
                          RecordingAgent, SlowConflictAgent, StubSummaryAgent,
                          UnavailableConflictAgent, full_registry)
from app.integrations.conflict_agent import DemoConflictAgent
from app.integrations.evidence_agent import DemoEvidenceAgent
from app.integrations.ocr_agent import DemoOcrAgent
from app.integrations.rule_agent import DemoRuleAgent
from app.integrations.summary_agent import DemoSummaryAgent


def stages(env, run_id):
    return {s["stage_name"]: s for s in env.client.get(f"/api/v1/analysis-runs/{run_id}/stages").json()}


def event_types(env, case_id):
    items = env.client.get(f"/api/v1/cases/{case_id}/audit-events", params={"limit": 200}).json()["items"]
    return [e["event_type"] for e in items]


def test_successful_pipeline_persists_everything(env):
    c = env.case()
    env.doc(c["id"], "fir.pdf")
    env.doc(c["id"], "order.pdf")
    r = env.run(c["id"])
    assert r.status_code == 201, r.text
    run = r.json()
    assert run["status"] == "COMPLETED" and run["error_summary"] is None
    assert [s["status"] for s in run["stages"]] == ["SUCCEEDED"] * 5
    assert run["summary"]["evidence_count"] >= 4 and run["summary"]["simulated_output"] is True
    assert run["summary"]["review_signals"] and run["summary"]["analysis_outcome"] is None
    assert len(run["input_documents"]) == 2 and run["started_at"] and run["completed_at"]

    ev = env.client.get(f"/api/v1/cases/{c['id']}/evidence").json()
    assert ev["total"] >= 4 and all(e["is_simulated"] and e["extraction_run_id"] == run["id"] for e in ev["items"])
    cf = env.client.get(f"/api/v1/cases/{c['id']}/conflicts").json()
    assert {x["conflict_type"] for x in cf["items"]} >= {"MISSING_EVIDENCE"}
    rr = env.client.get(f"/api/v1/cases/{c['id']}/rule-results").json()
    assert rr["total"] >= 1 and "Simulated" in rr["items"][0]["notice"]
    docs = env.client.get(f"/api/v1/cases/{c['id']}/documents").json()["items"]
    assert {d["processing_status"] for d in docs} == {"PROCESSED"}
    assert env.client.get(f"/api/v1/cases/{c['id']}").json()["analysis_needs_refresh"] is False
    types = event_types(env, c["id"])
    for t in ("ANALYSIS_RUN_CREATED", "ANALYSIS_RUN_STARTED", "EVIDENCE_STORED", "CONFLICTS_STORED",
              "RULE_RESULTS_STORED", "ANALYSIS_RUN_COMPLETED", "DOCUMENT_PROCESSING_COMPLETED"):
        assert t in types


def test_stage_order_is_correct(make_env):
    from app.orchestration.registry import AgentKey, AgentRegistry

    order: list[str] = []
    reg = AgentRegistry()
    reg.register(AgentKey.OCR, RecordingAgent(DemoOcrAgent(), "run_ocr", order, "ocr"), source="demo")
    reg.register(AgentKey.EVIDENCE_EXTRACTION,
                 RecordingAgent(DemoEvidenceAgent(), "extract", order, "evidence"), source="demo")
    reg.register(AgentKey.CONFLICT_DETECTION,
                 RecordingAgent(DemoConflictAgent(), "analyze", order, "conflict"), source="demo")
    reg.register(AgentKey.RULE_EVALUATION,
                 RecordingAgent(DemoRuleAgent(), "evaluate", order, "rule"), source="demo")
    reg.register(AgentKey.SUMMARY_GENERATION,
                 RecordingAgent(DemoSummaryAgent(), "summarize", order, "summary"), source="demo")
    e = make_env(registry=reg)
    c = e.case(); e.doc(c["id"])
    assert e.run(c["id"]).json()["status"] == "COMPLETED"
    assert order == ["ocr", "evidence", "conflict", "rule", "summary"]


def test_unconfigured_agents_reported_honestly(make_env, empty_registry):
    e = make_env(registry=empty_registry)
    c = e.case(); e.doc(c["id"])
    run = e.run(c["id"]).json()
    assert run["status"] == "FAILED"
    st = {s["stage_name"]: s for s in run["stages"]}
    assert st["ocr"]["status"] == "NOT_CONFIGURED"
    assert st["conflict_detection"]["status"] == "SKIPPED"
    assert st["summary_generation"]["status"] == "SKIPPED"
    assert run["summary"]["analysis_outcome"] == "ANALYSIS_INCOMPLETE"
    assert e.client.get(f"/api/v1/cases/{c['id']}/evidence").json()["total"] == 0
    assert e.client.get(f"/api/v1/cases/{c['id']}/documents").json()["items"][0]["processing_status"] == "PENDING"
    assert "ANALYSIS_RUN_FAILED" in event_types(e, c["id"])


def test_later_failure_keeps_earlier_outputs(make_env):
    e = make_env(registry=full_registry(conflict=FailingConflictAgent()))
    c = e.case(); e.doc(c["id"])
    run = e.run(c["id"]).json()
    assert run["status"] == "PARTIALLY_COMPLETED"
    st = {s["stage_name"]: s for s in run["stages"]}
    assert st["evidence_extraction"]["status"] == "SUCCEEDED"
    assert st["conflict_detection"]["status"] == "FAILED" and st["conflict_detection"]["error_code"] == "AGENT_PROCESSING_FAILED"
    assert st["rule_evaluation"]["status"] == "SKIPPED"
    assert e.client.get(f"/api/v1/cases/{c['id']}/evidence").json()["total"] >= 2
    assert e.client.get(f"/api/v1/cases/{c['id']}/conflicts").json()["total"] == 0
    assert "conflict_detection: FAILED" in run["error_summary"]
    assert "ANALYSIS_STAGE_FAILED" in event_types(e, c["id"])


def test_not_implemented_stage(make_env):
    e = make_env(registry=full_registry(summary=StubSummaryAgent()))
    c = e.case(); e.doc(c["id"])
    run = e.run(c["id"]).json()
    assert run["status"] == "PARTIALLY_COMPLETED"
    assert {s["stage_name"]: s["status"] for s in run["stages"]}["summary_generation"] == "NOT_IMPLEMENTED"


def test_invalid_agent_output_is_rejected_and_not_stored(make_env):
    e = make_env(registry=full_registry(conflict=InvalidOutputConflictAgent()))
    c = e.case(); e.doc(c["id"])
    run = e.run(c["id"]).json()
    st = {s["stage_name"]: s for s in run["stages"]}
    assert st["conflict_detection"]["status"] == "FAILED"
    assert st["conflict_detection"]["error_code"] == "AGENT_INVALID_OUTPUT"
    assert e.client.get(f"/api/v1/cases/{c['id']}/conflicts").json()["total"] == 0


def test_malformed_agent_payload_is_rejected(make_env):
    class BadDocAgent:
        name, version = "bad", "1"
        def extract(self, request):
            return {"status": "SUCCESS", "agent_name": "bad", "agent_version": "1",
                    "facts": [{"fact_type": "ARREST_DATE", "value": {"date": "31-02-2024"},
                               "source_document_id": request.documents[0].document_id}],
                    "document_results": [{"document_id": request.documents[0].document_id, "status": "SUCCESS"}]}
    e = make_env(registry=full_registry(document=BadDocAgent()))
    c = e.case(); e.doc(c["id"])
    run = e.run(c["id"]).json()
    assert run["status"] == "FAILED"
    assert run["stages"][0]["error_code"] == "AGENT_INVALID_OUTPUT"
    assert e.client.get(f"/api/v1/documents/{run['input_documents'][0]['document_id']}").json()["processing_status"] == "FAILED"


def test_missing_date_must_be_unknown_never_assumed():
    import pytest
    from pydantic import ValidationError
    from app.orchestration.contracts import ExtractedFact
    doc = "doc_" + "0" * 21
    with pytest.raises(ValidationError):
        ExtractedFact(fact_type="ARREST_DATE", value={"date": None}, source_document_id=doc,
                      verification_status="VERIFIED")
    ok = ExtractedFact(fact_type="ARREST_DATE", value={"date": None}, source_document_id=doc,
                       verification_status="UNKNOWN")
    assert ok.value["date"] is None
    with pytest.raises(ValidationError):
        ExtractedFact(fact_type="REMAND_PERIOD", value={"start_date": "2024-05-02", "end_date": "2024-05-01"},
                      source_document_id=doc)


def test_retryable_error_is_retried_within_stage(make_env):
    agent = UnavailableConflictAgent(fail_times=1)
    e = make_env(registry=full_registry(conflict=agent))
    c = e.case(); e.doc(c["id"])
    run = e.run(c["id"]).json()
    assert run["status"] == "COMPLETED" and agent.calls == 2
    assert {s["stage_name"]: s["attempts"] for s in run["stages"]}["conflict_detection"] == 2


def test_retries_are_bounded(make_env):
    agent = UnavailableConflictAgent(fail_times=99)
    e = make_env(registry=full_registry(conflict=agent), agent_max_attempts=3)
    c = e.case(); e.doc(c["id"])
    run = e.run(c["id"]).json()
    assert agent.calls == 3 and run["status"] == "PARTIALLY_COMPLETED"
    assert {s["stage_name"]: s["error_code"] for s in run["stages"]}["conflict_detection"] == "AGENT_UNAVAILABLE"


def test_agent_timeout(make_env):
    e = make_env(registry=full_registry(conflict=SlowConflictAgent()), agent_timeout_seconds=0.05,
                 agent_max_attempts=1)
    c = e.case(); e.doc(c["id"])
    run = e.run(c["id"]).json()
    assert {s["stage_name"]: s["error_code"] for s in run["stages"]}["conflict_detection"] == "AGENT_TIMEOUT"
    assert run["status"] == "PARTIALLY_COMPLETED"


def test_retry_creates_linked_run_and_reuses_successful_stages(make_env):
    rule = FlakyRuleAgent()
    e = make_env(registry=full_registry(rule=rule))
    c = e.case(); e.doc(c["id"])
    first = e.run(c["id"]).json()
    assert first["status"] == "PARTIALLY_COMPLETED"
    r = e.client.post(f"/api/v1/analysis-runs/{first['id']}/retry")
    assert r.status_code == 201, r.text
    second = r.json()
    assert second["status"] == "COMPLETED" and second["parent_run_id"] == first["id"]
    assert second["attempt_number"] == 2 and second["trigger_type"] == "RETRY"
    st = {s["stage_name"]: s for s in second["stages"]}
    assert st["document_intelligence"]["carried_over"] and st["conflict_detection"]["carried_over"]
    assert st["document_intelligence"]["output_run_id"] == first["id"]
    assert not st["reasoning"]["carried_over"]
    # earlier evidence was NOT duplicated by the retry; previous run is untouched
    assert e.client.get(f"/api/v1/cases/{c['id']}/evidence").json()["total"] == 2
    assert e.client.get(f"/api/v1/analysis-runs/{first['id']}").json()["status"] == "PARTIALLY_COMPLETED"
    assert e.client.get(f"/api/v1/cases/{c['id']}/analysis-runs").json()["total"] == 2
    assert "ANALYSIS_RERUN_TRIGGERED" in event_types(e, c["id"])
    # already retried / completed runs cannot be retried again
    assert e.client.post(f"/api/v1/analysis-runs/{first['id']}/retry").status_code == 409
    assert e.client.post(f"/api/v1/analysis-runs/{second['id']}/retry").status_code == 409


def test_retry_limit(make_env):
    e = make_env(registry=full_registry(conflict=FailingConflictAgent()), max_run_retries=1)
    c = e.case(); e.doc(c["id"])
    r1 = e.run(c["id"]).json()
    r2 = e.client.post(f"/api/v1/analysis-runs/{r1['id']}/retry").json()
    assert r2["status"] == "PARTIALLY_COMPLETED" and r2["attempt_number"] == 2
    r3 = e.client.post(f"/api/v1/analysis-runs/{r2['id']}/retry")
    assert r3.status_code == 409 and r3.json()["error"]["code"] == "RETRY_LIMIT_REACHED"


def test_idempotency_policies(env):
    c = env.case(); env.doc(c["id"])
    first = env.run(c["id"]).json()
    same = env.run(c["id"])
    assert same.status_code == 200 and same.json()["id"] == first["id"] and same.json()["reused_existing"]
    forced = env.run(c["id"], force=True)
    assert forced.status_code == 201 and forced.json()["id"] != first["id"]
    k1 = env.client.post(f"/api/v1/cases/{c['id']}/analysis-runs", json={"force": True},
                         headers={"Idempotency-Key": "abc"})
    k2 = env.client.post(f"/api/v1/cases/{c['id']}/analysis-runs", json={"force": True},
                         headers={"Idempotency-Key": "abc"})
    assert k1.json()["id"] == k2.json()["id"] and k2.status_code == 200
    assert env.client.get(f"/api/v1/cases/{c['id']}/analysis-runs").json()["total"] == 3


def test_concurrent_run_is_rejected(env):
    from app.models.analysis_run import AnalysisRun
    from app.models.enums import RunStatus, TriggerType
    c = env.case(); env.doc(c["id"])
    with env.session() as s:
        s.add(AnalysisRun(case_id=c["id"], trigger_type=TriggerType.MANUAL, status=RunStatus.RUNNING,
                          pipeline_version="1.0", input_fingerprint="x"))
        s.commit()
    r = env.run(c["id"], force=True)
    assert r.status_code == 409 and r.json()["error"]["code"] == "ANALYSIS_ALREADY_RUNNING"


def test_run_validation(env):
    c = env.case()
    assert env.run(c["id"]).status_code == 422  # no documents
    d = env.doc(c["id"])["document"]
    assert env.run(c["id"], document_ids=["doc_" + "0" * 21]).status_code == 404
    other = env.case(); od = env.doc(other["id"])["document"]
    assert env.run(c["id"], document_ids=[od["id"]]).status_code == 404  # other case's document
    assert env.run(c["id"], requested_modules=["nope"]).status_code == 422
    assert env.run("case_" + "0" * 21).status_code == 404
    assert env.client.get("/api/v1/analysis-runs/run_" + "0" * 21).status_code == 404
    assert env.client.get("/api/v1/analysis-runs/bad").status_code == 422
    assert env.client.post("/api/v1/analysis-runs/run_" + "0" * 21 + "/retry").status_code == 404
    ok = env.run(c["id"], requested_modules=["conflict_detection"], document_ids=[d["id"]])
    assert [s["stage_name"] for s in ok.json()["stages"]] == ["document_intelligence", "conflict_detection"]


def test_retry_rejected_for_completed_run(env):
    c = env.case(); env.doc(c["id"])
    run = env.run(c["id"]).json()
    r = env.client.post(f"/api/v1/analysis-runs/{run['id']}/retry")
    assert r.status_code == 409 and r.json()["error"]["code"] == "RETRY_NOT_ALLOWED"


def test_new_document_enables_reanalysis_without_overwriting_history(env):
    c = env.case()
    env.doc(c["id"], "fir.pdf", "one")
    first = env.run(c["id"]).json()
    ev_before = env.client.get(f"/api/v1/cases/{c['id']}/evidence").json()["total"]
    d2 = env.doc(c["id"], "order.pdf", "two")
    assert d2["analysis_needs_refresh"] is True
    assert env.client.get(f"/api/v1/analysis-runs/{first['id']}").json()["is_stale"] is True
    assert "ANALYSIS_MARKED_STALE" in event_types(env, c["id"])
    second = env.run(c["id"]).json()
    assert second["id"] != first["id"] and second["status"] == "COMPLETED"
    assert len(second["input_documents"]) == 2 and len(first["input_documents"]) == 1
    # first document was NOT re-sent to the document agent: no duplicate evidence
    assert env.client.get(f"/api/v1/cases/{c['id']}/evidence").json()["total"] == ev_before + 2
    # prior run outputs still retrievable
    old = env.client.get(f"/api/v1/cases/{c['id']}/rule-results", params={"analysis_run_id": first["id"]}).json()
    assert old["total"] == 1
    assert env.client.get(f"/api/v1/cases/{c['id']}").json()["analysis_needs_refresh"] is False


def test_new_version_of_same_filename_is_analysed_as_latest(env):
    c = env.case()
    env.doc(c["id"], "fir.pdf", "v1")
    r1 = env.run(c["id"]).json()
    v2 = env.doc(c["id"], "fir.pdf", "v2")["document"]
    r2 = env.run(c["id"]).json()
    assert [d["document_id"] for d in r2["input_documents"]] == [v2["id"]]
    assert r2["input_documents"][0]["version"] == 2
    assert r1["input_documents"][0]["version"] == 1


def test_auto_reanalysis_on_new_document(make_env):
    e = make_env(auto_reanalyze_on_new_document=True)
    c = e.case()
    res = e.doc(c["id"], "fir.pdf", "x")
    assert res["triggered_analysis_run_id"]
    run = e.client.get(f"/api/v1/analysis-runs/{res['triggered_analysis_run_id']}").json()
    assert run["trigger_type"] == "NEW_DOCUMENT" and run["status"] == "COMPLETED"


def test_run_status_state_machine():
    import pytest
    from app.core.exceptions import InvalidStateTransitionError
    from app.core.state import RUN_TRANSITIONS, ensure_transition
    from app.models.enums import RunStatus as R
    ensure_transition(R.PENDING, R.RUNNING, RUN_TRANSITIONS, "run")
    ensure_transition(R.RUNNING, R.PARTIALLY_COMPLETED, RUN_TRANSITIONS, "run")
    for a, b in [(R.PENDING, R.COMPLETED), (R.COMPLETED, R.RUNNING), (R.FAILED, R.COMPLETED),
                 (R.CANCELLED, R.RUNNING)]:
        with pytest.raises(InvalidStateTransitionError):
            ensure_transition(a, b, RUN_TRANSITIONS, "run")


def test_registry_loads_custom_agent_and_reports_bad_path(tmp_path):
    from tests.conftest import make_settings
    from app.orchestration.registry import build_default_registry
    s = make_settings(tmp_path, enable_demo_agents=False,
                      conflict_agent_class="app.integrations.conflict_agent:DemoConflictAgent",
                      reasoning_agent_class="no.such.module:Thing")
    d = build_default_registry(s).describe()
    assert d["conflict_detection"]["status"] == "CONFIGURED" and d["conflict_detection"]["source"] == "custom"
    assert d["reasoning"]["status"] == "NOT_CONFIGURED" and "configuration_error" in d["reasoning"]
    assert d["document_intelligence"]["status"] == "NOT_CONFIGURED"


def test_registry_rejects_object_without_required_method():
    import pytest
    from app.orchestration.registry import AgentRegistry
    with pytest.raises(TypeError):
        AgentRegistry().register("reasoning", object())
