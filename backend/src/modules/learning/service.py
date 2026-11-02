"""流程教學的服務層：路線可用性、session 管理、偏好、執行一步與命令分派。

執行一步時走命令管線（action 為該步的命令、module 為該命令所屬模組），handler 依序：
產生 payload → 透過模組的 `HANDLERS` 執行 → 寫入檢查點與前後讀值 → 核對完成證據；
證據不成立時拋出 409 learning_evidence_invalid，由管線回滾 SAVEPOINT。
"""

import uuid
from typing import Any

from sqlalchemy import update
from sqlmodel import Session, select

from src.core import clock
from src.core.ids import new_id
from src.core.problem import Problem, ensure
from src.modules.crm import router as crm_router
from src.modules.inventory import router as inventory_router
from src.modules.learning import evidence
from src.modules.learning.entity import LearningCheckpointRow, LearningSessionRow
from src.modules.learning.paths import (
    BLOCKED_COMPLETE,
    BLOCKED_INVALID,
    BLOCKED_NOT_STARTED,
    BLOCKED_ORDER,
    PATHS,
    Blocked,
    Checkpoint,
    LearningPath,
    LearningStep,
    Run,
    World,
    prepare,
)
from src.modules.manufacturing import router as manufacturing_router
from src.modules.projects import router as projects_router
from src.modules.sales import router as sales_router
from src.modules.services import router as services_router
from src.modules.wallets import router as wallets_router
from src.platform.context import CommandContext, WorkspaceRow
from src.platform.records import Handler

# 各模組 router 匯出的命令表；action → (模組, handler) 由這些表機械展開，不另外維護對照
_ROUTERS = (
    crm_router,
    wallets_router,
    inventory_router,
    sales_router,
    services_router,
    manufacturing_router,
    projects_router,
)
_ACTIONS: dict[str, tuple[str, Handler]] = {
    action: (r.MODULE, handler) for r in _ROUTERS for action, handler in r.HANDLERS.items()
}

SCOPES = ("lesson", "workspace")
VIEW_KEYS = frozenset({"paused", "scope", "compact", "quiz_choice", "selected_step"})
QUIZ_CHOICES = 3


# --- 命令分派 ---------------------------------------------------------------------------------


def _action_invalid() -> Problem:
    return Problem(422, "action_invalid", "不支援的操作")


def module_of(action: str) -> str:
    """命令所屬模組；未知命令回 422 action_invalid。"""
    entry = _ACTIONS.get(action)
    if entry is None:
        raise _action_invalid()
    return entry[0]


def dispatch(ctx: CommandContext, action: str, payload: dict[str, Any]) -> str | None:
    """以模組 router 的 `HANDLERS[action]` 執行命令；未知命令回 422 action_invalid。"""
    entry = _ACTIONS.get(action)
    if entry is None:
        raise _action_invalid()
    return entry[1](ctx, payload)


# --- 路線與 session ---------------------------------------------------------------------------


def _modules(db: Session, ws_id: str) -> list[str]:
    workspace = db.get(WorkspaceRow, uuid.UUID(ws_id))
    return list(workspace.modules) if workspace is not None else []


def _paths_for(modules: list[str]) -> list[str]:
    return [p.id for p in PATHS.values() if all(m in modules for m in p.modules)]


def available_paths(db: Session, ws_id: str) -> list[str]:
    """工作區已啟用全部所需模組的路線 id（依定義順序）。"""
    return _paths_for(_modules(db, ws_id))


def _path(ctx: CommandContext, path_id: str) -> LearningPath:
    """路線存在（否則 404）且所需模組皆已啟用（否則 403 module_disabled）。"""
    path = PATHS.get(path_id)
    if path is None:
        raise Problem(404, "learning_path_missing", "找不到這條教學路線")
    assert ctx.workspace is not None
    ensure(
        all(m in ctx.workspace.modules for m in path.modules),
        403,
        "module_disabled",
        "目前工作區未啟用這條教學需要的模組。",
    )
    return path


def _workspace(ctx: CommandContext) -> WorkspaceRow:
    ensure(ctx.workspace is not None, 409, "workspace_missing", "請先建立工作區")
    assert ctx.workspace is not None
    return ctx.workspace


