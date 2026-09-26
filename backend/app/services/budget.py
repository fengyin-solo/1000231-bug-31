"""预算科目业务规则：本层只负责取数、分页与出入参组织。

状态流转、超支判定、金额推导等真正的业务口径全部在 app.budget_rules，
列表、概览与操作共用同一份判定，结果不再互相矛盾。
"""
from __future__ import annotations

from typing import Any

from app import budget_rules as rules
from app.store import store

MODULE = "budget"
REQUIRED_FIELDS = ["科目编号", "科目名称", "费用类别"]


class BudgetService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("科目编号", ""))]
        if status:
            rows = [row for row in rows if rules.canonical_status(row) == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        page_rows = rows[start:start + size]
        # 统计基于过滤后的全量科目（不受分页影响），与列表展示同一批数据。
        stats = rules.summarize(rows)
        return [rules.present_budget_row(row) for row in page_rows], total, stats

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return rules.present_budget_row(entry) if entry is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = rules.new_budget_row(
            max((int(row.get("id", 0)) for row in rows), default=0) + 1, values
        )
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        rows.append(entry)
        return rules.present_budget_row(entry), []

    def run_action(
        self, entry_id: int, action: str, operator: str | None = None
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"预算科目 {entry_id} 不存在或已归档"
        updated, message, _changed = rules.run_budget_action(entry, action, operator)
        if updated is None:
            return None, message
        return rules.present_budget_row(updated), message
