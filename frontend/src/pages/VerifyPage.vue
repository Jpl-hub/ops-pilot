<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import AppShell from '@/components/AppShell.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingState from '@/components/LoadingState.vue'
import TagPill from '@/components/TagPill.vue'
import { useAsyncState } from '@/composables/useAsyncState'
import { get, post } from '@/lib/api'
import { buildEvidenceLink } from '@/lib/format'
import { useSession } from '@/lib/session'
import { persistWorkflowContext, resolveWorkflowContext } from '@/lib/workflowContext'

const companies = ref<string[]>([])
const reports = ref<any[]>([])
const selectedCompany = ref('')
const selectedPeriod = ref('')
const selectedReportTitle = ref<string | null>(null)
const state = useAsyncState<any>()
const runsState = useAsyncState<any>()
const companyState = useAsyncState<any>()
const route = useRoute()
const session = useSession()
const syncingFromRoute = ref(false)
const bootstrapping = ref(false)
const verifyCommandSurface = ref<any | null>(null)
const availablePeriods = ref<any[]>([])
const reportStatusMessage = ref('')
const reportCatalogReady = ref(false)
const actionPending = ref('')
const actionError = ref('')

const activeRole = computed(() => session.activeRole.value || 'investor')
const activeRoleLabel = computed(() => {
  const map: Record<string, string> = {
    investor: '投资者视角',
    management: '管理层视角',
    regulator: '监管风控视角',
  }
  return map[activeRole.value] || '投资者视角'
})
const verifyWatchItems = computed(() => verifyCommandSurface.value?.watch_items?.slice(0, 2) || [])
const verifyDominantSignal = computed(() => verifyCommandSurface.value?.dominant_signal || null)
const verifyPrimaryClaims = computed(() => state.data.value?.claim_cards?.slice(0, 4) || [])
const verifyPrimaryInsights = computed(() => state.data.value?.research_compare?.insights?.slice(0, 3) || [])
const verifyCompareRows = computed(() => state.data.value?.research_compare?.rows?.slice(0, 3) || [])
const recentRuns = computed(() => (runsState.data.value?.runs || []).slice(0, 4))
const companyWorkspace = computed(() => companyState.data.value || null)
const workflowTasks = computed(() => companyWorkspace.value?.tasks?.items?.slice(0, 3) || [])
const quickRoutes = computed(() => state.data.value?.related_routes || [])
const currentRunId = computed(() => state.data.value?.run_id || state.data.value?.run_meta?.run_id || '')
const watchboardActionLabel = computed(() =>
  companyWorkspace.value?.watchboard?.tracked ? '移出持续跟踪' : '加入持续跟踪',
)
const watchboardSummary = computed(() => {
  if (!selectedCompany.value) return '先选择公司，再把核验分歧推进成动作。'
  if (companyWorkspace.value?.watchboard?.tracked) {
    return `已纳入持续跟踪，当前 ${Number(companyWorkspace.value.watchboard.new_alerts || 0)} 条新增预警，${Number(companyWorkspace.value.watchboard.task_count || 0)} 项相关任务。`
  }
  return '当前还未进入持续跟踪，可直接纳入监测板继续盯分歧与后续预警。'
})
const workflowStatCards = computed(() => {
  const taskSummary = companyWorkspace.value?.tasks?.summary || {}
  return [
    {
      label: '持续跟踪',
      value: companyWorkspace.value?.watchboard?.tracked ? '已纳入' : '未纳入',
    },
    {
      label: '在办任务',
      value: `${Number(taskSummary.queued || 0) + Number(taskSummary.in_progress || 0)}项`,
    },
    {
      label: '已完成',
      value: `${Number(taskSummary.done || 0)}项`,
    },
  ]
})

