"""行政檢視：待辦概覽、入門路線、篩選列表、出勤差異與 CSV 匯出（A§4–A§6）。"""

import csv
import io
import re
from typing import Any

import pytest

from src.modules.administration import csv_export
from tests.helpers import ApiClient

BASE = "/api/v1/administration"
UNITS = f"{BASE}/units"
STAFF = f"{BASE}/staff"
SHIFTS = f"{BASE}/shifts"
ATTENDANCE = f"{BASE}/attendance"
REQUESTS = f"{BASE}/requests"
NOTICES = f"{BASE}/notices"
DEMO = f"{BASE}/demo"
OVERVIEW = f"{BASE}/overview"
ROWS = f"{BASE}/rows"
DIFF = f"{BASE}/attendance-diff"
EXPORT = f"{BASE}/export.csv"
WEEK = "2026-11-02"

SCOPE_HEADERS = [
    "模式",
    "工作區",
    "工作區版本",
    "資料類型",
    "組織範圍",
    "搜尋條件",
    "狀態篩選",
    "日期範圍",
    "時區",
    "產出時間",
    "篩選統計",
    "資料來源",
]
TAIL_HEADERS = ["建立時間（臺北）", "更新時間（臺北）", "更正與保留紀錄"]


def _error(r) -> tuple[int, str]:
    return r.status_code, r.json()["error"]["code"]


def _t(day: str, hm: str) -> str:
    return f"{day}T{hm}:00+08:00"


def _adm(api: ApiClient) -> dict[str, Any]:
    return api.snapshot()["administration"]


def _demo(api: ApiClient, *, setup: bool = True) -> dict[str, Any]:
    if setup:
        api.setup("general", company="星軌示範商店")
    api.ok("POST", DEMO, {"preset": "store", "week_start": WEEK})
    return _adm(api)


