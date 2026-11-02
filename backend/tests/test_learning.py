"""流程教學：三條路線的伺服器端進度、完成證據、前後讀值、偏好與命令分派。"""

from types import SimpleNamespace
from typing import Any

import pytest

from src.core.problem import Problem
from src.modules.learning import service as learning_service
from src.modules.learning.paths import PATHS
from tests.helpers import ApiClient

LEARNING = "/api/v1/learning"


def _error(r) -> tuple[int, str]:
    return r.status_code, r.json()["error"]["code"]


def _detail(api: ApiClient, path: str) -> dict[str, Any]:
    r = api.get(f"{LEARNING}/{path}")
    assert r.status_code == 200, r.text
    return r.json()


def _start(api: ApiClient, path: str) -> dict[str, Any]:
    return api.ok("POST", f"{LEARNING}/{path}/start")


def _execute(api: ApiClient, path: str, step_id: str, **kwargs: Any):
    return api.mutate("POST", f"{LEARNING}/{path}/execute", {"step_id": step_id}, **kwargs)


def _run_all(api: ApiClient, path: str) -> dict[str, Any]:
    for step in PATHS[path].steps:
        detail = _detail(api, path)
        assert detail["preview"]["blocked_reason"] is None, (step.id, detail["preview"])
        assert detail["preview"]["text"]
        r = _execute(api, path, step.id)
        assert r.status_code == 200, (step.id, r.text)
        assert r.json()["result"]
    return _detail(api, path)


def _assert_complete(detail: dict[str, Any], total: int) -> None:
    evaluation = detail["evaluation"]
    assert evaluation["complete"] is True
    assert evaluation["next_index"] == total
    assert len(evaluation["steps"]) == total
    for step in evaluation["steps"]:
        assert step["complete"] is True
        assert step["checkpoint"] is not None
        assert step["evidence_text"]
    assert set(detail["snapshots"]) == {s["id"] for s in evaluation["steps"]}
    for snapshot in detail["snapshots"].values():
        assert 0 < len(snapshot["rows"]) <= 12
        assert set(snapshot["rows"][0]) == {"label", "before", "after", "node"}
    _assert_fact_nodes(detail)
    assert detail["preview"]["text"] is None
    assert detail["preview"]["blocked_reason"] == "本次教學已完成，請開始另一輪練習。"


def _assert_fact_nodes(detail: dict[str, Any]) -> None:
    """每列讀值都帶 node：非 null 時必為路線示意圖的節點；每個節點至少有一列讀值，
    且「整個工作區」範圍涵蓋全部節點。前後讀值的 node 也只能是示意圖節點或 null。"""
    nodes = set(detail["path"]["nodes"])
    covered: set[str] = set()
    for scope in ("lesson", "workspace"):
        facts = detail["facts"][scope]
        assert all(set(f) == {"label", "value", "node"} for f in facts), facts
        tagged = {f["node"] for f in facts if f["node"] is not None}
        assert tagged <= nodes, (scope, tagged - nodes)
        covered |= tagged
    assert covered == nodes
    assert {f["node"] for f in detail["facts"]["workspace"]} >= nodes
    for snapshot in detail["snapshots"].values():
        assert {r["node"] for r in snapshot["rows"]} <= nodes | {None}


@pytest.mark.parametrize("path_id", sorted(PATHS))
def test_diagram_nodes_unique_and_steps_resolvable(path_id: str) -> None:
    path = PATHS[path_id]
    assert len(set(path.nodes)) == len(path.nodes)
    # 步驟的 node 若在示意圖上，必定只對應一個節點（不屬於示意圖的步驟例如建立顧客則不標示）
    for step in path.steps:
        assert path.nodes.count(step.node) <= 1


def test_fact_nodes_before_start(api: ApiClient) -> None:
    api.setup("retail")
    for path_id in api.get(LEARNING).json()["available_paths"]:
        _assert_fact_nodes(_detail(api, path_id))


