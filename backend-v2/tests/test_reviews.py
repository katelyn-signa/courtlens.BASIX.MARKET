def _setup(env):
    c = env.case(); env.doc(c["id"])
    run = env.run(c["id"]).json()
    return c, run


def test_review_lifecycle_and_validation(env):
    c, run = _setup(env)
    r = env.client.post(f"/api/v1/cases/{c['id']}/reviews",
                        json={"analysis_run_id": run["id"], "reviewer_id": "rev-1", "notes": "initial"})
    assert r.status_code == 201
    rv = r.json()
    assert rv["status"] == "PENDING_REVIEW" and "not a court order" in rv["notice"]
    url = f"/api/v1/reviews/{rv['id']}"
    assert env.client.patch(url, json={"status": "REVIEW_COMPLETED"}).status_code == 409  # must be IN_REVIEW first
    assert env.client.patch(url, json={"status": "IN_REVIEW"}).json()["status"] == "IN_REVIEW"
    done = env.client.patch(url, json={"status": "REVIEW_COMPLETED", "notes": "done"}).json()
    assert done["status"] == "REVIEW_COMPLETED" and done["completed_at"] and done["workflow_action"] == "COMPLETE_REVIEW"
    locked = env.client.patch(url, json={"notes": "edit after completion"})
    assert locked.status_code == 409 and locked.json()["error"]["code"] == "REVIEW_ALREADY_COMPLETED"
    assert env.client.get(url).json()["notes"] == "done"
    assert env.client.get(f"/api/v1/cases/{c['id']}/reviews").json()["total"] == 1


def test_review_is_separate_from_ai_results(env):
    c, run = _setup(env)
    before = (env.client.get(f"/api/v1/cases/{c['id']}/rule-results").json(),
              env.client.get(f"/api/v1/cases/{c['id']}/conflicts").json(),
              env.client.get(f"/api/v1/cases/{c['id']}/evidence").json())
    rr = before[1]["items"][0]
    rv = env.client.post(f"/api/v1/cases/{c['id']}/reviews", json={
        "analysis_run_id": run["id"], "reviewed_finding_refs": [{"type": "conflict", "id": rr["id"]}]}).json()
    env.client.patch(f"/api/v1/reviews/{rv['id']}", json={"status": "IN_REVIEW", "notes": "I disagree with the AI"})
    env.client.patch(f"/api/v1/reviews/{rv['id']}", json={"status": "REVIEW_COMPLETED"})
    after = (env.client.get(f"/api/v1/cases/{c['id']}/rule-results").json(),
             env.client.get(f"/api/v1/cases/{c['id']}/conflicts").json(),
             env.client.get(f"/api/v1/cases/{c['id']}/evidence").json())
    assert before == after
    assert env.client.get(f"/api/v1/reviews/{rv['id']}").json()["reviewed_finding_refs"][0]["id"] == rr["id"]


def test_review_reference_validation(env):
    c, run = _setup(env)
    other, other_run = _setup(env)
    url = f"/api/v1/cases/{c['id']}/reviews"
    assert env.client.post(url, json={"reviewed_finding_refs": [{"type": "conflict", "id": "cfl_" + "0" * 21}]}).status_code == 422
    assert env.client.post(url, json={"analysis_run_id": other_run["id"]}).status_code == 404
    assert env.client.post(url, json={"analysis_run_id": "run_" + "0" * 21}).status_code == 404
    assert env.client.post(url, json={"bogus": 1}).status_code == 422
    foreign = env.client.get(f"/api/v1/cases/{other['id']}/conflicts").json()["items"][0]["id"]
    assert env.client.post(url, json={"reviewed_finding_refs": [{"type": "conflict", "id": foreign}]}).status_code == 422
    assert env.client.post(f"/api/v1/cases/case_{'0'*21}/reviews", json={}).status_code == 404
    assert env.client.get(f"/api/v1/reviews/rev_{'0'*21}").status_code == 404


def test_request_additional_information(env):
    c, _ = _setup(env)
    rv = env.client.post(f"/api/v1/cases/{c['id']}/reviews", json={}).json()
    r = env.client.post(f"/api/v1/reviews/{rv['id']}/request-information",
                        json={"request_text": "Please upload the remand order."})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ADDITIONAL_INFORMATION_REQUESTED" and body["additional_evidence_requested"] is True
    assert body["additional_information_request"] == "Please upload the remand order."
    assert body["workflow_action"] == "REQUEST_ADDITIONAL_INFORMATION"
    types = [e["event_type"] for e in env.client.get(f"/api/v1/cases/{c['id']}/audit-events").json()["items"]]
    assert "ADDITIONAL_INFORMATION_REQUESTED" in types
    assert env.client.post(f"/api/v1/reviews/{rv['id']}/request-information", json={"request_text": ""}).status_code == 422
    # can resume after information arrives
    assert env.client.patch(f"/api/v1/reviews/{rv['id']}", json={"status": "IN_REVIEW"}).json()["status"] == "IN_REVIEW"


def test_review_filters_and_pagination(env):
    c, _ = _setup(env)
    for i in range(3):
        env.client.post(f"/api/v1/cases/{c['id']}/reviews", json={"reviewer_id": f"r{i % 2}"})
    base = f"/api/v1/cases/{c['id']}/reviews"
    assert env.client.get(base, params={"limit": 2}).json()["total"] == 3
    assert env.client.get(base, params={"reviewer_id": "r0"}).json()["total"] == 2
    assert env.client.get(base, params={"status": "IN_REVIEW"}).json()["total"] == 0