def _get(api: ApiClient, path: str, **params: str) -> Any:
    r = api.get(path, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _csv(api: ApiClient, **params: str) -> tuple[str, list[list[str]]]:
    r = api.get(EXPORT, params=params)
    assert r.status_code == 200, r.text
    body = r.content.decode("utf-8")
    assert body.startswith("﻿")
    return body, list(csv.reader(io.StringIO(body[1:], newline="")))


# --- 概覽與入門路線 -------------------------------------------------------------------


def test_overview_tiles(api: ApiClient) -> None:
    api.setup("general", company="星軌示範商店")
    empty = _get(api, OVERVIEW, now=_t("2026-11-03", "13:30"))
    guide = empty["onboarding"]
    assert [(s["id"], s["label"], s["done"]) for s in guide["steps"]] == [
        ("unit", "建立組織", False),
        ("staff", "加入假員工", False),
        ("shift", "排第一個班次", False),
    ]
    assert [s["reason"] for s in guide["steps"]] == [
        "",
        "先新增一個使用中的門市或部門。",
        "先新增使用中組織與假員工。",
    ]
    assert (guide["completed"], guide["open"], empty["demo_empty"]) == (0, True, True)
    assert [t["value"] for t in empty["tiles"]] == [0, 0, 0, None]
    assert empty["tiles"][3]["sub"] == "還沒有即將截止的公告"

    adm = _demo(api, setup=False)
    req = adm["requests"][0]["id"]
    api.ok("POST", f"{REQUESTS}/{req}/submit", {})
    notice = adm["notices"][0]

    # 11/03 13:30 台北：示範借用（13:00–15:00）進行中，設備不算可用
    during = _get(api, OVERVIEW, now=_t("2026-11-03", "13:30"))
    assert during["now"] == "2026-11-03T05:30:00.000Z"
    assert during["week"] == WEEK
    tiles = {t["id"]: t for t in during["tiles"]}
    assert list(tiles) == ["requests", "equipment", "attendance", "notice"]
    assert (tiles["requests"]["label"], tiles["requests"]["value"]) == ("申請待整理", 1)
    assert tiles["requests"]["sub"] == "0 件待補件"
    assert tiles["requests"]["target"] == {
        "tab": "requests",
        "unit": None,
        "type": "all",
        "status": "submitted",
    }
    assert (tiles["equipment"]["label"], tiles["equipment"]["value"]) == ("目前可用設備", 0)
    assert tiles["equipment"]["target"] == {
        "tab": "equipment",
        "unit": None,
        "status": "available_now",
    }
    # 兩位示範夥伴的排班與手動出勤分鐘都不同
    assert (tiles["attendance"]["label"], tiles["attendance"]["value"]) == ("本週出勤差異", 2)
    assert tiles["attendance"]["target"] == {"tab": "attendance", "status": "active"}
    assert (tiles["notice"]["label"], tiles["notice"]["value"]) == ("最近公告截止", "11-06")
    assert tiles["notice"]["sub"] == notice["title"]
    assert tiles["notice"]["target"] == {
        "tab": "notices",
        "unit": None,
        "status": "active",
        "q": notice["title"],
    }
    guide = during["onboarding"]
    assert [s["done"] for s in guide["steps"]] == [True, True, True]
    assert [s["button"] for s in guide["steps"]] == ["再建立組織", "再加入假員工", "新增另一個班次"]
    assert (guide["completed"], guide["open"], during["demo_empty"]) == (3, False, False)
    assert during["counts"] == {
        "units": 1,
        "staff": 2,
        "shifts": 5,
        "attendance": 2,
        "requests": 1,
        "equipment": 1,
        "reservations": 1,
        "notices": 2,
    }

    # 預約結束（end 不含）後設備可用；截止時間已過的公告不再列為最近截止
    after = _get(api, OVERVIEW, now=_t("2026-11-06", "16:00"))
    tiles = {t["id"]: t for t in after["tiles"]}
    assert tiles["equipment"]["value"] == 1
    assert tiles["notice"]["value"] == "11-06"
    later = _get(api, OVERVIEW, now=_t("2026-11-10", "09:00"))
    tiles = {t["id"]: t for t in later["tiles"]}
    assert (tiles["notice"]["value"], tiles["notice"]["sub"]) == (None, "還沒有即將截止的公告")
    assert later["week"] == "2026-11-09"
    assert (tiles["attendance"]["label"], tiles["attendance"]["value"]) == ("本週出勤差異", 0)
    chosen = _get(api, OVERVIEW, now=_t("2026-11-10", "09:00"), week=WEEK)
    tiles = {t["id"]: t for t in chosen["tiles"]}
    assert (tiles["attendance"]["label"], tiles["attendance"]["value"]) == ("選定週出勤差異", 2)


def test_overview_gates(api: ApiClient) -> None:
    assert _error(api.get(OVERVIEW)) == (409, "workspace_missing")
    api.setup("general", modules=["inventory"])
    for path in (OVERVIEW, ROWS, DIFF, EXPORT):
        assert _error(api.get(path, params={"tab": "units"})) == (403, "module_disabled")


# --- 篩選列表 -----------------------------------------------------------------------


def test_rows_filter_default_attendance_active(api: ApiClient) -> None:
    adm = _demo(api)
    first, second = (a["id"] for a in adm["attendance"])
    api.ok("POST", f"{ATTENDANCE}/{first}/void", {"reason": "輸入錯誤"})

    default = _get(api, ROWS, tab="attendance", week=WEEK)
    assert [r["id"] for r in default["rows"]] == [second]
    assert default["status_scope"] == "有效紀錄"
    assert default["period"] == "2026-11-02 至 2026-11-08（依開始日歸週）"
    # 篩選統計只算目前篩選結果
    assert default["summary"] == (
        "目前篩選的有效出勤 1 筆，共 410 分鐘；另保留 0 筆作廢紀錄，作廢不計入。"
    )
    every = _get(api, ROWS, tab="attendance", week=WEEK, status="all")
    # 開始時間由新到舊
    assert [r["id"] for r in every["rows"]] == [second, first]
    assert every["summary"] == (
        "目前篩選的有效出勤 1 筆，共 410 分鐘；另保留 1 筆作廢紀錄，作廢不計入。"
    )
    voided = _get(api, ROWS, tab="attendance", week=WEEK, status="voided")
    assert [r["id"] for r in voided["rows"]] == [first]
    assert voided["status_scope"] == "已作廢"
    # 其他週沒有資料
    assert _get(api, ROWS, tab="attendance", week="2026-11-09")["rows"] == []


def test_rows_filters_search_unit_and_sort(api: ApiClient) -> None:
    adm = _demo(api)
    unit = adm["units"][0]["id"]
    s1 = adm["staff"][0]

    shifts = _get(api, ROWS, tab="shifts", week=WEEK)
    assert [r["start_at"][:10] for r in shifts["rows"]] == [
        "2026-11-02",
        "2026-11-03",
        "2026-11-04",
        "2026-11-05",
        "2026-11-06",
    ]
    assert shifts["status_scope"] == "全部狀態"
    assert shifts["summary"] == ("目前篩選的有效班次 5 筆，共 2100 分鐘；另保留 0 筆取消紀錄。")
    # 搜尋暱稱（不分大小寫、去頭尾空白）
    mine = _get(api, ROWS, tab="shifts", week=WEEK, q=f"  {s1['alias']} ")
    assert len(mine["rows"]) == 3
    assert _get(api, ROWS, tab="staff", q="demo-1")["rows"][0]["id"] == s1["id"]
    other = api.ok("POST", UNITS, {"name": "倉庫", "kind": "branch"})["result"]
    assert _get(api, ROWS, tab="staff", unit=other)["rows"] == []
    assert len(_get(api, ROWS, tab="staff", unit=unit)["rows"]) == 2
    # 組織：搜尋含上層名稱；單位篩選比對組織本身
    assert [r["id"] for r in _get(api, ROWS, tab="units", unit=other)["rows"]] == [other]
    units = _get(api, ROWS, tab="units", status="inactive")
    assert (units["rows"], units["status_scope"]) == ([], "停用")
    assert units["summary"] == "目前篩選共 0 筆模擬紀錄。"

    # 申請：類型與狀態篩選
    req = _get(api, ROWS, tab="requests", type="purchase", status="draft")
    assert len(req["rows"]) == 1
    assert req["status_scope"] == "請購／草稿"
    assert (
        req["summary"] == "目前篩選的申請登錄合計 32.00 SIM。此為模擬登錄金額，不代表核准或支付。"
    )
    assert _get(api, ROWS, tab="requests", type="leave")["rows"] == []

    # 公告：預設只看發布中，全體公告不受單位篩選影響；置頂優先
    n1, n2 = adm["notices"]
    api.ok("POST", f"{NOTICES}/{n1['id']}/archive", {})
    active = _get(api, ROWS, tab="notices", unit=other)
    assert [r["id"] for r in active["rows"]] == [n2["id"]]
    assert active["status_scope"] == "發布中"
    every = _get(api, ROWS, tab="notices", status="all")
    assert every["summary"] == (
        "目前篩選 1 則發布中公告、1 則封存公告。封存公告不列入最近截止與置頂。"
    )
    # 設備：目前可用依 now 判斷；借用依設備所屬組織篩選
    eq = _get(api, ROWS, tab="equipment", status="available_now", now=_t("2026-11-03", "14:00"))
    assert (eq["rows"], eq["status_scope"]) == ([], "目前可用")
    eq = _get(api, ROWS, tab="equipment", status="available_now", now=_t("2026-11-03", "15:00"))
    assert len(eq["rows"]) == 1
    assert len(_get(api, ROWS, tab="reservations", unit=unit)["rows"]) == 1
    assert _get(api, ROWS, tab="reservations", unit=other)["rows"] == []
    returned = _get(api, ROWS, tab="reservations", status="returned")
    assert returned["status_scope"] == "已歸還"


@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({}, "office_fields_invalid"),
        ({"tab": "orders"}, "office_fields_invalid"),
        ({"tab": "units", "status": "scheduled"}, "office_fields_invalid"),
        ({"tab": "staff", "type": "leave"}, "office_fields_invalid"),
        ({"tab": "requests", "type": "loan"}, "office_fields_invalid"),
        ({"tab": "units", "unit": "not-a-uuid"}, "office_id_invalid"),
        ({"tab": "units", "q": "x" * 121}, "office_fields_invalid"),
        ({"tab": "shifts", "week": "2026-11-03"}, "office_week_invalid"),
        ({"tab": "units", "now": "yesterday"}, "office_time_invalid"),
    ],
)
def test_rows_invalid_params_422(api: ApiClient, params: dict[str, str], code: str) -> None:
    api.setup("general")
    assert _error(api.get(ROWS, params=params)) == (422, code)
    assert _error(api.get(EXPORT, params=params)) == (422, code)