const periodOptions = computed(() =>
  (availablePeriods.value || [])
    .map((item: any) => {
      if (typeof item === 'string') return { value: item, label: item }
      if (item && typeof item === 'object') {
        const value = String(item.value || item.period || item.report_period || item.label || '')
        const label = String(item.label || item.period || item.report_period || item.value || '')
        return value ? { value, label } : null
      }
      return null
    })
    .filter(Boolean) as Array<{ value: string; label: string }>,
)

function readQueryString(value: unknown) {
  const normalized = Array.isArray(value) ? value[0] : value
  return typeof normalized === 'string' ? normalized.trim() : ''
}

function formatTimestamp(value?: string) {
  if (!value) return '刚刚'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function displayClaimStatus(status?: string) {
  const map: Record<string, string> = {
    match: '一致',
    mismatch: '不一致',
    partial: '部分一致',
    insufficient_data: '待补证',
    review: '待复核',
  }
  return map[(status || '').toLowerCase()] || '待复核'
}

function claimTone(status?: string): 'success' | 'risk' | 'default' {
  const normalized = (status || '').toLowerCase()
  if (normalized === 'match') return 'success'
  if (normalized === 'mismatch') return 'risk'
  return 'default'
}

function displayTaskStatus(status?: string) {
  const map: Record<string, string> = {
    queued: '待开工',
    in_progress: '处理中',
    done: '已完成',
    blocked: '已阻断',
  }
  return map[(status || '').toLowerCase()] || '已记录'
}

function buildClaimTaskTitle(card: any) {
  return `核验${card.label}分歧`
}

function buildClaimTaskSummary(card: any) {
  const claimed = String(card.claimed_value ?? '未提取')
  const actual = String(card.actual_value ?? '未提取')
  return `继续核对 ${card.label}：研报 ${claimed}，财报 ${actual}。`.slice(0, 220)
}

function setSelectionFromPayload(payload: any) {
  syncingFromRoute.value = true
  try {
    if (payload?.company_name) {
      selectedCompany.value = payload.company_name
    }
    if (payload?.report_period) {
      selectedPeriod.value = payload.report_period
    }
    if (payload?.report_meta?.title) {
      selectedReportTitle.value = payload.report_meta.title
    }
  } finally {
    syncingFromRoute.value = false
  }
}

function resetVerifyState() {
  state.data.value = null
  state.error.value = null
  state.loading.value = false
  verifyCommandSurface.value = null
}

async function loadCompanies() {
  const data = await get<any>('/workspace/companies')
  companies.value = data.companies
  availablePeriods.value = data.available_periods || []
  const preferredPeriod = data.preferred_period
  selectedPeriod.value =
    selectedPeriod.value
    || (
      typeof preferredPeriod === 'string'
        ? preferredPeriod
        : String(preferredPeriod?.value || preferredPeriod?.period || preferredPeriod?.report_period || preferredPeriod?.label || '')
    )
    || ''
}

async function requestReports(companyName: string) {
  return get<any>(`/company/research-reports?company_name=${encodeURIComponent(companyName)}`)
}

async function loadReports() {
  if (!selectedCompany.value) {
    reports.value = []
    selectedReportTitle.value = null
    reportCatalogReady.value = true
    return
  }
  try {
    const payload = await requestReports(selectedCompany.value)
    reports.value = payload.reports
    if (!reports.value.some((item) => item.title === selectedReportTitle.value)) {
      selectedReportTitle.value = reports.value[0]?.title ?? null
    }
    reportStatusMessage.value = ''
  } catch (error) {
    reports.value = []
    selectedReportTitle.value = null
    reportStatusMessage.value = error instanceof Error ? error.message : '当前公司暂无可核对研报。'
  }
  reportCatalogReady.value = true
}

async function loadRuns() {
  if (!selectedCompany.value) {
    runsState.data.value = { runs: [] }
    runsState.error.value = null
    runsState.loading.value = false
    return
  }
  const query = new URLSearchParams({
    company_name: selectedCompany.value,
    user_role: activeRole.value,
    limit: '6',
  })
  if (selectedPeriod.value) {
    query.set('report_period', selectedPeriod.value)
  }
  if (selectedReportTitle.value) {
    query.set('report_title', selectedReportTitle.value)
  }
  await runsState.execute(() => get(`/claim/verify/runs?${query.toString()}`))
}

async function loadCompanyWorkspace() {
  if (!selectedCompany.value) {
    companyState.data.value = null
    companyState.error.value = null
    companyState.loading.value = false
    return
  }
  const query = new URLSearchParams({
    company_name: selectedCompany.value,
    user_role: activeRole.value,
  })
  if (selectedPeriod.value) {
    query.set('report_period', selectedPeriod.value)
  }
  try {
    await companyState.execute(() => get(`/company/workspace?${query.toString()}`))
  } catch {
    // 错误留给 companyState，用于局部展示。
  }
}

async function openVerifyRun(runId: string) {
  if (!runId) return
  await state.execute(() => get(`/claim/verify/runs/${encodeURIComponent(runId)}`))
  verifyCommandSurface.value = state.data.value?.verify_command_surface || null
  setSelectionFromPayload(state.data.value)
  await loadCompanyWorkspace()
}

async function runVerify() {
  if (!selectedCompany.value || !selectedReportTitle.value) {
    resetVerifyState()
    return
  }
  await state.execute(() =>
    post('/claim/verify', {
      company_name: selectedCompany.value,
      report_period: selectedPeriod.value || null,
      report_title: selectedReportTitle.value,
      user_role: activeRole.value,
    }),
  )
  verifyCommandSurface.value = state.data.value?.verify_command_surface || null
  setSelectionFromPayload(state.data.value)
  await Promise.allSettled([loadRuns(), loadCompanyWorkspace()])
}

async function syncVerifySurface(options?: { forceRun?: boolean; runId?: string }) {
  if (!selectedCompany.value) {
    resetVerifyState()
    await loadCompanyWorkspace()
    return
  }
  if (!selectedReportTitle.value) {
    resetVerifyState()
    await Promise.allSettled([loadRuns(), loadCompanyWorkspace()])
    return
  }
  await loadRuns()
  if (options?.runId) {
    await openVerifyRun(options.runId)
    return
  }
  const matchedRun = (runsState.data.value?.runs || []).find(
    (item: any) => item.report_title === selectedReportTitle.value,
  )
  if (!options?.forceRun && matchedRun) {
    await openVerifyRun(matchedRun.run_id)
    return
  }
  await runVerify()
}

function isActionPending(key: string) {
  return actionPending.value === key
}

async function runWorkflowAction(key: string, action: () => Promise<void>) {
  actionError.value = ''
  actionPending.value = key
  try {
    await action()
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : '执行失败'
  } finally {
    if (actionPending.value === key) {
      actionPending.value = ''
    }
  }
}

async function toggleWatchboardTracking() {
  if (!selectedCompany.value) return
  await runWorkflowAction(`watchboard:${selectedCompany.value}`, async () => {
    const reportPeriod = state.data.value?.report_period || selectedPeriod.value || null
    if (companyWorkspace.value?.watchboard?.tracked) {
      await post('/watchboard/remove', {
        company_name: selectedCompany.value,
        user_role: activeRole.value,
        report_period: reportPeriod,
      })
    } else {
      await post('/watchboard/add', {
        company_name: selectedCompany.value,
        user_role: activeRole.value,
        report_period: reportPeriod,
        note: `${activeRoleLabel.value}继续核验跟踪`,
      })
    }
    await loadCompanyWorkspace()
  })
}

async function createTaskFromClaim(card: any) {
  if (!selectedCompany.value) return
  const key = `task:${card.claim_id || card.label}`
  await runWorkflowAction(key, async () => {
    await post('/tasks/create', {
      company_name: selectedCompany.value,
      title: buildClaimTaskTitle(card),
      summary: buildClaimTaskSummary(card),
      priority: card.status === 'mismatch' ? 'P1' : 'P2',
      user_role: activeRole.value,
      report_period: state.data.value?.report_period || selectedPeriod.value || null,
      note: `来自观点核验：${state.data.value?.report_meta?.title || selectedReportTitle.value || ''}`.slice(0, 180),
      source_run_id: currentRunId.value || null,
    })
    await loadCompanyWorkspace()
  })
}

onMounted(async () => {
  bootstrapping.value = true
  try {
    const workflowContext = resolveWorkflowContext(route.query)
    const routeRunId = readQueryString(route.query.run_id)
    await loadCompanies()
    syncingFromRoute.value = true
    if (workflowContext.company && companies.value.includes(workflowContext.company)) {
      selectedCompany.value = workflowContext.company
    } else if (!selectedCompany.value) {
      selectedCompany.value = companies.value[0] || ''
    }
    if (workflowContext.period) {
      selectedPeriod.value = workflowContext.period
    }
    syncingFromRoute.value = false
    await loadReports()
    if (workflowContext.reportTitle && reports.value.some((item) => item.title === workflowContext.reportTitle)) {
      syncingFromRoute.value = true
      selectedReportTitle.value = workflowContext.reportTitle
      syncingFromRoute.value = false
    }
    await syncVerifySurface({ runId: routeRunId || undefined })
  } finally {
    bootstrapping.value = false
  }
})

watch(selectedCompany, async (_, oldValue) => {
  if (syncingFromRoute.value || bootstrapping.value) return
  if (oldValue && selectedCompany.value !== oldValue) {
    await loadReports()
    await syncVerifySurface()
  }
})

watch(selectedPeriod, async (value, oldValue) => {
  if (syncingFromRoute.value || bootstrapping.value) return
  if (value !== oldValue) {
    await syncVerifySurface()
  }
})

watch(selectedReportTitle, async (value, oldValue) => {
  if (syncingFromRoute.value || bootstrapping.value) return
  if (value && value !== oldValue) {
    await syncVerifySurface()
  }
})

watch(
  () => [route.query.company, route.query.report_title, route.query.period, route.query.run_id],
  async ([companyQuery, reportTitleQuery, periodQuery, runIdQuery]) => {
    if (bootstrapping.value) return
    const company = readQueryString(companyQuery)
    const reportTitle = readQueryString(reportTitleQuery)
    const period = readQueryString(periodQuery)
    const runId = readQueryString(runIdQuery)
    let companyChanged = false
    syncingFromRoute.value = true
    if (company && company !== selectedCompany.value && companies.value.includes(company)) {
      selectedCompany.value = company
      companyChanged = true
    }
    if (period && period !== selectedPeriod.value) {
      selectedPeriod.value = period
    }
    syncingFromRoute.value = false
    if (companyChanged) {
      await loadReports()
    }
    if (reportTitle && reports.value.some((item) => item.title === reportTitle)) {
      syncingFromRoute.value = true
      selectedReportTitle.value = reportTitle
      syncingFromRoute.value = false
    }
    if (companyChanged || period || reportTitle || runId) {
      await syncVerifySurface({ runId: runId || undefined })
    }
  },
)

watch(
  () => session.activeRole.value,
  async (value, oldValue) => {
    if (bootstrapping.value || !selectedCompany.value || !value || value === oldValue) return
    await syncVerifySurface()
  },
)

watch([selectedCompany, selectedPeriod, selectedReportTitle], ([company, period, reportTitle]) => {
  if (!company && !period && !reportTitle) return
  persistWorkflowContext({
    company,
    period,
    reportTitle: reportTitle || '',
  })
})
</script>

<template>
  <AppShell title="">
    <div class="page-shell">
      <section class="glass-panel control-bar">
        <div class="control-copy">
          <h1>{{ selectedCompany || '观点核验' }}</h1>
          <p>{{ selectedReportTitle || '选一篇研报开始核对' }}<span v-if="selectedPeriod"> · {{ selectedPeriod }}</span></p>
          <span class="role-pill">{{ activeRoleLabel }}</span>
        </div>
        <div class="control-fields">
          <select v-model="selectedCompany" class="glass-select">
            <option v-for="company in companies" :key="company" :value="company">{{ company }}</option>
          </select>
          <select v-model="selectedPeriod" class="glass-select">
            <option value="">默认主周期</option>
            <option v-for="period in periodOptions" :key="period.value" :value="period.value">{{ period.label }}</option>
          </select>
          <select v-model="selectedReportTitle" class="glass-select report-select">
            <option v-for="report in reports" :key="report.title" :value="report.title">{{ report.title }} | {{ report.publish_date }}</option>
          </select>
          <button class="button-primary action-button" @click="runVerify">重新核对</button>
        </div>
      </section>

      <LoadingState v-if="bootstrapping || state.loading.value || runsState.loading.value" class="state-container" />
      <ErrorState
        v-else-if="state.error.value || runsState.error.value || actionError"
        :message="String(state.error.value || runsState.error.value || actionError)"
        class="state-container"
      />

      <section v-else-if="!selectedCompany" class="glass-panel empty-panel">
        <div class="empty-content">
          <h2>公司池为空</h2>
          <p>当前环境还没有可核对的企业，请先完成正式公司池和研报数据接入。</p>
        </div>
      </section>

      <section v-else-if="reportCatalogReady && reports.length === 0" class="glass-panel empty-panel">
        <div class="empty-content">
          <h2>研报缺失</h2>
          <p>{{ reportStatusMessage || '当前公司没有可供核对的研报。' }}</p>
        </div>
      </section>

      <template v-else-if="state.data.value">
        <section class="glass-panel summary-panel">
          <div class="summary-head">
            <div>
              <h2>{{ state.data.value.report_meta.title }}</h2>
              <p>
                {{ state.data.value.report_meta.publish_date }} · {{ state.data.value.report_meta.source_name }}
                <span v-if="currentRunId"> · 核验于 {{ formatTimestamp(state.data.value.run_meta?.created_at || state.data.value.created_at) }}</span>
              </p>
            </div>
            <div class="summary-links">
              <a class="inline-link" :href="state.data.value.report_meta.source_url" target="_blank" rel="noreferrer">查看原文</a>
              <a
                v-if="state.data.value.report_meta.attachment_url"
                class="inline-link"
                :href="state.data.value.report_meta.attachment_url"
                target="_blank"
                rel="noreferrer"
              >
                原文附件
              </a>
            </div>
          </div>

          <div class="metric-row" v-if="verifyCommandSurface">
            <div class="metric-card">
              <span>核验度</span>
              <strong>{{ verifyCommandSurface.metric }}</strong>
            </div>
            <div class="metric-card">
              <span>有分歧</span>
              <strong class="risk-text">{{ state.data.value.key_numbers[1].value }}</strong>
            </div>
          </div>

          <div class="summary-grid">
            <div class="summary-copy">
              <strong>{{ verifyCommandSurface?.headline || '先把这篇研报的主要说法和财报原文放在一起看。' }}</strong>
              <p v-if="verifyDominantSignal">{{ verifyDominantSignal.value }}</p>
              <div v-if="quickRoutes.length" class="summary-links">
                <RouterLink
                  v-for="item in quickRoutes"
                  :key="item.path + JSON.stringify(item.query || {})"
                  class="inline-link"
                  :to="{ path: item.path, query: item.query || {} }"
                >
                  {{ item.label }}
                </RouterLink>
              </div>
            </div>
            <div class="summary-side">
              <article class="summary-card">
                <div class="card-head">
                  <strong>继续推进</strong>
                  <button
                    type="button"
                    class="inline-action"
                    :disabled="!selectedCompany || isActionPending(`watchboard:${selectedCompany}`)"
                    @click="toggleWatchboardTracking()"
                  >
                    {{
                      selectedCompany && isActionPending(`watchboard:${selectedCompany}`)
                        ? '处理中…'
                        : watchboardActionLabel
                    }}
                  </button>
                </div>
                <p class="card-copy">{{ watchboardSummary }}</p>
                <div class="watch-list">
                  <div v-for="item in workflowStatCards" :key="item.label" class="watch-item">
                    <span>{{ item.label }}</span>
                    <strong>{{ item.value }}</strong>
                  </div>
                  <div v-for="item in verifyWatchItems" :key="`verify-${item.label}`" class="watch-item">
                    <span>{{ item.label }}</span>
                    <strong>{{ item.value }}</strong>
                  </div>
                </div>
              </article>

              <article v-if="recentRuns.length" class="summary-card">
                <div class="card-head">
                  <strong>最近核验</strong>
                  <span class="subtle-copy">{{ activeRoleLabel }}</span>
                </div>
                <button
                  v-for="item in recentRuns"
                  :key="item.run_id"
                  type="button"
                  class="run-item-button"
                  :class="{ 'is-active': currentRunId === item.run_id }"
                  @click="openVerifyRun(item.run_id)"
                >
                  <div class="run-item-copy">
                    <strong>{{ item.report_title }}</strong>
                    <p>{{ item.headline || item.source_name || '回到该次核验' }}</p>
                  </div>
                  <span>{{ formatTimestamp(item.created_at) }}</span>
                </button>
              </article>
            </div>
          </div>
        </section>

        <section class="content-grid">
          <article class="glass-panel side-section">
            <h3>先看哪几处不一致</h3>
            <div v-if="verifyPrimaryInsights.length" class="insight-list">
              <div v-for="insight in verifyPrimaryInsights" :key="insight.title" class="insight-item">
                <strong>{{ insight.title }}</strong>
                <p>{{ insight.detail || '这条说法需要回到财报原文继续核对。' }}</p>
              </div>
            </div>
            <p v-else class="muted-copy">这篇研报暂时没有明显分歧，继续逐条回看关键数据即可。</p>

            <div v-if="verifyCompareRows.length" class="related-list">
              <h4>继续看</h4>
              <div v-for="row in verifyCompareRows" :key="row.title + row.publish_date" class="related-item">
                <strong>{{ row.source_name }}</strong>
                <p>{{ row.title }}</p>
                <span>{{ row.publish_date }} · 评级 {{ row.rating_text }} · 目标价 {{ row.target_price ?? '--' }}</span>
              </div>
            </div>

            <div v-if="workflowTasks.length" class="related-list">
              <h4>已经落入任务板</h4>
              <div v-for="task in workflowTasks" :key="task.task_id" class="related-item">
                <strong>{{ task.title }}</strong>
                <p>{{ task.summary }}</p>
                <span>{{ displayTaskStatus(task.status) }} · {{ task.priority || 'P1' }}</span>
              </div>
            </div>
          </article>

          <article class="glass-panel main-section">
            <div class="main-head">
              <div>
                <h3>逐条对照</h3>
              </div>
            </div>

            <div class="claim-list">
              <article v-for="(card, idx) in verifyPrimaryClaims" :key="card.claim_id" class="claim-item">
                <div class="claim-top">
                  <div class="claim-index">{{ String(idx + 1).padStart(2, '0') }}</div>
                  <div class="claim-title">
                    <strong>{{ card.label }}</strong>
                    <span>{{ displayClaimStatus(card.status) }}</span>
                  </div>
                  <TagPill :label="displayClaimStatus(card.status)" :tone="claimTone(card.status)" />
                </div>

                <div class="claim-compare">
                  <div class="claim-col">
                    <span>研报写法</span>
                    <strong class="accent-text">{{ card.claimed_value }}</strong>
                  </div>
                  <div class="claim-col">
                    <span>财报原文</span>
                    <strong :class="card.status === 'match' ? 'accent-text' : 'risk-text'">{{ card.actual_value }}</strong>
                  </div>
                </div>

                <div class="claim-links">
                  <RouterLink class="inline-link" :to="buildEvidenceLink(card.research_chunk_id, card.label, [card.label])">研报原文</RouterLink>
                  <RouterLink
                    v-for="item in card.evidence_refs"
                    :key="item"
                    class="inline-link"
                    :to="buildEvidenceLink(item, card.label, [card.label])"
                  >
                    财报出处
                  </RouterLink>
                </div>

                <div v-if="card.status !== 'match'" class="claim-actions">
                  <button
                    type="button"
                    class="inline-action"
                    :disabled="isActionPending(`task:${card.claim_id || card.label}`)"
                    @click="createTaskFromClaim(card)"
                  >
                    {{
                      isActionPending(`task:${card.claim_id || card.label}`)
                        ? '写入中…'
                        : '写入任务板'
                    }}
                  </button>
                </div>
              </article>
            </div>
          </article>
        </section>
      </template>
    </div>
  </AppShell>
</template>

<style scoped>
.page-shell {
  display: flex;
  flex-direction: column;
  gap: 20px;
  width: 100%;
  max-width: 1320px;
  margin: 0 auto;
}

.control-bar {
  display: flex;
  justify-content: space-between;
  gap: 24px;
  padding: 18px 20px;
  border-radius: 20px;
}

.control-copy {
  display: grid;
  gap: 6px;
}

.control-copy h1,
.summary-head h2,
.side-section h3,
.main-head h3,
.empty-content h2 {
  margin: 0;
  color: #f8fafc;
}

.control-copy h1 {
  font-size: 30px;
  line-height: 1;
}

.control-copy p,
.summary-head p,
.main-head p,
.muted-copy,
.empty-content p {
  margin: 0;
  color: var(--muted);
  line-height: 1.6;
}

.control-fields {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
}

.role-pill {
  display: inline-flex;
  align-items: center;
  width: fit-content;
  padding: 6px 12px;
  border-radius: 999px;
  background: rgba(16, 185, 129, 0.12);
  border: 1px solid rgba(16, 185, 129, 0.22);
  color: #bbf7d0;
  font-size: 12px;
}

.glass-select {
  min-width: 148px;
  min-height: 40px;
  padding: 0 14px;
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.04);
  color: #fff;
}