def _sessions(db: Session, workspace_id: uuid.UUID) -> list[LearningSessionRow]:
    stmt = (
        select(LearningSessionRow)
        .where(LearningSessionRow.workspace_id == workspace_id)
        .order_by(LearningSessionRow.seq)  # type: ignore[arg-type]
    )
    return list(db.exec(stmt))


def current_session(db: Session, workspace_id: uuid.UUID, path: str) -> LearningSessionRow | None:
    """該路線最新建立的一輪。"""
    stmt = (
        select(LearningSessionRow)
        .where(LearningSessionRow.workspace_id == workspace_id, LearningSessionRow.path == path)
        .order_by(LearningSessionRow.seq.desc())  # type: ignore[union-attr]
        .limit(1)
    )
    return db.exec(stmt).first()


def _require_session(ctx: CommandContext, path: LearningPath) -> LearningSessionRow:
    session = current_session(ctx.db, _workspace(ctx).id, path.id)
    if session is None:
        raise Problem(409, "learning_session_missing", BLOCKED_NOT_STARTED)
    return session


def _activate(ctx: CommandContext, session: LearningSessionRow) -> None:
    """工作區至多一輪為 active：先清掉其他輪，再標記這一輪。"""
    ctx.db.flush()
    ctx.db.execute(
        update(LearningSessionRow)
        .where(
            LearningSessionRow.workspace_id == session.workspace_id,  # type: ignore[arg-type]
            LearningSessionRow.id != session.id,  # type: ignore[arg-type]
            LearningSessionRow.active,  # type: ignore[arg-type]
        )
        .values(active=False)
        .execution_options(synchronize_session="fetch")
    )
    session.active = True
    session.updated_at = ctx.now
    ctx.db.flush()


def _new_session(
    ctx: CommandContext, path: LearningPath, like: LearningSessionRow | None = None
) -> LearningSessionRow:
    workspace = _workspace(ctx)
    session = LearningSessionRow(
        workspace_id=workspace.id,
        path=path.id,
        run_id=new_id(),
        paused=like.paused if like else False,
        scope=like.scope if like else "lesson",
        compact=like.compact if like else False,
        created_at=ctx.now,
        updated_at=ctx.now,
    )
    ctx.db.add(session)
    ctx.db.flush()
    return session


# --- 輸出 -------------------------------------------------------------------------------------


def session_out(s: LearningSessionRow) -> dict[str, Any]:
    return {
        "id": str(s.id),
        "path": s.path,
        "run_id": s.run_id,
        "active": s.active,
        "paused": s.paused,
        "scope": s.scope,
        "compact": s.compact,
        "quiz_choice": s.quiz_choice,
        "selected_step": s.selected_step,
        "created_at": clock.iso(s.created_at),
        "updated_at": clock.iso(s.updated_at),
    }


def _snapshots(db: Session, w: World, session: LearningSessionRow, run: Run) -> dict[str, Any]:
    """只保留與 history 相符之檢查點的前後讀值。"""
    stmt = select(LearningCheckpointRow).where(LearningCheckpointRow.session_id == session.id)
    out: dict[str, Any] = {}
    for row in db.exec(stmt):
        c = run.cp(row.step_id)
        if c is None or not evidence.history_matches(w, c):
            continue
        out[row.step_id] = {
            "version": row.version,
            "result": row.result,
            "rows": evidence.snapshot_rows(row.before, row.after),
        }
    return out


def _preview(
    ctx: CommandContext, w: World, run: Run | None, evaluation: evidence.Evaluation
) -> dict[str, str | None]:
    if run is None:
        return {"text": None, "blocked_reason": BLOCKED_NOT_STARTED}
    if not evidence.valid_run(w, run):
        return {"text": None, "blocked_reason": BLOCKED_INVALID}
    if evaluation["complete"]:
        return {"text": None, "blocked_reason": BLOCKED_COMPLETE}
    step = PATHS[run.path].steps[evaluation["next_index"]]
    command = prepare(w, run, step, ctx.now)
    if isinstance(command, Blocked):
        return {"text": None, "blocked_reason": command.reason}
    return {"text": command.preview, "blocked_reason": None}


