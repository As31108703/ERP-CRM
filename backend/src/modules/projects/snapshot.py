"""projects 模組的快照與還原。

tasks、milestones 存在 crm 的通用紀錄表，快照鍵與還原由 crm 的 `snapshot`／`restore`
一併處理（不論 crm 是否啟用都會執行），這裡不重複輸出，避免同一集合被寫兩次。
"""

from typing import Any

from sqlmodel import Session


def snapshot(_db: Session, _workspace_id: str) -> dict[str, Any]:
    return {}


def restore(_db: Session, _workspace_id: str, _data: dict[str, Any]) -> None:
    return None
