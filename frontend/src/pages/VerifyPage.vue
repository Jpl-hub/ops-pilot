<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
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
const selectedCompany = ref('TCL中环')
const selectedReportTitle = ref<string | null>(null)
const state = useAsyncState<any>()
const route = useRoute()
const syncingFromRoute = ref(false)
const verifyCommandSurface = ref<any | null>(null)
const verifyDeltaTape = ref<any[]>([])

async function loadCompanies() {
  const data = await get<any>('/workspace/companies')
  companies.value = data.companies
}

async function loadReports() {
  try {
    const payload = await get<any>(`/company/research-reports?company_name=${encodeURIComponent(selectedCompany.value)}`)
    reports.value = payload.reports
    selectedReportTitle.value = reports.value[0]?.title ?? null
  } catch {
    reports.value = []
    selectedReportTitle.value = null
  }
}

async function loadVerify() {
  if (!selectedReportTitle.value) {
    state.data.value = null
    state.error.value = null
    state.loading.value = false
    return
  }
  await state.execute(() => post('/claim/verify', { company_name: selectedCompany.value, report_title: selectedReportTitle.value }))
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
  if (!companies.value.includes(selectedCompany.value)) {
    selectedCompany.value = companies.value[0]
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
  <AppShell title="研报观点核验">
    <div class="dashboard-wrapper">
      
      <!-- Top Control Bar -->
      <section class="glass-panel control-bar">
        <div class="control-left">
          <div class="mode-query-icon glow-icon">核</div>
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
            <span class="subtle-label">研报</span>
            <select v-model="selectedReportTitle" class="glass-select" style="max-width:300px;">
              <option v-for="report in reports" :key="report.title" :value="report.title">{{ report.title }} | {{ report.publish_date }}</option>
            </select>
          </label>
          <button class="button-primary glow-button" @click="loadVerify">刷新核验</button>
        </div>
      </section>

      <LoadingState v-if="state.loading.value" class="state-container" />
      <ErrorState v-else-if="state.error.value" :message="state.error.value" class="state-container" />
      
      <section v-else-if="reports.length === 0" class="glass-panel empty-panel">
        <div class="empty-content">
          <h3 class="text-gradient mb-2">研报缺失</h3>
          <p class="muted">当前公司没有可供核验的结构化报告。</p>
        </div>
      </section>

      <!-- Main Dashboard Grid -->
      <div v-else-if="state.data.value" class="dashboard-grid">
        
        <!-- Left Column: Core Verification Grade -->
        <div class="dashboard-col left-col">
          <article class="glass-panel score-hero-panel">
            <div class="hero-top">
              <div class="eyebrow">研报溯源与核卡</div>
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
                  <span>提取数据</span>
                  <strong class="text-accent">{{ state.data.value.claim_cards.length }} 项</strong>
                </div>
                <div class="metric-row-inline">
                  <span>事实偏差</span>
                  <strong class="risk-text">{{ state.data.value.key_numbers[1].value }}</strong>
                </div>
                <div class="metric-row-inline mt-2">
                  <a class="inline-glass-link" :href="state.data.value.report_meta.source_url" target="_blank" rel="noreferrer" style="flex:1; text-align:center;">查看原文</a>
                  <a class="inline-glass-link" v-if="state.data.value.report_meta.attachment_url" :href="state.data.value.report_meta.attachment_url" target="_blank" rel="noreferrer" style="flex:1; text-align:center;">原文附件</a>
                </div>
              </div>
            </div>

            <!-- Signal Tape -->
            <div class="signal-tape scroll-area" v-if="verifyDeltaTape && verifyDeltaTape.length">
              <div
                v-for="item in verifyDeltaTape"
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
          
          <article class="glass-panel support-panel scroll-area mt-4">
            <h3 class="panel-sm-title">机构分歧速览</h3>
            <div class="tag-row compact-tags">
              <TagPill
                v-for="insight in state.data.value.research_compare.insights"
                :key="insight.title"
                :label="insight.title"
                tone="risk"
              />
            </div>
            
            <div class="compare-list mt-4">
               <div
                  v-for="row in state.data.value.research_compare.rows.slice(0, 3)"
                  :key="row.title + row.publish_date"
                  class="compare-item glass-panel-hover"
               >
                 <div class="ci-head">
                   <strong class="ci-source">{{ row.source_name }}</strong>
                   <span class="ci-date muted">{{ row.publish_date }}</span>
                 </div>
                 <h4 class="ci-title">{{ row.title }}</h4>
                 <div class="ci-metrics">
                   <span>评级: <strong :class="row.rating_text.includes('买入') ? 'text-accent' : ''">{{ row.rating_text }}</strong></span>
                   <span>目标: <strong>{{ row.target_price ?? '--' }}</strong></span>
                 </div>
               </div>
            </div>
          </article>
        </div>

        <!-- Right Column: Verification Details & Charts -->
        <div class="dashboard-col right-col">
          
          <!-- Top Row: Charts -->
          <div class="charts-row mb-4">
            <div v-for="chart in state.data.value.charts" :key="chart.title" class="glass-panel chart-container">
              <ChartPanel :title="chart.title" :options="chart.options" />
            </div>
            <div v-for="chart in state.data.value.research_compare.charts" :key="`compare-${chart.title}`" class="glass-panel chart-container">
              <ChartPanel :title="chart.title" :options="chart.options" />
            </div>
          </div>

          <!-- Bottom Row: Claim Cards List -->
          <div class="glass-panel details-panel scroll-area flex-1">
            <h3 class="panel-sm-title mb-4">观点校验明细</h3>
            
            <div class="claims-grid">
              <div
                v-for="card in state.data.value.claim_cards"
                :key="card.claim_id"
                class="claim-card glass-panel-hover"
              >
                <div class="cc-head">
                  <div class="cc-code">{{ card.metric_key }}</div>
                  <TagPill :label="card.status" :tone="card.status === 'match' ? 'success' : 'risk'" />
                </div>
                <h4 class="cc-title">{{ card.label }}</h4>
                <div class="cc-vs">
                  <div class="vs-col">
                    <span class="muted">研报披露</span>
                    <strong class="text-accent">{{ card.claimed_value }}</strong>
                  </div>
                  <div class="vs-vs">VS</div>
                  <div class="vs-col text-right">
                    <span class="muted">财报回溯</span>
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
.dashboard-wrapper { display: flex; flex-direction: column; gap: 16px; height: 100%; overflow: hidden; }
.control-bar { display: flex; justify-content: space-between; align-items: center; padding: 16px 24px; border-radius: 16px; flex-shrink: 0; }
.control-left { display: flex; align-items: center; gap: 16px; }
.glow-icon { width: 40px; height: 40px; border-radius: 12px; background: rgba(59, 130, 246, 0.15); border: 1px solid rgba(59, 130, 246, 0.4); color: #3b82f6; display: grid; place-items: center; font-weight: bold; font-size: 18px; box-shadow: 0 0 15px rgba(59, 130, 246, 0.2); }
.company-name { margin: 0; font-size: 20px; font-weight: 600; color: #60a5fa; }
.text-gradient { background-clip: text; -webkit-text-fill-color: transparent; background-image: linear-gradient(to right, #60a5fa, #34d399); }
.inline-context { display: flex; align-items: center; gap: 16px; }
.inline-field { display: flex; align-items: center; gap: 8px; min-width: unset; }
.subtle-label { font-size: 12px; color: var(--muted); text-transform: uppercase; }
.glass-select { background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1); min-height: 36px; padding: 0 12px; border-radius: 8px; color: #fff; max-width: max-content; }
.glow-button { min-height: 36px; border-radius: 8px; box-shadow: 0 0 15px rgba(59, 130, 246, 0.2); }
.empty-panel { display: grid; place-items: center; flex: 1; border-radius: 20px; }
.empty-content { text-align: center; }

/* Dashboard Grid */
.dashboard-grid { display: grid; grid-template-columns: 360px 1fr; gap: 16px; flex: 1; min-height: 0; }
.dashboard-col { display: flex; flex-direction: column; gap: 16px; min-height: 0; overflow-y: auto; overflow-x: hidden; }
.dashboard-col::-webkit-scrollbar { width: 4px; }
.dashboard-col::-webkit-scrollbar-track { background: transparent; }
.dashboard-col::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 2px; }
.scroll-area { overflow-y: auto; }

/* Score Hero (Left) */
.score-hero-panel { padding: 24px; border-radius: 20px; display: flex; flex-direction: column; gap: 20px; }
.grade-display { display: flex; align-items: center; gap: 20px; padding: 16px; background: rgba(0,0,0,0.2); border-radius: 16px; border: 1px solid rgba(255,255,255,0.05); }
.grade-circle { width: 72px; height: 72px; border-radius: 50%; display: flex; flex-direction: column; align-items: center; justify-content: center; border: 2px solid #3b82f6; box-shadow: 0 0 20px rgba(59, 130, 246, 0.2); }
.grade-score { font-size: 20px; font-weight: 700; line-height: 1; }
.grade-letter { font-size: 11px; margin-top: 4px; }
.grade-metrics { display: flex; flex-direction: column; gap: 6px; flex: 1; }
.metric-row-inline { display: flex; justify-content: space-between; font-size: 13px; align-items: center; }
.text-accent { color: #10b981; }
.risk-text { color: #f43f5e; }
.subtle-band { border-bottom: 1px solid rgba(255,255,255,0.05); padding: 12px 0; }

/* Support Panel */
.panel-sm-title { font-size: 13px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); margin: 0 0 12px; padding-bottom: 8px; border-bottom: 1px solid rgba(255,255,255,0.05); }
.support-panel { padding: 20px; border-radius: 20px; }
.compare-list { display: flex; flex-direction: column; gap: 10px; }
.compare-item { padding: 12px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.05); }
.ci-head { display: flex; justify-content: space-between; font-size: 11px; margin-bottom: 6px; }
.ci-source { color: #818cf8; }
.ci-title { font-size: 14px; margin: 0 0 8px; color: #fff; line-height: 1.4; }
.ci-metrics { display: flex; justify-content: space-between; font-size: 12px; color: #94a3b8; }

/* Charts & Details  */
.charts-row { display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; flex: 0 0 260px; flex-shrink: 0; }
.chart-container { border-radius: 20px; padding: 16px; display: flex; flex-direction: column; min-height: 0; }
:deep(.chart-panel) { padding: 0; flex: 1; display: flex; flex-direction: column; background: transparent !important; border: none !important; min-height: 0; }
:deep(.chart-root) { flex: 1; min-height: 200px !important; }

.details-panel { padding: 24px; border-radius: 20px; }
.claims-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
.claim-card { padding: 16px; border-radius: 14px; border: 1px solid rgba(255,255,255,0.05); display: flex; flex-direction: column; }
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
</style>