def test_reads_do_not_change_version(api: ApiClient) -> None:
    _demo(api)
    before = api.snapshot()
    _get(api, OVERVIEW)
    _get(api, ROWS, tab="shifts")
    _get(api, DIFF)
    _csv(api, tab="requests")
    assert api.snapshot() == before


# --- 出勤差異 -----------------------------------------------------------------------


def test_attendance_diff_week(api: ApiClient) -> None:
    api.setup("general")
    unit = api.ok("POST", UNITS, {"name": "門市", "kind": "branch"})["result"]
    other_unit = api.ok("POST", UNITS, {"name": "倉庫", "kind": "branch"})["result"]
    a = api.ok("POST", STAFF, {"code": "A", "alias": "甲", "unit_id": unit})["result"]
    b = api.ok("POST", STAFF, {"code": "B", "alias": "乙", "unit_id": unit})["result"]
    c = api.ok("POST", STAFF, {"code": "C", "alias": "丙", "unit_id": other_unit})["result"]
    api.ok("POST", STAFF, {"code": "D", "alias": "丁", "unit_id": unit})  # 本週沒有紀錄

    def seg(path: str, staff: str, unit_id: str, start: str, end: str, brk: int = 0) -> str:
        body = {"staff_id": staff, "unit_id": unit_id, "start_at": start, "end_at": end}
        return api.ok("POST", path, {**body, "break_minutes": brk})["result"]

    # 甲：週一 09–17 休 60 → 420；週日 23:30 起跨夜到下週一 07:30 → 480，歸本週
    seg(SHIFTS, a, unit, _t("2026-11-02", "09:00"), _t("2026-11-02", "17:00"), 60)
    seg(SHIFTS, a, unit, _t("2026-11-08", "23:30"), _t("2026-11-09", "07:30"))
    # 上週日、下週一的班次不計
    seg(SHIFTS, a, unit, _t("2026-11-01", "09:00"), _t("2026-11-01", "10:00"))
    seg(SHIFTS, a, unit, _t("2026-11-09", "09:00"), _t("2026-11-09", "10:00"))
    # 取消的班次不計
    cancelled = seg(SHIFTS, a, unit, _t("2026-11-04", "09:00"), _t("2026-11-04", "12:00"))
    api.ok("POST", f"{SHIFTS}/{cancelled}/cancel", {})
    seg(ATTENDANCE, a, unit, _t("2026-11-02", "09:00"), _t("2026-11-02", "17:30"), 30)  # 480
    # 作廢的出勤不計
    voided = seg(ATTENDANCE, a, unit, _t("2026-11-03", "09:00"), _t("2026-11-03", "12:00"))
    api.ok("POST", f"{ATTENDANCE}/{voided}/void", {"reason": "重複輸入"})
    # 乙：只有出勤 → 差異為正；丙在其他組織
    seg(ATTENDANCE, b, unit, _t("2026-11-05", "13:00"), _t("2026-11-05", "15:00"))
    seg(SHIFTS, c, other_unit, _t("2026-11-05", "13:00"), _t("2026-11-05", "15:00"))

    rows = _get(api, DIFF, week=WEEK)
    assert rows == [
        {"staff_id": a, "alias": "甲", "scheduled": 900, "recorded": 480, "diff": -420},
        {"staff_id": b, "alias": "乙", "scheduled": 0, "recorded": 120, "diff": 120},
        {"staff_id": c, "alias": "丙", "scheduled": 120, "recorded": 0, "diff": -120},
    ]
    assert [r["staff_id"] for r in _get(api, DIFF, week=WEEK, unit=unit)] == [a, b]
    assert _get(api, DIFF, week="2026-11-09") == [
        {"staff_id": a, "alias": "甲", "scheduled": 60, "recorded": 0, "diff": -60},
    ]
    assert _error(api.get(DIFF, params={"week": "2026-11-04"})) == (422, "office_week_invalid")


