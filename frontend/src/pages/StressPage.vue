<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

import AppShell from '@/components/AppShell.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingState from '@/components/LoadingState.vue'
import { useAsyncState } from '@/composables/useAsyncState'
import { get, post, type UserRole } from '@/lib/api'
import { useSession } from '@/lib/session'
import { persistWorkflowContext, resolveWorkflowContext } from '@/lib/workflowContext'

const overviewState = useAsyncState<any>()
const stressState = useAsyncState<any>()
const runsState = useAsyncState<any>()
const companyState = useAsyncState<any>()
const route = useRoute()
const session = useSession()

const companies = computed(() => overviewState.data.value?.companies || [])
const availablePeriods = computed(() => overviewState.data.value?.available_periods || [])
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
const hasCompanies = computed(() => companies.value.length > 0)
const selectedCompany = ref('')
const selectedPeriod = ref('')
const scenario = ref('欧盟对动力电池临时加征关税并限制关键材料进口')
const scenarioDraft = ref(scenario.value)
const activeStressStep = ref(0)
const syncingFromRoute = ref(false)
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
let stressTicker: number | null = null

const presetScenarios = [
  '欧盟对动力电池临时加征关税并限制关键材料进口',
  '上游碳酸锂价格急涨并持续三个月',
  '关键供应商停产两周导致交付延迟',
]

const propagationSteps = computed(() => stressState.data.value?.propagation_steps || [])
const stressWavefront = computed(() => stressState.data.value?.stress_wavefront || [])
const stressCommandSurface = computed(() => stressState.data.value?.stress_command_surface || null)
const recoverySequence = computed(() => stressState.data.value?.stress_recovery_sequence || [])
const affectedDimensions = computed(() => (stressState.data.value?.affected_dimensions || []).slice(0, 3))
const stressRelatedRoutes = computed(() => stressState.data.value?.related_routes || [])
const stressEvidenceLinks = computed(() => stressState.data.value?.evidence_navigation?.links?.slice(0, 4) || [])
const currentRunId = computed(() => stressState.data.value?.run_id || stressState.data.value?.run_meta?.run_id || '')
const companyWorkspace = computed(() => companyState.data.value || null)
const recentRuns = computed(() => (runsState.data.value?.runs || []).slice(0, 4))
const workflowTasks = computed(() => companyWorkspace.value?.tasks?.items?.slice(0, 3) || [])
const watchboardActionLabel = computed(() =>
  companyWorkspace.value?.watchboard?.tracked ? '移出持续跟踪' : '加入持续跟踪',
)
const watchboardSummary = computed(() => {
  if (!selectedCompany.value) return '先选择公司，再把这轮压力场景纳入持续跟踪。'
  if (companyWorkspace.value?.watchboard?.tracked) {
    return `已纳入持续跟踪，当前 ${Number(companyWorkspace.value.watchboard.new_alerts || 0)} 条新增预警，${Number(companyWorkspace.value.watchboard.task_count || 0)} 项相关任务。`
  }
  return '当前还未进入持续跟踪，可把这轮冲击继续放进监测板。'
})
const canRunStress = computed(() => !!selectedCompany.value && !!scenarioDraft.value.trim())
const focusedPropagationSteps = computed(() => propagationSteps.value.slice(0, 3))
const primaryRecoveryAction = computed(() => recoverySequence.value[0] || null)
const activeWavefront = computed(() => stressWavefront.value[activeStressStep.value] || stressWavefront.value[0] || null)
const primaryScenarioLabel = computed(() => selectedCompany.value || '选择公司后开始推演')
const selectedPeriodLabel = computed(() => {
  const match = periodOptions.value.find((item) => item.value === selectedPeriod.value)
  if (match) return match.label
  if (typeof selectedPeriod.value === 'string') return selectedPeriod.value
  return ''
})
const scenarioStatusLine = computed(() => selectedPeriodLabel.value || '默认主周期')
const focusExplanation = computed(
  () =>
    localizeStressText(
      activeWavefront.value?.log ||
        activeWavefront.value?.detail ||
        stressCommandSurface.value?.log_headline ||
        '推演完成后，会在这里把这次冲击为什么会传导成现在的样子说清楚。',
    ),
)

