"""预算科目业务规则：列表筛选、登记与状态流转。

具体的状态序列、金额口径、超支判定都在 budget_rules 里，本层只负责存取数据，
不在任何入口重复写判断。
"""
from __future__ import annotations

from typing import Any

from app.services import budget_rules as rules
from app.store import store

MODULE = "budget"


def _serialize(entry: dict[str, Any]) -> dict[str, Any]:
    """统一派生展示字段，并附上当前状态允许的动作，供列表渲染按钮。"""
    row = rules.apply_rules(dict(entry))
    row["actions"] = rules.available_actions(row)
    return row


class BudgetService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = [_serialize(row) for row in store.rows(MODULE)]
        if keyword:
            rows = [row for row in rows if keyword in str(row.get(rules.FIELD_CODE, ""))]
        if status:
            rows = [row for row in rows if rules.current_status(row) == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return _serialize(entry) if entry is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in rules.REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in rules.REQUIRED_FIELDS})
        for field in rules.AMOUNT_FIELDS:
            if field in values:
                entry[field] = rules.to_amount(values.get(field))
        if values.get(rules.FIELD_APPROVER) is not None:
            entry[rules.FIELD_APPROVER] = values.get(rules.FIELD_APPROVER)
        entry["status"] = rules.STATUS_PENDING
        rows.append(entry)
        return _serialize(entry), []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"预算科目 {entry_id} 不存在或已归档"
        error = rules.transition(entry, action)
        if error is not None:
            return None, error
        entry["status"] = rules.ACTION_RULES[action]
        rules.apply_rules(entry)
        return entry, f"预算科目已{action}"

    def summary(self) -> dict[str, float | int]:
        """预算页统计卡：总额、已用、超支科目数，口径与列表、概览完全一致。"""
        rows = [rules.apply_rules(dict(row)) for row in store.rows(MODULE)]
        return {
            "budget_total": sum(rules.to_amount(row.get(rules.FIELD_BUDGET)) for row in rows),
            "used_total": sum(rules.to_amount(row.get(rules.FIELD_USED)) for row in rows),
            "overspent_count": sum(1 for row in rows if rules.is_overspent(row)),
        }