def test_sales_path_full_run(api: ApiClient) -> None:
    api.setup("retail")
    _start(api, "sales")
    version_before = api.state()["version"]
    detail = _run_all(api, "sales")
    _assert_complete(detail, 8)
    assert api.state()["version"] == version_before + 8
    run_id = detail["session"]["run_id"]
    ws = api.snapshot()
    order = next(o for o in ws["orders"] if o["learning_run_id"] == run_id)
    assert order["paid_minor"] == order["total_minor"]
    assert order["lines"][0]["shipped_quantity"] == 1
    assert [h["action"] for h in ws["history"][-8:]] == [s.action for s in PATHS["sales"].steps]
    # 前後讀值：建立訂單那一步，本輪訂單由 0 筆變 1 筆
    rows = {r["label"]: r for r in detail["snapshots"]["order"]["rows"]}
    assert rows["本輪訂單"]["before"] == "0 筆"
    assert rows["本輪訂單"]["after"] == "1 筆"
    assert rows["本輪訂單"]["node"] == "order"
    assert rows["本輪已出貨"]["node"] == "shipment"
    labels = [f["label"].split(" ·")[0] for f in detail["facts"]["lesson"]]
    assert labels[:2] == ["本輪顧客", "本輪訂單"]
    assert detail["facts"]["workspace"][0]["label"] == "工作區顧客"
    listing = api.get(LEARNING).json()
    assert listing["sessions"] == [{"path": "sales", "run_id": run_id, "confirmed": 8, "total": 8}]


def test_cannot_skip_step_409(api: ApiClient) -> None:
    api.setup("retail")
    _start(api, "sales")
    before = api.snapshot()
    r = _execute(api, "sales", "buyer")
    assert _error(r) == (409, "learning_step_blocked")
    assert r.json()["error"]["message"] == "請先完成目前這一步，不會跳過前面的操作。"
    assert api.snapshot() == before
    # 不存在的步驟
    assert _error(_execute(api, "sales", "nope")) == (422, "learning_step_invalid")
    # 還沒開始的路線
    assert _error(_execute(api, "manufacturing", "fund-business"))[0] in (403, 409)
    assert api.snapshot() == before


def test_service_path_full_run(api: ApiClient) -> None:
    api.setup("service")
    _start(api, "service")
    detail = _run_all(api, "service")
    _assert_complete(detail, 12)
    ws = api.snapshot()
    run_id = detail["session"]["run_id"]
    service = next(s for s in ws["services"] if s["title"] == f"教學服務案件 {run_id}")
    assert service["status"] == "accepted"
    assert service["paid_minor"] == service["amount_minor"] == 100000


def test_manufacturing_path_full_run(api: ApiClient) -> None:
    api.setup("manufacturing")
    _start(api, "manufacturing")
    detail = _run_all(api, "manufacturing")
    _assert_complete(detail, 6)
    run_id = detail["session"]["run_id"]
    wo = next(o for o in api.snapshot()["work_orders"] if o["learning_run_id"] == run_id)
    assert wo["status"] == "completed"
    assert isinstance(wo["actual_cost_minor"], int)


def test_restart_new_run_keeps_data(api: ApiClient) -> None:
    api.setup("retail")
    first = _start(api, "sales")["session"]
    assert _execute(api, "sales", "customer").status_code == 200
    customers = len(api.snapshot()["customers"])
    version = api.state()["version"]
    restarted = api.ok("POST", f"{LEARNING}/sales/restart")
    assert restarted["session"]["run_id"] != first["run_id"]
    assert restarted["evaluation"]["next_index"] == 0
    assert restarted["snapshots"] == {}
    # 現有資料保留，另開一輪不增加版本號
    assert len(api.snapshot()["customers"]) == customers
    assert api.state()["version"] == version
    # start 接續最新一輪
    assert _start(api, "sales")["session"]["run_id"] == restarted["session"]["run_id"]
    assert _execute(api, "sales", "customer").status_code == 200
    assert _detail(api, "sales")["evaluation"]["next_index"] == 1


def test_paths_filtered_by_modules(api: ApiClient) -> None:
    api.setup("service")
    listing = api.get(LEARNING).json()
    assert listing["available_paths"] == ["service"]
    catalog = {p["id"]: p for p in listing["paths"]}
    assert set(catalog) == set(PATHS)
    for path_id, path in PATHS.items():
        assert catalog[path_id]["modules"] == list(path.modules)
        assert catalog[path_id]["title"] == path.title
        assert catalog[path_id]["available"] is (path_id == "service")
    assert listing["sessions"] == []
    assert listing["active"] == "service"
    assert _error(api.mutate("POST", f"{LEARNING}/sales/start")) == (403, "module_disabled")
    assert _error(api.mutate("POST", f"{LEARNING}/unknown/start")) == (404, "learning_path_missing")


