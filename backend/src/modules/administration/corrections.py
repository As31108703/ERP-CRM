"""附理由更正（A§2 correctRecord）：整列 before／after 快照寫進 change 紀錄。

更正後的整個工作區（時段重疊、change 鏈：沒有實際變更、改了不允許的欄位、前後不連續）
由命令管線之後的 invariants 檢查；任何一項失敗，整個命令連同這筆 change 一起回滾。
"""

from typing import Any

from src.modules.administration import validators as v
from src.modules.administration.changes import append_change, ensure_capacity
from src.modules.administration.entity import CHANGE_COLLECTIONS, COLLECTIONS
from src.modules.administration.lookup import row_by_id
from src.modules.administration.snapshot import row_out
from src.platform.context import CommandContext


def correct_record(
    ctx: CommandContext, table: str, row_id: Any, kind: str, edits: dict[str, Any], reason: str
) -> str:
    """更正 `table`（集合名稱，例如 "shifts"）中的一列，回傳該列 id。

    `edits` 是已驗證過的欄位值（資料表型別）。流程：理由 → 紀錄上限 → before 快照 →
    套用 edits 並把 updated_at 設為命令時間 → after 快照 → 新增 change（at 同為命令時間）。
    """
    if CHANGE_COLLECTIONS.get(kind) != table:
        raise ValueError(f"更正種類 {kind} 不屬於 {table}")
    text = v.text(reason, 1000)
    ensure_capacity(ctx)
    row = row_by_id(ctx, COLLECTIONS[table], str(row_id), lock=True)
    before = row_out(table, row)
    for key, value in edits.items():
        setattr(row, key, value)
    row.updated_at = ctx.now  # type: ignore[attr-defined]
    ctx.db.add(row)
    append_change(ctx, kind, row.id, text, before, row_out(table, row))  # type: ignore[attr-defined]
    return str(row.id)  # type: ignore[attr-defined]
