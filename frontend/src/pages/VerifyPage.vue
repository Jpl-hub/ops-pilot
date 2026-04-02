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
const reports = ref<any[]>([])
const selectedCompany = ref('')
const selectedPeriod = ref('')
const selectedReportTitle = ref<string | null>(null)
const state = useAsyncState<any>()
const route = useRoute()
const syncingFromRoute = ref(false)
const verifyCommandSurface = ref<any | null>(null)
const verifyDeltaTape = ref<any[]>([])
const availablePeriods = ref<string[]>([])
const reportStatusMessage = ref('')
const reportCatalogReady = ref(false)
const verifyWatchItems = computed(() => verifyCommandSurface.value?.watch_items?.slice(0, 2) || [])
const verifyDominantSignal = computed(() => verifyCommandSurface.value?.dominant_signal || null)
const verifyPrimaryClaims = computed(() => state.data.value?.claim_cards?.slice(0, 3) || [])
const verifyPrimaryInsights = computed(() => state.data.value?.research_compare?.insights?.slice(0, 3) || [])
const verifyCompareRows = computed(() => state.data.value?.research_compare?.rows?.slice(0, 2) || [])
const verifyCharts = computed(() => state.data.value?.charts?.slice(0, 1) || state.data.value?.research_compare?.charts?.slice(0, 1) || [])
const verifyDeltaItems = computed(() => verifyDeltaTape.value.slice(0, 3))
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

function displayClaimStatus(status?: string) {
  const map: Record<string, string> = {
    match: '一致',
    mismatch: '不一致',
    partial: '部分一致',
    review: '待复核',
  }
  return map[(status || '').toLowerCase()] || '待复核'
}

function claimTone(status?: string) {
  return (status || '').toLowerCase() === 'match' ? 'success' : 'risk'
}

async function loadCompanies() {
  const data = await get<any>('/workspace/companies')
  companies.value = data.companies
  availablePeriods.value = data.available_periods || []
  const preferredPeriod = data.preferred_period
  selectedPeriod.value = selectedPeriod.value || (
    typeof preferredPeriod === 'string'
      ? preferredPeriod
      : String(preferredPeriod?.value || preferredPeriod?.period || preferredPeriod?.report_period || preferredPeriod?.label || '')
  ) || ''
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
    reportStatusMessage.value = error instanceof Error ? error.message : '当前公司暂无可核验研报。'
  }
  reportCatalogReady.value = true
}

async function loadVerify() {
  if (!selectedCompany.value || !selectedReportTitle.value) {
    state.data.value = null
    state.error.value = null
    state.loading.value = false
    return
  }
  await state.execute(() =>
    post('/claim/verify', {
      company_name: selectedCompany.value,
      report_period: selectedPeriod.value || null,
      report_title: selectedReportTitle.value,
    }),
  )
  verifyCommandSurface.value = state.data.value?.verify_command_surface || null
  verifyDeltaTape.value = state.data.value?.verify_delta_tape || []
}

function applyQuerySelection() {
  const company = typeof route.query.company === 'string' ? route.query.company : ''
  const reportTitle = typeof route.query.report_title === 'string' ? route.query.report_title : ''
  syncingFromRoute.value = true
  if (company && companies.value.includes(company)) {
    selectedCompany.value = company
  }
  if (reportTitle && reports.value.some((item) => item.title === reportTitle)) {
    selectedReportTitle.value = reportTitle
  }
  syncingFromRoute.value = false
}

onMounted(async () => {
  await loadCompanies()
  if (!selectedCompany.value) {
    selectedCompany.value = companies.value[0] || ''
  }
  await loadReports()
  applyQuerySelection()
  await loadVerify()
})

watch(selectedCompany, async (_, oldValue) => {
  if (syncingFromRoute.value) {
    return
  }
  if (oldValue && selectedCompany.value !== oldValue) {
    await loadReports()
    await loadVerify()
  }
})

watch(selectedPeriod, async (value, oldValue) => {
  if (syncingFromRoute.value) {
    return
  }
  if (value !== oldValue) {
    await loadVerify()
  }
})

watch(selectedReportTitle, async (value, oldValue) => {
  if (syncingFromRoute.value) {
    return
  }
  if (value && value !== oldValue) {
    await loadVerify()
  }
})

