<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import AppShell from '@/components/AppShell.vue'
import ChartPanel from '@/components/ChartPanel.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingState from '@/components/LoadingState.vue'
import TagPill from '@/components/TagPill.vue'
import { useAsyncState } from '@/composables/useAsyncState'
import { get, post } from '@/lib/api'
import { useSession } from '@/lib/session'

const route = useRoute()
const session = useSession()

const companies = ref<string[]>([])
const availablePeriods = ref<string[]>([])
const preferredPeriod = ref('')
const selectedCompany = ref('')
const selectedPeriod = ref('')
const syncingFromRoute = ref(false)
const surfaceReloading = ref(false)
const actionPending = ref('')
const actionError = ref('')

const riskState = useAsyncState<any>()
const alertsState = useAsyncState<any>()
const tasksState = useAsyncState<any>()
const watchboardState = useAsyncState<any>()
const companyScoreState = useAsyncState<any>()

const activeRole = computed(() => session.activeRole.value || 'investor')
const activeRoleLabel = computed(() => {
  const map: Record<string, string> = {
    investor: '投资者视角',
    management: '管理层视角',
    regulator: '监管风控视角',
  }
  return map[activeRole.value] || '投资者视角'
})

const companyOptions = computed(() => {
  const ordered = [selectedCompany.value, ...companies.value, ...(riskState.data.value?.risk_board || []).map((item: any) => item.company_name)]
  const seen = new Set<string>()
  return ordered
    .map((value) => String(value || '').trim())
    .filter((value) => {
      if (!value || seen.has(value)) return false
      seen.add(value)
      return true
    })
})

const periodOptions = computed(() => {
  const ordered = [selectedPeriod.value, ...availablePeriods.value, preferredPeriod.value]
  const seen = new Set<string>()
  return ordered
    .map((value) => String(value || '').trim())
    .filter((value) => {
      if (!value || seen.has(value)) return false
      seen.add(value)
      return true
    })
    .map((value) => ({ value, label: value }))
})

const riskBoard = computed<any[]>(() => riskState.data.value?.risk_board || [])
const alertBoard = computed<any[]>(() => alertsState.data.value?.alerts || [])
const taskBoard = computed<any[]>(() => tasksState.data.value?.tasks || [])
const watchItems = computed<any[]>(() => watchboardState.data.value?.items || [])
const riskChart = computed<any>(() => riskState.data.value?.charts?.[0] || null)
const researchGroups = computed<any[]>(() => (riskState.data.value?.industry_research?.groups || []).slice(0, 4))
const researchNumbers = computed<any[]>(() => riskState.data.value?.industry_research?.key_numbers || [])
const selectedRiskItem = computed<any | null>(
  () => riskBoard.value.find((item) => item.company_name === selectedCompany.value) || null,
)
const selectedWatchItem = computed<any | null>(
  () => watchItems.value.find((item) => item.company_name === selectedCompany.value) || null,
)
const companyScorecard = computed<any>(() => companyScoreState.data.value?.scorecard || null)
const companyActionCards = computed<any[]>(() => companyScoreState.data.value?.action_cards?.slice(0, 3) || [])
const companyRiskLabels = computed<string[]>(() => {
  const scoreLabels = companyScorecard.value?.risk_labels || []
  if (scoreLabels.length) {
    return scoreLabels.map((item: any) => item.name)
  }
  return selectedRiskItem.value?.risk_labels || []
})

const visibleRiskRows = computed<any[]>(() => {
  const rows = riskBoard.value.slice(0, 8)
  if (selectedRiskItem.value && !rows.some((item) => item.company_name === selectedRiskItem.value.company_name)) {
    return [selectedRiskItem.value, ...rows.slice(0, 7)]
  }
  return rows
})

const visibleAlerts = computed<any[]>(() => {
  const selected = alertBoard.value.filter((item) => item.company_name === selectedCompany.value)
  return (selected.length ? selected : alertBoard.value).slice(0, 4)
})

const visibleTasks = computed<any[]>(() => {
  const selected = taskBoard.value.filter((item) => item.company_name === selectedCompany.value)
  return (selected.length ? selected : taskBoard.value).slice(0, 4)
})

const visibleWatchItems = computed<any[]>(() => {
  const rows = watchItems.value.slice(0, 5)
  if (selectedWatchItem.value && !rows.some((item) => item.company_name === selectedWatchItem.value.company_name)) {
    return [selectedWatchItem.value, ...rows.slice(0, 4)]
  }
  return rows
})

