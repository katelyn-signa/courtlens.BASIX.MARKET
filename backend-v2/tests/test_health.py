def test_app_imports():
    import app.main
    assert app.main.app.title


def test_health_endpoints(env):
    for path in ("/api/health", "/api/v1/health"):
        r = env.client.get(path)
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok" and body["database"] == "ok"
    assert "X-Request-ID" in env.client.get("/api/health").headers


def test_request_id_is_echoed(env):
    r = env.client.get("/api/health", headers={"X-Request-ID": "abc-123"})
    assert r.headers["X-Request-ID"] == "abc-123"


def test_openapi_and_docs_available(env):
    assert env.client.get("/docs").status_code == 200
    spec = env.client.get("/openapi.json").json()
    assert "/api/v1/cases" in spec["paths"]
    assert "/api/v1/analysis-runs/{run_id}/retry" in spec["paths"]


def test_system_status_reports_agents_without_secrets(make_env, empty_registry):
    e = make_env(registry=empty_registry, api_key="super-secret-key")
    r = e.client.get("/api/v1/system/status", headers={"X-API-Key": "super-secret-key"})
    assert r.status_code == 200
    body = r.json()
    assert all(a["status"] == "NOT_CONFIGURED" for a in body["agents"].values())
    assert body["authentication"]["api_key_required"] is True
    assert "super-secret-key" not in r.text


def test_system_status_shows_demo_agents_as_simulated(env):
    agents = env.client.get("/api/v1/system/status").json()["agents"]
    assert agents["reasoning"]["is_simulated"] is True


def test_api_key_enforced_but_health_open(make_env):
    e = make_env(api_key="k1")
    assert e.client.get("/api/health").status_code == 200
    assert e.client.get("/api/v1/cases").status_code == 401
    assert e.client.get("/api/v1/cases", headers={"X-API-Key": "wrong"}).status_code == 401
    assert e.client.get("/api/v1/cases", headers={"X-API-Key": "k1"}).status_code == 200


def test_error_shape_is_consistent(env):
    r = env.client.get("/api/v1/cases/not-an-id")
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "VALIDATION_ERROR" and err["request_id"]
    r = env.client.get("/api/v1/cases/case_" + "0" * 21)
    assert r.status_code == 404 and r.json()["error"]["code"] == "CASE_NOT_FOUND"
    assert env.client.get("/no/such/route").json()["error"]["code"] == "HTTP_ERROR"