watch(
  () => [route.query.company, route.query.report_title],
  async ([companyQuery, reportTitleQuery]) => {
    const company = typeof companyQuery === 'string' ? companyQuery : ''
    const reportTitle = typeof reportTitleQuery === 'string' ? reportTitleQuery : ''
    if (company && company !== selectedCompany.value && companies.value.includes(company)) {
      syncingFromRoute.value = true
      selectedCompany.value = company
      syncingFromRoute.value = false
      await loadReports()
      if (reportTitle && reports.value.some((item) => item.title === reportTitle)) {
        syncingFromRoute.value = true
        selectedReportTitle.value = reportTitle
        syncingFromRoute.value = false
      }
      await loadVerify()
      return
    }
    if (reportTitle && reportTitle !== selectedReportTitle.value && reports.value.some((item) => item.title === reportTitle)) {
      syncingFromRoute.value = true
      selectedReportTitle.value = reportTitle
      syncingFromRoute.value = false
      await loadVerify()
    }
  },
)
</script>

<template>
  <AppShell title="">
    <div class="dashboard-wrapper">
      
      <!-- Top Control Bar -->
      <section class="glass-panel control-bar">
        <div class="control-left">
          <div class="mode-query-icon glow-icon">核</div>
          <div class="mode-query-copy">
            <span class="control-kicker">观点核对</span>
            <h3 class="company-name text-gradient">{{ selectedCompany || '观点核验' }}</h3>
            <p class="control-meta">{{ selectedReportTitle || '选择一篇研报开始核对' }}<span v-if="selectedPeriod"> · {{ selectedPeriod }}</span></p>
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
            <span class="subtle-label">报期</span>
            <select v-model="selectedPeriod" class="glass-select">
              <option value="">默认主周期</option>
              <option v-for="period in periodOptions" :key="period.value" :value="period.value">{{ period.label }}</option>
            </select>
          </label>
          <label class="field inline-field">
            <span class="subtle-label">研报</span>
            <select v-model="selectedReportTitle" class="glass-select" style="max-width:300px;">
              <option v-for="report in reports" :key="report.title" :value="report.title">{{ report.title }} | {{ report.publish_date }}</option>
            </select>
          </label>
          <button class="button-primary glow-button" @click="loadVerify">重新核对</button>
        </div>
      </section>

      <LoadingState v-if="state.loading.value" class="state-container" />
      <ErrorState v-else-if="state.error.value" :message="state.error.value" class="state-container" />
      <section v-else-if="!selectedCompany" class="glass-panel empty-panel">
        <div class="empty-content">
          <h3 class="text-gradient mb-2">公司池为空</h3>
          <p class="muted">当前环境还没有可核验的企业，请先完成正式公司池和研报数据接入。</p>
        </div>
      </section>
      
      <section v-else-if="reportCatalogReady && reports.length === 0" class="glass-panel empty-panel">
        <div class="empty-content">
          <h3 class="text-gradient mb-2">研报缺失</h3>
          <p class="muted">{{ reportStatusMessage || '当前公司没有可供核验的结构化报告。' }}</p>
        </div>
      </section>

      <!-- Main Dashboard Grid -->
      <div v-else-if="state.data.value" class="dashboard-grid">
        
        <!-- Left Column: Core Verification Grade -->
        <div class="dashboard-col left-col">
          <article class="glass-panel score-hero-panel">
            <div class="hero-top">
              <div class="eyebrow">当前对象</div>
              <h2 class="hero-title compact">{{ state.data.value.report_meta.title }}</h2>
              <p class="hero-text text-sm muted">
                {{ state.data.value.report_meta.publish_date }} · {{ state.data.value.report_meta.source_name }}
              </p>
            </div>
            
            <div class="grade-display" v-if="verifyCommandSurface">
              <div class="grade-circle" :data-grade="verifyCommandSurface.metric">
                <span class="grade-score text-gradient">{{ verifyCommandSurface.metric }}</span>
                <span class="grade-letter muted">核验度</span>
              </div>
              <div class="grade-metrics">
                <div class="metric-row-inline">
                  <span>核对条目</span>
                  <strong class="text-accent">{{ state.data.value.claim_cards.length }} 项</strong>
                </div>
                <div class="metric-row-inline">
                  <span>有分歧</span>
                  <strong class="risk-text">{{ state.data.value.key_numbers[1].value }}</strong>
                </div>
                <div class="metric-row-inline mt-2">
                  <a class="inline-glass-link" :href="state.data.value.report_meta.source_url" target="_blank" rel="noreferrer" style="flex:1; text-align:center;">查看原文</a>
                  <a class="inline-glass-link" v-if="state.data.value.report_meta.attachment_url" :href="state.data.value.report_meta.attachment_url" target="_blank" rel="noreferrer" style="flex:1; text-align:center;">原文附件</a>
                </div>
              </div>
            </div>

            <div v-if="verifyCommandSurface" class="hero-summary">
              <div class="hero-summary-head">
                <strong>{{ verifyCommandSurface.headline }}</strong>
                <span class="hero-summary-badge">{{ verifyCommandSurface.institution }}</span>
              </div>
              <p v-if="verifyDominantSignal" class="hero-summary-copy">
                当前核验焦点：{{ verifyDominantSignal.value }}
              </p>
              <div v-if="verifyWatchItems.length" class="watch-grid">
                <div
                  v-for="item in verifyWatchItems"
                  :key="item.label"
                  class="watch-card"
                >
                  <span>{{ item.label }}</span>
                  <strong>{{ item.value }}</strong>
                </div>
              </div>
            </div>

            <!-- Signal Tape -->
            <div class="signal-tape scroll-area" v-if="verifyDeltaItems.length">
              <div
                v-for="item in verifyDeltaItems"
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
          
          <article class="glass-panel support-panel mt-4">
            <h3 class="panel-sm-title">先看哪几处不一致</h3>
            <div v-if="verifyPrimaryInsights.length" class="insight-list">
              <div
                v-for="insight in verifyPrimaryInsights"
                :key="insight.title"
                class="insight-row"
              >
                <strong>{{ insight.title }}</strong>
                <p class="muted">{{ insight.detail || '这条说法需要回到财报原文继续核对。' }}</p>
              </div>
            </div>
            <p v-else class="muted">这篇研报暂时没有明显分歧，继续逐条对照关键数据即可。</p>
            
            <div class="compare-list mt-4">
               <div
                  v-for="row in verifyCompareRows"
                  :key="row.title + row.publish_date"
                  class="compare-item glass-panel-hover"
               >
                 <div class="ci-head">
                   <strong class="ci-source">{{ row.source_name }}</strong>
                   <span class="ci-date muted">{{ row.publish_date }}</span>
                 </div>
                 <h4 class="ci-title">{{ row.title }}</h4>
                 <div class="ci-metrics">
                   <span>评级 <strong :class="row.rating_text.includes('买入') ? 'text-accent' : ''">{{ row.rating_text }}</strong></span>
                   <span>目标价 <strong>{{ row.target_price ?? '--' }}</strong></span>
                 </div>
               </div>
            </div>
          </article>
        </div>

        <!-- Right Column: Verification Details & Charts -->
        <div class="dashboard-col right-col">
          
          <!-- Top Row: Charts -->
          <div v-if="verifyCharts.length" class="charts-row mb-4">
            <div v-for="chart in verifyCharts" :key="chart.title" class="glass-panel chart-container">
              <ChartPanel :title="chart.title" :options="chart.options" />
            </div>
          </div>

          <!-- Bottom Row: Claim Cards List -->
          <div class="glass-panel details-panel scroll-area flex-1">
            <h3 class="panel-sm-title mb-4">逐条对照</h3>
            
            <div class="claims-grid">
              <div
                v-for="(card, idx) in verifyPrimaryClaims"
                :key="card.claim_id"
                class="claim-card glass-panel-hover"
              >
                <div class="cc-head">
                  <div class="cc-code">条目 {{ String(idx + 1).padStart(2, '0') }}</div>
                  <TagPill :label="displayClaimStatus(card.status)" :tone="claimTone(card.status)" />
                </div>
                <h4 class="cc-title">{{ card.label }}</h4>
                <div class="cc-vs">
                  <div class="vs-col">
                    <span class="muted">研报写法</span>
                    <strong class="text-accent">{{ card.claimed_value }}</strong>
                  </div>
                  <div class="vs-vs">对照</div>
                  <div class="vs-col text-right">
                    <span class="muted">财报原文</span>
                    <strong :class="card.status === 'match' ? 'text-accent' : 'risk-text'">{{ card.actual_value }}</strong>
                  </div>
                </div>
                
                <div class="cc-links mt-3 border-t-subtle pt-3">
                  <RouterLink class="inline-glass-link" :to="buildEvidenceLink(card.research_chunk_id, card.label, [card.label])">研报原文</RouterLink>
                  <RouterLink
                    v-for="item in card.evidence_refs"
                    :key="item"
                    class="inline-glass-link"
                    :to="buildEvidenceLink(item, card.label, [card.label])"
                  >
                    财报出处
                  </RouterLink>
                </div>
              </div>
            </div>

          </div>
        </div>

      </div>
    </div>
  </AppShell>
