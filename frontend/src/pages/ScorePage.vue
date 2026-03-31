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

const companies = ref<string[]>([])
const selectedCompany = ref('')
const selectedPeriod = ref<string>('')
const scoreState = useAsyncState<any>()
const timelineState = useAsyncState<any>()
const companyState = useAsyncState<any>()
const route = useRoute()
const syncingFromRoute = ref(false)

const scoreCommandSurface = computed(() => scoreState.data.value?.score_command_surface || null)
const scoreSignalTape = computed(() => scoreState.data.value?.score_signal_tape || [])
const scoreWatchItems = computed(() => scoreCommandSurface.value?.watch_items || [])
const dominantSignal = computed(() => scoreCommandSurface.value?.dominant_signal || null)
const scorePrimaryActions = computed(() => scoreState.data.value?.action_cards?.slice(0, 3) || [])
const scoreTagGroups = computed(() => ({
  risks: scoreState.data.value?.scorecard?.risk_labels?.slice(0, 4) || [],
  opportunities: scoreState.data.value?.scorecard?.opportunity_labels?.slice(0, 3) || [],
}))

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
  const query = new URLSearchParams({ company_name: selectedCompany.value })
  if (selectedPeriod.value) {
    query.set('report_period', selectedPeriod.value)
  }
  await companyState.execute(() =>
    get<any>(`/company/workspace?${query.toString()}`),
  )
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
    selectedPeriod.value = scoreState.data.value?.report_period || ''
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
    selectedPeriod.value = scoreState.data.value?.report_period || ''
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
        selectedPeriod.value = scoreState.data.value?.report_period || ''
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
</script>

<template>
  <AppShell title="企业运营体检">
    <div class="dashboard-wrapper">
      <!-- Top Control Bar -->
      <section class="glass-panel control-bar">
        <div class="control-left">
          <div class="mode-query-icon glow-icon">体</div>
          <div class="mode-query-copy">
            <h3 class="company-name text-gradient">{{ selectedCompany }}</h3>
          </div>
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
                v-for="period in scoreState.data.value?.available_periods || []"
                :key="period"
                :value="period"
              >
                {{ period }}
              </option>
            </select>
          </label>
          <button class="button-primary glow-button" @click="loadScore">刷新诊断</button>
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
              <div class="eyebrow">当前结论</div>
              <h2 class="hero-title compact">{{ scoreState.data.value.company_name }}</h2>
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
                  <strong class="text-gradient">{{ scoreState.data.value.scorecard.subindustry_percentile }}pct</strong>
                </div>
                <div class="metric-row-inline">
                  <span>总风险</span>
                  <strong class="risk-text">{{ scoreState.data.value.scorecard.risk_labels.length }}项</strong>
                </div>
              </div>
            </div>

            <div v-if="scoreCommandSurface" class="hero-summary">
              <div class="hero-summary-head">
                <strong>{{ scoreCommandSurface.headline }}</strong>
                <span class="hero-summary-badge">{{ scoreCommandSurface.metric }} · {{ scoreCommandSurface.delta_label }}</span>
              </div>
              <p v-if="dominantSignal" class="hero-summary-copy">
                当前主判断：{{ dominantSignal.value }}
              </p>
              <div v-if="scoreWatchItems.length" class="watch-grid">
                <div
                  v-for="item in scoreWatchItems"
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
                v-for="item in scoreSignalTape"
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
            <h3 class="panel-sm-title">优先动作与标签</h3>
            <div class="tag-row compact-tags">
              <TagPill
                v-for="label in scoreTagGroups.risks"
                :key="label.code"
                :label="label.name"
                tone="risk"
              />
              <TagPill
                v-for="label in scoreTagGroups.opportunities"
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
            <div v-for="chart in scoreState.data.value.charts" :key="chart.title" class="glass-panel chart-container">
              <ChartPanel :title="chart.title" :options="chart.options" />
            </div>
          </div>

          <!-- Bottom Row: Timeline & Details -->
          <div class="details-row">
            <!-- Timeline Snapshots -->
            <article class="glass-panel details-panel scroll-area" v-if="timelineState.data.value">
              <h3 class="panel-sm-title">阶段轨迹</h3>
              <div class="timeline-stack">
                <div
                  v-for="item in timelineState.data.value.snapshots.slice(0, 4)"
                  :key="item.report_period"
                  class="timeline-card glass-panel-hover"
                >
                  <div class="tc-head">
                    <span class="tc-period">{{ item.report_period }}</span>
                    <strong class="tc-grade">{{ item.grade }} ({{ item.total_score }}分)</strong>
                  </div>
                  <div class="tc-metrics">
                    <span>风险: {{ item.risk_count }}</span>
                    <span>增速: {{ item.revenue_growth ?? '--' }}</span>
                  </div>
                </div>
              </div>
            </article>

            <!-- Key Metrics Highlights -->
            <article class="glass-panel details-panel scroll-area flex-2">
              <h3 class="panel-sm-title">重点指标探测</h3>
              <div class="metrics-grid-compact">
                <div
                  v-for="card in scoreState.data.value.label_cards.slice(0, 4)"
                  :key="card.code"
                  class="metric-glance glass-panel-hover"
                >
                  <div class="mg-head">
                    <span class="mg-code">{{ card.code }}</span>
                    <span class="mg-val">{{ card.signal_values[0] }}</span>
                  </div>
                  <h4 class="mg-title">{{ card.name }}</h4>
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
}

