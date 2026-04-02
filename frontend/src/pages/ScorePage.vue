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
import { buildEvidenceLink } from '@/lib/format'
import { useSession } from '@/lib/session'

const companies = ref<string[]>([])
const selectedCompany = ref('')
const selectedPeriod = ref<string>('')
const scoreState = useAsyncState<any>()
const timelineState = useAsyncState<any>()
const companyState = useAsyncState<any>()
const route = useRoute()
const syncingFromRoute = ref(false)
const watchboardBusy = ref(false)
const session = useSession()

const scoreCommandSurface = computed(() => scoreState.data.value?.score_command_surface || null)
const scoreSignalTape = computed(() => scoreState.data.value?.score_signal_tape || [])
const scoreWatchItems = computed(() => scoreCommandSurface.value?.watch_items || [])
const dominantSignal = computed(() => scoreCommandSurface.value?.dominant_signal || null)
const scorePrimaryActions = computed(() => scoreState.data.value?.action_cards?.slice(0, 2) || [])
const scorePrimaryCharts = computed(() => scoreState.data.value?.charts?.slice(0, 1) || [])
const scoreMetricCards = computed(() => scoreState.data.value?.label_cards?.slice(0, 2) || [])
const scoreTagGroups = computed(() => ({
  risks: scoreState.data.value?.scorecard?.risk_labels?.slice(0, 4) || [],
  opportunities: scoreState.data.value?.scorecard?.opportunity_labels?.slice(0, 3) || [],
}))
const availablePeriods = computed(() =>
  (scoreState.data.value?.available_periods || [])
    .map((period: any) => normalizePeriodOption(period))
    .filter((period: { value: string; label: string }) => period.value),
)
const activeRole = computed(() => session.activeRole.value || 'investor')
const activeRoleLabel = computed(() => {
  const map: Record<string, string> = {
    investor: '投资者视角',
    management: '管理层视角',
    regulator: '监管风控视角',
  }
  return map[activeRole.value] || '投资者视角'
})
const companyWorkspace = computed(() => companyState.data.value || null)
const companyWatchboard = computed(() => companyWorkspace.value?.watchboard || null)
const companyResearch = computed(() => companyWorkspace.value?.research || null)
const companyAlertSummary = computed(() => companyWorkspace.value?.alerts?.summary || {})
const companyTaskSummary = computed(() => companyWorkspace.value?.tasks?.summary || {})
const companyRuntimeSummary = computed(() => companyWorkspace.value?.intelligence_runtime?.summary || null)
const companyRuntimePulses = computed(
  () => companyWorkspace.value?.intelligence_runtime?.module_pulses?.slice(0, 4) || [],
)
const documentStageSummary = computed(() => companyWorkspace.value?.document_upgrades?.stage_summary || {})
const documentStageItems = computed(() =>
  Object.entries(documentStageSummary.value || {})
    .map(([stage, count]) => ({ stage, count: Number(count) || 0 }))
    .sort((left, right) => right.count - left.count)
    .slice(0, 3),
)
const workflowStatCards = computed(() => {
  const taskSummary = companyTaskSummary.value || {}
  const alertSummary = companyAlertSummary.value || {}
  const activeTasks = Number(taskSummary.queued || 0) + Number(taskSummary.in_progress || 0)
  return [
    {
      label: '监测状态',
      value: companyWatchboard.value?.tracked ? '已跟踪' : '未跟踪',
      detail: companyWatchboard.value?.tracked ? '持续进入监测板' : '还没纳入重点监测',
      tone: companyWatchboard.value?.tracked ? 'success' : 'default',
    },
    {
      label: '新增预警',
      value: `${Number(alertSummary.new || 0)}项`,
      detail: `${Number(alertSummary.in_progress || 0)} 项正在处理`,
      tone: Number(alertSummary.new || 0) > 0 ? 'risk' : 'default',
    },
    {
      label: '在办任务',
      value: `${activeTasks}项`,
      detail: `${Number(taskSummary.done || 0)} 项已完成`,
      tone: activeTasks > 0 ? 'warning' : 'default',
    },
    {
      label: '文档升级',
      value: `${Number(companyWorkspace.value?.document_upgrades?.count || 0)}项`,
      detail: documentStageItems.value.length ? '可继续回到页块证据' : '当前无升级产物',
      tone: Number(companyWorkspace.value?.document_upgrades?.count || 0) > 0 ? 'accent' : 'default',
    },
  ]
})

