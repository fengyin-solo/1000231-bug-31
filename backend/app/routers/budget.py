"""预算科目接口：维护预算科目，覆盖提交审批、确认批复、标记超支等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.budget import BudgetService

router = APIRouter(prefix="/api/budget", tags=["预算科目"])

service = BudgetService()

LIST_FIELDS = ["科目编号", "科目名称", "费用类别", "预算金额", "已用金额", "剩余额度", "审批人", "科目状态"]
STATUSES = ["待审批", "已批复", "执行中", "已超支"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按科目编号检索"),
    status: str | None = Query(default=None, description="待审批、已批复、执行中、已超支"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按科目编号与状态过滤预算科目列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total, stats = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size, stats=stats)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出预算科目清单：返回当前过滤条件下的全量数据。"""
    items, total, stats = service.list_entries(page=1, size=10000)
    return {"module": "budget", "total": total, "stats": stats, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条预算科目明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"预算科目 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条预算科目，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="预算科目已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条预算科目执行提交审批、确认批复、标记超支；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    operator = str(payload.values.get("operator") or "").strip()
    entry, message = service.run_action(entry_id, action, operator or None)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
