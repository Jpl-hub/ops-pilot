<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import AppShell from '@/components/AppShell.vue'
import ChartPanel from '@/components/ChartPanel.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingState from '@/components/LoadingState.vue'
import StatCard from '@/components/StatCard.vue'
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

async function loadCompanies() {
  const risk = await get<any>('/industry/risk-scan')
  companies.value = risk.risk_board.map((item: any) => item.company_name)
}

async function loadReports() {
  const payload = await get<any>(`/company/research-reports?company_name=${encodeURIComponent(selectedCompany.value)}`)
  reports.value = payload.reports
  selectedReportTitle.value = reports.value[0]?.title ?? null
}

async function loadVerify() {
  await state.execute(() => post('/claim/verify', { company_name: selectedCompany.value, report_title: selectedReportTitle.value }))
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
  <AppShell
    title="研报观点核验"
    subtitle="对照研报观点、评级和真实财报数据。"
  >
    <section class="toolbar panel multi">
      <label class="field">
        <span>选择公司</span>
        <select v-model="selectedCompany">
          <option v-for="company in companies" :key="company" :value="company">{{ company }}</option>
        </select>
      </label>
      <label class="field field-wide">
        <span>选择研报</span>
        <select v-model="selectedReportTitle">
          <option v-for="report in reports" :key="report.title" :value="report.title">{{ report.title }} | {{ report.publish_date }}</option>
        </select>
      </label>
      <button class="button-primary" @click="loadVerify">刷新核验</button>
    </section>

    <LoadingState v-if="state.loading.value" />
    <ErrorState v-else-if="state.error.value" :message="state.error.value" />
    <template v-else-if="state.data.value">
      <section class="metrics-grid">
        <StatCard label="核验报期" :value="state.data.value.report_period" :hint="state.data.value.company_name" tone="accent" />
        <StatCard label="匹配观点" :value="String(state.data.value.key_numbers[0].value)" hint="与真实财报一致" tone="success" />
        <StatCard label="偏差观点" :value="String(state.data.value.key_numbers[1].value)" hint="存在偏差" tone="danger" />
        <StatCard label="投资评级" :value="`${state.data.value.report_meta.rating_change}${state.data.value.report_meta.rating_label}`" :hint="state.data.value.report_meta.source_name" />
      </section>

      <section class="chart-grid">
        <ChartPanel v-for="chart in state.data.value.charts" :key="chart.title" :title="chart.title" :options="chart.options" />
        <ChartPanel v-for="chart in state.data.value.research_compare.charts" :key="`compare-${chart.title}`" :title="chart.title" :options="chart.options" />
      </section>

      <section class="split-grid">
        <article class="panel hero-panel">
          <div>
            <div class="eyebrow">研报标题</div>
            <h2 class="hero-title compact">{{ state.data.value.report_meta.title }}</h2>
            <p class="hero-text">{{ state.data.value.report_meta.publish_date }} · {{ state.data.value.report_meta.source_name }}</p>
          </div>
          <div class="chip-grid">
            <div class="metric-chip"><span>评级动作</span><strong>{{ state.data.value.report_meta.rating_change || '未披露' }}</strong></div>
            <div class="metric-chip"><span>目标价</span><strong>{{ state.data.value.report_meta.target_price ?? '未披露' }}</strong></div>
            <div class="metric-chip"><span>匹配</span><strong>{{ state.data.value.claim_cards.length }}</strong></div>
            <div class="metric-chip"><span>预测</span><strong>{{ state.data.value.forecast_cards.length }}</strong></div>
          </div>
        </article>

        <article class="panel">
          <div class="panel-header"><h3>研报元信息</h3></div>
          <div class="detail-list">
            <div class="detail-row"><span>研究机构</span><strong>{{ state.data.value.report_meta.source_name }}</strong></div>
            <div class="detail-row"><span>分析师</span><strong>{{ state.data.value.report_meta.researcher || '未披露' }}</strong></div>
            <div class="detail-row"><span>评级</span><strong>{{ state.data.value.report_meta.rating_change }}{{ state.data.value.report_meta.rating_label }}</strong></div>
            <div class="detail-row"><span>目标价</span><strong>{{ state.data.value.report_meta.target_price ?? '未披露' }}</strong></div>
          </div>
          <div class="link-row">
            <a class="inline-link" :href="state.data.value.report_meta.source_url" target="_blank" rel="noreferrer">查看详情</a>
            <a class="inline-link" :href="state.data.value.report_meta.attachment_url" target="_blank" rel="noreferrer">打开附件</a>
          </div>
        </article>
      </section>

      <section>
        <div class="page-header" style="margin-top: 32px; margin-bottom: 16px;"><h3>观点对照</h3></div>
        <div class="stack-grid">
          <article v-for="card in state.data.value.claim_cards" :key="card.claim_id" class="signal-card">
            <div class="signal-top">
              <div><div class="signal-code">{{ card.metric_key }}</div><h4>{{ card.label }}</h4></div>
              <TagPill :label="card.status" :tone="card.status === 'match' ? 'success' : 'risk'" />
            </div>
            <div class="metric-list">
              <div class="metric-row"><span>研报值</span><strong>{{ card.claimed_value }}</strong></div>
              <div class="metric-row"><span>财报值</span><strong>{{ card.actual_value }}</strong></div>
              <div class="metric-row"><span>差值</span><strong>{{ card.delta }}</strong></div>
            </div>
            <p class="evidence-excerpt">{{ card.excerpt }}</p>
            <div class="evidence-links">
              <RouterLink class="inline-link" :to="buildEvidenceLink(card.research_chunk_id, card.label, [card.label])">研报证据</RouterLink>
              <RouterLink v-for="item in card.evidence_refs" :key="item" class="inline-link" :to="buildEvidenceLink(item, card.label, [card.label])">财报证据</RouterLink>
            </div>
          </article>
        </div>
      </section>

      <section>
        <div class="page-header" style="margin-top: 32px; margin-bottom: 16px;"><h3>同公司研报横向对比</h3></div>
        <div class="tag-row" style="margin-bottom: 16px;">
          <TagPill v-for="insight in state.data.value.research_compare.insights" :key="insight.title" :label="insight.title" tone="risk" />
        </div>
        <div class="stack-grid">
          <article v-for="row in state.data.value.research_compare.rows" :key="row.title + row.publish_date" class="research-card">
            <div class="signal-top">
              <div><div class="signal-code">{{ row.source_name }}</div><h4>{{ row.title }}</h4></div>
              <div class="signal-subtitle">{{ row.publish_date }}</div>
            </div>
            <div class="tag-row">
              <TagPill v-for="tag in row.signal_tags" :key="tag" :label="tag" />
            </div>
            <div class="metric-list">
              <div class="metric-row"><span>评级</span><strong>{{ row.rating_text }}</strong></div>
              <div class="metric-row"><span>目标价</span><strong>{{ row.target_price ?? '未披露' }}</strong></div>
              <div class="metric-row"><span>首年利润预测</span><strong>{{ row.headline_forecast_value ?? 'N/A' }}</strong></div>
            </div>
          </article>
        </div>
      </section>
    </template>
  </AppShell>
</template>