.report-select {
  min-width: 320px;
}

.action-button {
  min-height: 40px;
  border-radius: 12px;
}

.state-container {
  min-height: 420px;
}

.empty-panel {
  min-height: 360px;
  display: grid;
  place-items: center;
  border-radius: 24px;
}

.empty-content {
  text-align: center;
  display: grid;
  gap: 10px;
}

.summary-panel,
.side-section,
.main-section {
  padding: 24px;
  border-radius: 24px;
}

.summary-head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
}

.summary-links,
.claim-links {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.inline-link {
  padding: 7px 14px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.04);
  color: var(--muted);
  font-size: 12px;
  text-decoration: none;
  transition: all 0.2s ease;
}

.inline-link:hover {
  color: #60a5fa;
  background: rgba(59, 130, 246, 0.1);
  border-color: rgba(59, 130, 246, 0.28);
}

.metric-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-top: 18px;
}

.metric-card {
  display: grid;
  gap: 6px;
  padding: 16px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.025);
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.metric-card span,
.claim-col span,
.watch-item span,
.claim-title span,
.related-item span {
  color: var(--muted);
}

.metric-card strong {
  font-size: 24px;
  color: #f8fafc;
}

.risk-text {
  color: #fb7185 !important;
}

.accent-text {
  color: #10b981 !important;
}