const summaryCards = computed(() => {
  const riskCompanies = riskBoard.value.filter((item) => Number(item.risk_count || 0) > 0)
  const taskSummary = tasksState.data.value?.summary || {}
  const alertSummary = alertsState.data.value?.summary || {}
  const watchSummary = watchboardState.data.value?.summary || {}
  return [
    {
      label: '高风险公司',
      value: riskCompanies.length,
      hint: selectedPeriod.value || '当前主周期',
    },
    {
      label: '新增预警',
      value: alertSummary.new ?? 0,
      hint: `${alertSummary.in_progress ?? 0} 项处理中`,
    },
    {
      label: '在办任务',
      value: Number(taskSummary.queued || 0) + Number(taskSummary.in_progress || 0),
      hint: `${taskSummary.done ?? 0} 项已完成`,
    },
    {
      label: '监测主体',
      value: watchSummary.tracked_companies ?? 0,
      hint: `${watchSummary.companies_with_new_alerts ?? 0} 家有新增预警`,
    },
  ]
})

const riskHeadline = computed(() => {
  const summary = alertsState.data.value?.summary || {}
  const roleCopy: Record<string, string> = {
    investor: '先把需要继续核验的风险主体和研报分歧点拉出来。',
    management: '先把新增预警、整改任务和重点监测主体收口到动作。',
    regulator: '先把新增风险暴露、处置状态和待排查主体压到同一张面板。',
  }
  const trailing = selectedPeriod.value
    ? ` 当前报期 ${selectedPeriod.value} 有 ${summary.new ?? 0} 条新增预警。`
    : ''
  return `${roleCopy[activeRole.value] || roleCopy.investor}${trailing}`
})

const companyFocusSummary = computed(() => {
  if (!selectedCompany.value) return '先选择公司，再看这轮风险收口。'
  const parts = [
    companyScorecard.value?.total_score ? `${companyScorecard.value.total_score} 分 / ${companyScorecard.value.grade}` : '',
    selectedRiskItem.value?.subindustry || '',
    selectedWatchItem.value?.note || '',
  ].filter(Boolean)
  return parts.join(' · ') || `${selectedCompany.value} 当前没有补充说明`
})

const companyQuickLinks = computed(() => {
  if (!selectedCompany.value) return []
  return [
    { label: '进入体检', to: { path: '/score', query: { company: selectedCompany.value, period: selectedPeriod.value } } },
    { label: '进入协同分析', to: { path: '/workspace', query: { company: selectedCompany.value, period: selectedPeriod.value, role: activeRole.value } } },
    { label: '进入图谱', to: { path: '/graph', query: { company: selectedCompany.value, period: selectedPeriod.value } } },
    { label: '进入核验', to: { path: '/verify', query: { company: selectedCompany.value, period: selectedPeriod.value } } },
  ]
})

function readQueryString(value: unknown) {
  const normalized = Array.isArray(value) ? value[0] : value
  return typeof normalized === 'string' ? normalized.trim() : ''
}

function displayStatusLabel(status?: string) {
  const map: Record<string, string> = {
    queued: '待开工',
    in_progress: '处理中',
    done: '已完成',
    blocked: '已阻断',
    new: '待派发',
    dispatched: '已派发',
    resolved: '已处理',
    dismissed: '已忽略',
  }
  return map[(status || '').toLowerCase()] || '已记录'
}

function statusTone(status?: string) {
  const normalized = (status || '').toLowerCase()
  if (normalized === 'new' || normalized === 'blocked') return 'risk'
  if (normalized === 'queued' || normalized === 'in_progress' || normalized === 'dispatched') return 'warning'
  if (normalized === 'done' || normalized === 'resolved') return 'success'
  return 'neutral'
}

function displayPriority(priority?: string) {
  const map: Record<string, string> = {
    P0: '最高优先',
    P1: '优先处理',
    P2: '持续跟进',
    high: '高优先',
    medium: '中优先',
    low: '低优先',
  }
  return map[priority || ''] || priority || '待定级'
}

function resolveDefaultCompany() {
  const knownCompanies = new Set(companyOptions.value)
  const routeCompany = readQueryString(route.query.company)
  const candidates = [
    selectedCompany.value,
    routeCompany,
    selectedRiskItem.value?.company_name,
    riskBoard.value[0]?.company_name,
    alertBoard.value[0]?.company_name,
    companyOptions.value[0],
  ]
  return (
    candidates.find(
      (value) =>
        typeof value === 'string' &&
        value.trim() &&
        (!knownCompanies.size || knownCompanies.has(value.trim())),
    ) || ''
  )
}

async function loadCompanies() {
  const payload = await get<any>('/workspace/companies')
  companies.value = payload.companies || []
  availablePeriods.value = payload.available_periods || []
  preferredPeriod.value = payload.preferred_period || ''
}

