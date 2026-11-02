"""行政命令的 payload 形狀（A§2）：必填鍵與選填鍵，其餘鍵一律 422 office_fields_invalid。"""

from dataclasses import dataclass, field
from typing import Any

from src.modules.administration.validators import precheck, strict_keys


@dataclass(frozen=True)
class Shape:
    required: frozenset[str]
    optional: frozenset[str] = field(default_factory=frozenset)


def shape(required: tuple[str, ...], optional: tuple[str, ...] = ()) -> Shape:
    return Shape(frozenset(required), frozenset(optional))


ACTIONS: dict[str, Shape] = {
    "office.enable": shape(()),
    "office.unit.create": shape(("name", "kind"), ("parent_id",)),
    "office.unit.update": shape(("id",), ("name", "active")),
    "office.staff.create": shape(("code", "alias", "unit_id"), ("role_label",)),
    "office.staff.update": shape(("id",), ("alias", "role_label", "status")),
    "office.equipment.create": shape(("code", "name", "unit_id")),
    "office.equipment.update": shape(("id",), ("name", "state")),
    "office.notice.create": shape(("title",), ("body", "unit_id", "pinned", "due_at")),
    "office.notice.update": shape(("id",), ("title", "body", "unit_id", "pinned", "due_at")),
    "office.notice.archive": shape(("id",)),
    "office.notice.restore": shape(("id",)),
}


def parse(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    """通用前置檢查加上嚴格鍵檢查；回傳同一個 payload 方便串接。"""
    precheck(payload)
    spec = ACTIONS[action]
    strict_keys(payload, set(spec.required), set(spec.optional))
    return payload