function normalizePeriodOption(period: any) {
  if (typeof period === 'string') {
    return { value: period, label: period }
  }
  if (period && typeof period === 'object') {
    const value = period.value || period.report_period || period.period || period.label || ''
    const label = period.label || period.report_period || period.period || period.value || ''
    return {
      value: String(value || ''),
      label: String(label || value || ''),
    }
  }
  return { value: '', label: '' }
}

function normalizePeriodValue(period: any) {
  if (typeof period === 'string') {
    return period
  }
  if (period && typeof period === 'object') {
    return String(period.value || period.report_period || period.period || period.label || '')
  }
  return ''
}

function displayPulseStatus(status?: string) {
  const map: Record<string, string> = {
    ready: '已就绪',
    idle: '待运行',
    completed: '已完成',
    running: '运行中',
    blocked: '已阻断',
  }
  return map[status || ''] || status || '待运行'
}

function pulseTone(status?: string) {
  const normalized = (status || '').toLowerCase()
  if (normalized === 'ready' || normalized === 'completed') return 'success'
  if (normalized === 'running') return 'accent'
  if (normalized === 'blocked') return 'risk'
  return 'default'
}

function pulseIntensity(value: unknown) {
  const numeric = Number(value || 0)
  if (!Number.isFinite(numeric) || numeric <= 0) return 14
  return Math.max(14, Math.min(100, Math.round(numeric)))
}

function displayResearchTone(status?: string): 'default' | 'success' {
  return status === 'ready' ? 'success' : 'default'
}

function displayStageLabel(stage: string) {
  const map: Record<string, string> = {
    cross_page_merge: '跨页拼接',
    title_hierarchy: '标题层级',
    cell_trace: '单元格溯源',
  }
  return map[stage] || stage
}

async function loadCompanies() {
  const data = await get<any>('/workspace/companies')
  companies.value = data.companies
}

async function loadScore() {
  if (!selectedCompany.value) {
    scoreState.data.value = null
    scoreState.error.value = null
    scoreState.loading.value = false
    return
  }
  await scoreState.execute(() =>
    post('/company/score', {
      company_name: selectedCompany.value,
      report_period: selectedPeriod.value || null,
    }),
  )
}

async function loadTimeline() {
  if (!selectedCompany.value) {
    timelineState.data.value = null
    timelineState.error.value = null
    timelineState.loading.value = false
    return
  }
  await timelineState.execute(() =>
    get<any>(`/company/timeline?company_name=${encodeURIComponent(selectedCompany.value)}`),
  )
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
    await companyState.execute(() =>
      get<any>(`/company/workspace?${query.toString()}`),
    )
  } catch {
    // 错误状态已写入 companyState，页面继续展示评分主体。
  }
}

async function toggleWatchboardTracking() {
  if (!selectedCompany.value || watchboardBusy.value) return
  watchboardBusy.value = true
  try {
    const reportPeriod =
      selectedPeriod.value || normalizePeriodValue(scoreState.data.value?.report_period) || null
    if (companyWatchboard.value?.tracked) {
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
        note: `${activeRoleLabel.value}持续跟踪`,
      })
    }
    await loadCompanyWorkspace()
  } finally {
    watchboardBusy.value = false
  }
}

function applyQuerySelection() {
  const queryCompany = typeof route.query.company === 'string' ? route.query.company : ''
  const queryPeriod = typeof route.query.period === 'string' ? route.query.period : ''
  syncingFromRoute.value = true
  if (queryCompany && companies.value.includes(queryCompany)) {
    selectedCompany.value = queryCompany
  }
  if (queryPeriod) {
    selectedPeriod.value = queryPeriod
  }
  syncingFromRoute.value = false
}

onMounted(async () => {
  await loadCompanies()
  if (!selectedCompany.value) {
    selectedCompany.value = companies.value[0] || ''
  }
  applyQuerySelection()
  await loadScore()
  await loadTimeline()
  if (!selectedPeriod.value) {
    selectedPeriod.value = normalizePeriodValue(scoreState.data.value?.report_period) || availablePeriods.value[0]?.value || ''
  }
  await loadCompanyWorkspace()
})

watch(selectedCompany, async (_, oldValue) => {
  if (syncingFromRoute.value) {
    return
  }
  if (oldValue && selectedCompany.value !== oldValue) {
    selectedPeriod.value = ''
    await loadScore()
    await loadTimeline()
    selectedPeriod.value = normalizePeriodValue(scoreState.data.value?.report_period) || availablePeriods.value[0]?.value || ''
    await loadCompanyWorkspace()
  }
})

watch(selectedPeriod, async (_, oldValue) => {
  if (syncingFromRoute.value) {
    return
  }
  if (oldValue && selectedPeriod.value !== oldValue) {
    await loadScore()
    await loadCompanyWorkspace()
  }
})