const stressPhraseMap: Record<string, string> = {
  'Material Supply Constraints': '关键材料供给受限',
  'Production Delays': '生产排期延后',
  'Sales Decline in EU Market': '欧洲市场销量回落',
  'Initial Tariff Implementation': '关税冲击开始落地',
  'Supply Chain Disruption': '供应链开始失衡',
  'Market Reaction': '市场开始反应',
  'Temporary tariffs are imposed.': '临时关税开始落地。',
  'Material imports are constrained.': '关键材料进口开始受限。',
  'Stress scenario initiated.': '本轮冲击推演已经启动。',
  'High Risk': '高风险',
  'Severe': '高冲击',
  'Moderate': '中等冲击',
  'Low': '低冲击',
}

function escapeForReplace(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function localizeStressText(value?: string) {
  if (!value) return ''
  let localized = value
  Object.entries(stressPhraseMap).forEach(([english, chinese]) => {
    localized = localized.replace(new RegExp(escapeForReplace(english), 'gi'), chinese)
  })
  return localized
    .replace(/\bupstream\b/gi, '上游')
    .replace(/\bmidstream\b/gi, '中游')
    .replace(/\bdownstream\b/gi, '下游')
    .replace(/\bactions?\b/gi, '动作')
    .replace(/\bcritical\b/gi, '极高')
    .replace(/\bhigh\b/gi, '高')
    .replace(/\bmoderate\b/gi, '中')
    .replace(/\bmedium\b/gi, '中')
    .replace(/\blow\b/gi, '低')
    .replace(/\brisk\b/gi, '风险')
    .replace(/\bimpact\b/gi, '冲击')
    .replace(/\bseverity\b/gi, '等级')
    .replace(/\bshock\b/gi, '冲击')
    .replace(/\btrend\b/gi, '走势')
    .replace(/\brecovery\b/gi, '修复')
    .replace(/\bsupply\b/gi, '供应')
    .replace(/\bdelay(s)?\b/gi, '延后')
    .replace(/\bmarket\b/gi, '市场')
  }

function displayStageName(value?: string) {
  const normalized = (value || '').toLowerCase()
  const map: Record<string, string> = {
    upstream: '上游',
    midstream: '中游',
    downstream: '下游',
    actions: '动作',
  }
  return map[normalized] || localizeStressText(value)
}

function displaySeverityLevel(level?: string) {
  const map: Record<string, string> = {
    CRITICAL: '极高',
    HIGH: '高',
    MODERATE: '中',
    MEDIUM: '中',
    LOW: '低',
  }
  return map[(level || '').toUpperCase()] || '待定'
}

function displaySeverityBadge(severity?: { label?: string; level?: string }) {
  const translated = displaySeverityLevel(severity?.level)
  return translated !== '待定' ? translated : localizeStressText(severity?.label)
}

function displayToneClass(color?: string) {
  if (color === 'risk') return 'tone-risk'
  if (color === 'warning') return 'tone-warning'
  if (color === 'success' || color === 'safe') return 'tone-safe'
  return 'tone-warning'
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

function displayTaskStatus(status?: string) {
  const map: Record<string, string> = {
    queued: '待开工',
    in_progress: '处理中',
    done: '已完成',
    blocked: '已阻断',
  }
  return map[(status || '').toLowerCase()] || '已记录'
}

function readQueryString(value: unknown) {
  const normalized = Array.isArray(value) ? value[0] : value
  return typeof normalized === 'string' ? normalized.trim() : ''
}

function parseRoleQuery(value: unknown): UserRole | null {
  const normalized = readQueryString(value)
  if (normalized === 'investor' || normalized === 'management' || normalized === 'regulator') {
    return normalized
  }
  return null
}

function buildStressTaskTitle() {
  const title = localizeStressText(primaryRecoveryAction.value?.title || activeWavefront.value?.headline || '压力推演动作')
  return `落实${title}`.slice(0, 60)
}

function buildStressTaskSummary() {
  const detail = localizeStressText(primaryRecoveryAction.value?.detail || focusExplanation.value || scenario.value)
  return `围绕压力场景“${scenario.value}”继续推进：${detail}`.replace(/\s+/g, ' ').slice(0, 220)
}

function buildStressTaskPriority() {
  const severityLevel = String(stressState.data.value?.severity?.level || '').toUpperCase()
  return severityLevel === 'CRITICAL' || severityLevel === 'HIGH' ? 'P1' : 'P2'
}

async function runStress() {
  if (!selectedCompany.value || !scenarioDraft.value.trim()) return
  scenario.value = scenarioDraft.value.trim()
  await stressState.execute(() =>
    post('/company/stress-test', {
      company_name: selectedCompany.value,
      report_period: selectedPeriod.value || null,
      user_role: activeRole.value,
      scenario: scenario.value,
    }),
  )
  activeStressStep.value = 0
  await Promise.allSettled([loadStressRuns(), loadCompanyWorkspace()])
}

async function openStressRun(runId: string) {
  const normalizedRunId = runId.trim()
  if (!normalizedRunId) return
  await stressState.execute(() => get(`/stress-test/runs/${encodeURIComponent(normalizedRunId)}`))
  const payload = stressState.data.value
  if (!payload) return
  const meta = payload.run_meta || {}
  syncingFromRoute.value = true
  try {
    if (typeof meta.company_name === 'string' && meta.company_name.trim()) {
      selectedCompany.value = meta.company_name.trim()
    }
    if (typeof meta.report_period === 'string' && meta.report_period.trim()) {
      selectedPeriod.value = meta.report_period.trim()
    }
  } finally {
    syncingFromRoute.value = false
  }
  scenario.value = String(payload.scenario || scenario.value)
  scenarioDraft.value = scenario.value
  activeStressStep.value = 0
  await Promise.allSettled([loadStressRuns(), loadCompanyWorkspace()])
}

async function loadStressRuns() {
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
  await runsState.execute(() => get(`/stress-test/runs?${query.toString()}`))
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
    // 错误留给局部状态展示。
  }
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
    const reportPeriod = stressState.data.value?.report_period || selectedPeriod.value || null
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
        note: `压力推演跟进：${scenario.value}`.slice(0, 180),
      })
    }
    await loadCompanyWorkspace()
  })
}

