import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError

from app.db.base import Base
from app.db.migrate import upgrade_to_head
from app.models import (AnalysisRun, AuditEvent, AuditImmutableError, Case, Conflict, Document,
                        Evidence, Review, RuleResult)
from app.models.enums import (ConflictType, RuleEvaluationStatus, ReviewSignal, RunStatus,
                              TriggerType)


def _case(s):
    c = Case(title="t")
    s.add(c)
    s.flush()
    return c


def _doc(s, case, name="a.pdf", version=1):
    d = Document(case_id=case.id, filename=name, mime_type="application/pdf", size_bytes=1,
                 checksum_sha256="a" * 64, version=version)
    s.add(d)
    s.flush()
    return d


def _run(s, case):
    r = AnalysisRun(case_id=case.id, trigger_type=TriggerType.MANUAL, pipeline_version="1.0",
                    input_fingerprint="f" * 64)
    s.add(r)
    s.flush()
    return r


def test_connection_and_timestamps_are_utc_aware(env):
    with env.session() as s:
        c = _case(s)
        s.commit()
        s.refresh(c)
        assert c.created_at.tzinfo is not None and c.status.value == "OPEN"


def test_migrations_create_same_schema_as_models(tmp_path):
    url = f"sqlite:///{tmp_path / 'mig.db'}"
    upgrade_to_head(url)
    engine = create_engine(url)
    insp = inspect(engine)
    tables = set(insp.get_table_names()) - {"alembic_version"}
    assert tables == set(Base.metadata.tables)
    for name, table in Base.metadata.tables.items():
        assert {c["name"] for c in insp.get_columns(name)} == {c.name for c in table.columns}
    upgrade_to_head(url)  # idempotent
    engine.dispose()


def test_api_works_on_migrated_database(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from tests.conftest import make_settings
    s = make_settings(tmp_path, auto_migrate=True)
    with TestClient(create_app(s)) as client:  # lifespan runs Alembic
        assert client.post("/api/v1/cases", json={"title": "x"}).status_code == 201


def test_entities_persist_with_relationships(env):
    with env.session() as s:
        case = _case(s)
        doc = _doc(s, case)
        run = _run(s, case)
        ev = Evidence(case_id=case.id, document_id=doc.id, fact_type="FIR_REFERENCE",
                      fact_value={"reference": "X"}, source_page=1, confidence=0.9,
                      extraction_run_id=run.id)
        cf = Conflict(case_id=case.id, analysis_run_id=run.id,
                      conflict_type=ConflictType.AMBIGUOUS_FACT, description="d")
        rr = RuleResult(case_id=case.id, analysis_run_id=run.id, rule_id="R", rule_version="1",
                        evaluation_status=RuleEvaluationStatus.EVALUATED,
                        review_signal=ReviewSignal.NEEDS_HUMAN_REVIEW, explanation="e",
                        output_schema_version="1.0")
        rv = Review(case_id=case.id, analysis_run_id=run.id)
        s.add_all([ev, cf, rr, rv])
        s.commit()
        s.refresh(case)
        assert [d.id for d in case.documents] == [doc.id]
        assert [r.id for r in case.analysis_runs] == [run.id]
        assert [r.id for r in case.reviews] == [rv.id]
        assert doc.evidence_items[0].id == ev.id


def test_constraints(env):
    def expect_integrity(build):
        with env.session() as s:
            with pytest.raises(IntegrityError):
                build(s)
                s.commit()

    def dup_doc(s):
        c = _case(s)
        _doc(s, c)
        _doc(s, c)
    expect_integrity(dup_doc)

    def orphan_evidence(s):
        s.add(Evidence(case_id="nope", document_id="nope", fact_type="X", fact_value={"a": 1}))
    expect_integrity(orphan_evidence)

    def bad_confidence(s):
        c = _case(s); d = _doc(s, c)
        s.add(Evidence(case_id=c.id, document_id=d.id, fact_type="X", fact_value={"a": 1}, confidence=1.5))
    expect_integrity(bad_confidence)

    def bad_offsets(s):
        c = _case(s); d = _doc(s, c)
        s.add(Evidence(case_id=c.id, document_id=d.id, fact_type="X", fact_value={"a": 1},
                       char_start=10, char_end=2))
    expect_integrity(bad_offsets)

    def dup_ref(s):
        s.add(Case(external_reference="R")); s.add(Case(external_reference="R"))
    expect_integrity(dup_ref)

    def dup_idem(s):
        c = _case(s)
        for _ in range(2):
            r = AnalysisRun(case_id=c.id, trigger_type=TriggerType.MANUAL, pipeline_version="1",
                            input_fingerprint="f", idempotency_key="K")
            s.add(r); s.flush()
    expect_integrity(dup_idem)


def test_cannot_delete_case_with_history(env):
    with env.session() as s:
        c = _case(s)
        s.add(AuditEvent(case_id=c.id, event_type="CASE_CREATED"))
        s.commit()
        s.delete(c)
        with pytest.raises(IntegrityError):
            s.commit()


def test_audit_events_are_append_only_in_orm(env):
    with env.session() as s:
        c = _case(s)
        ev = AuditEvent(case_id=c.id, event_type="CASE_CREATED")
        s.add(ev)
        s.commit()
        ev.actor = "tamper"
        with pytest.raises(AuditImmutableError):
            s.commit()
        s.rollback()
        s.delete(s.get(AuditEvent, ev.id))
        with pytest.raises(AuditImmutableError):
            s.commit()
        s.rollback()
        assert s.get(AuditEvent, ev.id).actor is None


def test_audit_metadata_sanitised():
    from app.services.audit_service import sanitize_metadata
    out = sanitize_metadata({"quote": "secret words", "api_key": "k", "ok": 1,
                             "long": "x" * 500, "nested": {"text": "t", "n": [1, 2]}})
    assert out["quote"] == "[REDACTED]" and out["api_key"] == "[REDACTED]"
    assert out["long"].startswith("[TRUNCATED") and out["nested"]["text"] == "[REDACTED]"
    assert out["ok"] == 1


def test_identifiers_are_unique_and_sortable():
    from app.utils.identifiers import new_id, is_valid_id
    ids = [new_id("case") for _ in range(500)]
    assert len(set(ids)) == 500 and ids == sorted(ids)
    assert all(is_valid_id(i, "case") for i in ids)