.summary-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(280px, 0.8fr);
  gap: 20px;
  margin-top: 18px;
}

.summary-copy {
  display: grid;
  gap: 10px;
}

.summary-copy strong {
  font-size: 20px;
  line-height: 1.45;
  color: #f8fafc;
}

.summary-copy p {
  margin: 0;
  color: var(--muted);
}

.watch-list {
  display: grid;
  gap: 10px;
}

.summary-side {
  display: grid;
  gap: 14px;
}

.summary-card {
  display: grid;
  gap: 12px;
  padding: 16px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.025);
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.card-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.card-head strong,
.run-item-copy strong {
  color: #f8fafc;
}

.subtle-copy,
.card-copy,
.run-item-copy p {
  margin: 0;
  color: var(--muted);
}

.inline-action {
  min-height: 34px;
  padding: 0 12px;
  border-radius: 999px;
  border: 1px solid rgba(16, 185, 129, 0.22);
  background: rgba(16, 185, 129, 0.1);
  color: #d1fae5;
  cursor: pointer;
}

.inline-action:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.run-item-button {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  width: 100%;
  padding: 12px 14px;
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.03);
  text-align: left;
  color: inherit;
  cursor: pointer;
}

.run-item-button.is-active {
  border-color: rgba(16, 185, 129, 0.28);
  background: rgba(16, 185, 129, 0.08);
}