async function loadRiskScan() {
  const params = new URLSearchParams()
  if (selectedPeriod.value) {
    params.set('report_period', selectedPeriod.value)
  }
  const suffix = params.toString() ? `?${params.toString()}` : ''
  await riskState.execute(() => get(`/industry/risk-scan${suffix}`))
}

async function loadAlerts() {
  const params = new URLSearchParams()
  if (selectedPeriod.value) {
    params.set('report_period', selectedPeriod.value)
  }
  const suffix = params.toString() ? `?${params.toString()}` : ''
  await alertsState.execute(() => get(`/alerts/board${suffix}`))
}

async function loadTasks() {
  const params = new URLSearchParams({ user_role: activeRole.value })
  if (selectedPeriod.value) {
    params.set('report_period', selectedPeriod.value)
  }
  await tasksState.execute(() => get(`/tasks/board?${params.toString()}`))
}

async function loadWatchboard() {
  const params = new URLSearchParams({ user_role: activeRole.value })
  if (selectedPeriod.value) {
    params.set('report_period', selectedPeriod.value)
  }
  await watchboardState.execute(() => get(`/watchboard?${params.toString()}`))
}

async function loadCompanyScore() {
  if (!selectedCompany.value) {
    companyScoreState.data.value = null
    companyScoreState.error.value = null
    companyScoreState.loading.value = false
    return
  }
  await companyScoreState.execute(() =>
    post('/company/score', {
      company_name: selectedCompany.value,
      report_period: selectedPeriod.value || null,
    }),
  )
}

async function loadSurface() {
  surfaceReloading.value = true
  try {
    await Promise.allSettled([loadRiskScan(), loadAlerts(), loadTasks(), loadWatchboard()])
    const nextCompany = resolveDefaultCompany()
    if (nextCompany && nextCompany !== selectedCompany.value) {
      selectedCompany.value = nextCompany
    }
    await loadCompanyScore().catch(() => {})
  } finally {
    surfaceReloading.value = false
  }
}

function applyRouteSelection() {
  const queryCompany = readQueryString(route.query.company)
  const queryPeriod = readQueryString(route.query.period)
  syncingFromRoute.value = true
  if (queryPeriod) {
    selectedPeriod.value = queryPeriod
  }
  if (queryCompany && companyOptions.value.includes(queryCompany)) {
    selectedCompany.value = queryCompany
  }
  syncingFromRoute.value = false
}

function isActionPending(key: string) {
  return actionPending.value === key
}

async function runAction(key: string, action: () => Promise<void>) {
  actionError.value = ''
  actionPending.value = key
  try {
    await action()
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : '风险动作执行失败'
  } finally {
    actionPending.value = ''
  }
}

async function refreshOperationalPanels() {
  await Promise.allSettled([loadAlerts(), loadTasks(), loadWatchboard()])
}

async function refreshSurface() {
  await runAction('refresh', async () => {
    await loadSurface()
  })
}

async function scanWatchboard() {
  await runAction('watchboard-scan', async () => {
    await post('/watchboard/scan', {
      user_role: activeRole.value,
      report_period: selectedPeriod.value || null,
    })
    await loadWatchboard()
  })
}

async function dispatchWatchboard() {
  await runAction('watchboard-dispatch', async () => {
    await post('/watchboard/dispatch', {
      user_role: activeRole.value,
      report_period: selectedPeriod.value || null,
      limit: 6,
    })
    await refreshOperationalPanels()
  })
}

async function toggleWatchboard() {
  if (!selectedCompany.value) return
  await runAction('watchboard-toggle', async () => {
    if (selectedWatchItem.value) {
      await post('/watchboard/remove', {
        company_name: selectedCompany.value,
        user_role: activeRole.value,
        report_period: selectedPeriod.value || null,
      })
    } else {
      await post('/watchboard/add', {
        company_name: selectedCompany.value,
        user_role: activeRole.value,
        report_period: selectedPeriod.value || null,
        note: `${activeRoleLabel.value}纳入风险跟踪`,
      })
    }
    await loadWatchboard()
  })
}

async function dispatchAlert(alertId: string) {
  await runAction(`alert-dispatch:${alertId}`, async () => {
    await post('/alerts/dispatch', {
      alert_id: alertId,
      user_role: activeRole.value,
      report_period: selectedPeriod.value || null,
    })
    await refreshOperationalPanels()
  })
}

async function updateAlert(alertId: string, status: 'resolved' | 'dismissed') {
  await runAction(`alert:${status}:${alertId}`, async () => {
    await post('/alerts/update', {
      alert_id: alertId,
      status,
      report_period: selectedPeriod.value || null,
    })
    await refreshOperationalPanels()
  })
}

