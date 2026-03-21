<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
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
const selectedCompany = ref('TCL中环')
const selectedPeriod = ref<string>('')
const scoreState = useAsyncState<any>()
const timelineState = useAsyncState<any>()
const companyState = useAsyncState<any>()
const route = useRoute()
const syncingFromRoute = ref(false)

const summaryBullets = computed(() => {
  const scorecard = scoreState.data.value?.scorecard
  if (!scorecard) return []
  return [
    `总分 ${scorecard.total_score}，等级 ${scorecard.grade}，子行业分位 ${scorecard.subindustry_percentile}pct。`,
    `强项：${scorecard.strengths.map((item: any) => item.name).join('、') || '暂无显著强项'}`,
    `弱项：${scorecard.weaknesses.map((item: any) => item.name).join('、') || '暂无显著弱项'}`,
  ]
})

async function loadCompanies() {
  const risk = await get<any>('/industry/risk-scan')
  companies.value = risk.risk_board.map((item: any) => item.company_name)
}

async function loadScore() {
  await scoreState.execute(() =>
    post('/company/score', {
      company_name: selectedCompany.value,
      report_period: selectedPeriod.value || null,
    }),
  )
}

async function loadTimeline() {
  await timelineState.execute(() =>
    get<any>(`/company/timeline?company_name=${encodeURIComponent(selectedCompany.value)}`),
  )
}

