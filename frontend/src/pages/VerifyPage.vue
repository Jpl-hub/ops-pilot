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
const availablePeriods = ref<any[]>([])
const reportStatusMessage = ref('')
const reportCatalogReady = ref(false)

const verifyWatchItems = computed(() => verifyCommandSurface.value?.watch_items?.slice(0, 2) || [])
const verifyDominantSignal = computed(() => verifyCommandSurface.value?.dominant_signal || null)
const verifyPrimaryClaims = computed(() => state.data.value?.claim_cards?.slice(0, 4) || [])
const verifyPrimaryInsights = computed(() => state.data.value?.research_compare?.insights?.slice(0, 3) || [])
const verifyCompareRows = computed(() => state.data.value?.research_compare?.rows?.slice(0, 3) || [])
const verifyCharts = computed(() => state.data.value?.charts?.slice(0, 1) || state.data.value?.research_compare?.charts?.slice(0, 1) || [])
const verifyDeltaItems = computed(() => verifyDeltaTape.value.slice(0, 2))

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
  if (syncingFromRoute.value) return
  if (oldValue && selectedCompany.value !== oldValue) {
    await loadReports()
    await loadVerify()
  }
})

watch(selectedPeriod, async (value, oldValue) => {
  if (syncingFromRoute.value) return
  if (value !== oldValue) {
    await loadVerify()
  }
})