.run-item-copy {
  display: grid;
  gap: 4px;
}

.watch-item {
  display: flex;
  justify-content: space-between;
  gap: 14px;
  padding: 14px 0;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.watch-item:first-child {
  padding-top: 0;
  border-top: none;
}

.watch-item strong {
  color: #f8fafc;
  text-align: right;
}

.content-grid {
  display: grid;
  grid-template-columns: 360px minmax(0, 1fr);
  gap: 20px;
}

.side-section,
.main-section {
  display: grid;
  gap: 18px;
}

.insight-list,
.related-list,
.claim-list {
  display: grid;
  gap: 14px;
}

.insight-item,
.related-item,
.claim-item {
  padding-top: 14px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.insight-item:first-child,
.claim-item:first-child {
  padding-top: 0;
  border-top: none;
}

.insight-item strong,
.related-item strong,
.claim-title strong {
  color: #f8fafc;
}

.insight-item p,
.related-item p {
  margin: 6px 0 0;
  color: var(--muted);
  line-height: 1.6;
}

.related-list {
  padding-top: 10px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.related-list h4 {
  margin: 0;
  font-size: 14px;
  color: #f8fafc;
}

.main-head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-end;
}

.claim-item {
  display: grid;
  gap: 14px;
}

.claim-actions {
  display: flex;
  justify-content: flex-end;
}

.claim-top {
  display: grid;
  grid-template-columns: 52px minmax(0, 1fr) auto;
  gap: 14px;
  align-items: center;
}

.claim-index {
  width: 52px;
  height: 52px;
  border-radius: 16px;
  display: grid;
  place-items: center;
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
  color: var(--muted);
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.05);
}

.claim-title {
  display: grid;
  gap: 4px;
}

.claim-compare {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.claim-col {
  display: grid;
  gap: 8px;
  padding: 18px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.025);
  border: 1px solid rgba(255, 255, 255, 0.05);
}

.claim-col strong {
  font-size: 18px;
  line-height: 1.45;
  color: #f8fafc;
  word-break: break-word;
}

@media (max-width: 1180px) {
  .summary-grid,
  .content-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 960px) {
  .control-bar,
  .control-fields {
    flex-direction: column;
    align-items: stretch;
  }

  .glass-select,
  .report-select {
    width: 100%;
    min-width: 0;
  }

  .metric-row,
  .claim-compare {
    grid-template-columns: 1fr;
  }

  .claim-top {
    grid-template-columns: 52px minmax(0, 1fr);
  }
}
</style>
