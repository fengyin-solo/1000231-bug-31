"""预算科目共用判定：状态机、超支口径、金额推导与统计全部收在这一处。

列表展示、运营概览（store.overview）和动作流转（BudgetService）都必须走这里的
函数，避免同一科目在不同入口被算出不同状态。判定只依赖金额与流转标记，绝不修改
已有的「预算金额」「已用金额」和「审批记录」。
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from numbers import Real
from typing import Any

# ---- 状态序列与动作 ---------------------------------------------------------
DRAFT = "待审批"
APPROVED = "已批复"
RUNNING = "执行中"
OVERSPENT = "已超支"

STATUS_ORDER = [DRAFT, APPROVED, RUNNING, OVERSPENT]

SUBMIT = "提交审批"
APPROVE = "确认批复"
MARK_OVERSPENT = "标记超支"
ACTIONS = [SUBMIT, APPROVE, MARK_OVERSPENT]

# 金额字段：任何流转都不允许改这两个字段，已有金额以入库值为准。
BUDGET_FIELD = "预算金额"
SPENT_FIELD = "已用金额"
REMAINING_FIELD = "剩余额度"
STATUS_FIELD = "科目状态"
APPROVER_FIELD = "审批人"
RECORDS_FIELD = "审批记录"

# ---- 基础工具 ---------------------------------------------------------------


def to_amount(value: Any) -> float:
    """把任意输入转成金额数字；无法识别时按 0 处理，绝不抛异常。"""
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, Real):
        return round(float(value), 2)
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if text:
            try:
                return round(float(text), 2)
            except ValueError:
                return 0.0
    return 0.0


def budget_amount(entry: dict[str, Any]) -> float:
    return to_amount(entry.get(BUDGET_FIELD))


def spent_amount(entry: dict[str, Any]) -> float:
    return to_amount(entry.get(SPENT_FIELD))


def remaining_amount(entry: dict[str, Any]) -> float:
    """剩余额度的唯一口径：预算金额 − 已用金额，超支时为负。"""
    return round(budget_amount(entry) - spent_amount(entry), 2)


def is_over_budget(entry: dict[str, Any]) -> bool:
    """超支口径：已用金额严格大于预算金额，或存在已确认的超支标记。

    over_marked 是历史/人工标记（由旧 abnormal 标志迁移），一经确认不可撤销，
    保证已超支科目不会因为金额恰好相等而在概览里“恢复正常”。
    """
    return bool(entry.get("over_marked")) or spent_amount(entry) > budget_amount(entry)


def canonical_status(entry: dict[str, Any]) -> str:
    """科目的权威状态：超支优先，其次取合法的流转状态。"""
    if is_over_budget(entry):
        return OVERSPENT
    stored = str(entry.get("status") or "")
    return stored if stored in STATUS_ORDER else DRAFT


def is_pending(entry: dict[str, Any]) -> bool:
    """待处理：只有等待批复的科目算待处理；已超支计入异常，不再重复计数。"""
    return canonical_status(entry) == DRAFT


def is_abnormal(entry: dict[str, Any]) -> bool:
    """异常：与列表里的「已超支」完全同一口径。"""
    return canonical_status(entry) == OVERSPENT


def available_actions(entry: dict[str, Any]) -> list[str]:
    """当前状态下真正可执行的动作，列表按钮与 run_action 守卫共用这一份。"""
    status = canonical_status(entry)
    if status == DRAFT:
        result: list[str] = []
        if not entry.get("已提交"):
            result.append(SUBMIT)
        result.append(APPROVE)
        return result
    if status in (APPROVED, RUNNING):
        # 批复后的科目可人工确认超支（例如已发生待入账支出）；金额超支的科目
        # 同样在这里确认，确认后状态统一落到「已超支」。
        return [MARK_OVERSPENT]
    return []


# ---- 数据规整与展示 ---------------------------------------------------------


def normalize_budget_row(entry: dict[str, Any]) -> dict[str, Any]:
    """规整一条预算科目：统一金额类型、迁移历史超支标志、重算派生状态。

    只重算派生字段（剩余额度是展示层字段，不在这里落库）；预算金额、已用金额、
    审批人等历史数据保持原值。幂等，可重复调用。
    """
    entry[BUDGET_FIELD] = budget_amount(entry)
    entry[SPENT_FIELD] = spent_amount(entry)

    # 迁移旧数据里手填的 abnormal / 已超支 状态，避免概览与列表各认一套标志。
    if entry.get("abnormal") is True or str(entry.get("status") or "") == OVERSPENT:
        entry["over_marked"] = True

    entry.setdefault(RECORDS_FIELD, [])
    if not isinstance(entry[RECORDS_FIELD], list):
        entry[RECORDS_FIELD] = []

    status = canonical_status(entry)
    entry["status"] = status
    entry["pending"] = is_pending(entry)
    entry["abnormal"] = is_abnormal(entry)
    return entry


def present_budget_row(entry: dict[str, Any]) -> dict[str, Any]:
    """列表/导出/动作回包的统一视图：剩余额度、科目状态都现算，不读脏字段。"""
    view = dict(entry)
    view[REMAINING_FIELD] = remaining_amount(entry)
    view[STATUS_FIELD] = canonical_status(entry)
    view["actions"] = available_actions(entry)
    return view


def new_budget_row(entry_id: int, values: dict[str, Any]) -> dict[str, Any]:
    """新建科目的初始形态：金额取提交值（缺省 0），状态待审批，无历史包袱。"""
    entry: dict[str, Any] = {
        "id": entry_id,
        "status": DRAFT,
        "over_marked": False,
        "已提交": False,
        BUDGET_FIELD: to_amount(values.get(BUDGET_FIELD)),
        SPENT_FIELD: to_amount(values.get(SPENT_FIELD)),
        APPROVER_FIELD: str(values.get(APPROVER_FIELD) or "").strip(),
        RECORDS_FIELD: [],
    }
    entry["pending"] = is_pending(entry)
    entry["abnormal"] = is_abnormal(entry)
    return entry


# ---- 动作流转 ---------------------------------------------------------------


def _append_record(entry: dict[str, Any], action: str, operator: str, result: str) -> None:
    entry.setdefault(RECORDS_FIELD, []).append(
        {
            "动作": action,
            "操作人": operator or "系统",
            "时间": datetime.now().isoformat(timespec="seconds"),
            "结果状态": result,
        }
    )


def run_budget_action(
    entry: dict[str, Any], action: str, operator: str | None = None
) -> tuple[dict[str, Any] | None, str, bool]:
    """执行预算动作。

    返回 (更新后的条目, 说明, 是否生效)。守卫不满足时不改动任何数据；重复点击
    不会造成状态来回切换。金额字段全程只读。
    """
    operator = (operator or "").strip()
    status = canonical_status(entry)

    if action == SUBMIT:
        if status != DRAFT:
            return None, f"科目当前为「{status}」，无需重复提交审批", False
        if entry.get("已提交"):
            return None, "科目已提交，等待批复，请勿重复提交", False
        entry["已提交"] = True
        _append_record(entry, action, operator, status)
        return entry, "预算科目已提交，等待批复", True

    if action == APPROVE:
        if status == OVERSPENT:
            return None, "科目已超支，不能批复，请先处理超支", False
        if status != DRAFT:
            return None, f"科目当前为「{status}」，请勿重复确认批复", False
        entry["status"] = APPROVED
        entry["已提交"] = True
        # 保留已有审批人：本次带了操作人才覆盖，否则维持历史记录。
        if operator:
            entry[APPROVER_FIELD] = operator
        _append_record(entry, action, operator or str(entry.get(APPROVER_FIELD) or ""), APPROVED)
        entry["pending"] = is_pending(entry)
        entry["abnormal"] = is_abnormal(entry)
        return entry, "预算科目已确认批复", True

    if action == MARK_OVERSPENT:
        if status == OVERSPENT:
            # 金额已自动判超但首次显式确认：把标记落库并留痕；
            # 之后再点属于重复操作，状态不切换、不新增记录。
            if not entry.get("over_marked"):
                entry["over_marked"] = True
                entry["status"] = OVERSPENT
                _append_record(entry, action, operator, OVERSPENT)
                entry["pending"] = is_pending(entry)
                entry["abnormal"] = is_abnormal(entry)
                return entry, "预算科目已标记超支", True
            entry["status"] = OVERSPENT
            entry["pending"] = is_pending(entry)
            entry["abnormal"] = is_abnormal(entry)
            return entry, "预算科目已处于已超支状态，无需重复标记", True
        if status not in (APPROVED, RUNNING):
            return None, "仅已批复或执行中的科目可以标记超支", False
        entry["over_marked"] = True
        entry["status"] = OVERSPENT
        _append_record(entry, action, operator, OVERSPENT)
        entry["pending"] = is_pending(entry)
        entry["abnormal"] = is_abnormal(entry)
        return entry, "预算科目已标记超支", True

    return None, f"动作「{action}」不属于预算科目可执行范围", False


# ---- 统计 -------------------------------------------------------------------


def summarize(rows: list[dict[str, Any]]) -> dict[str, float]:
    """预算总额 / 已用金额 / 超支科目数，口径与列表、概览完全一致。"""
    return {
        "预算总额": round(sum(budget_amount(row) for row in rows), 2),
        "已用金额": round(sum(spent_amount(row) for row in rows), 2),
        "超支科目": sum(1 for row in rows if is_abnormal(row)),
    }


# store 在不感知具体业务的前提下，通过这张表取用各模块的判定。
MODULE_RULES: dict[str, dict[str, Callable[..., Any]]] = {
    "budget": {
        "normalize": normalize_budget_row,
        "is_pending": is_pending,
        "is_abnormal": is_abnormal,
    }
}
