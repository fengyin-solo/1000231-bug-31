"""预算科目规则的唯一出口。

状态流转、金额口径、超支判定与展示字段派生全部收拢在这里：
列表、运营概览、动作接口都只准调用本模块的函数，不允许再各写一遍判断，
避免同一个科目在不同入口显示成不同状态、不同金额。

判定口径：
- ``status`` 是科目的唯一权威状态；列表里的「科目状态」列只是它的展示镜像。
- 超支只看权威状态是否为「已超支」，概览异常量与列表超支科目因此天然一致。
- 剩余额度 = 预算金额 - 已用金额，纯派生值，可能为负（超支时即为超支额）。
"""
from __future__ import annotations

from typing import Any

# 状态序列：登记后从「待审批」开始，按顺序流转，「已超支」为终态。
STATUS_PENDING = "待审批"
STATUS_APPROVED = "已批复"
STATUS_RUNNING = "执行中"
STATUS_OVERSPENT = "已超支"
STATUS_ORDER = [STATUS_PENDING, STATUS_APPROVED, STATUS_RUNNING, STATUS_OVERSPENT]

# 动作 -> 目标状态。
ACTION_SUBMIT = "提交审批"
ACTION_APPROVE = "确认批复"
ACTION_MARK_OVERSPENT = "标记超支"
ACTION_RULES = {
    ACTION_SUBMIT: STATUS_APPROVED,
    ACTION_APPROVE: STATUS_RUNNING,
    ACTION_MARK_OVERSPENT: STATUS_OVERSPENT,
}

# 动作 -> 允许发起该动作的前置状态。
# 每个动作只在其前置状态下可执行：终态科目任何动作都被拒绝，
# 因此连续点击不会重复切换，已超支也不会被后续动作冲掉。
ACTION_GUARDS = {
    ACTION_SUBMIT: {STATUS_PENDING},
    ACTION_APPROVE: {STATUS_APPROVED},
    ACTION_MARK_OVERSPENT: {STATUS_RUNNING},
}

# 列表展示用的业务字段名（内部权威状态字段是 status）。
FIELD_CODE = "科目编号"
FIELD_NAME = "科目名称"
FIELD_CATEGORY = "费用类别"
FIELD_BUDGET = "预算金额"
FIELD_USED = "已用金额"
FIELD_REMAINING = "剩余额度"
FIELD_APPROVER = "审批人"
FIELD_STATUS = "科目状态"

REQUIRED_FIELDS = [FIELD_CODE, FIELD_NAME, FIELD_CATEGORY]
AMOUNT_FIELDS = (FIELD_BUDGET, FIELD_USED)


def to_amount(value: Any) -> float:
    """把金额字段安全解析成数字；空值或无法解析的内容按 0 处理。"""
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def current_status(entry: dict[str, Any]) -> str:
    """读取科目的权威状态；异常数据统一回落到初始状态。"""
    status = entry.get("status")
    return status if status in STATUS_ORDER else STATUS_PENDING


def remaining_amount(entry: dict[str, Any]) -> float:
    """剩余额度 = 预算金额 - 已用金额；金额是唯一事实来源，这里只做派生。"""
    return to_amount(entry.get(FIELD_BUDGET)) - to_amount(entry.get(FIELD_USED))


def is_overspent(entry: dict[str, Any]) -> bool:
    """超支判定的共用口径：只认权威状态「已超支」。"""
    return current_status(entry) == STATUS_OVERSPENT


def is_pending(entry: dict[str, Any]) -> bool:
    """待处理口径：已超支为终态，其余状态都仍在审批/执行链路上。"""
    return current_status(entry) != STATUS_OVERSPENT


def available_actions(entry: dict[str, Any]) -> list[str]:
    """按当前状态给出可执行动作，供列表收口按钮，避免点到必然被拒的动作。"""
    status = current_status(entry)
    return [action for action, allowed in ACTION_GUARDS.items() if status in allowed]


def transition(entry: dict[str, Any], action: str) -> str | None:
    """校验动作能否执行；不合法时返回错误说明，合法时返回 None（不改数据）。"""
    if action not in ACTION_RULES:
        return f"动作「{action}」不属于预算科目可执行范围"
    status = current_status(entry)
    if status not in ACTION_GUARDS[action]:
        return f"科目当前为「{status}」，不能执行「{action}」"
    return None


def apply_rules(entry: dict[str, Any]) -> dict[str, Any]:
    """以权威状态为准，统一派生展示字段与概览标记。

    金额（预算金额、已用金额）与审批人保持原值不动；只重算剩余额度、
    镜像状态列以及 pending/abnormal 两个标记，保证列表与概览永不互相矛盾。
    """
    status = current_status(entry)
    entry["status"] = status
    entry[FIELD_STATUS] = status
    entry[FIELD_REMAINING] = remaining_amount(entry)
    entry["pending"] = is_pending(entry)
    entry["abnormal"] = is_overspent(entry)
    return entry