def test_execute_is_idempotent(api: ApiClient) -> None:
    api.setup("retail")
    _start(api, "sales")
    state = api.state()
    key = "learning-key-0001"
    first = _execute(api, "sales", "customer", key=key, version=state["version"])
    assert first.status_code == 200, first.text
    again = _execute(api, "sales", "customer", key=key, version=state["version"])
    assert again.status_code == 200, again.text
    assert again.json()["replayed"] is True
    assert again.json()["result"] == first.json()["result"]
    assert api.state()["version"] == state["version"] + 1
    detail = _detail(api, "sales")
    assert detail["evaluation"]["next_index"] == 1
    names = [c["name"] for c in api.snapshot()["customers"]]
    assert names.count(f"教學客戶 {detail['session']['run_id']}") == 1


def test_view_preferences_without_version(api: ApiClient) -> None:
    api.setup("retail")
    _start(api, "sales")
    version = api.state()["version"]
    body = {"paused": True, "scope": "workspace", "compact": True, "quiz_choice": 1}
    r = api.mutate("PATCH", f"{LEARNING}/sales/view", {**body, "selected_step": "pay"})
    assert r.status_code == 200, r.text
    session = r.json()["session"]
    assert session["paused"] is True
    assert session["scope"] == "workspace"
    assert session["compact"] is True
    assert session["quiz_choice"] == 1
    assert session["selected_step"] == "pay"
    assert api.state()["version"] == version
    # 暫停時不能執行
    assert _error(_execute(api, "sales", "customer")) == (409, "learning_paused")
    bad = api.mutate("PATCH", f"{LEARNING}/sales/view", {"scope": "all"})
    assert _error(bad) == (422, "learning_view_invalid")
    assert _error(api.mutate("PATCH", f"{LEARNING}/sales/view", {"x": 1})) == (
        422,
        "learning_view_invalid",
    )
    # CSRF 與 Origin 仍要檢查
    r = api.mutate("PATCH", f"{LEARNING}/sales/view", {"paused": False}, csrf="bad")
    assert _error(r) == (403, "csrf_invalid")
    r = api.mutate("PATCH", f"{LEARNING}/sales/view", {"paused": False}, origin="http://evil")
    assert _error(r) == (403, "origin_invalid")
    assert _detail(api, "sales")["session"]["paused"] is True


def test_evidence_invalid_rolls_back(api: ApiClient, monkeypatch: pytest.MonkeyPatch) -> None:
    api.setup("retail")
    _start(api, "sales")
    before = api.snapshot()
    version = api.state()["version"]
    monkeypatch.setattr(learning_service.evidence, "evidence_for", lambda *a, **k: None)
    r = _execute(api, "sales", "customer")
    assert _error(r) == (409, "learning_evidence_invalid")
    assert api.snapshot() == before
    assert api.state()["version"] == version
    monkeypatch.undo()
    assert _detail(api, "sales")["evaluation"]["next_index"] == 0


@pytest.mark.parametrize("action", ["workOrder.delete", "task.delete", "nope"])
def test_dispatch_unknown_action_422(action: str) -> None:
    ctx = SimpleNamespace()
    with pytest.raises(Problem) as exc:
        learning_service.dispatch(ctx, action, {})  # type: ignore[arg-type]
    assert (exc.value.status, exc.value.code) == (422, "action_invalid")


def test_available_paths_helper(api: ApiClient, db_engine) -> None:
    from sqlmodel import Session, select

    from src.platform.context import WorkspaceRow

    api.setup("manufacturing")
    with Session(db_engine) as db:
        ws = db.exec(select(WorkspaceRow)).one()
        assert learning_service.available_paths(db, str(ws.id)) == ["sales", "manufacturing"]


def test_learning_cascades_with_workspace(api: ApiClient) -> None:
    api.setup("retail")
    _start(api, "sales")
    assert _execute(api, "sales", "customer").status_code == 200
    api.ok("POST", "/api/v1/workspace/clear")
    api.setup("retail")
    listing = api.get(LEARNING).json()
    assert listing["sessions"] == []


def test_listing_without_workspace_lists_requirements(api: ApiClient) -> None:
    r = api.get(LEARNING)
    assert r.status_code == 200
    body = r.json()
    assert body["available_paths"] == [] and body["sessions"] == [] and body["active"] is None
    assert [p["id"] for p in body["paths"]] == list(PATHS)
    assert all(p["available"] is False and p["modules"] for p in body["paths"])