async function createStressTask() {
  if (!selectedCompany.value) return
  const taskKey = `task:${currentRunId.value || selectedCompany.value}:${activeStressStep.value}`
  await runWorkflowAction(taskKey, async () => {
    await post('/tasks/create', {
      company_name: selectedCompany.value,
      title: buildStressTaskTitle(),
      summary: buildStressTaskSummary(),
      priority: buildStressTaskPriority(),
      user_role: activeRole.value,
      report_period: stressState.data.value?.report_period || selectedPeriod.value || null,
      note: `来自压力推演：${scenario.value}`.slice(0, 180),
      source_run_id: currentRunId.value || null,
    })
    await loadCompanyWorkspace()
  })
}

async function primeStressFromRoute() {
  const targetRole = parseRoleQuery(route.query.role)
  if (targetRole && session.activeRole.value !== targetRole) {
    session.setActiveRole(targetRole)
    return
  }
  const workflowContext = resolveWorkflowContext(route.query)
  const targetRunId = readQueryString(route.query.run_id)
  syncingFromRoute.value = true
  try {
    const initialCompany =
      workflowContext.company && companies.value.includes(workflowContext.company)
        ? workflowContext.company
        : companies.value[0] || ''
    selectedCompany.value = initialCompany
    const preferredPeriod = overviewState.data.value?.preferred_period
    selectedPeriod.value = workflowContext.period
      ? workflowContext.period
      : typeof preferredPeriod === 'string'
        ? preferredPeriod
        : String(preferredPeriod?.value || preferredPeriod?.period || preferredPeriod?.report_period || preferredPeriod?.label || '')
  } finally {
    syncingFromRoute.value = false
  }
  if (targetRunId) {
    await openStressRun(targetRunId)
    return
  }
  await runStress()
}

onMounted(async () => {
  await overviewState.execute(() => get('/workspace/companies'))
  await primeStressFromRoute()
  stressTicker = window.setInterval(() => {
    if (!focusedPropagationSteps.value.length) return
    activeStressStep.value = (activeStressStep.value + 1) % focusedPropagationSteps.value.length
  }, 3200)
})

