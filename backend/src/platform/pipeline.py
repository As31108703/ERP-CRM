"""命令管線：所有寫入 API 共用的檢查、冪等收據、版本鎖、模組閘、一致性檢查與歷史紀錄。

同一個 session 的寫入以 `SELECT … FOR UPDATE` 鎖住 session 列而依序執行；
速率計數在鎖內先寫入，其餘步驟包在 SAVEPOINT 裡，任何一步失敗都只回滾 SAVEPOINT，
因此失敗的請求仍會計入速率限制，但業務資料、版本號、history 與收據完全不變。
"""

import hmac
import json
import re
import uuid
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Any, NoReturn, TypedDict, TypeVar

from fastapi import Request
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session, select

from src.config.settings import Settings
from src.core import clock
from src.core.canonical import digest
from src.core.ids import token_hex
from src.core.problem import Problem, ensure
from src.middleware.session import hash_token, request_scheme, session_token
from src.platform import invariants, ratelimit, receipts
from src.platform.context import CommandContext, HistoryRow, WorkspaceRow, WorkspaceSessionRow
from src.platform.receipts import RECEIPT_CAP, ReceiptOut, ReceiptRow

BODY_LIMIT = 32_768
IMPORT_BODY_LIMIT = 3 * 1024 * 1024
_KEY_RE = re.compile(r"[A-Za-z0-9_-]{8,100}", re.ASCII)
_VERSION_RE = re.compile(r"[0-9]+", re.ASCII)
# 版本號存在 int 欄位，超過這個長度的數字不可能相符，直接視為過期，避免轉換超長字串
_VERSION_MAX_DIGITS = 18

Handler = Callable[[CommandContext, dict[str, Any]], str | None]
T = TypeVar("T")


class MutationResponse(TypedDict):
    result: str | None
    receipt: ReceiptOut
    csrf: str
    version: int
    replayed: bool


async def raw_body(request: Request) -> bytes:
    """FastAPI 依賴：讀取原始 body。

    最多讀到備份匯入上限多 1 byte 就停，超過上限的請求由管線的 body_limit 檢查回 413。
    """
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        chunks.append(chunk)
        size += len(chunk)
        if size > IMPORT_BODY_LIMIT:
            break
    return b"".join(chunks)


