<script setup lang="ts">
import { onMounted, ref } from 'vue'

import AppShell from '@/components/AppShell.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingState from '@/components/LoadingState.vue'
import StatCard from '@/components/StatCard.vue'
import TagPill from '@/components/TagPill.vue'
import { useAsyncState } from '@/composables/useAsyncState'
import { get, post } from '@/lib/api'

const state = useAsyncState<any>()
const pipelineRunState = useAsyncState<any>()
const resultsState = useAsyncState<any>()
const runningStage = ref('')

onMounted(() => {
  void state.execute(() => get('/admin/overview'))
  void resultsState.execute(() => get('/admin/document-pipeline/results?limit=12'))
})

async function runStage(stage: 'cross_page_merge' | 'title_hierarchy' | 'cell_trace') {
  runningStage.value = stage
  await pipelineRunState.execute(() => post('/admin/document-pipeline/run', { stage, limit: 5 }))
  await state.execute(() => get('/admin/overview'))
  await resultsState.execute(() => get(`/admin/document-pipeline/results?stage=${stage}&limit=12`))
  runningStage.value = ''
}
</script>

<template>
  <AppShell
    title="管理台"
    subtitle="查看覆盖缺口与文档解析作业"
    compact
  >
    <LoadingState v-if="state.loading.value" />
    <ErrorState v-else-if="state.error.value" :message="state.error.value" />
    <template v-else-if="state.data.value">
      <section class="metrics-grid">
        <StatCard label="运行状态" :value="state.data.value.health.status" :hint="state.data.value.health.env" tone="success" />
        <StatCard label="主周期" :value="state.data.value.health.preferred_period" :hint="`公司 ${state.data.value.health.companies} 家`" />
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

      <section class="split-grid">
        <article class="panel">
          <div class="panel-header">
            <h3>解析链状态</h3>
          </div>
          <div class="detail-list">
            <div class="detail-row"><span>版面解析</span><strong>{{ state.data.value.document_pipeline.layout_engine }}</strong></div>
            <div class="detail-row"><span>OCR 引擎</span><strong>{{ state.data.value.document_pipeline.ocr_engine }}</strong></div>
            <div class="detail-row"><span>OCR 运行时</span><strong>{{ state.data.value.document_pipeline.ocr_runtime_enabled ? 'active' : 'planned' }}</strong></div>
            <div class="detail-row"><span>跨页拼接</span><strong>{{ state.data.value.document_pipeline.cross_page_merge.status }}</strong></div>
            <div class="detail-row"><span>标题层级恢复</span><strong>{{ state.data.value.document_pipeline.title_hierarchy.status }}</strong></div>
            <div class="detail-row"><span>单元格溯源</span><strong>{{ state.data.value.document_pipeline.cell_trace.status }}</strong></div>
          </div>
          <div class="tag-row" style="margin-top: 14px;">
            <TagPill
              v-for="item in state.data.value.document_pipeline.coverage"
              :key="item.label"
              :label="`${item.label} ${item.value}${item.unit}`"
            />
          </div>
        </article>

        <article class="panel">
          <div class="panel-header">
            <h3>解析作业队列</h3>
          </div>
          <div class="timeline-list">
            <div
              v-for="item in state.data.value.document_pipeline_jobs.stage_summary"
              :key="item.stage"
              class="timeline-item"
            >
              <strong>{{ item.stage }}</strong>
              <span>completed {{ item.completed }} · pending {{ item.pending }} · blocked {{ item.blocked }}</span>
              <button
                v-if="item.stage !== 'cell_trace'"
                type="button"
                class="button-secondary"
                :disabled="runningStage === item.stage"
                @click="runStage(item.stage)"
              >
                {{ runningStage === item.stage ? '执行中' : '执行 5 条' }}
              </button>
            </div>
          </div>
        </article>
      </section>

      <section>
        <div class="page-header" style="margin-top: 32px; margin-bottom: 16px;">
          <h3>文档升级结果</h3>
        </div>
        <div class="company-grid">
          <article
            v-for="job in (resultsState.data.value?.results || []).slice(0, 18)"
            :key="`${job.report_id}-${job.stage}`"
            class="company-card"
          >
            <div class="signal-top">
              <div>
                <div class="signal-code">{{ job.stage }}</div>
                <h4>{{ job.company_name }}</h4>
              </div>
              <div class="signal-subtitle">{{ job.status }}</div>
            </div>
            <div class="metric-list">
              <div class="metric-row"><span>报期</span><strong>{{ job.report_period || '-' }}</strong></div>
              <div class="metric-row"><span>报告</span><strong>{{ job.report_id }}</strong></div>
              <div class="metric-row"><span>摘要</span><strong>{{ job.artifact_summary || '-' }}</strong></div>
            </div>
          </article>
        </div>
      </section>

      <section class="split-grid">
        <article class="panel">
          <div class="panel-header">
            <h3>2026 技术雷达</h3>
          </div>
          <div class="timeline-list">
            <div
              v-for="item in state.data.value.innovation_radar.items"
              :key="item.id"
              class="timeline-item"
            >
              <strong>{{ item.title }}</strong>
              <span>{{ item.domain }} · {{ item.source }} · {{ item.year }}</span>
              <div class="tag-row">
                <TagPill v-for="point in item.core_points" :key="point" :label="point" />
              </div>
              <a class="inline-link" :href="item.url" target="_blank" rel="noreferrer">查看论文</a>
            </div>
          </div>
        </article>

        <article class="panel">
          <div class="panel-header">
            <h3>最近运行历史</h3>
          </div>
          <div class="timeline-list">
            <div
              v-for="run in state.data.value.workspace_runs.runs"
              :key="run.run_id"
              class="timeline-item"
            >
              <strong>{{ run.company_name || '行业巡检' }}</strong>
              <span>{{ run.query }}</span>
              <div class="metric-list">
                <div class="metric-row"><span>类型</span><strong>{{ run.query_type }}</strong></div>
                <div class="metric-row"><span>角色</span><strong>{{ run.user_role }}</strong></div>
                <div class="metric-row"><span>时间</span><strong>{{ run.created_at?.slice(0, 19).replace('T', ' ') }}</strong></div>
              </div>
            </div>
          </div>
        </article>
      </section>

      <section>
        <div class="page-header" style="margin-top: 32px; margin-bottom: 16px;">
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
