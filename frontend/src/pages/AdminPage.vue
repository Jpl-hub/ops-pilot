<script setup lang="ts">
import { onMounted } from 'vue'

import AppShell from '@/components/AppShell.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingState from '@/components/LoadingState.vue'
import StatCard from '@/components/StatCard.vue'
import TagPill from '@/components/TagPill.vue'
import { useAsyncState } from '@/composables/useAsyncState'
import { get } from '@/lib/api'

const state = useAsyncState<any>()

onMounted(() => {
  void state.execute(() => get('/admin/overview'))
})
</script>

<template>
  <AppShell
    title="系统管理台"
    subtitle="把系统健康、覆盖缺口和标准作业放到一个视图里，数据链哪里断，一眼能看见。"
  >
    <LoadingState v-if="state.loading.value" />
    <ErrorState v-else-if="state.error.value" :message="state.error.value" />
    <template v-else-if="state.data.value">
      <section class="metrics-grid">
        <StatCard label="系统状态" :value="state.data.value.health.status" :hint="state.data.value.health.env" tone="success" />
        <StatCard label="默认主周期" :value="state.data.value.health.preferred_period" :hint="`公司 ${state.data.value.health.companies} 家`" />
        <StatCard label="原始报告" :value="String(state.data.value.data_status.periodic_reports.record_count)" :hint="`公司 ${state.data.value.data_status.periodic_reports.company_count} 家`" />
        <StatCard label="结构化指标" :value="String(state.data.value.data_status.silver_financial_metrics.record_count)" :hint="`公司 ${state.data.value.data_status.silver_financial_metrics.company_count} 家`" tone="accent" />
      </section>

      <section class="panel">
        <div class="panel-header">
          <h3>覆盖诊断</h3>
        </div>
        <div class="metrics-grid">
          <StatCard label="正式公司池" :value="String(state.data.value.quality_overview.coverage.pool_companies)" hint="当前冻结正式公司范围" />
          <StatCard label="主周期可评估" :value="String(state.data.value.quality_overview.coverage.preferred_period_ready)" :hint="state.data.value.health.preferred_period" tone="success" />
          <StatCard label="研报已覆盖" :value="String(state.data.value.quality_overview.coverage.research_ready)" hint="有真实研报详情页" />
          <StatCard label="页级解析" :value="String(state.data.value.quality_overview.coverage.bronze_ready)" hint="raw -> bronze 已打通" />
        </div>
      </section>

      <section class="panel">
        <div class="panel-header">
          <h3>问题分桶</h3>
        </div>
        <div class="tag-row">
          <TagPill v-for="bucket in state.data.value.quality_overview.issue_buckets" :key="bucket.code" :label="`${bucket.label} ${bucket.count}`" tone="risk" />
        </div>
      </section>

      <section class="panel">
        <div class="panel-header">
          <h3>公司覆盖明细</h3>
        </div>
        <div class="company-grid">
          <article v-for="row in state.data.value.quality_overview.companies.slice(0, 18)" :key="row.company_name" class="company-card">
            <div class="signal-top">
              <div>
                <div class="signal-code">{{ row.subindustry }}</div>
                <h4>{{ row.company_name }}</h4>
              </div>
              <div class="signal-subtitle">{{ row.latest_silver_period }}</div>
            </div>
            <div class="metric-list">
              <div class="metric-row"><span>定期报告</span><strong>{{ row.raw_report_count }}</strong></div>
              <div class="metric-row"><span>页级解析</span><strong>{{ row.bronze_report_count }}</strong></div>
              <div class="metric-row"><span>结构化记录</span><strong>{{ row.silver_record_count }}</strong></div>
              <div class="metric-row"><span>研报</span><strong>{{ row.research_report_count }}</strong></div>
            </div>
            <div class="tag-row">
              <TagPill
                v-if="row.issues.length === 0"
                label="链路完整"
                tone="success"
              />
              <TagPill v-for="flag in row.issues" :key="flag" :label="flag" tone="risk" />
            </div>
          </article>
        </div>
      </section>
    </template>
  </AppShell>
</template>