async function loadCompanyWorkspace() {
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
  if (!companies.value.includes(selectedCompany.value)) {
    selectedCompany.value = companies.value[0]
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
  <AppShell
    title="企业运营体检"
  >
    <section class="mode-query-panel">
      <div class="mode-query-icon">体</div>
      <div class="mode-query-copy">
        <div class="eyebrow">经营诊断</div>
        <h3>{{ selectedCompany }}</h3>
      </div>
      <button class="button-primary" @click="loadScore">刷新诊断</button>
    </section>

    <section class="graph-context-bar">
      <label class="field">
        <span>公司</span>
        <select v-model="selectedCompany">
          <option v-for="company in companies" :key="company" :value="company">{{ company }}</option>
        </select>
      </label>
      <label class="field">
        <span>报告期</span>
        <select v-model="selectedPeriod">
          <option
            v-for="period in scoreState.data.value?.available_periods || []"
            :key="period"
            :value="period"
          >
            {{ period }}
          </option>
        </select>
      </label>
    </section>

    <LoadingState v-if="scoreState.loading.value" />
    <ErrorState v-else-if="scoreState.error.value" :message="scoreState.error.value" />
    <template v-else-if="scoreState.data.value">
      <article class="panel evaluation-stage">
        <section class="evaluation-header">
          <div class="evaluation-hero">
            <div class="eyebrow">当前结论</div>
            <h2 class="hero-title compact">{{ scoreState.data.value.company_name }}</h2>
            <p class="hero-text">
              {{ scoreState.data.value.report_period }} · {{ scoreState.data.value.subindustry }} ·
              等级 {{ scoreState.data.value.scorecard.grade }}
            </p>
            <div class="chip-grid">
              <div class="metric-chip"><span>总分</span><strong>{{ scoreState.data.value.scorecard.total_score }}</strong></div>
              <div class="metric-chip"><span>分位</span><strong>{{ scoreState.data.value.scorecard.subindustry_percentile }}pct</strong></div>
              <div class="metric-chip"><span>风险</span><strong>{{ scoreState.data.value.scorecard.risk_labels.length }}</strong></div>
              <div class="metric-chip"><span>机会</span><strong>{{ scoreState.data.value.scorecard.opportunity_labels.length }}</strong></div>
            </div>
          </div>

          <div class="evaluation-brief">
            <ul class="bullet-list">
              <li v-for="item in summaryBullets" :key="item">{{ item }}</li>
            </ul>
          </div>
        </section>

        <section class="graph-support-strip evaluation-support-strip">
          <article class="graph-support-card">
            <div class="panel-header"><h3>经营标签</h3></div>
            <div class="tag-row">
              <TagPill
                v-for="label in scoreState.data.value.scorecard.risk_labels"
                :key="label.code"
                :label="label.name"
                tone="risk"
              />
              <TagPill
                v-for="label in scoreState.data.value.scorecard.opportunity_labels"
                :key="`op-${label.code}`"
                :label="label.name"
                tone="success"
              />
              <TagPill
                v-if="
                  scoreState.data.value.scorecard.risk_labels.length === 0 &&
                  scoreState.data.value.scorecard.opportunity_labels.length === 0
                "
                label="暂无显著标签"
              />
            </div>
          </article>

          <article class="graph-support-card">
            <div class="panel-header"><h3>优先动作</h3></div>
            <div class="support-stack">
              <article
                v-for="action in scoreState.data.value.action_cards.slice(0, 2)"
                :key="action.title"
                class="support-inline-card"
              >
                <div class="signal-top">
                  <div>
                    <div class="signal-code">{{ action.priority }}</div>
                    <h4>{{ action.title }}</h4>
                  </div>
                </div>
                <p class="command-copy">{{ action.reason }}</p>
              </article>
            </div>
          </article>

          <article
            v-if="companyState.data.value?.runtime_capsule?.modules?.length"
            class="graph-support-card"
          >
            <div class="panel-header"><h3>运行胶囊</h3></div>
            <div class="support-stack">
              <article
                v-for="item in companyState.data.value.runtime_capsule.modules"
                :key="item.module_key"
                class="support-inline-card"
              >
                <div class="signal-top">
                  <div>
                    <div class="signal-code">{{ item.label }}</div>
                    <h4>{{ item.summary }}</h4>
                  </div>
                  <div class="signal-subtitle">{{ item.status === 'ready' ? '已运行' : '待运行' }}</div>
                </div>
                <div v-if="item.details?.length" class="metric-list">
                  <div class="metric-row"><span>最近状态</span><strong>{{ item.details.join(' · ') }}</strong></div>
                </div>
              </article>
            </div>
          </article>
        </section>
      </article>

      <section class="chart-grid evaluation-chart-grid">
        <ChartPanel v-for="chart in scoreState.data.value.charts" :key="chart.title" :title="chart.title" :options="chart.options" />
      </section>

      <section v-if="timelineState.data.value" class="graph-support-strip evaluation-support-strip">
        <article class="graph-support-card">
          <div class="panel-header"><h3>阶段轨迹</h3></div>
          <div class="support-stack">
            <article
              v-for="item in timelineState.data.value.snapshots.slice(0, 4)"
              :key="item.report_period"
              class="support-inline-card"
            >
              <div class="signal-top">
                <div>
                  <div class="signal-code">{{ item.report_period }}</div>
                  <h4>{{ item.grade }}</h4>
                </div>
                <div class="signal-subtitle">{{ item.total_score }} 分</div>
              </div>
              <div class="metric-list">
                <div class="metric-row"><span>风险数</span><strong>{{ item.risk_count }}</strong></div>
                <div class="metric-row"><span>营收增速</span><strong>{{ item.revenue_growth ?? '--' }}</strong></div>
              </div>
            </article>
          </div>
        </article>

        <article class="graph-support-card">
          <div class="panel-header"><h3>重点指标</h3></div>
          <div class="support-stack">
            <article
              v-for="card in scoreState.data.value.label_cards.slice(0, 3)"
              :key="card.code"
              class="support-inline-card"
            >
              <div class="signal-top">
                <div>
                  <div class="signal-code">{{ card.code }}</div>
                  <h4>{{ card.name }}</h4>
                </div>
                <div class="signal-value">{{ card.signal_values.join(' / ') }}</div>
              </div>
              <div class="metric-list">
                <div
                  v-for="metric in card.metrics.slice(0, 2)"
                  :key="metric.metric_code"
                  class="metric-row"
                >
                  <span>{{ metric.metric_name }}</span>
                  <strong>{{ metric.value }}</strong>
                </div>
              </div>
              <div class="evidence-links">
                <RouterLink
                  v-for="item in card.evidence_refs"
                  :key="item"
                  class="inline-link"
                  :to="buildEvidenceLink(item, `${card.code} ${card.name}`, card.anchor_terms)"
                >
                  证据
                </RouterLink>
              </div>
            </article>
          </div>
        </article>
      </section>

      <section v-if="timelineState.data.value" class="chart-grid evaluation-chart-grid">
        <ChartPanel
          v-for="chart in timelineState.data.value.charts"
          :key="chart.title"
          :title="chart.title"
          :options="chart.options"
        />
      </section>

      <section class="graph-support-strip evaluation-support-strip">
        <article class="graph-support-card">
          <div class="panel-header"><h3>公式回放</h3></div>
          <div class="support-stack">
            <article
              v-for="formula in scoreState.data.value.formula_cards.slice(0, 3)"
              :key="formula.metric_code"
              class="support-inline-card"
            >
              <div class="signal-top">
                <div>
                  <div class="signal-code">{{ formula.metric_code }}</div>
                  <h4>{{ formula.title }}</h4>
                </div>
                <div class="signal-value">{{ formula.value }}</div>
              </div>
              <code class="formula-inline">{{ formula.formula }}</code>
              <div class="evidence-links">
                <RouterLink
                  v-for="item in formula.evidence_refs"
                  :key="item"
                  class="inline-link"
                  :to="buildEvidenceLink(item, `${formula.metric_code} ${formula.title}`, formula.anchor_terms)"
                >
                  证据
                </RouterLink>
              </div>
            </article>
          </div>
        </article>
      </section>
    </template>
  </AppShell>
</template>
