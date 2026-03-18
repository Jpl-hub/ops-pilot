<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

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

onMounted(async () => {
  await loadCompanies()
  if (!companies.value.includes(selectedCompany.value)) {
    selectedCompany.value = companies.value[0]
  }
  await loadScore()
  selectedPeriod.value = scoreState.data.value?.report_period || ''
})

watch(selectedCompany, async (_, oldValue) => {
  if (oldValue && selectedCompany.value !== oldValue) {
    selectedPeriod.value = ''
    await loadScore()
    selectedPeriod.value = scoreState.data.value?.report_period || ''
  }
})

watch(selectedPeriod, async (_, oldValue) => {
  if (oldValue && selectedPeriod.value !== oldValue) {
    await loadScore()
  }
})
</script>

<template>
  <AppShell
    title="企业运营体检"
    subtitle="查看经营结论、关键指标、建议动作和证据来源。"
  >
    <section class="toolbar panel">
      <label class="field">
        <span>选择公司</span>
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
      <button class="button-primary" @click="loadScore">刷新评分</button>
    </section>

    <LoadingState v-if="scoreState.loading.value" />
    <ErrorState v-else-if="scoreState.error.value" :message="scoreState.error.value" />
    <template v-else-if="scoreState.data.value">
      <section class="metrics-grid">
        <StatCard label="总分" :value="`${scoreState.data.value.scorecard.total_score} 分`" :hint="`等级 ${scoreState.data.value.scorecard.grade}`" tone="accent" />
        <StatCard label="报告期" :value="scoreState.data.value.report_period" :hint="scoreState.data.value.company_name" />
        <StatCard label="风险标签" :value="String(scoreState.data.value.scorecard.risk_labels.length)" hint="命中高风险规则数" tone="danger" />
        <StatCard label="机会标签" :value="String(scoreState.data.value.scorecard.opportunity_labels.length)" hint="命中机会规则数" tone="success" />
      </section>

      <section class="split-grid">
        <article class="panel hero-panel">
          <div>
            <div class="eyebrow">经营结论</div>
            <h2 class="hero-title compact">{{ scoreState.data.value.company_name }}</h2>
            <p class="hero-text">{{ scoreState.data.value.report_period }} · {{ scoreState.data.value.subindustry }} · 等级 {{ scoreState.data.value.scorecard.grade }}</p>
            <div class="chip-grid">
              <div class="metric-chip"><span>总分</span><strong>{{ scoreState.data.value.scorecard.total_score }}</strong></div>
              <div class="metric-chip"><span>分位</span><strong>{{ scoreState.data.value.scorecard.subindustry_percentile }}pct</strong></div>
              <div class="metric-chip"><span>强项</span><strong>{{ scoreState.data.value.scorecard.strengths.length }}</strong></div>
              <div class="metric-chip"><span>弱项</span><strong>{{ scoreState.data.value.scorecard.weaknesses.length }}</strong></div>
            </div>
          </div>
        </article>

        <article class="panel">
          <div class="panel-header"><h3>核心判断</h3></div>
          <ul class="bullet-list">
            <li v-for="item in summaryBullets" :key="item">{{ item }}</li>
          </ul>
          <div class="subsection-label">风险标签</div>
          <div class="tag-row">
            <TagPill v-for="label in scoreState.data.value.scorecard.risk_labels" :key="label.code" :label="label.name" tone="risk" />
          </div>
          <div class="subsection-label">机会标签</div>
          <div class="tag-row">
            <TagPill v-if="scoreState.data.value.scorecard.opportunity_labels.length === 0" label="暂无显著机会标签" />
            <TagPill v-for="label in scoreState.data.value.scorecard.opportunity_labels" v-else :key="label.code" :label="label.name" tone="success" />
          </div>
        </article>
      </section>

      <section class="panel">
        <div class="panel-header"><h3>标签拆解</h3></div>
        <div class="stack-grid">
          <article v-for="card in scoreState.data.value.label_cards" :key="card.code" class="signal-card">
            <div class="signal-top">
              <div><div class="signal-code">{{ card.code }}</div><h4>{{ card.name }}</h4></div>
              <div class="signal-value">{{ card.signal_values.join(' / ') }}</div>
            </div>
            <div class="metric-list">
              <div v-for="metric in card.metrics" :key="metric.metric_code" class="metric-row">
                <span>{{ metric.metric_code }} {{ metric.metric_name }}</span>
                <strong>{{ metric.value }}</strong>
              </div>
            </div>
            <div class="evidence-links">
              <RouterLink v-for="item in card.evidence_refs" :key="item" class="inline-link" :to="buildEvidenceLink(item, `${card.code} ${card.name}`, card.anchor_terms)">
                证据
              </RouterLink>
            </div>
          </article>
        </div>
      </section>

      <section class="panel">
        <div class="panel-header"><h3>建议动作</h3></div>
        <div class="stack-grid">
          <article v-for="action in scoreState.data.value.action_cards" :key="action.title" class="company-card">
            <div class="signal-top">
              <div>
                <div class="signal-code">{{ action.priority }}</div>
                <h4>{{ action.title }}</h4>
              </div>
            </div>
            <p class="command-copy">{{ action.reason }}</p>
            <div class="analysis-copy">{{ action.action }}</div>
          </article>
        </div>
      </section>

      <section class="chart-grid">
        <ChartPanel v-for="chart in scoreState.data.value.charts" :key="chart.title" :title="chart.title" :options="chart.options" />
      </section>

      <section class="panel">
        <div class="panel-header"><h3>公式回放</h3></div>
        <div class="stack-grid">
          <article v-for="formula in scoreState.data.value.formula_cards" :key="formula.metric_code" class="formula-card">
            <div class="signal-top">
              <div><div class="signal-code">{{ formula.metric_code }}</div><h4>{{ formula.title }}</h4></div>
              <div class="signal-value">{{ formula.value }}</div>
            </div>
            <code class="formula-inline">{{ formula.formula }}</code>
            <ul class="bullet-list compact">
              <li v-for="line in formula.lines" :key="line">{{ line }}</li>
            </ul>
            <div class="evidence-links">
              <RouterLink v-for="item in formula.evidence_refs" :key="item" class="inline-link" :to="buildEvidenceLink(item, `${formula.metric_code} ${formula.title}`, formula.anchor_terms)">
                证据
              </RouterLink>
            </div>
          </article>
        </div>
      </section>
    </template>
  </AppShell>
</template>