onBeforeUnmount(() => {
  if (stressTicker) {
    window.clearInterval(stressTicker)
    stressTicker = null
  }
})

function selectPreset(item: string) {
  scenarioDraft.value = item
  runStress()
}

watch(
  () => session.activeRole.value,
  async (value, oldValue) => {
    if (!selectedCompany.value || !value || value === oldValue) return
    await primeStressFromRoute()
  },
)
watch(
  () => [route.query.company, route.query.period, route.query.run_id, route.query.role],
  async () => {
    await primeStressFromRoute()
  },
)

watch([selectedCompany, selectedPeriod], ([company, period]) => {
  if (!company && !period) return
  persistWorkflowContext({
    company,
    period,
  })
})
watch(selectedCompany, async (_company, previous) => {
  if (!_company || previous === _company || syncingFromRoute.value) return
  await runStress()
})
watch(selectedPeriod, async (period, previous) => {
  if (period === previous || syncingFromRoute.value) return
  await runStress()
})
</script>

<template>
  <AppShell title="">
    <div class="stress-console">
      <LoadingState v-if="overviewState.loading.value || stressState.loading.value" class="stress-state" />
      <ErrorState v-else-if="stressState.error.value" class="stress-state" :message="String(stressState.error.value)" />
      <section v-else-if="!hasCompanies" class="stress-state stress-empty">
        <p>当前无可推演企业，请先完成正式公司池接入。</p>
      </section>
      <section v-else class="stress-shell">
        <header class="stress-topbar">
          <div class="stress-topbar-left">
            <span class="page-kicker">压力推演</span>
          </div>
          <div class="stress-topbar-right">
            <label class="control-field">
              <span>公司</span>
              <select v-model="selectedCompany">
                <option v-if="!companies.length" value="">暂无公司</option>
                <option v-for="company in companies" :key="company" :value="company">{{ company }}</option>
              </select>
            </label>
            <label class="control-field">
              <span>报期</span>
              <select v-model="selectedPeriod">
                <option value="">默认主周期</option>
                <option v-for="period in periodOptions" :key="period.value" :value="period.value">{{ period.label }}</option>
              </select>
            </label>
            <span class="role-chip">{{ activeRoleLabel }}</span>
          </div>
        </header>

        <section class="stress-frame">
          <aside class="stress-side">
            <article class="stress-panel">
              <span class="panel-kicker">给一个冲击假设</span>
              <textarea
                v-model="scenarioDraft"
                class="scenario-input"
                :disabled="stressState.loading.value || !selectedCompany"
                :placeholder="selectedCompany ? '输入一个冲击假设，例如：上游原料价格急涨并持续三个月' : '当前无可推演企业，请先完成公司池接入'"
              />
              <button class="panel-button" :disabled="stressState.loading.value || !canRunStress" @click="runStress">
                {{ stressState.loading.value ? '推演中...' : '开始推演' }}
              </button>
            </article>

            <article class="stress-panel">
              <span class="panel-kicker">可以直接从这里开始</span>
              <div class="preset-list">
                <button
                  v-for="item in presetScenarios"
                  :key="item"
                  type="button"
                  class="preset-button"
                  @click="scenarioDraft = item"
                >
                  {{ item }}
                </button>
              </div>
            </article>
          </aside>

          <section class="stress-main">
            <article class="stress-hero">
              <div class="stress-hero-copy">
                <span class="panel-kicker">本轮判断</span>
                <h1>{{ localizeStressText(stressCommandSurface?.headline || activeWavefront?.headline || '先把这轮冲击说清楚') }}</h1>
                <p>{{ scenario }}</p>
              </div>
              <div class="severity-badge" :class="displayToneClass(stressState.data.value?.severity?.color)">
                {{ displaySeverityBadge(stressState.data.value?.severity) }}
              </div>
            </article>

            <div v-if="affectedDimensions.length" class="impact-strip">
              <div v-for="item in affectedDimensions" :key="item.label" class="impact-chip">
                <span>{{ item.label }}</span>
                <strong>{{ item.value }}</strong>
                <small>{{ item.hint }}</small>
              </div>
            </div>

            <section class="stress-grid">
              <article class="stress-panel stress-panel-wide">
                <span class="panel-kicker">冲击会先传到哪里</span>
                <div v-if="focusedPropagationSteps.length" class="chain-list">
                  <button
                    v-for="(item, idx) in focusedPropagationSteps"
                    :key="item.step"
                    type="button"
                    class="chain-step"
                    :class="{ 'is-active': idx === activeStressStep }"
                    @click="activeStressStep = idx"
                  >
                    <em>{{ String(item.step).padStart(2, '0') }}</em>
                    <div>
                      <strong>{{ localizeStressText(item.title) }}</strong>
                      <p>{{ localizeStressText(item.detail) }}</p>
                    </div>
                  </button>
                </div>
                <p v-else class="panel-muted">当前还没有形成完整传导链。</p>
              </article>

              <article class="stress-panel">
                <span class="panel-kicker">这一轮先做什么</span>
                <strong class="panel-title">{{ localizeStressText(primaryRecoveryAction?.title || '先把冲击路径说清楚') }}</strong>
                <p class="panel-summary">{{ localizeStressText(primaryRecoveryAction?.detail || '当前还没有收敛出明确动作，先看传导链和最先受影响的环节。') }}</p>
                <div class="action-row">
                  <button
                    type="button"
                    class="panel-button"
                    :disabled="!selectedCompany || isActionPending(`watchboard:${selectedCompany}`)"
                    @click="toggleWatchboardTracking()"
                  >
                    {{
                      selectedCompany && isActionPending(`watchboard:${selectedCompany}`)
                        ? '处理中...'
                        : watchboardActionLabel
                    }}
                  </button>
                  <button
                    type="button"
                    class="panel-button is-secondary"
                    :disabled="isActionPending(`task:${currentRunId || selectedCompany}:${activeStressStep}`)"
                    @click="createStressTask()"
                  >
                    {{
                      isActionPending(`task:${currentRunId || selectedCompany}:${activeStressStep}`)
                        ? '写入中...'
                        : '写入任务板'
                    }}
                  </button>
                </div>
              </article>

              <article class="stress-panel">
                <span class="panel-kicker">为什么会这样</span>
                <strong class="panel-title">{{ localizeStressText(activeWavefront?.headline || stressCommandSurface?.headline || '这轮冲击正在传导') }}</strong>
                <p class="panel-summary">{{ focusExplanation }}</p>
                <div v-if="stressRelatedRoutes.length || stressEvidenceLinks.length" class="route-links">
                  <RouterLink
                    v-for="item in [...stressRelatedRoutes.slice(0, 1), ...stressEvidenceLinks.slice(0, 1)]"
                    :key="`${item.path}-${item.label}`"
                    :to="{ path: item.path, query: item.query || {} }"
                    class="inline-link"
                  >
                    {{ item.label }}
                  </RouterLink>
                </div>
                <p v-if="actionError" class="panel-error">{{ actionError }}</p>
              </article>
            </section>
          </section>
        </section>
      </section>
    </div>
  </AppShell>