async function updateTask(taskId: string, status: 'in_progress' | 'done' | 'blocked') {
  await runAction(`task:${status}:${taskId}`, async () => {
    await post('/tasks/update', {
      task_id: taskId,
      status,
      user_role: activeRole.value,
      report_period: selectedPeriod.value || null,
    })
    await Promise.allSettled([loadTasks(), loadWatchboard()])
  })
}

onMounted(async () => {
  await loadCompanies()
  selectedPeriod.value = preferredPeriod.value || availablePeriods.value[0] || ''
  applyRouteSelection()
  if (!selectedPeriod.value) {
    selectedPeriod.value = preferredPeriod.value || availablePeriods.value[0] || ''
  }
  await loadSurface()
})

watch(selectedPeriod, async (value, oldValue) => {
  if (syncingFromRoute.value || !value || value === oldValue) return
  await loadSurface()
})

watch(selectedCompany, async (value, oldValue) => {
  if (syncingFromRoute.value || surfaceReloading.value || !value || value === oldValue) return
  await loadCompanyScore().catch(() => {})
})

watch(
  () => [route.query.company, route.query.period],
  async ([companyQuery, periodQuery]) => {
    const company = readQueryString(companyQuery)
    const period = readQueryString(periodQuery)
    if (period && period !== selectedPeriod.value) {
      syncingFromRoute.value = true
      selectedPeriod.value = period
      if (company && companyOptions.value.includes(company)) {
        selectedCompany.value = company
      }
      syncingFromRoute.value = false
      await loadSurface()
      return
    }
    if (company && company !== selectedCompany.value && companyOptions.value.includes(company)) {
      syncingFromRoute.value = true
      selectedCompany.value = company
      syncingFromRoute.value = false
      await loadCompanyScore().catch(() => {})
    }
  },
)

watch(
  () => session.activeRole.value,
  async (value, oldValue) => {
    if (!value || value === oldValue) return
    await Promise.allSettled([loadTasks(), loadWatchboard()])
  },
)
</script>

