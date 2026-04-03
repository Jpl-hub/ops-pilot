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
import { persistWorkflowContext, resolveWorkflowContext } from '@/lib/workflowContext'

const companies = ref<string[]>([])
const reports = ref<any[]>([])
const selectedCompany = ref('')
const selectedPeriod = ref('')
const selectedReportTitle = ref<string | null>(null)
const state = useAsyncState<any>()
const route = useRoute()
const syncingFromRoute = ref(false)
const verifyCommandSurface = ref<any | null>(null)
const availablePeriods = ref<any[]>([])
const reportStatusMessage = ref('')
const reportCatalogReady = ref(false)

const verifyWatchItems = computed(() => verifyCommandSurface.value?.watch_items?.slice(0, 2) || [])
const verifyDominantSignal = computed(() => verifyCommandSurface.value?.dominant_signal || null)
const verifyPrimaryClaims = computed(() => state.data.value?.claim_cards?.slice(0, 4) || [])
const verifyPrimaryInsights = computed(() => state.data.value?.research_compare?.insights?.slice(0, 3) || [])
const verifyCompareRows = computed(() => state.data.value?.research_compare?.rows?.slice(0, 3) || [])

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
}

onMounted(async () => {
  const workflowContext = resolveWorkflowContext(route.query)
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
  () => [route.query.company, route.query.report_title, route.query.period],
  async ([companyQuery, reportTitleQuery, periodQuery]) => {
    const company = typeof companyQuery === 'string' ? companyQuery : ''
    const reportTitle = typeof reportTitleQuery === 'string' ? reportTitleQuery : ''
    const period = typeof periodQuery === 'string' ? periodQuery : ''
    if (company && company !== selectedCompany.value && companies.value.includes(company)) {
      syncingFromRoute.value = true
      selectedCompany.value = company
      if (period) {
        selectedPeriod.value = period
      }
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
    if (period && period !== selectedPeriod.value) {
      syncingFromRoute.value = true
      selectedPeriod.value = period
      syncingFromRoute.value = false
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
          <button class="button-primary action-button" @click="loadVerify">重新核对</button>
        </div>
      </section>

      <LoadingState v-if="state.loading.value" class="state-container" />
      <ErrorState v-else-if="state.error.value" :message="state.error.value" class="state-container" />

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
              <p>{{ state.data.value.report_meta.publish_date }} · {{ state.data.value.report_meta.source_name }}</p>
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
            </div>
            <div v-if="verifyWatchItems.length" class="watch-list">
              <div v-for="item in verifyWatchItems" :key="item.label" class="watch-item">
                <span>{{ item.label }}</span>
                <strong>{{ item.value }}</strong>
              </div>
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