def test_net_minutes_rounds_and_clamps() -> None:
    from src.modules.administration.views import net_minutes

    row = {"start_at": "2026-11-02T01:00:00.000Z", "end_at": "2026-11-02T01:10:31.000Z"}
    assert net_minutes({**row, "break_minutes": 3}) == 8
    assert net_minutes({**row, "break_minutes": 30}) == 0


# --- CSV ------------------------------------------------------------------------------


def test_csv_bom_crlf_and_quotes(api: ApiClient) -> None:
    _demo(api)
    r = api.get(EXPORT, params={"tab": "units", "now": _t("2026-11-03", "00:30")})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "text/csv; charset=utf-8"
    assert r.headers["content-disposition"] == (
        'attachment; filename="erpcrm-admin-units-2026-11-03.csv"'
    )
    body = r.content.decode("utf-8")
    assert body.startswith('﻿"模式","工作區",')
    assert body.endswith("\r\n")
    lines = body[1:].split("\r\n")
    assert len(lines) == 3 and lines[-1] == ""
    quoted = re.compile(r'"(?:[^"]|"")*"(?:,"(?:[^"]|"")*")*')
    for line in lines[:-1]:
        assert quoted.fullmatch(line), line
    assert csv_export.to_csv([['a"b', None, 3]]) == '﻿"a""b","","3"\r\n'


