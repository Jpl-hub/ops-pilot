<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import AppShell from '@/components/AppShell.vue'
import ChartPanel from '@/components/ChartPanel.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingState from '@/components/LoadingState.vue'
import StatCard from '@/components/StatCard.vue'
import TagPill from '@/components/TagPill.vue'
import { useAsyncState } from '@/composables/useAsyncState'
import { get } from '@/lib/api'

const state = useAsyncState<any>()
const selectedAlertCompany = ref('')
const alertFilter = ref<'all' | 'delta'>('all')

const alertBoard = computed(() => {
  const alerts = state.data.value?.alert_board || []
  if (alertFilter.value === 'delta') {
    return alerts.filter((item: any) => item.risk_delta > 0)
  }
  return alerts
})

const selectedAlert = computed(() => {
  const alerts = alertBoard.value
  if (!alerts.length) return null
  return alerts.find((item: any) => item.company_name === selectedAlertCompany.value) || alerts[0]
})

watch(
  alertBoard,
  (alerts) => {
    if (!alerts.length) {
      selectedAlertCompany.value = ''
      return
    }
    if (!alerts.some((item: any) => item.company_name === selectedAlertCompany.value)) {
      selectedAlertCompany.value = alerts[0].company_name
    }
  },
  { immediate: true },
)

onMounted(() => {
  void state.execute(() => get('/industry/risk-scan'))
})
</script>

<template>
  <AppShell
    title="行业风险与机会"
    subtitle="先看主动预警，再下钻到公司体检和证据。"
  >
    <LoadingState v-if="state.loading.value" />
    <ErrorState v-else-if="state.error.value" :message="state.error.value" />
    <template v-else-if="state.data.value">
      <section class="metrics-grid">
        <StatCard label="覆盖公司" :value="String(state.data.value.risk_board.length)" hint="正式公司池" tone="accent" />
        <StatCard label="高风险公司" :value="String(state.data.value.risk_board.filter((item: any) => item.risk_count > 0).length)" hint="风险标签命中数大于 0" tone="danger" />
        <StatCard label="覆盖行业" :value="String(state.data.value.industry_research.key_numbers[0].value)" hint="行业研报" />
        <StatCard label="行业研报" :value="String(state.data.value.industry_research.key_numbers[1].value)" hint="真实详情页" tone="success" />
      </section>

      <section class="panel">
        <div class="panel-header">
          <div>
            <h3>主动预警</h3>
            <p class="page-subtitle">识别本期风险抬升、营收转负或利润继续承压的公司。</p>
          </div>
          <div class="hero-actions">
            <button
              class="button-secondary"
              :class="{ 'is-active-toggle': alertFilter === 'all' }"
              @click="alertFilter = 'all'"
            >
              全部预警
            </button>
            <button
              class="button-secondary"
              :class="{ 'is-active-toggle': alertFilter === 'delta' }"
              @click="alertFilter = 'delta'"
            >
              只看新增风险
            </button>
          </div>
        </div>

        <div v-if="alertBoard.length" class="stack-grid">
          <button
            v-for="item in alertBoard"
            :key="`${item.company_name}-${item.report_period}`"
            type="button"
            class="company-card interactive-card"
            :class="{ 'is-active-card': selectedAlertCompany === item.company_name }"
            @click="selectedAlertCompany = item.company_name"
          >
            <div class="signal-top">
              <div>
                <div class="signal-code">{{ item.subindustry }}</div>
                <h4>{{ item.company_name }}</h4>
              </div>
              <div class="signal-value">{{ item.risk_count }}</div>
            </div>
            <p class="command-copy">{{ item.summary }}</p>
            <div class="tag-row">
              <TagPill :label="`${item.report_period}`" />
              <TagPill
                :label="item.risk_delta > 0 ? `较上期 +${item.risk_delta}` : '风险延续'"
                :tone="item.risk_delta > 0 ? 'risk' : undefined"
              />
              <TagPill
                v-for="label in item.new_labels"
                :key="label"
                :label="label"
                tone="risk"
              />
            </div>
          </button>
        </div>
        <div v-else class="analysis-answer">
          <div class="analysis-copy">当前主周期没有识别到新的重点预警。</div>
        </div>

        <article v-if="selectedAlert" class="panel" style="margin-top: 18px;">
          <div class="panel-header">
            <div>
              <div class="eyebrow">预警详情</div>
              <h3>{{ selectedAlert.company_name }}</h3>
            </div>
            <div class="signal-subtitle">{{ selectedAlert.report_period }}</div>
          </div>
          <p class="analysis-copy">{{ selectedAlert.summary }}</p>
          <div class="link-row">
            <RouterLink
              class="button-primary"
              :to="`/score?company=${encodeURIComponent(selectedAlert.company_name)}&period=${encodeURIComponent(selectedAlert.report_period)}`"
            >
              查看当前体检
            </RouterLink>
            <RouterLink
              v-if="selectedAlert.previous_period"
              class="button-secondary"
              :to="`/score?company=${encodeURIComponent(selectedAlert.company_name)}&period=${encodeURIComponent(selectedAlert.previous_period)}`"
            >
              对比上一期
            </RouterLink>
          </div>
        </article>
      </section>

      <section class="chart-grid">
        <ChartPanel v-for="chart in state.data.value.charts" :key="chart.title" :title="chart.title" :options="chart.options" />
      </section>

      <section class="panel">
        <div class="panel-header">
          <h3>行业风险名单</h3>
        </div>
        <div class="company-grid">
          <RouterLink
            v-for="item in state.data.value.risk_board"
            :key="item.company_name"
            class="company-card interactive-card"
            :to="`/score?company=${encodeURIComponent(item.company_name)}`"
          >
            <div class="signal-top">
              <div>
                <div class="signal-code">{{ item.subindustry }}</div>
                <h4>{{ item.company_name }}</h4>
              </div>
              <div class="signal-value">{{ item.risk_count }}</div>
            </div>
            <div class="tag-row">
              <TagPill v-if="item.risk_labels.length === 0" label="当前主周期无高风险标签" />
              <TagPill v-for="label in item.risk_labels" v-else :key="label" :label="label" tone="risk" />
            </div>
          </RouterLink>
        </div>
      </section>

      <section class="panel">
        <div class="panel-header">
          <h3>行业研报观察</h3>
        </div>
        <div class="stack-grid">
          <article v-for="group in state.data.value.industry_research.groups" :key="group.industry_name" class="research-card">
            <div class="signal-top">
              <div>
                <div class="signal-code">行业研报</div>
                <h4>{{ group.industry_name }}</h4>
              </div>
              <div class="signal-subtitle">{{ group.report_count }} 篇</div>
            </div>
            <h5 class="research-title">{{ group.latest_report.title }}</h5>
            <p class="evidence-excerpt">{{ group.latest_report.excerpt }}</p>
            <div class="research-meta">
              <span>{{ group.latest_report.source_name }}</span>
              <span>{{ group.latest_report.publish_date }}</span>
            </div>
            <a class="inline-link" :href="group.latest_report.source_url" target="_blank" rel="noreferrer">查看详情</a>
          </article>
        </div>
      </section>
    </template>
  </AppShell>
</template>