watch(
  () => [route.query.company, route.query.period],
  async ([companyQuery, periodQuery]) => {
    const company = typeof companyQuery === 'string' ? companyQuery : ''
    const period = typeof periodQuery === 'string' ? periodQuery : ''
    if (company && company !== selectedCompany.value && companies.value.includes(company)) {
      syncingFromRoute.value = true
      selectedCompany.value = company
      selectedPeriod.value = period || ''
      syncingFromRoute.value = false
      await loadScore()
      await loadTimeline()
      if (!period) {
        selectedPeriod.value = normalizePeriodValue(scoreState.data.value?.report_period) || availablePeriods.value[0]?.value || ''
      }
      await loadCompanyWorkspace()
      return
    }
    if (period && period !== selectedPeriod.value) {
      syncingFromRoute.value = true
      selectedPeriod.value = period
      syncingFromRoute.value = false
      await loadScore()
      await loadCompanyWorkspace()
    }
  },
)

watch(
  () => session.activeRole.value,
  async (value, oldValue) => {
    if (!selectedCompany.value || !value || value === oldValue) return
    await loadCompanyWorkspace()
  },
)
</script>

<template>
  <AppShell title="">
    <div class="dashboard-wrapper">
      <!-- Top Control Bar -->
      <section class="glass-panel control-bar">
        <div class="control-left">
          <div class="mode-query-icon glow-icon">体</div>
          <div class="mode-query-copy">
            <span class="control-kicker">经营体检</span>
            <h3 class="company-name text-gradient">{{ selectedCompany || '经营诊断' }}</h3>
            <p class="control-meta">{{ scoreCommandSurface?.headline || '先看这次判断' }}<span v-if="selectedPeriod"> · {{ selectedPeriod }}</span></p>
          </div>
          <span class="role-pill">{{ activeRoleLabel }}</span>
        </div>
        
        <div class="graph-context-bar inline-context">
          <label class="field inline-field">
            <span class="subtle-label">公司</span>
            <select v-model="selectedCompany" class="glass-select">
              <option v-for="company in companies" :key="company" :value="company">{{ company }}</option>
            </select>
          </label>
          <label class="field inline-field">
            <span class="subtle-label">报告期</span>
            <select v-model="selectedPeriod" class="glass-select">
              <option
                v-for="period in availablePeriods"
                :key="period.value"
                :value="period.value"
              >
                {{ period.label }}
              </option>
            </select>
          </label>
          <button class="button-primary glow-button" @click="loadScore">重新体检</button>
        </div>
      </section>

      <LoadingState v-if="scoreState.loading.value" class="state-container" />
      <ErrorState v-else-if="scoreState.error.value" :message="scoreState.error.value" class="state-container" />
      <section v-else-if="!selectedCompany" class="glass-panel empty-panel">
        <div class="empty-content">
          <h3 class="text-gradient mb-2">公司池为空</h3>
          <p class="muted">当前环境还没有可评分的企业，请先完成正式公司池和财报数据接入。</p>
        </div>
      </section>
      
      <!-- Main Dashboard Grid -->
      <div v-else-if="scoreState.data.value" class="dashboard-grid">
        <!-- Left Column: Core Score & Signals -->
        <div class="dashboard-col left-col">
          <!-- Main Grade Panel -->
          <article class="glass-panel score-hero-panel">
            <div class="hero-top">
              <div class="eyebrow">当前判断</div>
              <h2 class="hero-title compact">{{ scoreCommandSurface?.headline || scoreState.data.value.company_name }}</h2>
              <p class="hero-text text-sm muted">
                {{ scoreState.data.value.report_period }} · {{ scoreState.data.value.subindustry }}
              </p>
            </div>
            
            <div class="grade-display" v-if="scoreCommandSurface">
              <div class="grade-circle" :data-grade="scoreState.data.value.scorecard.grade">
                <span class="grade-score">{{ scoreState.data.value.scorecard.total_score }}</span>
                <span class="grade-letter">{{ scoreState.data.value.scorecard.grade }}</span>
              </div>
              <div class="grade-metrics">
                <div class="metric-row-inline">
                  <span>行业分位</span>
                  <strong class="text-gradient">{{ scoreState.data.value.scorecard.subindustry_percentile }}分位</strong>
                </div>
                <div class="metric-row-inline">
                  <span>总风险</span>
                  <strong class="risk-text">{{ scoreState.data.value.scorecard.risk_labels.length }}项</strong>
                </div>
              </div>
            </div>

            <div v-if="scoreCommandSurface" class="hero-summary">
              <div class="hero-summary-head">
                <strong>{{ scoreCommandSurface.title || '经营诊断' }}</strong>
                <span class="hero-summary-badge">{{ scoreCommandSurface.metric }} · {{ scoreCommandSurface.delta_label }}</span>
              </div>
              <p v-if="dominantSignal" class="hero-summary-copy">
                当前主判断：{{ dominantSignal.value }}
              </p>
              <div v-if="scoreWatchItems.length" class="watch-grid">
                <div
                  v-for="item in scoreWatchItems.slice(0, 2)"
                  :key="item.label"
                  class="watch-card"
                >
                  <span>{{ item.label }}</span>
                  <strong>{{ item.value }}</strong>
                </div>
              </div>
            </div>

            <!-- Signal Tape -->
            <div class="signal-tape scroll-area" v-if="scoreSignalTape && scoreSignalTape.length">
              <div
                v-for="item in scoreSignalTape.slice(0, 3)"
                :key="`${item.step}-${item.label}`"
                class="graph-route-band subtle-band"
                :class="[`tone-${item.tone || 'accent'}`]"
              >
                <em>{{ item.label }}</em>
                <div class="graph-route-band-copy">
                  <strong class="text-glow">{{ item.value }}</strong>
                </div>
                <i :style="{ width: `${item.intensity || 0}%` }" class="glow-bar" />
              </div>
            </div>
          </article>

          <!-- Tags & Actions -->
          <article class="glass-panel support-panel scroll-area">
            <h3 class="panel-sm-title">先做这两步</h3>
            <div class="tag-row compact-tags">
              <TagPill
                v-for="label in scoreTagGroups.risks.slice(0, 3)"
                :key="label.code"
                :label="label.name"
                tone="risk"
              />
              <TagPill
                v-for="label in scoreTagGroups.opportunities.slice(0, 2)"
                :key="`op-${label.code}`"
                :label="label.name"
                tone="success"
              />
            </div>
            
            <div class="actions-list mt-4">
              <div
                v-for="action in scorePrimaryActions"
                :key="action.title"
                class="action-item glass-panel-hover"
              >
                <div class="action-head">
                  <span class="priority-dot"></span>
                  <h4>{{ action.title }}</h4>
                </div>
                <p class="action-desc">{{ action.reason }}</p>
                <p v-if="action.action" class="action-next">{{ action.action }}</p>
              </div>
            </div>
          </article>
        </div>

        <!-- Right Column: Charts & Analysis -->
        <div class="dashboard-col right-col">
          <!-- Top Row: Charts -->
          <div class="charts-row">
            <div v-for="chart in scorePrimaryCharts" :key="chart.title" class="glass-panel chart-container">
              <ChartPanel :title="chart.title" :options="chart.options" />
            </div>
          </div>

          <!-- Bottom Row: Timeline & Details -->
          <div class="details-row">
            <!-- Timeline Snapshots -->
            <article class="glass-panel details-panel scroll-area" v-if="timelineState.data.value">
              <h3 class="panel-sm-title">最近两期</h3>
              <div class="timeline-stack">
                <div
                  v-for="item in timelineState.data.value.snapshots.slice(0, 2)"
                  :key="item.report_period"
                  class="timeline-card glass-panel-hover"
                >
                  <div class="tc-head">
                    <span class="tc-period">{{ item.report_period }}</span>
                    <strong class="tc-grade">{{ item.grade }} ({{ item.total_score }}分)</strong>
                  </div>
                  <div class="tc-metrics">
                    <span>风险项 {{ item.risk_count }}</span>
                    <span>营收增速 {{ item.revenue_growth ?? '--' }}</span>
                  </div>
                </div>
              </div>
            </article>

            <!-- Key Metrics Highlights -->
            <article class="glass-panel details-panel scroll-area flex-2">
              <h3 class="panel-sm-title">先盯这几个指标</h3>
              <div class="metrics-grid-compact">
                <div
                  v-for="card in scoreMetricCards"
                  :key="card.code"
                  class="metric-glance glass-panel-hover"
                >
                  <div class="mg-head">
                    <span class="mg-code">{{ card.name }}</span>
                    <span class="mg-val">{{ card.signal_values[0] }}</span>
                  </div>
                  <div class="mg-links">
                    <RouterLink
                      v-for="item in card.evidence_refs.slice(0,2)"
                      :key="item"
                      class="inline-glass-link"
                      :to="buildEvidenceLink(item, `${card.code} ${card.name}`, card.anchor_terms)"
                    >
                      溯源
                    </RouterLink>
                  </div>
                </div>
              </div>
            </article>
          </div>

          <div v-if="companyWorkspace || companyState.error.value" class="workflow-row">
            <article class="glass-panel details-panel workflow-panel">
              <div class="workflow-head">
                <div class="workflow-copy">
                  <h3 class="workflow-title">执行闭环</h3>
                  <p class="workflow-caption">把这次经营判断直接连到监测、任务和文档链路。</p>
                </div>
                <button
                  class="workflow-action"
                  type="button"
                  :disabled="watchboardBusy || !!companyState.error.value"
                  @click="toggleWatchboardTracking"
                >
                  {{
                    watchboardBusy
                      ? '处理中...'
                      : companyWatchboard?.tracked
                        ? '移出重点监测'
                        : '加入重点监测'
                  }}
                </button>
              </div>

              <ErrorState v-if="companyState.error.value" :message="companyState.error.value" />

              <template v-else>
                <div class="monitor-banner" :class="companyWatchboard?.tracked ? 'is-tracked' : 'is-idle'">
                  <div class="monitor-copy">
                    <strong>{{ companyWatchboard?.tracked ? '已纳入重点监测' : '尚未纳入重点监测' }}</strong>
                    <p>
                      {{
                        companyWatchboard?.tracked
                          ? companyWatchboard?.note || '当前公司已经进入持续跟踪。'
                          : '需要连续跟踪时，可以直接从这里加入监测板。'
                      }}
                    </p>
                  </div>
                  <TagPill
                    :label="companyWatchboard?.tracked ? '监测中' : '待加入'"
                    :tone="companyWatchboard?.tracked ? 'success' : 'default'"
                  />
                </div>

                <div class="workflow-stat-grid">
                  <article
                    v-for="item in workflowStatCards"
                    :key="item.label"
                    class="workflow-stat-card"
                    :class="`tone-${item.tone}`"
                  >
                    <span>{{ item.label }}</span>
                    <strong>{{ item.value }}</strong>
                    <small>{{ item.detail }}</small>
                  </article>
                </div>

                <div v-if="documentStageItems.length" class="document-stage-row">
                  <span
                    v-for="item in documentStageItems"
                    :key="item.stage"
                    class="document-stage-chip"
                  >
                    {{ displayStageLabel(item.stage) }} {{ item.count }}
                  </span>
                </div>

                <div class="workflow-links">
                  <RouterLink
                    class="inline-glass-link"
                    :to="{ path: '/workspace', query: { company: selectedCompany, period: selectedPeriod, role: activeRole } }"
                  >
                    进入协同分析
                  </RouterLink>
                  <RouterLink
                    class="inline-glass-link"
                    :to="{ path: '/graph', query: { company: selectedCompany, period: selectedPeriod } }"
                  >
                    查看图谱链路
                  </RouterLink>
                </div>
              </template>
            </article>

            <article v-if="companyWorkspace" class="glass-panel details-panel workflow-panel">
              <div class="workflow-head">
                <div class="workflow-copy">
                  <h3 class="workflow-title">原文与运行</h3>
                  <p class="workflow-caption">{{ companyRuntimeSummary?.latest_label || '继续回看最新运行脉冲。' }}</p>
                </div>
                <TagPill
                  v-if="companyResearch"
                  :label="companyResearch.status === 'ready' ? '研报已核验' : '研报缺失'"
                  :tone="displayResearchTone(companyResearch.status)"
                />
              </div>

              <div class="research-banner" :class="`tone-${displayResearchTone(companyResearch?.status)}`">
                <div class="research-copy">
                  <strong>
                    {{
                      companyResearch?.status === 'ready'
                        ? companyResearch.report_title || '最新研报核验已就绪'
                        : '当前没有可直接核验的研报'
                    }}
                  </strong>
                  <p>
                    {{
                      companyResearch?.status === 'ready'
                        ? `${companyResearch.institution || '机构未披露'} · 匹配 ${companyResearch.claim_matches || 0} 条 / 偏差 ${companyResearch.claim_mismatches || 0} 条`
                        : companyResearch?.detail || '需要先补齐正式研报，再回到原文核验。'
                    }}
                  </p>
                </div>
                <RouterLink
                  class="inline-glass-link"
                  :to="{ path: '/verify', query: { company: selectedCompany } }"
                >
                  进入原文核验
                </RouterLink>
              </div>

              <div v-if="companyRuntimePulses.length" class="runtime-pulse-list">
                <article
                  v-for="pulse in companyRuntimePulses"
                  :key="pulse.module_key"
                  class="runtime-pulse-card"
                >
                  <div class="runtime-pulse-head">
                    <strong>{{ pulse.label }}</strong>
                    <span :class="`tone-${pulseTone(pulse.status)}`">{{ displayPulseStatus(pulse.status) }}</span>
                  </div>
                  <p>{{ pulse.headline }}</p>
                  <small>{{ pulse.signal }}</small>
                  <div class="runtime-pulse-meter">
                    <i :style="{ width: `${pulseIntensity(pulse.intensity)}%` }"></i>
                  </div>
                  <RouterLink
                    class="inline-glass-link"
                    :to="{ path: pulse.route?.path || '/workspace', query: pulse.route?.query || {} }"
                  >
                    打开 {{ pulse.label }}
                  </RouterLink>
                </article>
              </div>

              <div v-else class="workflow-empty-state">
                当前还没有新的运行记录，先从协同分析或图谱检索发起一轮判断。
              </div>
            </article>
          </div>
        </div>
      </div>
    </div>
  </AppShell>