/* Control Bar */
.control-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 24px;
  border-radius: 16px;
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
  font-size: 20px;
  font-weight: 600;
  color: var(--accent);
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
  grid-template-columns: 360px 1fr;
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
  padding: 20px;
  border-radius: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  flex-shrink: 0;
}

.grade-display {
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 16px;
  background: rgba(0,0,0,0.2);
  border-radius: 16px;
  border: 1px solid rgba(255,255,255,0.05);
}

.grade-circle {
  width: 80px;
  height: 80px;
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

.grade-score { font-size: 24px; font-weight: 700; line-height: 1; color: #fff; }
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
  padding: 16px;
  border-radius: 16px;
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
  font-size: 15px;
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
  padding: 12px;
  border-radius: 12px;
  background: rgba(0,0,0,0.18);
  border: 1px solid rgba(255,255,255,0.05);
}

.watch-card span {
  color: var(--muted);
  font-size: 11px;
}

.watch-card strong {
  color: #fff;
  font-size: 18px;
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
  padding: 20px;
  border-radius: 20px;
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
  padding: 12px 16px;
  border-radius: 10px;
  border: 1px solid rgba(255,255,255,0.05);
  margin-bottom: 8px;
  background: rgba(255, 255, 255, 0.02);
}

.action-head { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.priority-dot { width: 10px; height: 10px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 10px var(--accent); }
.action-item h4 { margin: 0; font-size: 16px; font-weight: 500; color: #fff; }
.action-desc { margin: 0; font-size: 14px; color: var(--muted); line-height: 1.6; }
.action-next { margin: 10px 0 0; font-size: 12px; line-height: 1.6; color: #cbd5e1; }

/* Right Col Layout */
.charts-row {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
  flex: 0 0 260px;
}

.chart-container {
  border-radius: 20px;
  padding: 16px;
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

.details-panel {
  flex: 1;
  padding: 20px;
  border-radius: 20px;
  min-height: 200px;
}
.details-panel::-webkit-scrollbar { width: 4px; }

@media (max-width: 1100px) {
  .watch-grid { grid-template-columns: 1fr; }
}
.details-panel::-webkit-scrollbar-track { background: transparent; }
.details-panel::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 2px; }
.flex-2 { flex: 2; }

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
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
}

.metric-glance {
  padding: 18px;
  border-radius: 14px;
  border: 1px solid rgba(255,255,255,0.05);
  display: flex;
  flex-direction: column;
  gap: 12px;
  background: rgba(255, 255, 255, 0.02);
}

.mg-head { display: flex; justify-content: space-between; align-items: center; font-size: 13px; font-family: 'JetBrains Mono', monospace; }
.mg-code { color: var(--muted); background: rgba(0,0,0,0.3); padding: 4px 8px; border-radius: 6px; }
.mg-val { color: var(--accent); background: rgba(16,185,129,0.1); padding: 4px 8px; border-radius: 6px; }
.mg-title { margin: 0; font-size: 16px; font-weight: 500; color: #fff;}

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
</style>