<template>
  <AppShell title="">
    <div class="risk-console">
      <LoadingState v-if="riskState.loading.value && !riskState.data.value" class="risk-panel risk-loading" />
      <ErrorState
        v-else-if="riskState.error.value && !riskState.data.value"
        :message="riskState.error.value"
        class="risk-panel risk-loading"
      />

      <template v-else>
        <section class="risk-header">
          <div class="risk-title">
            <div class="risk-title-row">
              <h1>行业风险预警</h1>
              <span class="risk-role-pill">{{ activeRoleLabel }}</span>
            </div>
            <p>{{ riskHeadline }}</p>
          </div>

          <div class="risk-controls">
            <label class="risk-field">
              <span>公司</span>
              <select v-model="selectedCompany" class="glass-select">
                <option v-for="company in companyOptions" :key="company" :value="company">{{ company }}</option>
              </select>
            </label>
            <label class="risk-field">
              <span>报告期</span>
              <select v-model="selectedPeriod" class="glass-select">
                <option v-for="period in periodOptions" :key="period.value" :value="period.value">
                  {{ period.label }}
                </option>
              </select>
            </label>
            <button class="button-secondary risk-action" :disabled="isActionPending('watchboard-scan')" @click="scanWatchboard">
              刷监测板
            </button>
            <button class="button-primary risk-action" :disabled="isActionPending('refresh')" @click="refreshSurface">
              刷新风险面
            </button>
          </div>
        </section>

        <section v-if="actionError" class="risk-inline-error">
          <strong>动作执行失败</strong>
          <p>{{ actionError }}</p>
        </section>

        <section class="risk-summary-strip">
          <article v-for="item in summaryCards" :key="item.label" class="risk-summary-card">
            <span>{{ item.label }}</span>
            <strong>{{ item.value }}</strong>
            <small>{{ item.hint }}</small>
          </article>
        </section>

        <section class="risk-main-grid">
          <article class="risk-panel risk-board-panel">
            <div class="section-head">
              <strong>当前高风险序列</strong>
              <small>{{ selectedPeriod || preferredPeriod || '当前主周期' }}</small>
            </div>

            <div class="risk-board-layout">
              <div v-if="visibleRiskRows.length" class="risk-board-list">
                <button
                  v-for="item in visibleRiskRows"
                  :key="`${item.company_name}-${item.subindustry}`"
                  type="button"
                  class="risk-company-row glass-panel-hover"
                  :class="{ 'is-active': item.company_name === selectedCompany }"
                  @click="selectedCompany = item.company_name"
                >
                  <div class="risk-company-top">
                    <div>
                      <strong>{{ item.company_name }}</strong>
                      <small>{{ item.subindustry || '未标注赛道' }}</small>
                    </div>
                    <span class="risk-count-pill">{{ item.risk_count }} 项</span>
                  </div>
                  <div class="risk-company-bottom">
                    <div class="risk-tags">
                      <TagPill
                        v-for="label in (item.risk_labels || []).slice(0, 3)"
                        :key="`${item.company_name}-${label}`"
                        :label="label"
                        tone="risk"
                      />
                    </div>
                    <RouterLink
                      class="risk-row-link"
                      :to="{ path: '/score', query: { company: item.company_name, period: selectedPeriod } }"
                      @click.stop
                    >
                      进入体检
                    </RouterLink>
                  </div>
                </button>
              </div>
              <div v-else class="risk-empty-state">当前报期没有拉到风险公司序列。</div>

              <div class="risk-chart-wrap">
                <ChartPanel
                  v-if="riskChart"
                  :title="riskChart.title || '行业风险标签命中数'"
                  :options="riskChart.options"
                  class="risk-chart-panel"
                />
                <div v-else class="risk-empty-state">风险图表尚未生成。</div>
              </div>
            </div>
          </article>

          <aside class="risk-panel risk-focus-panel">
            <div class="section-head">
              <strong>{{ selectedCompany || '当前焦点公司' }}</strong>
              <button
                class="button-secondary risk-mini-action"
                :disabled="!selectedCompany || isActionPending('watchboard-toggle')"
                @click="toggleWatchboard"
              >
                {{ selectedWatchItem ? '移出监测' : '加入监测' }}
              </button>
            </div>

            <div v-if="selectedCompany" class="risk-focus-stack">
              <div class="risk-focus-score">
                <div>
                  <span>经营体质</span>
                  <strong>{{ companyScorecard?.total_score ?? '--' }}</strong>
                </div>
                <div>
                  <span>评级</span>
                  <strong>{{ companyScorecard?.grade || selectedWatchItem?.grade || '--' }}</strong>
                </div>
                <div>
                  <span>监测状态</span>
                  <strong>{{ selectedWatchItem ? '已跟踪' : '未跟踪' }}</strong>
                </div>
              </div>

              <p class="risk-focus-copy">{{ companyFocusSummary }}</p>

              <div class="risk-focus-tags">
                <TagPill
                  v-for="label in companyRiskLabels.slice(0, 4)"
                  :key="`${selectedCompany}-${label}`"
                  :label="label"
                  tone="risk"
                />
                <TagPill
                  v-if="selectedWatchItem?.research_status === 'ready'"
                  label="研报可核验"
                  tone="success"
                />
              </div>

              <div class="risk-quick-links">
                <RouterLink
                  v-for="item in companyQuickLinks"
                  :key="item.label"
                  class="risk-quick-link"
                  :to="item.to"
                >
                  {{ item.label }}
                </RouterLink>
              </div>

              <div v-if="companyActionCards.length" class="risk-action-list">
                <div v-for="item in companyActionCards" :key="item.title" class="risk-action-card">
                  <strong>{{ item.title }}</strong>
                  <p>{{ item.reason }}</p>
                  <small>{{ item.action }}</small>
                </div>
              </div>
              <div v-else class="risk-empty-state">当前没有新增动作建议。</div>
            </div>
            <div v-else class="risk-empty-state">先从左侧风险序列里选一家公司。</div>
          </aside>
        </section>

        <section class="risk-ops-grid">
          <article class="risk-panel risk-ops-panel">
            <div class="section-head">
              <strong>{{ selectedCompany ? `${selectedCompany} 预警处置` : '预警处置' }}</strong>
              <small>{{ alertsState.data.value?.summary?.new ?? 0 }} 条待派发</small>
            </div>

            <div v-if="visibleAlerts.length" class="risk-ops-list">
              <div
                v-for="item in visibleAlerts"
                :key="item.alert_id"
                class="risk-ops-item glass-panel-hover"
              >
                <div class="risk-ops-top">
                  <div>
                    <strong>{{ item.company_name }}</strong>
                    <p>{{ item.summary }}</p>
                  </div>
                  <span class="risk-status-pill" :class="`is-${statusTone(item.status)}`">
                    {{ displayStatusLabel(item.status) }}
                  </span>
                </div>
                <div class="risk-ops-meta">
                  <span>{{ item.report_period }}</span>
                  <span>{{ item.risk_delta >= 0 ? `+${item.risk_delta}` : item.risk_delta }} 风险变化</span>
                  <span>{{ item.risk_count }} 个风险标签</span>
                </div>
                <div class="risk-tags">
                  <TagPill
                    v-for="label in (item.new_labels || []).slice(0, 3)"
                    :key="`${item.alert_id}-${label}`"
                    :label="label"
                    tone="risk"
                  />
                </div>
                <div class="risk-ops-actions">
                  <button
                    v-if="item.status === 'new'"
                    class="button-secondary risk-mini-action"
                    :disabled="isActionPending(`alert-dispatch:${item.alert_id}`)"
                    @click="dispatchAlert(item.alert_id)"
                  >
                    派任务
                  </button>
                  <button
                    v-if="item.status !== 'resolved'"
                    class="button-secondary risk-mini-action"
                    :disabled="isActionPending(`alert:resolved:${item.alert_id}`)"
                    @click="updateAlert(item.alert_id, 'resolved')"
                  >
                    标已处理
                  </button>
                  <button
                    v-if="item.status === 'new' || item.status === 'dispatched'"
                    class="button-secondary risk-mini-action"
                    :disabled="isActionPending(`alert:dismissed:${item.alert_id}`)"
                    @click="updateAlert(item.alert_id, 'dismissed')"
                  >
                    忽略
                  </button>
                </div>
              </div>
            </div>
            <div v-else class="risk-empty-state">当前没有需要立即处理的预警。</div>
          </article>

          <article class="risk-panel risk-ops-panel">
            <div class="section-head">
              <strong>{{ selectedCompany ? `${selectedCompany} 任务推进` : '任务推进' }}</strong>
              <small>{{ activeRoleLabel }}</small>
            </div>

            <div v-if="visibleTasks.length" class="risk-ops-list">
              <div
                v-for="item in visibleTasks"
                :key="item.task_id"
                class="risk-ops-item glass-panel-hover"
              >
                <div class="risk-ops-top">
                  <div>
                    <strong>{{ item.title }}</strong>
                    <p>{{ item.summary }}</p>
                  </div>
                  <span class="risk-status-pill" :class="`is-${statusTone(item.status)}`">
                    {{ displayStatusLabel(item.status) }}
                  </span>
                </div>
                <div class="risk-ops-meta">
                  <span>{{ item.company_name }}</span>
                  <span>{{ displayPriority(item.priority) }}</span>
                  <span>{{ item.report_period }}</span>
                </div>
                <div class="risk-tags">
                  <TagPill
                    v-for="label in (item.label_names || []).slice(0, 3)"
                    :key="`${item.task_id}-${label}`"
                    :label="label"
                    tone="risk"
                  />
                </div>
                <div class="risk-ops-actions">
                  <button
                    v-if="item.status === 'queued'"
                    class="button-secondary risk-mini-action"
                    :disabled="isActionPending(`task:in_progress:${item.task_id}`)"
                    @click="updateTask(item.task_id, 'in_progress')"
                  >
                    开始
                  </button>
                  <button
                    v-if="item.status === 'in_progress'"
                    class="button-secondary risk-mini-action"
                    :disabled="isActionPending(`task:done:${item.task_id}`)"
                    @click="updateTask(item.task_id, 'done')"
                  >
                    完成
                  </button>
                  <button
                    v-if="item.status !== 'done' && item.status !== 'blocked'"
                    class="button-secondary risk-mini-action"
                    :disabled="isActionPending(`task:blocked:${item.task_id}`)"
                    @click="updateTask(item.task_id, 'blocked')"
                  >
                    阻断
                  </button>
                </div>
              </div>
            </div>
            <div v-else class="risk-empty-state">当前视角下还没有派发出来的任务。</div>
          </article>

          <article class="risk-panel risk-ops-panel">
            <div class="section-head">
              <strong>重点监测板</strong>
              <button
                class="button-secondary risk-mini-action"
                :disabled="!watchItems.length || isActionPending('watchboard-dispatch')"
                @click="dispatchWatchboard"
              >
                批量派发
              </button>
            </div>

            <div v-if="visibleWatchItems.length" class="risk-watch-list">
              <button
                v-for="item in visibleWatchItems"
                :key="`${item.company_name}-${item.report_period}`"
                type="button"
                class="risk-watch-item glass-panel-hover"
                :class="{ 'is-active': item.company_name === selectedCompany }"
                @click="selectedCompany = item.company_name"
              >
                <div class="risk-watch-top">
                  <strong>{{ item.company_name }}</strong>
                  <span>{{ item.score }} / {{ item.grade }}</span>
                </div>
                <p>{{ item.note || '持续跟踪当前报期风险变化。' }}</p>
                <div class="risk-watch-meta">
                  <span>{{ item.new_alerts }} 条新增预警</span>
                  <span>{{ item.task_count }} 项任务</span>
                  <span>{{ item.document_upgrade_count }} 项文档升级</span>
                </div>
              </button>
            </div>
            <div v-else class="risk-empty-state">当前还没有加入监测板的主体。</div>
          </article>
        </section>

        <section class="risk-bottom-grid">
          <article class="risk-panel risk-research-panel">
            <div class="section-head">
              <strong>行业研判补充</strong>
              <div class="risk-research-metrics">
                <span v-for="item in researchNumbers" :key="item.label">
                  {{ item.label }} {{ item.value }}{{ item.unit || '' }}
                </span>
              </div>
            </div>

            <div v-if="researchGroups.length" class="risk-research-grid">
              <a
                v-for="group in researchGroups"
                :key="group.industry_name"
                class="risk-research-card glass-panel-hover"
                :href="group.latest_report?.source_url || group.latest_report?.attachment_url || '#'"
                :target="group.latest_report?.source_url || group.latest_report?.attachment_url ? '_blank' : undefined"
                rel="noreferrer"
              >
                <div class="risk-research-top">
                  <span>{{ group.industry_name }}</span>
                  <strong>{{ group.report_count }} 篇</strong>
                </div>
                <h3>{{ group.latest_report?.title || '最新行业研报' }}</h3>
                <p>{{ group.latest_report?.excerpt || '当前没有可展示摘要。' }}</p>
                <small>
                  {{
                    [
                      group.latest_report?.source_name,
                      group.latest_report?.publish_date,
                      group.latest_report?.rating_text,
                    ].filter(Boolean).join(' · ')
                  }}
                </small>
              </a>
            </div>
            <div v-else class="risk-empty-state">当前没有额外行业研报补充。</div>
          </article>
        </section>
      </template>
    </div>
  </AppShell>
