import pytest


def test_create_get_list_update_case(env):
    c = env.case(external_reference="EXT-1", court_name="Court A",
                 statutory_sections=[{"act": "Demo Act", "section": "12"}],
                 metadata={"note": "synthetic"})
    assert c["id"].startswith("case_") and c["status"] == "OPEN"
    assert c["statutory_sections"][0]["section"] == "12"
    got = env.client.get(f"/api/v1/cases/{c['id']}").json()
    assert got["metadata"] == {"note": "synthetic"}

    r = env.client.patch(f"/api/v1/cases/{c['id']}", json={"court_name": "Court B", "police_station": None})
    assert r.status_code == 200 and r.json()["court_name"] == "Court B"
    assert env.client.get("/api/v1/cases").json()["total"] == 1


def test_invalid_case_input(env):
    assert env.client.post("/api/v1/cases", json={}).status_code == 422
    assert env.client.post("/api/v1/cases", json={"title": "x", "bogus": 1}).status_code == 422
    c = env.case()
    assert env.client.patch(f"/api/v1/cases/{c['id']}", json={"status": None}).status_code == 422
    assert env.client.patch(f"/api/v1/cases/{c['id']}", json={"created_by": "x"}).status_code == 422


def test_duplicate_external_reference_conflicts(env):
    env.case(external_reference="DUP")
    r = env.client.post("/api/v1/cases", json={"title": "again", "external_reference": "DUP"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "DUPLICATE_CASE_REFERENCE"


def test_case_status_transitions_validated(env):
    c = env.case()
    url = f"/api/v1/cases/{c['id']}"
    assert env.client.patch(url, json={"status": "ARCHIVED"}).status_code == 200
    r = env.client.patch(url, json={"status": "OPEN"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


def test_pagination_and_filters(env):
    for i in range(5):
        env.case(title=f"Case {i}", court_name="Court X" if i % 2 == 0 else "Court Y")
    page = env.client.get("/api/v1/cases", params={"limit": 2, "offset": 0}).json()
    assert len(page["items"]) == 2 and page["total"] == 5
    last = env.client.get("/api/v1/cases", params={"limit": 2, "offset": 4}).json()
    assert len(last["items"]) == 1
    assert env.client.get("/api/v1/cases", params={"court_name": "Court X"}).json()["total"] == 3
    assert env.client.get("/api/v1/cases", params={"limit": 0}).status_code == 422
    assert env.client.get("/api/v1/cases", params={"limit": 1000}).status_code == 422


def test_case_history_contains_only_that_case(env):
    a, b = env.case(), env.case()
    env.doc(a["id"])
    env.doc(b["id"])
    h = env.client.get(f"/api/v1/cases/{a['id']}/history").json()
    assert h["case"]["id"] == a["id"]
    assert h["documents"]["total"] == 1
    assert {e["case_id"] for e in h["audit_events"]["items"]} == {a["id"]}


def test_document_registration_versions_and_idempotency(env):
    c = env.case()
    d1 = env.doc(c["id"], "order.pdf", "v1-content")
    assert d1["created"] is True and d1["document"]["version"] == 1
    again = env.doc(c["id"], "order.pdf", "v1-content")
    assert again["created"] is False and again["document"]["id"] == d1["document"]["id"]
    d2 = env.doc(c["id"], "order.pdf", "v2-content")
    assert d2["document"]["version"] == 2 and d2["analysis_needs_refresh"] is True
    listing = env.client.get(f"/api/v1/cases/{c['id']}/documents").json()
    assert listing["total"] == 2  # old version preserved
    st = env.client.get(f"/api/v1/documents/{d2['document']['id']}/status").json()
    assert st["processing_status"] == "PENDING" and st["evidence_count"] == 0


def test_document_validation(env):
    c = env.case()
    url = f"/api/v1/cases/{c['id']}/documents"
    base = {"filename": "a.pdf", "mime_type": "application/pdf", "size_bytes": 1,
            "checksum_sha256": "a" * 64}
    assert env.client.post(url, json={**base, "filename": "a.exe"}).status_code == 415
    assert env.client.post(url, json={**base, "mime_type": "application/x-msdownload"}).status_code == 415
    assert env.client.post(url, json={**base, "checksum_sha256": "zz"}).status_code == 422
    assert env.client.post(url, json={**base, "size_bytes": 10**9}).status_code == 413
    assert env.client.post(url, json={**base, "storage_key": "../etc/passwd"}).status_code == 422
    assert env.client.post(f"/api/v1/cases/case_{'0'*21}/documents", json=base).status_code == 404
    assert env.client.get(f"/api/v1/documents/doc_{'0'*21}").status_code == 404


def test_upload_endpoint_validates_and_stores_privately(make_env, tmp_path):
    e = make_env(max_upload_bytes=100)
    c = e.case()
    url = f"/api/v1/cases/{c['id']}/documents/upload"
    ok = e.client.post(url, files={"file": ("../../evil name.pdf", b"%PDF-1.4 synthetic", "application/pdf")})
    assert ok.status_code == 201, ok.text
    doc = ok.json()["document"]
    assert doc["filename"] == "evil name.pdf" and ".." not in doc["storage_key"]
    stored = (tmp_path / "storage" / doc["storage_key"])
    assert stored.is_file() and stored.read_bytes().startswith(b"%PDF")
    # identical re-upload is idempotent
    again = e.client.post(url, files={"file": ("evil name.pdf", b"%PDF-1.4 synthetic", "application/pdf")})
    assert again.status_code == 200 and again.json()["created"] is False
    assert e.client.post(url, files={"file": ("a.pdf", b"not a pdf", "application/pdf")}).status_code == 415
    assert e.client.post(url, files={"file": ("a.exe", b"MZ", "application/octet-stream")}).status_code == 415
    assert e.client.post(url, files={"file": ("a.pdf", b"%PDF-" + b"x" * 500, "application/pdf")}).status_code == 413
    assert e.client.post(url, files={"file": ("a.pdf", b"", "application/pdf")}).status_code == 422
    leftovers = [p for p in (tmp_path / "storage" / c["id"]).iterdir() if p.name.endswith(".part")]
    assert leftovers == []


def test_storage_resolve_blocks_traversal(tmp_path):
    from app.core.exceptions import InvalidInputError
    from app.services.storage import LocalFileStorage
    s = LocalFileStorage(tmp_path)
    for bad in ("../x", "a/../../x", "/abs", "a//b", ""):
        with pytest.raises(InvalidInputError):
            s.resolve(bad)
    assert s.resolve("ok/file.pdf").is_relative_to(tmp_path.resolve())
