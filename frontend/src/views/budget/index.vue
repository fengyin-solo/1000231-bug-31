<template>
  <section class="page" data-module="budget">
    <header class="page-head">
      <div>
        <h2>预算科目管理</h2>
        <p class="page-desc">维护预算科目，围绕科目编号、科目名称、费用类别、预算金额做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记预算科目</button>
        <button class="btn" type="button" @click="exportRows">导出预算科目清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ formatCell(column, row[column]) }}</td>
          <td class="row-actions">
            <template v-if="rowActions(row).length">
              <button
                v-for="action in rowActions(row)"
                :key="action"
                class="link"
                type="button"
                @click="runAction(action, row)"
              >
                {{ action }}
              </button>
            </template>
            <span v-else class="muted-text">—</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无预算科目数据，可先登记预算科目</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条预算科目记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type Row = Record<string, string | number | boolean | string[] | null>
type Stat = { label: string; value: number }

const ENDPOINT = '/api/budget'
const columns = ["科目编号", "科目名称", "费用类别", "预算金额", "已用金额", "剩余额度", "审批人", "科目状态"]
const AMOUNT_COLUMNS = new Set(["预算金额", "已用金额", "剩余额度"])
// 统计卡片顺序固定，数值全部来自后端同一口径，前端不再自行计算。
const EMPTY_STATS: Stat[] = [{"label": "预算总额", "value": 0}, {"label": "已用金额", "value": 0}, {"label": "超支科目", "value": 0}]

const session = useSessionStore()
const rows = ref<Row[]>([])
const total = ref(0)
const stats = ref<Stat[]>(EMPTY_STATS)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

function rowActions(row: Row): string[] {
  const actions = row.actions
  return Array.isArray(actions) ? (actions as string[]) : []
}

function formatCell(column: string, value: Row[keyof Row]): string | number | null {
  if (value === null || value === undefined || value === '') return '—'
  if (AMOUNT_COLUMNS.has(column) && typeof value === 'number') {
    return value.toFixed(2)
  }
  return value as string | number
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '预算科目登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action, operator: session.operator }),
    })
    if (!response.ok) {
      throw new Error('预算科目动作未生效，请稍后重试')
    }
    const payload = await response.json()
    // 守卫拦截时后端返回 ok:false；必须展示后端消息，不能静默刷新成“成功”。
    if (!payload.ok) {
      errorMessage.value = payload.message || '预算科目操作未生效'
      return
    }
    errorMessage.value = payload.message || ''
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '预算科目操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('预算科目列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    const remoteStats = payload.stats ?? {}
    stats.value = EMPTY_STATS.map((item) => ({
      label: item.label,
      value: Number(remoteStats[item.label] ?? 0),
    }))
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '预算科目列表读取失败'
  }
}

onMounted(reload)
</script>