def test_csv_formula_injection_prefixed(api: ApiClient) -> None:
    api.setup("general")
    api.ok("POST", NOTICES, {"title": '=HYPERLINK("x")', "body": "+1"})
    body, rows = _csv(api, tab="notices")
    assert '"\'=HYPERLINK(""x"")"' in body
    header, row = rows
    assert row[header.index("公告標題")] == '\'=HYPERLINK("x")'
    assert row[header.index("內容")] == "'+1"
    cell = csv_export.guard
    assert cell(" \x01-2") == "' \x01-2"
    assert cell("@a") == "'@a"
    assert cell("\tplain") == "'\tplain"
    assert cell("\rplain") == "'\rplain"
    assert cell("a=b") == "a=b"
    assert cell("") == ""


def test_csv_scope_columns_12(api: ApiClient) -> None:
    adm = _demo(api)
    shift = adm["shifts"][0]["id"]
    api.ok(
        "PATCH",
        f"{SHIFTS}/{shift}",
        {"reason": "延後一小時", "start_at": _t("2026-11-02", "10:00")},
    )
    version = api.snapshot()["version"]
    unit = adm["units"][0]
    _, rows = _csv(api, tab="shifts", week=WEEK, unit=unit["id"], now=_t("2026-11-03", "08:15"))
    header, *data = rows
    assert header[:12] == SCOPE_HEADERS
    assert header[12:] == [
        "紀錄編號",
        "假員工",
        "組織",
        "開始時間（臺北）",
        "結束時間（臺北）",
        "休息分鐘",
        "原段淨分鐘",
        "有效分鐘",
        "狀態",
        "備註",
        *TAIL_HEADERS,
    ]
    assert len(data) == 5
    first = data[0]
    assert first[:12] == [
        "SIM 流程練習",
        "星軌示範商店",
        str(version),
        "週班表",
        unit["name"],
        "未設定",
        "全部狀態",
        "2026-11-02 至 2026-11-08（依開始日歸週）",
        "Asia/Taipei（UTC+08:00）",
        "2026-11-03 08:15",
        "目前篩選的有效班次 5 筆，共 2040 分鐘；另保留 0 筆取消紀錄。",
        "目前訪客工作區的模擬紀錄；僅匯出目前篩選結果",
    ]
    assert first[12:22] == [
        shift,
        adm["staff"][0]["alias"],
        unit["name"],
        "2026-11-02 10:00",
        "2026-11-02 17:00",
        "60",
        "360",
        "360",
        "已排班",
        "合成示範排班，供流程練習",
    ]
    at, rest = first[24].split(" 班次時段更正：", 1)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", at)
    assert rest == (
        "延後一小時；開始時間 2026-11-02 09:00 → 2026-11-02 10:00；"
        "結束時間 2026-11-02 17:00 → 2026-11-02 17:00；休息分鐘 60 → 60；"
        "備註 合成示範排班，供流程練習 → 合成示範排班，供流程練習"
    )
    assert first[23] == at  # 更新時間就是更正時間
    assert all(len(row) == len(header) for row in data)