</template>

<style scoped>
/* Dashboard Shell */
.dashboard-wrapper {
  display: flex;
  flex-direction: column;
  gap: 16px;
  height: 100%;
  overflow: hidden;
  width: 100%;
  max-width: 1280px;
  margin: 0 auto;
}

/* Control Bar */
.control-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-radius: 14px;
  flex-shrink: 0;
}

.control-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.glow-icon {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  background: rgba(16, 185, 129, 0.15);
  border: 1px solid rgba(16, 185, 129, 0.4);
  color: #10b981;
  display: grid;
  place-items: center;
  font-weight: bold;
  font-size: 18px;
  box-shadow: 0 0 15px rgba(16, 185, 129, 0.2);
}

.company-name {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: var(--accent);
}

.control-kicker {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--muted);
}

.control-meta {
  margin: 2px 0 0;
  font-size: 12px;
  color: var(--muted);
}

.role-pill {
  min-height: 34px;
  padding: 0 12px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  background: rgba(59, 130, 246, 0.12);
  border: 1px solid rgba(59, 130, 246, 0.2);
  color: #bfdbfe;
  font-size: 12px;
  white-space: nowrap;
}

.inline-context {
  display: flex;
  align-items: center;
  gap: 16px;
}

.inline-field {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: unset;
}