</template>

<style scoped>
.risk-console {
  display: grid;
  gap: 14px;
  min-height: 100%;
  width: 100%;
  max-width: 1320px;
  margin: 0 auto;
  color: #edf2f7;
}

.risk-panel {
  border-radius: 24px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: linear-gradient(180deg, rgba(14, 16, 22, 0.98), rgba(9, 11, 17, 0.96));
}

.risk-loading {
  min-height: 420px;
}

.risk-header,
.risk-title,
.risk-controls,
.risk-summary-strip,
.risk-main-grid,
.risk-board-layout,
.risk-focus-stack,
.risk-focus-tags,
.risk-quick-links,
.risk-ops-grid,
.risk-ops-list,
.risk-watch-list,
.risk-bottom-grid,
.risk-research-grid {
  display: grid;
  gap: 12px;
}

.risk-header {
  grid-template-columns: minmax(0, 1fr) minmax(360px, auto);
  align-items: end;
}

.risk-title {
  gap: 8px;
}

.risk-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.risk-title h1,
.risk-company-top strong,
.risk-ops-top strong,
.risk-watch-top strong,
.risk-research-card h3,
.section-head strong {
  margin: 0;
  color: #f8fafc;
}

.risk-title h1 {
  font-size: clamp(28px, 3vw, 36px);
  letter-spacing: -0.05em;
  line-height: 0.98;
}