</template>

<style scoped>
.stress-console {
  min-height: 100%;
  width: 100%;
  max-width: 1320px;
  margin: 0 auto;
}

.stress-state {
  min-height: 420px;
  display: grid;
  place-items: center;
}

.stress-empty p {
  margin: 0;
  color: rgba(191, 207, 228, 0.82);
}

.stress-shell {
  display: grid;
  gap: 16px;
}

.stress-topbar {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 18px;
  padding-bottom: 14px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.page-kicker,
.panel-kicker,
.control-field span,
.chain-step em {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: rgba(120, 143, 172, 0.82);
}

.stress-topbar-right {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.control-field {
  display: grid;
  gap: 6px;
}

.control-field select {
  min-width: 220px;
  min-height: 44px;
  padding: 0 14px;
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.03);
  color: #eef2f7;
}

.role-chip {
  min-height: 34px;
  padding: 0 14px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  background: rgba(18, 62, 45, 0.88);
  border: 1px solid rgba(52, 211, 153, 0.18);
  color: #d9fff0;
  font-size: 13px;
}

.stress-frame {
  display: grid;
  grid-template-columns: 340px minmax(0, 1fr);
  gap: 18px;
}

.stress-side,
.stress-main,
.stress-grid,
.preset-list,
.chain-list {
  display: grid;
  gap: 16px;
}

.stress-panel,
.stress-hero {
  border-radius: 22px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: linear-gradient(180deg, rgba(15, 16, 20, 0.98), rgba(11, 12, 17, 0.96));
}

.stress-panel {
  padding: 20px 22px;
}

.scenario-input {
  width: 100%;
  min-height: 168px;
  resize: none;
  border: 0;
  margin-top: 10px;
  padding: 16px 18px;
  border-radius: 18px;
  background: rgba(7, 10, 18, 0.94);
  color: #eef2f7;
  font: inherit;
  line-height: 1.65;
}

.panel-button {
  min-height: 52px;
  margin-top: 12px;
  border-radius: 18px;
  border: 1px solid rgba(52, 211, 153, 0.22);
  background: rgba(18, 62, 45, 0.88);
  color: #effff6;
}

.panel-button.is-secondary {
  background: rgba(255, 255, 255, 0.03);
  color: #eef2f7;
  border-color: rgba(255, 255, 255, 0.08);
}

.preset-button,
.chain-step,
.inline-link {
  border-radius: 18px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.02);
  color: #eef2f7;
}