.subtle-label {
  font-size: 12px;
  color: var(--muted);
  text-transform: uppercase;
}

.glass-select {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  min-height: 36px;
  padding: 0 12px;
  border-radius: 8px;
  color: #fff;
}

.glow-button {
  min-height: 36px;
  border-radius: 8px;
  box-shadow: 0 0 15px rgba(16, 185, 129, 0.2);
}

/* Main Grid */
.dashboard-grid {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 16px;
  flex: 1;
  min-height: 0;
}

.dashboard-col {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: 0;
}

.left-col {
  overflow-y: auto;
  overflow-x: hidden;
}
.left-col::-webkit-scrollbar { width: 4px; }
.left-col::-webkit-scrollbar-track { background: transparent; }
.left-col::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 2px; }

.right-col {
  overflow-y: auto;
}
.right-col::-webkit-scrollbar { width: 4px; }
.right-col::-webkit-scrollbar-track { background: transparent; }
.right-col::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 2px; }

.scroll-area {
  overflow-y: auto;
}
.scroll-area::-webkit-scrollbar { width: 4px; }
.scroll-area::-webkit-scrollbar-track { background: transparent; }
.scroll-area::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 2px; }

/* Left Hero Panel */
.score-hero-panel {
  padding: 16px;
  border-radius: 18px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  flex-shrink: 0;
}