def detail(ctx: CommandContext, path_id: str) -> dict[str, Any]:
    """`GET /api/v1/learning/{path}`：路線內容、目前這一輪、進度、預覽、讀值與前後讀值。"""
    workspace = _workspace(ctx)
    path = _path(ctx, path_id)
    session = current_session(ctx.db, workspace.id, path.id)
    run = evidence.load_run(ctx.db, session) if session is not None else None
    w = evidence.load_world(ctx.db, workspace, (c.version for c in run.checkpoints) if run else ())
    shown = run or Run(path.id, "")
    evaluation = evidence.evaluate_world(w, shown)
    return {
        "path": path.public(),
        "session": session_out(session) if session is not None else None,
        "evaluation": evaluation,
        "preview": _preview(ctx, w, run, evaluation),
        "facts": {
            "lesson": evidence.facts(w, shown, "lesson"),
            "workspace": evidence.facts(w, shown, "workspace"),
        },
        "snapshots": _snapshots(ctx.db, w, session, run) if session and run else {},
    }


def listing(ctx: CommandContext) -> dict[str, Any]:
    """`GET /api/v1/learning`：可用路線、各路線目前這一輪的進度，以及建議接續的路線。"""
    if ctx.workspace is None:
        return {"available_paths": [], "sessions": [], "active": None}
    workspace = ctx.workspace
    available = _paths_for(list(workspace.modules))
    current: dict[str, LearningSessionRow] = {}
    active_path: str | None = None
    for s in _sessions(ctx.db, workspace.id):
        if s.path in available:
            current[s.path] = s  # 依 seq 排序，最後一筆即最新一輪
            if s.active:
                active_path = s.path
    runs = {p: evidence.load_run(ctx.db, s) for p, s in current.items()}
    versions = [c.version for r in runs.values() for c in r.checkpoints]
    w = evidence.load_world(ctx.db, workspace, versions)
    sessions = []
    for path_id in available:
        if path_id not in current:
            continue
        evaluation = evidence.evaluate_world(w, runs[path_id])
        sessions.append(
            {
                "path": path_id,
                "run_id": current[path_id].run_id,
                "confirmed": sum(1 for s in evaluation["steps"] if s["complete"]),
                "total": len(evaluation["steps"]),
            }
        )
    if active_path is None and runs:
        # 沒有選取中的路線時，接續最後一個檢查點版本最高的一輪
        def last_version(path_id: str) -> int:
            checkpoints = runs[path_id].checkpoints
            return checkpoints[-1].version if checkpoints else 0

        active_path = max(runs, key=last_version)
    if active_path is None and available:
        active_path = available[0]
    return {"available_paths": available, "sessions": sessions, "active": active_path}


# --- 偏好寫入（不經過命令管線） ----------------------------------------------------------------


def _empty_body(body: dict[str, Any]) -> None:
    ensure(not body, 422, "payload_invalid", "參數不符")


