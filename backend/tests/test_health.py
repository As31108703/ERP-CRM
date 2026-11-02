def test_health_reports_simulation_flags(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {
        "name": "erpcrm",
        "version": "0.1.0",
        "simulation": True,
        "real_finance": False,
        "currency": "SIM",
    }
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"