.grade-display {
  display: flex;
  align-items: center;
  gap: 18px;
  padding: 12px;
  background: rgba(0,0,0,0.2);
  border-radius: 14px;
  border: 1px solid rgba(255,255,255,0.05);
}

.grade-circle {
  width: 72px;
  height: 72px;
  border-radius: 50%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  border: 2px solid var(--accent);
  box-shadow: 0 0 20px rgba(16, 185, 129, 0.2);
  position: relative;
}

.grade-circle[data-grade^="A"] { border-color: #10b981; box-shadow: 0 0 20px rgba(16, 185, 129, 0.3); }
.grade-circle[data-grade^="B"] { border-color: #3b82f6; box-shadow: 0 0 20px rgba(59, 130, 246, 0.3); }
.grade-circle[data-grade^="C"] { border-color: #f59e0b; box-shadow: 0 0 20px rgba(245, 158, 11, 0.3); }

.grade-score { font-size: 21px; font-weight: 700; line-height: 1; color: #fff; }
.grade-letter { font-size: 12px; color: var(--muted); margin-top: 4px; }

.grade-metrics {
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex: 1;
}

.metric-row-inline {
  display: flex;
  justify-content: space-between;
  font-size: 14px;
}

.metric-row-inline span { color: var(--muted); }
.risk-text { color: #f43f5e; }

.hero-summary {
  padding: 12px;
  border-radius: 14px;
  border: 1px solid rgba(255,255,255,0.06);
  background: rgba(255,255,255,0.03);
}

.hero-summary-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.hero-summary-head strong {
  color: #fff;
  font-size: 14px;
  line-height: 1.5;
}

.hero-summary-badge {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(16,185,129,0.1);
  border: 1px solid rgba(16,185,129,0.2);
  color: #86efac;
  font-size: 11px;
  white-space: nowrap;
}

.hero-summary-copy {
  margin: 10px 0 0;
  font-size: 13px;
  line-height: 1.6;
  color: #cbd5e1;
}

.watch-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-top: 14px;
}

.watch-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px;
  border-radius: 10px;
  background: rgba(0,0,0,0.18);
  border: 1px solid rgba(255,255,255,0.05);
}

.watch-card span {
  color: var(--muted);
  font-size: 11px;
}

.watch-card strong {
  color: #fff;
  font-size: 16px;
}

.subtle-band {
  background: transparent;
  border: none;
  border-bottom: 1px solid rgba(255,255,255,0.05);
  border-radius: 0;
  padding: 12px 0;
}

/* Actions Panel */
.support-panel {
  padding: 16px;
  border-radius: 18px;
  min-height: 180px;
}

.panel-sm-title {
  font-size: 13px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--muted);
  margin: 0 0 14px;
  padding-bottom: 10px;
  border-bottom: 1px solid rgba(255,255,255,0.05);
  flex-shrink: 0;
}

.action-item {
  padding: 12px 14px;
  border-radius: 10px;
  border: 1px solid rgba(255,255,255,0.05);
  margin-bottom: 8px;
  background: rgba(255, 255, 255, 0.02);
}

.action-head { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.priority-dot { width: 10px; height: 10px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 10px var(--accent); }
.action-item h4 { margin: 0; font-size: 16px; font-weight: 500; color: #fff; }
.action-desc { margin: 0; font-size: 13px; color: var(--muted); line-height: 1.6; }
.action-next { margin: 10px 0 0; font-size: 12px; line-height: 1.6; color: #cbd5e1; }

/* Right Col Layout */
.charts-row {
  display: grid;
  grid-template-columns: 1fr;
  gap: 16px;
  flex: 0 0 236px;
}

.chart-container {
  border-radius: 18px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

:deep(.chart-panel) {
  padding: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  background: transparent !important;
  border: none !important;
  min-height: 0;
}
:deep(.chart-root) {
  flex: 1;
  min-height: 200px !important;
}

.details-row {
  display: flex;
  gap: 16px;
}

.workflow-row {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.details-panel {
  flex: 1;
  padding: 16px;
  border-radius: 18px;
  min-height: 200px;
}
.details-panel::-webkit-scrollbar { width: 4px; }
.details-panel::-webkit-scrollbar-track { background: transparent; }
.details-panel::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 2px; }
.flex-2 { flex: 2; }

.workflow-panel {
  display: grid;
  gap: 16px;
}

.workflow-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.workflow-copy {
  display: grid;
  gap: 6px;
}

.workflow-title {
  margin: 0;
  font-size: 13px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
}

.workflow-caption,
.monitor-copy p,
.research-copy p,
.workflow-empty-state,
.workflow-stat-card small,
.runtime-pulse-card p,
.runtime-pulse-card small {
  margin: 0;
  color: var(--muted);
  line-height: 1.6;
}

.workflow-action {
  min-height: 38px;
  padding: 0 14px;
  border-radius: 10px;
  border: 1px solid rgba(16, 185, 129, 0.24);
  background: rgba(16, 185, 129, 0.1);
  color: #86efac;
  cursor: pointer;
  white-space: nowrap;
}

.workflow-action:disabled {
  opacity: 0.6;
  cursor: wait;
}

.monitor-banner,
.research-banner {
  display: flex;
  justify-content: space-between;
  gap: 14px;
  padding: 16px;
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.03);
}

.monitor-banner.is-tracked {
  border-color: rgba(16, 185, 129, 0.22);
  background: rgba(16, 185, 129, 0.08);
}

.monitor-banner.is-idle {
  border-color: rgba(148, 163, 184, 0.18);
}

.research-banner.tone-success {
  border-color: rgba(59, 130, 246, 0.22);
  background: rgba(59, 130, 246, 0.08);
}

.monitor-copy,
.research-copy {
  display: grid;
  gap: 6px;
}

.monitor-copy strong,
.research-copy strong,
.runtime-pulse-head strong {
  color: #f8fafc;
}

.workflow-stat-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.workflow-stat-card {
  display: grid;
  gap: 6px;
  padding: 14px;
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.025);
}

.workflow-stat-card span,
.document-stage-chip,
.runtime-pulse-head span {
  color: var(--muted);
  font-size: 12px;
}

.workflow-stat-card strong {
  color: #f8fafc;
  font-size: 20px;
}

.workflow-stat-card.tone-risk {
  border-color: rgba(251, 113, 133, 0.22);
  background: rgba(251, 113, 133, 0.08);
}

.workflow-stat-card.tone-warning {
  border-color: rgba(245, 158, 11, 0.22);
  background: rgba(245, 158, 11, 0.08);
}

.workflow-stat-card.tone-success {
  border-color: rgba(16, 185, 129, 0.22);
  background: rgba(16, 185, 129, 0.08);
}

.workflow-stat-card.tone-accent {
  border-color: rgba(59, 130, 246, 0.22);
  background: rgba(59, 130, 246, 0.08);
}

.document-stage-row,
.workflow-links {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.document-stage-chip {
  padding: 6px 10px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.04);
}

.runtime-pulse-list {
  display: grid;
  gap: 12px;
}

.runtime-pulse-card {
  display: grid;
  gap: 8px;
  padding: 14px;
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.025);
}

.runtime-pulse-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
}

.runtime-pulse-head span.tone-success {
  color: #86efac;
}

.runtime-pulse-head span.tone-accent {
  color: #93c5fd;
}

.runtime-pulse-head span.tone-risk {
  color: #fda4af;
}

.runtime-pulse-meter {
  width: 100%;
  height: 6px;
  border-radius: 999px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.05);
}

.runtime-pulse-meter i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, rgba(16, 185, 129, 0.9), rgba(59, 130, 246, 0.9));
}