watch(selectedReportTitle, async (value, oldValue) => {
  if (syncingFromRoute.value) return
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
    <div class="verify-page">
      <section class="glass-panel control-bar">
        <div class="control-left">
          <div class="glow-icon">核</div>
          <div class="control-copy">
            <span class="control-kicker">观点核对</span>
            <h3 class="company-name text-gradient">{{ selectedCompany || '观点核验' }}</h3>
            <p class="control-meta">{{ selectedReportTitle || '选择一篇研报开始核对' }}<span v-if="selectedPeriod"> · {{ selectedPeriod }}</span></p>
          </div>
        </div>

        <div class="inline-context">
          <label class="inline-field">
            <span class="subtle-label">公司</span>
            <select v-model="selectedCompany" class="glass-select">
              <option v-for="company in companies" :key="company" :value="company">{{ company }}</option>
            </select>
          </label>
          <label class="inline-field">
            <span class="subtle-label">报期</span>
            <select v-model="selectedPeriod" class="glass-select">
              <option value="">默认主周期</option>
              <option v-for="period in periodOptions" :key="period.value" :value="period.value">{{ period.label }}</option>
            </select>
          </label>
          <label class="inline-field">
            <span class="subtle-label">研报</span>
            <select v-model="selectedReportTitle" class="glass-select report-select">
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
          <h3 class="text-gradient">公司池为空</h3>
          <p class="muted">当前环境还没有可核对的企业，请先完成正式公司池和研报数据接入。</p>
        </div>
      </section>

      <section v-else-if="reportCatalogReady && reports.length === 0" class="glass-panel empty-panel">
        <div class="empty-content">
          <h3 class="text-gradient">研报缺失</h3>
          <p class="muted">{{ reportStatusMessage || '当前公司没有可供核对的研报。' }}</p>
        </div>
      </section>

      <div v-else-if="state.data.value" class="verify-grid">
        <aside class="verify-sidebar">
          <article class="glass-panel sidebar-section">
            <div class="section-headline">
              <span class="section-kicker">当前研报</span>
              <h2>{{ state.data.value.report_meta.title }}</h2>
              <p class="muted">{{ state.data.value.report_meta.publish_date }} · {{ state.data.value.report_meta.source_name }}</p>
            </div>

            <div v-if="verifyCommandSurface" class="metric-strip">
              <div class="metric-pill">
                <span>核验度</span>
                <strong>{{ verifyCommandSurface.metric }}</strong>
              </div>
              <div class="metric-pill">
                <span>核对条目</span>
                <strong>{{ state.data.value.claim_cards.length }} 项</strong>
              </div>
              <div class="metric-pill">
                <span>有分歧</span>
                <strong class="risk-text">{{ state.data.value.key_numbers[1].value }}</strong>
              </div>
            </div>

            <p v-if="verifyCommandSurface?.headline" class="context-copy">{{ verifyCommandSurface.headline }}</p>
            <p v-if="verifyDominantSignal" class="context-copy muted">当前先看：{{ verifyDominantSignal.value }}</p>

            <div v-if="verifyWatchItems.length" class="watch-lines">
              <div v-for="item in verifyWatchItems" :key="item.label" class="watch-line">
                <span>{{ item.label }}</span>
                <strong>{{ item.value }}</strong>
              </div>
            </div>

            <div class="context-links">
              <a class="inline-glass-link" :href="state.data.value.report_meta.source_url" target="_blank" rel="noreferrer">查看原文</a>
              <a
                v-if="state.data.value.report_meta.attachment_url"
                class="inline-glass-link"
                :href="state.data.value.report_meta.attachment_url"
                target="_blank"
                rel="noreferrer"
              >
                原文附件
              </a>
            </div>
          </article>

          <article class="glass-panel sidebar-section">
            <div class="section-headline">
              <span class="section-kicker">先看分歧</span>
              <h3>这一轮先核哪几处</h3>
            </div>
            <div v-if="verifyPrimaryInsights.length" class="simple-list">
              <div v-for="insight in verifyPrimaryInsights" :key="insight.title" class="simple-row">
                <strong>{{ insight.title }}</strong>
                <p class="muted">{{ insight.detail || '这条说法需要回到财报原文继续核对。' }}</p>
              </div>
            </div>
            <p v-else class="muted">这篇研报暂时没有明显分歧，继续逐条回看关键数据即可。</p>
          </article>

          <article v-if="verifyCompareRows.length" class="glass-panel sidebar-section">
            <div class="section-headline">
              <span class="section-kicker">同类研报</span>
              <h3>最近还可以顺手看哪几篇</h3>
            </div>
            <div class="report-list">
              <div v-for="row in verifyCompareRows" :key="row.title + row.publish_date" class="report-row">
                <div class="report-row-head">
                  <strong>{{ row.source_name }}</strong>
                  <span class="muted">{{ row.publish_date }}</span>
                </div>
                <p>{{ row.title }}</p>
                <div class="report-row-meta muted">
                  <span>评级 {{ row.rating_text }}</span>
                  <span>目标价 {{ row.target_price ?? '--' }}</span>
                </div>
              </div>
            </div>
          </article>
        </aside>

        <section class="verify-main">
          <article v-if="verifyCharts.length" class="glass-panel verify-chart">
            <ChartPanel :title="verifyCharts[0].title" :options="verifyCharts[0].options" />
          </article>

          <article class="glass-panel verify-claims">
            <div class="section-headline claim-header">
              <div>
                <span class="section-kicker">逐条对照</span>
                <h3>把研报写法和财报原文一条条放在一起看</h3>
              </div>
              <div v-if="verifyDeltaItems.length" class="delta-inline">
                <span>{{ verifyDeltaItems[0].label }}</span>
                <strong>{{ verifyDeltaItems[0].value }}</strong>
              </div>
            </div>

            <div class="claim-list">
              <article v-for="(card, idx) in verifyPrimaryClaims" :key="card.claim_id" class="claim-row">
                <div class="claim-row-head">
                  <div class="claim-index">{{ String(idx + 1).padStart(2, '0') }}</div>
                  <div class="claim-title-block">
                    <strong>{{ card.label }}</strong>
                    <span class="muted">{{ displayClaimStatus(card.status) }}</span>
                  </div>
                  <TagPill :label="displayClaimStatus(card.status)" :tone="claimTone(card.status)" />
                </div>

                <div class="claim-compare">
                  <div class="claim-col">
                    <span class="muted">研报写法</span>
                    <strong class="text-accent">{{ card.claimed_value }}</strong>
                  </div>
                  <div class="claim-divider">对照</div>
                  <div class="claim-col align-right">
                    <span class="muted">财报原文</span>
                    <strong :class="card.status === 'match' ? 'text-accent' : 'risk-text'">{{ card.actual_value }}</strong>
                  </div>
                </div>

                <div class="claim-links">
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
              </article>
            </div>
          </article>
        </section>
      </div>
    </div>
  </AppShell>
</template>

<style scoped>
.verify-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  height: 100%;
  width: 100%;
  max-width: 1280px;
  margin: 0 auto;
  overflow: hidden;
}

.control-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding: 12px 16px;
  border-radius: 16px;
  flex-shrink: 0;
}

.control-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.control-copy {
  display: grid;
  gap: 4px;
}

.glow-icon {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  background: rgba(59, 130, 246, 0.15);
  border: 1px solid rgba(59, 130, 246, 0.38);
  color: #60a5fa;
  font-size: 18px;
  font-weight: 700;
}

.control-kicker {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--muted);
}

.company-name {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}

.control-meta {
  margin: 0;
  font-size: 12px;
  color: var(--muted);
}

.text-gradient {
  background-clip: text;
  -webkit-text-fill-color: transparent;
  background-image: linear-gradient(to right, #60a5fa, #34d399);
}

.inline-context {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}

.inline-field {
  display: flex;
  align-items: center;
  gap: 8px;
}

.subtle-label {
  font-size: 12px;
  color: var(--muted);
  text-transform: uppercase;
}

.glass-select {
  min-height: 36px;
  padding: 0 12px;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.05);
  color: #fff;
}

.report-select {
  max-width: 320px;
}

.glow-button {
  min-height: 36px;
  border-radius: 10px;
}

.state-container {
  flex: 1;
}

.empty-panel {
  display: grid;
  place-items: center;
  flex: 1;
  border-radius: 20px;
}