.risk-title p,
.risk-focus-copy,
.risk-action-card p,
.risk-ops-top p,
.risk-watch-item p,
.risk-research-card p {
  margin: 0;
  color: rgba(191, 207, 228, 0.82);
  line-height: 1.65;
}

.risk-role-pill,
.risk-count-pill,
.risk-status-pill {
  min-height: 30px;
  padding: 0 10px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.risk-role-pill {
  color: #8af4c8;
  background: rgba(16, 185, 129, 0.12);
  border-color: rgba(52, 211, 153, 0.24);
}

.risk-inline-error {
  padding: 14px 18px;
  border-radius: 18px;
  border: 1px solid rgba(251, 113, 133, 0.24);
  background: rgba(190, 24, 93, 0.12);
  display: grid;
  gap: 4px;
}

.risk-inline-error strong,
.risk-inline-error p {
  margin: 0;
}

.risk-controls {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  align-items: end;
}

.risk-field {
  display: grid;
  gap: 8px;
}

.risk-field span {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: rgba(130, 209, 168, 0.74);
}

.risk-action {
  width: 100%;
}

.risk-summary-strip {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.risk-summary-card {
  padding: 18px 20px;
  border-radius: 22px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.02);
  display: grid;
  gap: 6px;
}

.risk-summary-card span,
.risk-summary-card small,
.risk-company-top small,
.risk-watch-meta,
.risk-ops-meta,
.risk-research-card small,
.section-head small,
.risk-action-card small {
  color: rgba(148, 163, 184, 0.8);
}

.risk-summary-card strong {
  font-size: 28px;
  letter-spacing: -0.05em;
}

.risk-main-grid {
  grid-template-columns: minmax(0, 1.65fr) minmax(320px, 0.95fr);
}

.risk-board-panel,
.risk-focus-panel,
.risk-ops-panel,
.risk-research-panel {
  padding: 18px;
}

.section-head,
.risk-company-top,
.risk-company-bottom,
.risk-ops-top,
.risk-ops-actions,
.risk-watch-top,
.risk-research-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.risk-board-layout {
  grid-template-columns: minmax(0, 1.2fr) minmax(280px, 0.9fr);
  align-items: start;
}

.risk-board-list {
  display: grid;
  gap: 10px;
}

.risk-company-row,
.risk-watch-item {
  width: 100%;
  padding: 16px;
  border-radius: 18px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.02);
  color: inherit;
  text-align: left;
  cursor: pointer;
  display: grid;
  gap: 12px;
}