.workflow-empty-state {
  padding: 14px;
  border-radius: 14px;
  border: 1px dashed rgba(255, 255, 255, 0.12);
}

.timeline-stack { display: flex; flex-direction: column; gap: 8px; }
.timeline-card {
  padding: 12px;
  border-radius: 10px;
  border: 1px solid rgba(255,255,255,0.05);
}
.tc-head { display: flex; justify-content: space-between; margin-bottom: 4px; align-items: center; }
.tc-period { font-size: 13px; color: var(--muted); }
.tc-grade { font-size: 14px; color: var(--accent); }
.tc-metrics { display: flex; justify-content: space-between; font-size: 12px; color: #718096; }

.metrics-grid-compact {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.metric-glance {
  padding: 14px;
  border-radius: 12px;
  border: 1px solid rgba(255,255,255,0.05);
  display: flex;
  flex-direction: column;
  gap: 10px;
  background: rgba(255, 255, 255, 0.02);
}

.mg-head { display: flex; justify-content: space-between; align-items: center; font-size: 13px; font-family: 'JetBrains Mono', monospace; }
.mg-code { color: #e5edf7; font-family: inherit; font-size: 14px; }
.mg-val { color: var(--accent); background: rgba(16,185,129,0.1); padding: 4px 8px; border-radius: 6px; }

.inline-glass-link {
  font-size: 13px;
  padding: 6px 14px;
  border-radius: 6px;
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.1);
  color: var(--muted);
  text-decoration: none;
  transition: all 0.2s;
}
.inline-glass-link:hover {
  background: rgba(16,185,129,0.1);
  border-color: rgba(16,185,129,0.3);
  color: #10b981;
}
.mg-links { display: flex; gap: 6px; margin-top: auto; }

@media (max-width: 1180px) {
  .dashboard-grid {
    grid-template-columns: 1fr;
  }

  .details-row {
    flex-direction: column;
  }
}

@media (max-width: 1100px) {
  .watch-grid,
  .metrics-grid-compact,
  .workflow-stat-grid,
  .workflow-row {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 960px) {
  .control-bar,
  .control-fields {
    flex-direction: column;
    align-items: stretch;
  }

  .glass-select {
    width: 100%;
    min-width: 0;
  }

  .workflow-head,
  .monitor-banner,
  .research-banner {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