def start(ctx: CommandContext, path_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """接續該路線最新一輪；沒有時建立一輪。並設為工作區目前選取的路線。"""
    _empty_body(body)
    workspace = _workspace(ctx)
    path = _path(ctx, path_id)
    session = current_session(ctx.db, workspace.id, path.id) or _new_session(ctx, path)
    _activate(ctx, session)
    return detail(ctx, path.id)


def restart(ctx: CommandContext, path_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """另開一輪：新的 run_id，沿用暫停、資料範圍與精簡設定；現有工作區資料保留。"""
    _empty_body(body)
    workspace = _workspace(ctx)
    path = _path(ctx, path_id)
    previous = current_session(ctx.db, workspace.id, path.id)
    session = _new_session(ctx, path, like=previous)
    _activate(ctx, session)
    return detail(ctx, path.id)


def _view_invalid() -> Problem:
    return Problem(422, "learning_view_invalid", "教學畫面設定不符")


def update_view(ctx: CommandContext, path_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """`PATCH /view`：只更新目前這一輪的畫面偏好。"""
    _workspace(ctx)
    path = _path(ctx, path_id)
    if not set(body) <= VIEW_KEYS:
        raise _view_invalid()
    for key in ("paused", "compact"):
        if key in body and not isinstance(body[key], bool):
            raise _view_invalid()
    if "scope" in body and body["scope"] not in SCOPES:
        raise _view_invalid()
    if "quiz_choice" in body:
        choice = body["quiz_choice"]
        if choice is not None and not (
            isinstance(choice, int) and not isinstance(choice, bool) and 0 <= choice < QUIZ_CHOICES
        ):
            raise _view_invalid()
    if "selected_step" in body:
        step = body["selected_step"]
        if step is not None and (not isinstance(step, str) or path.step(step) is None):
            raise _view_invalid()
    session = _require_session(ctx, path)
    for key, value in body.items():
        setattr(session, key, value)
    session.updated_at = ctx.now
    ctx.db.flush()
    return detail(ctx, path.id)


# --- 執行一步（走命令管線） ---------------------------------------------------------------------


def requested_step(path_id: str, body: Any) -> LearningStep | None:
    """body 指定的步驟；路線或步驟不存在時回 None。"""
    path = PATHS.get(path_id)
    if path is None or not isinstance(body, dict):
        return None
    step_id = body.get("step_id")
    return path.step(step_id) if isinstance(step_id, str) else None


def execute_handler(path_id: str) -> Handler:
    """`POST /execute {step_id}` 的管線 handler。"""

    def handler(ctx: CommandContext, body: dict[str, Any]) -> str | None:
        workspace = _workspace(ctx)
        path = _path(ctx, path_id)
        ensure(set(body) <= {"step_id"}, 422, "payload_invalid", "參數不符")
        step = requested_step(path_id, body)
        if step is None:
            raise Problem(422, "learning_step_invalid", "找不到這個教學步驟")
        session = _require_session(ctx, path)
        ensure(not session.paused, 409, "learning_paused", "教學已暫停，繼續教學後才能執行。")
        return _execute(ctx, workspace, path, session, step)

    return handler


def _blocked(reason: str) -> Problem:
    return Problem(409, "learning_step_blocked", reason)


def _execute(
    ctx: CommandContext,
    workspace: WorkspaceRow,
    path: LearningPath,
    session: LearningSessionRow,
    step: LearningStep,
) -> str | None:
    run = evidence.load_run(ctx.db, session)
    w = evidence.load_world(ctx.db, workspace, (c.version for c in run.checkpoints))
    if not evidence.valid_run(w, run):
        raise _blocked(BLOCKED_INVALID)
    progress = evidence.evaluate_world(w, run)
    if progress["complete"]:
        raise _blocked(BLOCKED_COMPLETE)
    index = progress["next_index"]
    if path.steps[index].id != step.id:
        raise _blocked(BLOCKED_ORDER)
    # 前面若有未通過證據的舊檢查點（例如紀錄已被改動），這一輪無法再前進
    if any(c.step_id == step.id for c in run.checkpoints):
        raise _blocked(BLOCKED_INVALID)
    command = prepare(w, run, step, ctx.now)
    if isinstance(command, Blocked):
        raise _blocked(command.reason)
    before = evidence.facts(w, run, "lesson")[: evidence.FACT_ROWS_MAX]

    result = dispatch(ctx, command.action, dict(command.payload))
    ctx.db.flush()
    if not isinstance(result, str) or not 0 < len(result) <= evidence.RESULT_MAX:
        raise _evidence_invalid()
    # 管線在 handler 之後把版本號加一，並以同一組 {action, result, version} 寫入 history
    version = ctx.session_row.version + 1
    checkpoint = Checkpoint(step.id, step.action, command.payload, result, version)
    updated = Run(run.path, run.run_id, [*run.checkpoints, checkpoint])
    w_after = evidence.load_world(ctx.db, workspace, (c.version for c in run.checkpoints))
    w_after["version"] = version
    w_after["history"].append({"action": step.action, "result": result, "version": version})
    after = evidence.facts(w_after, updated, "lesson")[: evidence.FACT_ROWS_MAX]

    ctx.db.add(
        LearningCheckpointRow(
            session_id=session.id,
            step_id=step.id,
            action=step.action,
            payload=command.payload,
            result=result,
            version=version,
            before=before,
            after=after,
        )
    )
    session.selected_step = step.id
    session.updated_at = ctx.now
    ctx.db.flush()

    if not evidence.evaluate_world(w_after, updated)["steps"][index]["complete"]:
        raise _evidence_invalid()
    return result


def _evidence_invalid() -> Problem:
    return Problem(409, "learning_evidence_invalid", "未找到這次教學操作的實際證據，未保存進度。")
