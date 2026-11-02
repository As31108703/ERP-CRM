"""業務命令的通用前置檢查（B§3.1）：records.precheck 的順序與各錯誤碼。"""

from typing import Any

import pytest

from src.core.problem import Problem
from src.platform import records


def _code(action: str, payload: Any) -> str:
    with pytest.raises(Problem) as e:
        records.precheck(action, payload)
    return e.value.code


@pytest.mark.parametrize(
    ("action", "payload", "code"),
    [
        ("product.create", [], "payload_invalid"),
        ("product.create", None, "payload_invalid"),
        ("order.create", {"bank": 1}, "simulation_required"),
        ("order.create", {"xPAYERx": 1}, "simulation_required"),
        ("order.create", {"finance_note": 1}, "simulation_required"),
        ("order.create", {"Legal": 1}, "simulation_required"),
        ("order.create", {"payment_url": 1}, "simulation_required"),
        # 禁用鍵名先於保護欄位
        ("order.create", {"bank": 1, "currency": "SIM"}, "simulation_required"),
        ("order.create", {"currency": "SIM"}, "protected_field"),
        ("order.create", {"simulation": True}, "protected_field"),
        # real_finance 同時命中禁用鍵名（finance），禁用鍵名先檢查
        ("order.create", {"real_finance": False}, "simulation_required"),
        ("order.create", {"balance_minor": 1}, "protected_field"),
        ("order.create", {"on_hand": 1}, "protected_field"),
        ("order.create", {"reserved": 1}, "protected_field"),
        ("order.create", {"lots": []}, "protected_field"),
        ("order.create", {"stock_value_minor": 1}, "protected_field"),
        ("order.pay", {"learning_run_id": "abcdefgh"}, "learning_id_invalid"),
        ("order.create", {"learning_run_id": "short"}, "learning_id_invalid"),
        ("order.create", {"learning_run_id": "bad id!!"}, "learning_id_invalid"),
        ("workOrder.create", {"learning_run_id": 12345678}, "learning_id_invalid"),
        ("order.pay", {"amount_minor": 0}, "number_invalid"),
        ("order.ship", {"quantity": -1}, "number_invalid"),
        ("order.ship", {"quantity": True}, "number_invalid"),
        ("order.create", {"lines": []}, "lines_invalid"),
        ("order.create", {"lines": {}}, "lines_invalid"),
        ("order.create", {"lines": [{"quantity": 1}] * 51}, "lines_invalid"),
        ("order.create", {"lines": [{"quantity": 0}]}, "number_invalid"),
        ("order.create", {"lines": ["x"]}, "number_invalid"),
        ("wallet.create", {"kind": "business", "name": "x"}, "wallet_invalid"),
        ("product.update", {"id": "x", "color": "red"}, "product_invalid"),
    ],
)
def test_precheck_rejects(action: str, payload: Any, code: str) -> None:
    assert _code(action, payload) == code


@pytest.mark.parametrize(
    ("action", "payload"),
    [
        ("order.create", {"learning_run_id": "run_ABC-123", "lines": [{"quantity": 1}] * 50}),
        ("workOrder.create", {"learning_run_id": "x" * 80, "quantity": 1}),
        # 行政命令不檢查 quantity／amount_minor 下限
        ("office.request.create", {"amount_minor": 0, "quantity": 0}),
        ("real_finance_only_in_value", {"note": "bank"}),
    ],
)
def test_precheck_accepts(action: str, payload: Any) -> None:
    records.precheck(action, payload)


def test_precheck_normalizes_integral_floats() -> None:
    out = records.precheck("order.pay", {"amount_minor": 5.0, "id": "x"})
    assert out == {"amount_minor": 5, "id": "x"}
    assert type(out["amount_minor"]) is int


def test_command_merges_path_params_after_body() -> None:
    seen: list[dict[str, Any]] = []

    def handler(_ctx, payload):
        seen.append(payload)
        return "ok"

    wrapped = records.command("wallet.fund", handler, wallet_id="path-id")
    assert wrapped(None, {"wallet_id": "body-id", "amount_minor": 1}) == "ok"  # type: ignore[arg-type]
    assert seen == [{"wallet_id": "path-id", "amount_minor": 1}]


def test_command_prechecks_before_handler() -> None:
    def handler(_ctx, _payload):
        raise AssertionError("不應執行")

    with pytest.raises(Problem) as e:
        records.command("wallet.create", handler)(None, {"bank": 1})  # type: ignore[arg-type]
    assert e.value.code == "simulation_required"