def test_csv_tab_columns_and_fallbacks(api: ApiClient) -> None:
    adm = _demo(api)
    req = adm["requests"][0]["id"]
    api.ok("POST", f"{REQUESTS}/{req}/submit", {})
    api.ok("POST", f"{REQUESTS}/{req}/return", {"processing_note": "補附件"})
    _, rows = _csv(api, tab="requests")
    header, row = rows
    assert header[12:24] == [
        "紀錄編號",
        "申請類型",
        "組織",
        "假員工",
        "標題",
        "內容",
        "SIM 測試幣金額",
        "開始時間（臺北）",
        "結束時間（臺北）",
        "狀態",
        "最新退回原因",
        "申請狀態紀錄",
    ]
    assert row[6] == "全部類型／全部狀態"
    assert (row[13], row[18], row[19], row[20], row[21], row[22]) == (
        "請購",
        "32.00",
        "未設定",
        "未設定",
        "退回補件",
        "補附件",
    )
    lines = row[23].split("\n")
    assert [line.split(" ", 2)[2] for line in lines] == ["草稿", "待整理", "退回補件：補附件"]

    _, rows = _csv(api, tab="notices", status="all")
    header, *data = rows
    assert header[12:19] == [
        "紀錄編號",
        "公告標題",
        "內容",
        "公告對象",
        "置頂設定",
        "截止時間（臺北）",
        "公告狀態",
    ]
    assert [(r[15], r[16], r[17], r[18]) for r in data] == [
        (adm["units"][0]["name"], "置頂", "2026-11-06 16:00", "發布中"),
        ("全體", "一般", "未設定", "發布中"),
    ]
    for tab, cols in {
        "units": ["紀錄編號", "組織名稱", "類型", "所屬門市", "狀態"],
        "staff": ["紀錄編號", "假員工代號", "假員工暱稱", "組織", "職務稱呼", "狀態"],
        "equipment": ["紀錄編號", "設備代號", "設備名稱", "組織", "狀態"],
        "reservations": ["紀錄編號", "設備", "假員工", "開始時間（臺北）", "結束時間（臺北）",
                         "借用用途", "狀態"],
    }.items():  # fmt: skip
        _, rows = _csv(api, tab=tab)
        assert rows[0] == [*SCOPE_HEADERS, *cols, *TAIL_HEADERS], tab
    _, rows = _csv(api, tab="units")
    assert rows[1][12 + 2 : 12 + 5] == ["門市", "獨立組織", "使用中"]

    # 沒有符合的紀錄時只輸出表頭
    _, rows = _csv(api, tab="staff", q="不存在的暱稱")
    assert len(rows) == 1