.empty-content {
  text-align: center;
  display: grid;
  gap: 8px;
}

.empty-content h3 {
  margin: 0;
}

.verify-grid {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 16px;
  min-height: 0;
  flex: 1;
}

.verify-sidebar,
.verify-main {
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.verify-sidebar {
  overflow-y: auto;
  padding-right: 4px;
}

.verify-sidebar::-webkit-scrollbar,
.claim-list::-webkit-scrollbar {
  width: 4px;
}

.verify-sidebar::-webkit-scrollbar-thumb,
.claim-list::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.12);
  border-radius: 999px;
}

.sidebar-section,
.verify-chart,
.verify-claims {
  padding: 18px;
  border-radius: 20px;
}

.section-headline {
  display: grid;
  gap: 6px;
}

.section-kicker {
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--muted);
}

.section-headline h2,
.section-headline h3 {
  margin: 0;
  font-size: 18px;
  line-height: 1.28;
  color: #f8fafc;
}

.section-headline p,
.muted {
  color: var(--muted);
}

.metric-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.metric-pill {
  display: grid;
  gap: 4px;
  padding: 10px 12px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.025);
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.metric-pill span {
  font-size: 11px;
  color: var(--muted);
}

.metric-pill strong {
  font-size: 15px;
  color: #f8fafc;
}

.text-accent {
  color: #10b981;
}

.risk-text {
  color: #fb7185;
}

.context-copy {
  margin: 0;
  font-size: 13px;
  line-height: 1.65;
}

.watch-lines,
.simple-list,
.report-list {
  display: grid;
  gap: 10px;
}

.watch-line,
.simple-row,
.report-row {
  padding-top: 10px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.watch-line {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.watch-line span {
  font-size: 13px;
  color: var(--muted);
}

.watch-line strong,
.simple-row strong,
.report-row-head strong {
  color: #f8fafc;
}

.simple-row p,
.report-row p {
  margin: 4px 0 0;
  font-size: 12px;
  line-height: 1.6;
}

.report-row-head,
.report-row-meta {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.report-row-meta {
  margin-top: 8px;
  font-size: 12px;
}

.context-links,
.claim-links {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.verify-main {
  overflow: hidden;
}

.verify-chart {
  flex: 0 0 244px;
  min-height: 0;
}

:deep(.chart-panel) {
  padding: 0;
  background: transparent !important;
  border: none !important;
}

:deep(.chart-root) {
  min-height: 198px !important;
}

.verify-claims {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: 0;
  overflow: hidden;
}

.claim-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 12px;
}

.delta-inline {
  display: grid;
  gap: 2px;
  text-align: right;
}

.delta-inline span {
  font-size: 11px;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.12em;
}

.delta-inline strong {
  font-size: 14px;
  color: #f8fafc;
}

.claim-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
  overflow-y: auto;
  padding-right: 4px;
}

.claim-row {
  display: grid;
  gap: 14px;
  padding: 16px 0;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.claim-row:first-child {
  padding-top: 0;
  border-top: none;
}

.claim-row-head {
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
}

.claim-index {
  width: 44px;
  height: 44px;
  border-radius: 14px;
  display: grid;
  place-items: center;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  color: var(--muted);
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.05);
}

.claim-title-block {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.claim-title-block strong {
  color: #f8fafc;
  line-height: 1.45;
}

.claim-compare {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  gap: 16px;
  align-items: center;
  padding: 14px 16px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.025);
  border: 1px solid rgba(255, 255, 255, 0.05);
}

.claim-col {
  display: grid;
  gap: 6px;
}

.claim-col strong {
  font-size: 16px;
  color: #f8fafc;
  word-break: break-word;
}

.claim-divider {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.24);
  text-transform: uppercase;
  letter-spacing: 0.14em;
}

.align-right {
  text-align: right;
}

.inline-glass-link {
  padding: 6px 12px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.04);
  color: var(--muted);
  font-size: 11px;
  text-decoration: none;
  transition: all 0.2s ease;
}

.inline-glass-link:hover {
  color: #60a5fa;
  background: rgba(59, 130, 246, 0.1);
  border-color: rgba(59, 130, 246, 0.28);
}

@media (max-width: 1180px) {
  .verify-grid {
    grid-template-columns: 1fr;
  }

  .verify-sidebar,
  .verify-main {
    overflow: visible;
  }
}

@media (max-width: 900px) {
  .control-bar,
  .inline-context {
    flex-direction: column;
    align-items: stretch;
  }

  .inline-field {
    width: 100%;
  }

  .glass-select,
  .report-select {
    width: 100%;
    max-width: none;
  }

  .metric-strip,
  .claim-compare {
    grid-template-columns: 1fr;
  }

  .claim-divider {
    display: none;
  }

  .align-right {
    text-align: left;
  }

  .claim-row-head {
    grid-template-columns: 44px minmax(0, 1fr);
  }
}
</style>
