<script setup lang="ts">
import { onMounted } from 'vue'

import AppShell from '@/components/AppShell.vue'
import ChartPanel from '@/components/ChartPanel.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingState from '@/components/LoadingState.vue'
import StatCard from '@/components/StatCard.vue'
import TagPill from '@/components/TagPill.vue'
import { useAsyncState } from '@/composables/useAsyncState'
import { get } from '@/lib/api'

const state = useAsyncState<any>()

onMounted(() => {
  void state.execute(() => get('/industry/risk-scan'))
})
</script>

<template>
  <AppShell
    title="行业风险与机会"
    subtitle="把正式公司池放到一个主周期里，看风险密度、公司分布和行业研报背景，而不是盯着单个点位。"
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

      <section class="chart-grid">
        <ChartPanel v-for="chart in state.data.value.charts" :key="chart.title" :title="chart.title" :options="chart.options" />
      </section>

      <section class="panel">
        <div class="panel-header">
          <h3>行业风险名单</h3>
        </div>
        <div class="company-grid">
          <article v-for="item in state.data.value.risk_board" :key="item.company_name" class="company-card">
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
          </article>
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