def _session_query(token_hash: str):  # SQLModel select 的型別冗長，交給推論
    return (
        select(WorkspaceSessionRow)
        .where(WorkspaceSessionRow.token_hash == token_hash)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def lock_session(db: Session, token: str, now: datetime) -> WorkspaceSessionRow:
    """取得並鎖住權杖對應的 session 列；不存在就建立（同權杖並行建立時只會有一筆）。"""
    token_hash = hash_token(token)
    row = db.exec(_session_query(token_hash)).first()
    if row is None:
        db.execute(
            pg_insert(WorkspaceSessionRow.__table__)
            .values(
                id=uuid.uuid4(),
                token_hash=token_hash,
                csrf=token_hex(32),
                version=0,
                last_seen_at=now,
                rate_start=now,
                rate_count=0,
                created_at=now,
            )
            .on_conflict_do_nothing(index_elements=["token_hash"])
        )
        row = db.exec(_session_query(token_hash)).one()
    return row


def session_now(row: WorkspaceSessionRow) -> datetime:
    """取得鎖之後讀取的目前時間，且不早於該 session 最後存取時間。

    系統時鐘可能倒退（WSL 實測約 1.5 秒）；同一 session 的請求依鎖序執行，
    取最大值讓時間對每個工作區單調不減，更正與申請紀錄的時間順序規則才不會誤判。
    """
    now = clock.utcnow()
    last = row.last_seen_at
    return max(now, last) if last is not None else now


def load_workspace(db: Session, session_id: uuid.UUID) -> WorkspaceRow | None:
    stmt = (
        select(WorkspaceRow)
        .where(WorkspaceRow.session_id == session_id)
        .execution_options(populate_existing=True)
    )
    return db.exec(stmt).first()


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def begin_consistent_read(db: Session) -> None:
    """在 db 目前沒有交易時，以 REPEATABLE READ 開始下一個交易。

    GET 的讀取分成多個查詢（各模組快照、報表、工作台）；預設的 READ COMMITTED 每個查詢各自
    取快照，並行命令在讀取途中提交就會讀到前後不一致的資料。REPEATABLE READ 讓整次讀取
    共用第一個查詢時的快照，也不會擋住命令寫入。交易結束後連線歸還連線池時隔離等級會還原。"""
    db.connection(execution_options={"isolation_level": "REPEATABLE READ"})


def touch_session(request: Request) -> Iterator[CommandContext]:
    """GET 用的 FastAPI 依賴：計入速率限制、更新最後存取時間並提交，
    再以單一 REPEATABLE READ 交易交出唯讀用的 context。"""
    with Session(request.app.state.engine, expire_on_commit=False) as db:
        try:
            row = lock_session(db, session_token(request), clock.utcnow())
            # 速率與存取時間以取得鎖之後為準，且同一 session 單調不減
            now = session_now(row)
            ratelimit.hit(row, now)
            db.commit()
        except BaseException:
            db.rollback()
            raise
        begin_consistent_read(db)
        yield CommandContext(
            db=db,
            session_row=row,
            workspace=load_workspace(db, row.id),
            now=now,
            settings=_settings(request),
        )


def _origin_ok(request: Request, settings: Settings) -> bool:
    origin = request.headers.get("origin")
    if not origin:
        return False
    origin = origin.lower()
    allowed = [o.rstrip("/").lower() for o in settings.app.allowed_origins]
    if allowed:
        return origin in allowed
    forwarded_host = request.headers.get("x-forwarded-host", "").split(",")[0].strip()
    host = forwarded_host or request.headers.get("host", "")
    if not host:
        return False
    scheme = request_scheme(request.scope, request.headers)
    return origin == f"{scheme}://{host}".lower()


def _json_invalid() -> NoReturn:
    raise Problem(422, "json_invalid", "JSON 格式不符")


def _reject_constant(_name: str) -> NoReturn:
    # NaN、Infinity 不是合法 JSON
    _json_invalid()


def _parse_json(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError, RecursionError):
        _json_invalid()


def check_origin_csrf(request: Request, settings: Settings, row: WorkspaceSessionRow) -> None:
    """寫入請求的 Origin 與 CSRF 檢查（命令管線第 4–5 步，偏好寫入共用）。"""
    ensure(_origin_ok(request, settings), 403, "origin_invalid", "拒絕跨來源寫入")
    csrf = request.headers.get("x-csrf-token", "")
    ensure(
        hmac.compare_digest(csrf.encode("utf-8"), row.csrf.encode("utf-8")),
        403,
        "csrf_invalid",
        "工作區驗證失敗",
    )


def parse_body(raw: bytes, body_limit: int = BODY_LIMIT) -> dict[str, Any]:
    """body 大小與 JSON 物件檢查（命令管線第 8–9 步）。"""
    ensure(len(raw) <= body_limit, 413, "body_limit", "請求太大")
    body = _parse_json(raw)
    ensure(isinstance(body, dict), 422, "payload_invalid", "參數不符")
    return body


class CommandPipeline:
    def preference(
        self,
        request: Request,
        raw: bytes,
        *,
        handler: Callable[[CommandContext, dict[str, Any]], T],
        body_limit: int = BODY_LIMIT,
    ) -> T:
        """不影響業務資料的偏好寫入（例如教學畫面設定）：同樣鎖住 session 列、計入速率限制，
        並檢查 Origin、CSRF 與 body，但不需要 Idempotency-Key 與 If-Match-Version，
        也不增加版本號、不寫 history 與收據。handler 失敗時只回滾 SAVEPOINT。"""
        settings = _settings(request)
        token = session_token(request)
        with Session(request.app.state.engine, expire_on_commit=False) as db:
            try:
                row = lock_session(db, token, clock.utcnow())
                now = session_now(row)
                ratelimit.hit(row, now)
                db.flush()
            except BaseException:
                db.rollback()
                raise

            savepoint = db.begin_nested()
            try:
                check_origin_csrf(request, settings, row)
                body = parse_body(raw, body_limit)
                workspace = load_workspace(db, row.id)
                ensure(workspace is not None, 409, "workspace_missing", "請先建立工作區")
                ctx = CommandContext(
                    db=db, session_row=row, workspace=workspace, now=now, settings=settings
                )
                out = handler(ctx, body)
                db.flush()
                savepoint.commit()
            except BaseException:
                savepoint.rollback()
                db.commit()
                raise
            db.commit()
            return out

    def mutate(
        self,
        request: Request,
        raw: bytes,
        *,
        action: str,
        handler: Handler,
        needs_workspace: bool = True,
        module: str | None = None,
        body_limit: int = BODY_LIMIT,
        prunes_receipts: bool = False,
        bypass_receipt_cap: bool = False,
    ) -> MutationResponse:
        settings = _settings(request)
        token = session_token(request)
        with Session(request.app.state.engine, expire_on_commit=False) as db:
            try:
                # 1–2：解析並鎖住 session 列
                row = lock_session(db, token, clock.utcnow())
                # 鎖可能等了一段時間，之後的步驟以取得鎖之後的時間為準
                now = session_now(row)
                # 3：速率限制；計數在 SAVEPOINT 之外，後續步驟失敗也會保留
                ratelimit.hit(row, now)
                db.flush()
            except BaseException:
                db.rollback()
                raise

            savepoint = db.begin_nested()
            try:
                response = self._run(
                    db,
                    row,
                    request,
                    raw,
                    now=now,
                    settings=settings,
                    action=action,
                    handler=handler,
                    needs_workspace=needs_workspace,
                    module=module,
                    body_limit=body_limit,
                    prunes_receipts=prunes_receipts,
                    bypass_receipt_cap=bypass_receipt_cap,
                )
                savepoint.commit()
            except BaseException:
                savepoint.rollback()
                # 21：只提交速率計數與最後存取時間
                db.commit()
                raise
            db.commit()
            return response

    def _run(
        self,
        db: Session,
        row: WorkspaceSessionRow,
        request: Request,
        raw: bytes,
        *,
        now: datetime,
        settings: Settings,
        action: str,
        handler: Handler,
        needs_workspace: bool,
        module: str | None,
        body_limit: int,
        prunes_receipts: bool,
        bypass_receipt_cap: bool,
    ) -> MutationResponse:
        headers = request.headers
        # 4–5：Origin 與 CSRF
        check_origin_csrf(request, settings, row)
        # 6：Idempotency-Key
        key = headers.get("idempotency-key", "")
        ensure(_KEY_RE.fullmatch(key) is not None, 422, "key_required", "請提供操作識別")
        # 7：If-Match-Version
        expected = headers.get("if-match-version", "")
        ensure(
            _VERSION_RE.fullmatch(expected) is not None, 428, "version_required", "請提供工作區版本"
        )
        # 8–9：body 大小與 JSON
        body = parse_body(raw, body_limit)
        # 10：請求摘要綁定路徑、body 與預期版本字串
        request_hash = digest({"path": request.url.path, "body": body, "expected": expected})
        # 11：重播（必須在版本比對之前：前端重送時帶的是原本的版本號）
        prior = receipts.find(db, row.id, key)
        if prior is not None:
            ensure(
                prior.hash == request_hash,
                409,
                "idempotency_conflict",
                "相同識別不能使用不同參數",
            )
            return {
                "result": prior.result,
                "receipt": receipts.to_out(prior),
                "csrf": row.csrf,
                "version": row.version,
                "replayed": True,
            }
        # 12：版本鎖
        expected_version = int(expected) if len(expected) <= _VERSION_MAX_DIGITS else -1
        ensure(expected_version == row.version, 412, "version_stale", "工作區版本已更新")
        # 13：收據上限
        if not bypass_receipt_cap:
            ensure(
                receipts.count(db, row.id) < RECEIPT_CAP,
                429,
                "receipt_limit",
                "操作數已達試用上限，請先備份，再清除或還原工作區",
            )
        # 14：工作區
        workspace = load_workspace(db, row.id)
        if needs_workspace:
            ensure(workspace is not None, 409, "workspace_missing", "請先建立工作區")
        # 15：模組閘
        if module is not None:
            ensure(
                workspace is not None and module in workspace.modules,
                403,
                "module_disabled",
                "模組未啟用",
            )
        # 16：業務邏輯
        ctx = CommandContext(
            db=db, session_row=row, workspace=workspace, now=now, settings=settings
        )
        result = handler(ctx, body)
        db.flush()
        # handler 可能建立或刪除工作區（setup、clear、import），以資料庫現況為準
        ctx.workspace = load_workspace(db, row.id)
        # 17：版本號
        row.version += 1
        # 18：history 只記業務命令（setup、clear、import 不記）
        if needs_workspace and ctx.workspace is not None:
            db.add(
                HistoryRow(
                    workspace_id=ctx.workspace.id,
                    action=action,
                    result=result,
                    version=row.version,
                    created_at=now,
                )
            )
        # 19：一致性檢查在版本號與 history 寫入之後，檢查的是命令完成後的完整工作區
        # （工作區大小含新的 history 與版本號）；失敗時兩者隨 SAVEPOINT 一起回滾
        invariants.check_all(ctx)
        # 20：收據；已達上限時，可修剪的操作先修剪到最近 100 筆
        if prunes_receipts and receipts.count(db, row.id) >= RECEIPT_CAP:
            receipts.prune(db, row.id)
        receipt = ReceiptRow(
            session_id=row.id,
            key=key,
            hash=request_hash,
            expected_version=expected_version,
            version=row.version,
            action=action,
            result=result,
            created_at=now,
        )
        receipts.record(db, receipt)
        db.flush()
        return {
            "result": result,
            "receipt": receipts.to_out(receipt),
            "csrf": row.csrf,
            "version": row.version,
            "replayed": False,
        }


_PIPELINE = CommandPipeline()


def get_pipeline() -> CommandPipeline:
    """FastAPI 依賴：命令管線本身沒有狀態，共用同一個實例。"""
    return _PIPELINE