</template>

<style scoped>
.dashboard-wrapper { display: flex; flex-direction: column; gap: 16px; height: 100%; overflow: hidden; width: 100%; max-width: 1320px; margin: 0 auto; }
.control-bar { display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; border-radius: 14px; flex-shrink: 0; }
.control-left { display: flex; align-items: center; gap: 16px; }
.glow-icon { width: 40px; height: 40px; border-radius: 12px; background: rgba(59, 130, 246, 0.15); border: 1px solid rgba(59, 130, 246, 0.4); color: #3b82f6; display: grid; place-items: center; font-weight: bold; font-size: 18px; box-shadow: 0 0 15px rgba(59, 130, 246, 0.2); }
.company-name { margin: 0; font-size: 18px; font-weight: 600; color: #60a5fa; }
.control-kicker { font-family: 'JetBrains Mono', monospace; font-size: 10px; letter-spacing: 0.16em; text-transform: uppercase; color: var(--muted); }
.control-meta { margin: 2px 0 0; font-size: 12px; color: var(--muted); }
.text-gradient { background-clip: text; -webkit-text-fill-color: transparent; background-image: linear-gradient(to right, #60a5fa, #34d399); }
.inline-context { display: flex; align-items: center; gap: 16px; }
.inline-field { display: flex; align-items: center; gap: 8px; min-width: unset; }
.subtle-label { font-size: 12px; color: var(--muted); text-transform: uppercase; }
.glass-select { background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1); min-height: 36px; padding: 0 12px; border-radius: 8px; color: #fff; max-width: max-content; }
.glow-button { min-height: 36px; border-radius: 8px; box-shadow: 0 0 15px rgba(59, 130, 246, 0.2); }
.empty-panel { display: grid; place-items: center; flex: 1; border-radius: 20px; }
.empty-content { text-align: center; }

/* Dashboard Grid */
.dashboard-grid { display: grid; grid-template-columns: 320px 1fr; gap: 16px; flex: 1; min-height: 0; }
.dashboard-col { display: flex; flex-direction: column; gap: 16px; min-height: 0; overflow-y: auto; overflow-x: hidden; }
.dashboard-col::-webkit-scrollbar { width: 4px; }
.dashboard-col::-webkit-scrollbar-track { background: transparent; }
.dashboard-col::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 2px; }
.scroll-area { overflow-y: auto; }

/* Score Hero (Left) */
.score-hero-panel { padding: 16px; border-radius: 18px; display: flex; flex-direction: column; gap: 14px; }
.grade-display { display: flex; align-items: center; gap: 18px; padding: 14px; background: rgba(0,0,0,0.2); border-radius: 14px; border: 1px solid rgba(255,255,255,0.05); }
.grade-circle { width: 68px; height: 68px; border-radius: 50%; display: flex; flex-direction: column; align-items: center; justify-content: center; border: 2px solid #3b82f6; box-shadow: 0 0 20px rgba(59, 130, 246, 0.2); }
.grade-score { font-size: 18px; font-weight: 700; line-height: 1; }
.grade-letter { font-size: 11px; margin-top: 4px; }
.grade-metrics { display: flex; flex-direction: column; gap: 6px; flex: 1; }
.metric-row-inline { display: flex; justify-content: space-between; font-size: 13px; align-items: center; }
.text-accent { color: #10b981; }
.risk-text { color: #f43f5e; }
.subtle-band { border-bottom: 1px solid rgba(255,255,255,0.05); padding: 12px 0; }
.hero-summary { display: flex; flex-direction: column; gap: 14px; padding: 14px 16px; border-radius: 14px; background: rgba(12, 18, 32, 0.72); border: 1px solid rgba(148, 163, 184, 0.16); }
.hero-summary-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.hero-summary-head strong { font-size: 14px; line-height: 1.5; color: #f8fafc; }
.hero-summary-badge { flex-shrink: 0; padding: 6px 10px; border-radius: 999px; background: rgba(16, 185, 129, 0.12); border: 1px solid rgba(16, 185, 129, 0.3); color: #6ee7b7; font-size: 12px; }
.hero-summary-copy { margin: 0; font-size: 13px; line-height: 1.7; color: #cbd5e1; }
.watch-grid { display: grid; grid-template-columns: 1fr; gap: 10px; }
.watch-card { display: flex; flex-direction: column; gap: 6px; padding: 10px 12px; border-radius: 12px; background: rgba(15, 23, 42, 0.72); border: 1px solid rgba(148, 163, 184, 0.14); }
.watch-card span { font-size: 11px; letter-spacing: 0.04em; color: #94a3b8; }
.watch-card strong { font-size: 14px; color: #f8fafc; line-height: 1.4; }

/* Support Panel */
.panel-sm-title { font-size: 13px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); margin: 0 0 12px; padding-bottom: 8px; border-bottom: 1px solid rgba(255,255,255,0.05); }
.support-panel { padding: 16px; border-radius: 18px; }
.insight-list { display: grid; gap: 10px; }
.insight-row { padding: 12px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.06); background: rgba(255,255,255,0.02); display: grid; gap: 6px; }
.insight-row strong { color: #f8fafc; font-size: 14px; line-height: 1.45; }
.insight-row p { margin: 0; font-size: 12px; line-height: 1.6; }
.compare-list { display: flex; flex-direction: column; gap: 10px; max-height: none; overflow: visible; }
.compare-item { padding: 12px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.05); }
.ci-head { display: flex; justify-content: space-between; font-size: 11px; margin-bottom: 6px; }
.ci-source { color: #818cf8; }
.ci-title { font-size: 14px; margin: 0 0 8px; color: #fff; line-height: 1.4; }
.ci-metrics { display: flex; justify-content: space-between; font-size: 12px; color: #94a3b8; }

/* Charts & Details  */
.charts-row { display: grid; grid-template-columns: 1fr; gap: 16px; flex: 0 0 244px; flex-shrink: 0; }
.chart-container { border-radius: 18px; padding: 14px; display: flex; flex-direction: column; min-height: 0; }
:deep(.chart-panel) { padding: 0; flex: 1; display: flex; flex-direction: column; background: transparent !important; border: none !important; min-height: 0; }
:deep(.chart-root) { flex: 1; min-height: 200px !important; }

.details-panel { padding: 16px; border-radius: 18px; }
.claims-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 14px; }
.claim-card { padding: 13px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.05); display: flex; flex-direction: column; }
.cc-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.cc-code { font-size: 11px; font-family: 'JetBrains Mono', monospace; color: var(--muted); background: rgba(0,0,0,0.3); padding: 2px 6px; border-radius: 4px; }
.cc-title { margin: 0 0 12px; font-size: 15px; font-weight: 500; color: #f8fafc; }
.cc-vs { display: flex; align-items: center; justify-content: space-between; background: rgba(0,0,0,0.2); padding: 10px 14px; border-radius: 10px; font-size: 13px; }
.vs-col { display: flex; flex-direction: column; gap: 4px; }
.vs-vs { font-size: 10px; font-weight: bold; color: rgba(255,255,255,0.2); }
.text-right { text-align: right; }
.cc-links { display: flex; gap: 8px; flex-wrap: wrap; }
.border-t-subtle { border-top: 1px solid rgba(255,255,255,0.05); }
.inline-glass-link { font-size: 11px; padding: 6px 12px; border-radius: 6px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); color: var(--muted); text-decoration: none; transition: all 0.2s; }
.inline-glass-link:hover { background: rgba(59, 130, 246, 0.1); border-color: rgba(59, 130, 246, 0.3); color: #60a5fa; }

@media (max-width: 1280px) {
  .dashboard-grid { grid-template-columns: 1fr; }
  .charts-row { grid-template-columns: 1fr; flex-basis: auto; }
}

@media (max-width: 960px) {
  .control-bar,
  .inline-context { flex-direction: column; align-items: stretch; }
  .grade-display { flex-direction: column; align-items: stretch; }
  .watch-grid { grid-template-columns: 1fr; }
}
</style>