.risk-company-row.is-active,
.risk-watch-item.is-active {
  border-color: rgba(52, 211, 153, 0.28);
  background: rgba(16, 185, 129, 0.08);
}

.risk-count-pill {
  color: #fbbf24;
  background: rgba(245, 158, 11, 0.1);
  border-color: rgba(245, 158, 11, 0.18);
}

.risk-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.risk-row-link,
.risk-quick-link {
  text-decoration: none;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  padding: 8px 12px;
  color: #dff8ee;
  background: rgba(255, 255, 255, 0.02);
}

.risk-chart-wrap {
  min-height: 100%;
  border-radius: 20px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.02);
  padding: 10px;
}

.risk-chart-panel {
  min-height: 340px;
}

.risk-focus-score {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.risk-focus-score > div {
  padding: 14px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  display: grid;
  gap: 6px;
}

.risk-focus-score span {
  color: rgba(148, 163, 184, 0.8);
  font-size: 12px;
}

.risk-focus-score strong {
  font-size: 24px;
  letter-spacing: -0.04em;
}

.risk-action-list {
  display: grid;
  gap: 10px;
}

.risk-action-card {
  padding: 14px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.025);
  border: 1px solid rgba(255, 255, 255, 0.06);
  display: grid;
  gap: 6px;
}

.risk-action-card strong {
  color: #f8fafc;
}

.risk-ops-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.risk-ops-list {
  margin-top: 14px;
}

.risk-ops-item {
  padding: 14px;
  border-radius: 18px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.02);
  display: grid;
  gap: 10px;
}

.risk-ops-top {
  align-items: start;
}

.risk-ops-meta,
.risk-watch-meta,
.risk-research-metrics {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 12px;
}

.risk-status-pill.is-risk {
  color: #fda4af;
  background: rgba(190, 24, 93, 0.12);
  border-color: rgba(251, 113, 133, 0.22);
}

.risk-status-pill.is-warning {
  color: #fcd34d;
  background: rgba(245, 158, 11, 0.12);
  border-color: rgba(245, 158, 11, 0.22);
}

.risk-status-pill.is-success {
  color: #8af4c8;
  background: rgba(16, 185, 129, 0.12);
  border-color: rgba(52, 211, 153, 0.24);
}

.risk-status-pill.is-neutral {
  color: #cbd5f5;
  background: rgba(148, 163, 184, 0.08);
}

.risk-mini-action {
  min-height: 34px;
  padding: 0 12px;
}

.risk-watch-list {
  margin-top: 14px;
}

.risk-bottom-grid {
  grid-template-columns: minmax(0, 1fr);
}

.risk-research-grid {
  margin-top: 14px;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.risk-research-card {
  padding: 16px;
  border-radius: 18px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.02);
  text-decoration: none;
  display: grid;
  gap: 10px;
}

.risk-research-top span {
  color: #8af4c8;
  font-size: 12px;
}

.risk-research-card h3 {
  font-size: 17px;
  line-height: 1.25;
}

.risk-empty-state {
  min-height: 180px;
  display: grid;
  place-items: center;
  text-align: center;
  color: rgba(148, 163, 184, 0.82);
}

@media (max-width: 1200px) {
  .risk-main-grid,
  .risk-ops-grid,
  .risk-board-layout,
  .risk-header,
  .risk-research-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 780px) {
  .risk-summary-strip,
  .risk-focus-score,
  .risk-controls {
    grid-template-columns: minmax(0, 1fr);
  }

  .risk-console {
    padding-bottom: 24px;
  }

  .risk-panel {
    border-radius: 20px;
  }
}
</style>