.preset-button {
  min-height: 76px;
  padding: 0 16px;
  text-align: left;
}

.stress-hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
  padding: 24px 26px;
}

.stress-hero-copy {
  display: grid;
  gap: 10px;
}

.stress-hero-copy h1,
.impact-chip strong,
.chain-step strong,
.panel-title {
  margin: 0;
  color: #f8fafc;
}

.stress-hero-copy h1 {
  font-size: clamp(30px, 4vw, 48px);
  line-height: 0.95;
  letter-spacing: -0.05em;
}

.stress-hero-copy p,
.impact-chip small,
.chain-step p,
.panel-summary {
  margin: 0;
  color: rgba(191, 207, 228, 0.82);
  line-height: 1.65;
}

.severity-badge {
  min-height: 44px;
  padding: 0 18px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
}

.tone-risk {
  border: 1px solid rgba(251, 113, 133, 0.2);
  background: rgba(127, 29, 29, 0.66);
  color: #fee2e2;
}

.tone-warning {
  border: 1px solid rgba(251, 191, 36, 0.2);
  background: rgba(120, 53, 15, 0.66);
  color: #fde68a;
}

.tone-safe {
  border: 1px solid rgba(52, 211, 153, 0.22);
  background: rgba(18, 62, 45, 0.88);
  color: #d9fff0;
}

.impact-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.impact-chip {
  display: grid;
  gap: 6px;
  padding: 16px 18px;
  border-radius: 18px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.025);
}

.impact-chip span {
  color: rgba(168, 179, 194, 0.76);
}

.stress-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.stress-panel-wide {
  grid-column: 1 / -1;
}

.chain-list {
  margin-top: 12px;
}

.chain-step {
  display: grid;
  grid-template-columns: 52px minmax(0, 1fr);
  gap: 14px;
  min-height: 94px;
  padding: 18px;
  text-align: left;
}

.chain-step.is-active {
  border-color: rgba(96, 165, 250, 0.22);
  background: rgba(21, 33, 58, 0.72);
}

.panel-title {
  font-size: 22px;
  line-height: 1.18;
  margin-top: 12px;
}

.action-row,
.route-links {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 12px;
}

.inline-link {
  min-height: 40px;
  padding: 0 14px;
  display: inline-flex;
  align-items: center;
  text-decoration: none;
}

.panel-error {
  color: #fda4af;
  margin-top: 10px;
}

@media (max-width: 1180px) {
  .stress-frame {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 860px) {
  .stress-topbar {
    flex-direction: column;
    align-items: stretch;
  }

  .stress-topbar-right,
  .stress-grid,
  .impact-strip {
    grid-template-columns: 1fr;
    flex-direction: column;
    justify-content: flex-start;
  }

  .stress-hero {
    flex-direction: column;
  }
}
</style>
