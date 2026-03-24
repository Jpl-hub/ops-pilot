<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, RouterLink } from 'vue-router'

import AppShell from '@/components/AppShell.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingState from '@/components/LoadingState.vue'
import TagPill from '@/components/TagPill.vue'
import { useAsyncState } from '@/composables/useAsyncState'
import { get, post } from '@/lib/api'

const state = useAsyncState<any>()
const pipelineRunState = useAsyncState<any>()
const resultsState = useAsyncState<any>()
const detailState = useAsyncState<any>()
const runningStage = ref('')
const selectedIssueCode = ref('')
const selectedCompanyName = ref('')
const route = useRoute()

const selectedStage = computed(() => String(route.query.stage || ''))
const selectedReportId = computed(() => String(route.query.report_id || ''))
const issueBuckets = computed(() => state.data.value?.quality_overview?.issue_buckets || [])
const filteredCompanies = computed(() => {
  const companies = state.data.value?.quality_overview?.companies || []
  if (!selectedIssueCode.value) {
    return companies
  }
  return companies.filter((row: any) => row.issues.includes(selectedIssueCode.value))
})
const blockerSummary = computed(() => {
  return issueBuckets.value.map((bucket: any) => ({
    ...bucket,
    ratio:
      state.data.value?.quality_overview?.coverage?.pool_companies
        ? Math.round((bucket.count / state.data.value.quality_overview.coverage.pool_companies) * 100)
        : 0,
  }))
})
const selectedCompanyDetail = computed(() => {
  const companies = filteredCompanies.value
  if (!companies.length) {
    return null
  }
  return companies.find((row: any) => row.company_name === selectedCompanyName.value) || companies[0]
})
const selectedCompanyIssueGuide = computed(() => {
  const row = selectedCompanyDetail.value
  if (!row) {
    return []
  }
  const guideMap: Record<string, { owner: string; action: string }> = {
    '缺定期报告': { owner: '数据接入', action: '优先补原始定期报告清单和归档文件。' },
    '缺页级解析': { owner: '文档解析', action: '检查 bronze 页级 JSON 是否生成并回填 manifest。' },
    '缺结构化指标': { owner: '指标抽取', action: '回看 silver 抽取结果与异常拦截规则。' },
    '缺研报': { owner: '研究接入', action: '补齐公司研报源，避免核验与横评能力失效。' },
    '缺主周期': { owner: '主周期治理', action: '补齐主报期数据，避免当前周期无法评估。' },
  }
  return row.issues.map((issue: string) => ({
    issue,
    owner: guideMap[issue]?.owner || '数据治理',
    action: guideMap[issue]?.action || '需要补充对应链路数据。',
  }))
})

onMounted(() => {
  void state.execute(() => get('/admin/overview'))
  void resultsState.execute(() => get('/admin/document-pipeline/results?limit=12'))
})

watch(
  filteredCompanies,
  (companies) => {
    if (!companies.length) {
      selectedCompanyName.value = ''
      return
    }
    if (!companies.some((row: any) => row.company_name === selectedCompanyName.value)) {
      selectedCompanyName.value = companies[0].company_name
    }
  },
  { immediate: true },
)

watch(
  [selectedStage, selectedReportId],
  async ([stage, reportId]) => {
    if (!stage || !reportId) {
      detailState.data.value = null
      return
    }
    await detailState.execute(() => get(`/admin/document-pipeline/results/${encodeURIComponent(stage)}/${encodeURIComponent(reportId)}`))
  },
  { immediate: true },
)

async function runStage(stage: 'cross_page_merge' | 'title_hierarchy' | 'cell_trace') {
  runningStage.value = stage
  await pipelineRunState.execute(() => post('/admin/document-pipeline/run', { stage, limit: 5 }))
  await state.execute(() => get('/admin/overview'))
  await resultsState.execute(() => get(`/admin/document-pipeline/results?stage=${stage}&limit=12`))
  runningStage.value = ''
}

function toggleIssueFilter(issueCode: string) {
  selectedIssueCode.value = selectedIssueCode.value === issueCode ? '' : issueCode
}
</script>

<template>
  <AppShell title="系统管理台" subtitle="全域数据覆盖与文档解析追踪" compact>
    <div class="dashboard-wrapper">
      <LoadingState v-if="state.loading.value" class="state-container" />
      <ErrorState v-else-if="state.error.value" :message="state.error.value" class="state-container" />
      
      <div v-else-if="state.data.value" class="admin-dashboard-grid">
        
        <!-- Top Health Strip -->
        <section class="glass-panel metrics-strip">
          <div class="metric-block">
            <span class="mb-label">系统状态</span>
            <div class="mb-val-wrap"><span class="status-dot"></span><strong class="mb-value text-accent">{{ state.data.value.health.status }}</strong></div>
            <span class="muted text-xs">{{ state.data.value.health.env }}</span>
          </div>
          <div class="metric-block">
            <span class="mb-label">主评估周期</span>
            <strong class="mb-value">{{ state.data.value.health.preferred_period }}</strong>
            <span class="muted text-xs">公司池 {{ state.data.value.health.companies }} 家</span>
          </div>
          <div class="metric-block">
            <span class="mb-label">原始定期报告</span>
            <strong class="mb-value">{{ state.data.value.data_status.periodic_reports.record_count }}</strong>
            <span class="muted text-xs">实供公司 {{ state.data.value.data_status.periodic_reports.company_count }} 家</span>
          </div>
          <div class="metric-block border-none">
            <span class="mb-label">结构化指标池</span>
            <strong class="mb-value text-gradient">{{ state.data.value.data_status.silver_financial_metrics.record_count }}</strong>
            <span class="muted text-xs">覆盖 {{ state.data.value.data_status.silver_financial_metrics.company_count }} 家</span>
          </div>
        </section>

        <!-- 2 Columns Panel -->
        <div class="admin-cols">
          <!-- LEFT COLUMN -->
          <div class="admin-col">
            
            <article class="glass-panel p-panel">
              <h3 class="panel-sm-title mb-4">覆盖诊断与漏斗</h3>
              <div class="metrics-grid-compact">
                <div class="stat-mini glass-panel-hover">
                  <span class="sm-label">正式公司池</span>
                  <strong class="sm-value">{{ state.data.value.quality_overview.coverage.pool_companies }}</strong>
                </div>
                <div class="stat-mini glass-panel-hover" style="border-color: rgba(16,185,129,0.3);">
                  <span class="sm-label text-accent">主周期可评估</span>
                  <strong class="sm-value">{{ state.data.value.quality_overview.coverage.preferred_period_ready }}</strong>
                </div>
                <div class="stat-mini glass-panel-hover">
                  <span class="sm-label">有真实研报</span>
                  <strong class="sm-value">{{ state.data.value.quality_overview.coverage.research_ready }}</strong>
                </div>
                <div class="stat-mini glass-panel-hover">
                  <span class="sm-label">页级解析打通</span>
                  <strong class="sm-value">{{ state.data.value.quality_overview.coverage.bronze_ready }}</strong>
                </div>
              </div>
              
                <div v-if="state.data.value.quality_overview.issue_buckets?.length" class="mt-4 border-t-subtle pt-4">
                  <span class="eyebrow inline-mr">异常阻断分桶:</span>
                  <div class="tag-row compact-tags mt-2">
                  <button
                    v-for="bucket in issueBuckets"
                    :key="bucket.code"
                    type="button"
                    class="bucket-filter"
                    :class="{ active: selectedIssueCode === bucket.code }"
                    @click="toggleIssueFilter(bucket.code)"
                  >
                    <TagPill :label="`${bucket.label} ${bucket.count}`" tone="risk" />
                  </button>
                </div>
              </div>
            </article>

            <article class="glass-panel p-panel mt-6">
              <div class="panel-head-compact">
                <h3 class="panel-sm-title mb-4">交付就绪度</h3>
                <span class="readiness-badge" :class="`is-${state.data.value.delivery_readiness.stage}`">
                  {{ state.data.value.delivery_readiness.stage.toUpperCase() }}
                </span>
              </div>
              <div class="readiness-grid">
                <div class="readiness-stat">
                  <span>主周期覆盖</span>
                  <strong>{{ state.data.value.delivery_readiness.coverage_ratio }}%</strong>
                </div>
                <div class="readiness-stat">
                  <span>银层就绪</span>
                  <strong>{{ state.data.value.delivery_readiness.silver_ratio }}%</strong>
                </div>
                <div class="readiness-stat">
                  <span>研报就绪</span>
                  <strong>{{ state.data.value.delivery_readiness.research_ratio }}%</strong>
                </div>
                <div class="readiness-stat">
                  <span>可直接交付</span>
                  <strong>{{ state.data.value.delivery_readiness.ready_company_count }}</strong>
                </div>
              </div>
              <div class="readiness-actions">
                <div
                  v-for="item in state.data.value.delivery_readiness.priority_actions"
                  :key="item.title"
                  class="readiness-action-card"
                >
                  <div class="readiness-action-head">
                    <strong>{{ item.title }}</strong>
                    <span class="muted text-xs">{{ item.companies.length ? `${item.companies.length} 家样本` : '系统级' }}</span>
                  </div>
                  <p>{{ item.summary }}</p>
                  <div v-if="item.companies.length" class="tag-row compact-tags">
                    <span v-for="company in item.companies" :key="company" class="tag subtle-tag text-xs">{{ company }}</span>
                  </div>
                </div>
              </div>
            </article>

            <article v-if="blockerSummary.length" class="glass-panel p-panel mt-6">
              <h3 class="panel-sm-title mb-4">阻断分布</h3>
              <div class="bucket-list">
                <div v-for="bucket in blockerSummary" :key="bucket.code" class="bucket-row">
                  <div class="bucket-meta">
                    <strong>{{ bucket.label }}</strong>
                    <span>{{ bucket.count }} 家</span>
                  </div>
                  <div class="bucket-bar-track">
                    <i class="bucket-bar-fill" :style="{ width: `${bucket.ratio}%` }" />
                  </div>
                  <small class="muted">{{ bucket.ratio }}%</small>
                </div>
              </div>
            </article>

            <article class="glass-panel p-panel mt-6">
              <h3 class="panel-sm-title mb-4">解析引擎与链条</h3>
              <div class="engine-list">
                <div class="engine-row">
                  <span class="muted">版面还原</span>
                  <strong class="eg-val">{{ state.data.value.document_pipeline.layout_engine }}</strong>
                </div>
                <div class="engine-row">
                  <span class="muted">OCR核心</span>
                  <strong class="eg-val">{{ state.data.value.document_pipeline.ocr_engine }}</strong>
                  <span class="tag subtle-tag ml-auto" :class="state.data.value.document_pipeline.ocr_runtime_enabled ? 'text-accent' : ''">{{ state.data.value.document_pipeline.ocr_runtime_enabled ? 'Active' : 'Planned' }}</span>
                </div>
                <div class="engine-row">
                  <span class="muted">跨页拼接</span>
                  <strong class="eg-val">{{ state.data.value.document_pipeline.cross_page_merge.status }}</strong>
                </div>
                <div class="engine-row">
                  <span class="muted">标题恢复</span>
                  <strong class="eg-val">{{ state.data.value.document_pipeline.title_hierarchy.status }}</strong>
                </div>
              </div>
              
              <div class="mt-4 flex gap-2">
                <span v-for="item in state.data.value.document_pipeline.coverage" :key="item.label" class="minimal-stat">
                   {{ item.label }} <strong class="ml-1">{{ item.value }}{{ item.unit }}</strong>
                </span>
              </div>
            </article>

            <article class="glass-panel p-panel mt-6 min-h-[300px]">
              <h3 class="panel-sm-title mb-4">执行作业队列</h3>
              <div class="job-list">
                <div
                  v-for="item in state.data.value.document_pipeline_jobs.stage_summary"
                  :key="item.stage"
                  class="job-card glass-panel-hover"
                >
                  <div class="jc-head">
                    <strong class="jc-stage">{{ item.stage }}</strong>
                    <button
                      v-if="item.stage !== 'cell_trace'"
                      class="button-secondary glow-button-small"
                      :disabled="runningStage === item.stage"
                      @click="runStage(item.stage)"
                    >
                      {{ runningStage === item.stage ? 'RUNNING' : 'EXECUTE BATCH' }}
                    </button>
                    <span v-else class="text-xs muted">
                      {{ state.data.value.document_pipeline.ocr_runtime_enabled ? 'WAITING OCR' : 'BLOCKED' }}
                    </span>
                  </div>
                  <div class="jc-stats">
                    <span class="text-accent">✔ {{ item.completed }}</span>
                    <span class="text-[#fbbf24]">⟳ {{ item.pending }}</span>
                    <span class="risk-text">✖ {{ item.blocked }}</span>
                  </div>
                </div>
              </div>
            </article>
            
            <!-- 技术雷达 -->
             <article class="glass-panel p-panel mt-6">
               <h3 class="panel-sm-title mb-4">技术雷达 2026</h3>
               <div class="radar-list">
                 <div v-for="item in state.data.value.innovation_radar.items" :key="item.id" class="radar-card glass-panel-hover">
                   <div class="rd-head">
                     <span class="rd-domain">{{ item.domain }}</span>
                     <span class="rd-year">{{ item.year }} · {{ item.source }}</span>
                   </div>
                   <h4 class="rd-title">{{ item.title }}</h4>
                   <div class="tag-row compact-tags mb-3">
                     <TagPill v-for="point in item.core_points" :key="point" :label="point" />
                   </div>
                   <a class="inline-glass-link text-center w-full block" :href="item.url" target="_blank" rel="noreferrer">SOURCE CODE / PAPER</a>
                 </div>
               </div>
             </article>

          </div>

          <!-- RIGHT COLUMN -->
          <div class="admin-col">

             <!-- Detail Inspector -->
             <article v-if="detailState.data.value" class="glass-panel p-panel highlight-panel mb-6">
                <div class="panel-header flex justify-between items-center mb-4">
                  <h3 class="panel-sm-title m-0 border-none pb-0">解析调试终端</h3>
                  <button class="icon-btn" @click="$router.push({ query: {} })">×</button>
                </div>
                <div class="inspector-head mb-4">
                  <div class="ih-row"><span class="muted w-16">STAGE</span><strong class="text-gradient">{{ detailState.data.value.job.stage }}</strong></div>
                  <div class="ih-row"><span class="muted w-16">CORP</span><strong>{{ detailState.data.value.job.company_name }}</strong></div>
                  <div class="ih-row"><span class="muted w-16">PERIOD</span><strong>{{ detailState.data.value.job.report_period || '-' }}</strong></div>
                  <div class="ih-row"><span class="muted w-16">STATUS</span><span class="tag" :class="detailState.data.value.job.status === 'completed' ? 'success-tag' : detailState.data.value.job.status === 'blocked' ? 'risk-tag' : 'subtle-tag'">{{ detailState.data.value.job.status }}</span></div>
                </div>

                <div class="terminal-view scroll-area">
                  <div v-for="section in (detailState.data.value.consumable_sections || [])" :key="section.section_type" class="tv-block">
                     <div class="tv-title">> {{ section.title }} ({{ section.count }})</div>
                     <div v-for="(item, i) in section.items.slice(0, 5)" :key="i" class="tv-line">
                       <span class="tv-text">{{ String(item.text || item.title || item.reason || 'ITEM').substring(0, 60) }}...</span>
                       <span class="tv-page">p.{{ item.page || item.level || item.to_page || '--' }}</span>
                     </div>
                  </div>
                </div>
                
                <div class="mt-4 flex gap-2" v-if="detailState.data.value.evidence_navigation?.links?.length">
                  <RouterLink
                    v-for="link in detailState.data.value.evidence_navigation.links"
                    :key="`${link.path}-${link.label}`"
                    class="button-primary glow-button-small flex-1 text-center"
                    style="line-height: normal;"
                    :to="{ path: link.path, query: link.query || {} }"
                  >{{ link.label }}</RouterLink>
                </div>
             </article>

             <!-- Latest Results -->
             <article class="glass-panel p-panel mb-6">
               <h3 class="panel-sm-title mb-4">升级结果日志</h3>
               <div class="logs-grid">
                  <div v-for="job in (resultsState.data.value?.results || []).slice(0, 16)" :key="`${job.report_id}-${job.stage}`" class="log-card glass-panel-hover">
                     <div class="lc-head">
                       <span class="lc-stage">{{ job.stage }}</span>
                       <span class="status-dot" :class="`is-${job.status}`"></span>
                     </div>
                     <h4 class="lc-company">{{ job.company_name }}</h4>
                     <p class="lc-summary muted">{{ job.artifact_summary || 'No summary generated' }}</p>
                     <div class="lc-foot">
                       <span>{{ job.report_period || '-' }}</span>
                       <RouterLink class="inline-glass-link py-1 px-3" :to="{ path: '/admin', query: { stage: job.stage, report_id: job.report_id } }">INSPECT</RouterLink>
                     </div>
                  </div>
               </div>
             </article>

             <article v-if="selectedCompanyDetail" class="glass-panel p-panel mb-6">
               <div class="matrix-header">
                 <h3 class="panel-sm-title mb-4">公司问题诊断卡</h3>
                 <span class="muted text-xs">{{ selectedCompanyDetail.subindustry }}</span>
               </div>
               <div class="company-detail-head">
                 <div>
                   <strong class="detail-company">{{ selectedCompanyDetail.company_name }}</strong>
                   <div class="detail-periods">
                     <span>主周期: {{ state.data.value.health.preferred_period || '-' }}</span>
                     <span>最新银层: {{ selectedCompanyDetail.latest_silver_period || '-' }}</span>
                   </div>
                 </div>
                 <div class="detail-health" :class="{ healthy: selectedCompanyDetail.issues.length === 0 }">
                   {{ selectedCompanyDetail.issues.length === 0 ? 'READY' : `${selectedCompanyDetail.issues.length} BLOCKERS` }}
                 </div>
               </div>
               <div class="detail-stats">
                 <div class="detail-stat">
                   <span>RAW</span>
                   <strong>{{ selectedCompanyDetail.raw_report_count }}</strong>
                 </div>
                 <div class="detail-stat">
                   <span>BRONZE</span>
                   <strong>{{ selectedCompanyDetail.bronze_report_count }}</strong>
                 </div>
                 <div class="detail-stat">
                   <span>SILVER</span>
                   <strong>{{ selectedCompanyDetail.silver_record_count }}</strong>
                 </div>
                 <div class="detail-stat">
                   <span>RESEARCH</span>
                   <strong>{{ selectedCompanyDetail.research_report_count }}</strong>
                 </div>
               </div>
               <div v-if="selectedCompanyIssueGuide.length" class="issue-guide-list">
                 <div v-for="item in selectedCompanyIssueGuide" :key="item.issue" class="issue-guide-card">
                   <div class="issue-guide-head">
                     <TagPill :label="item.issue" tone="risk" />
                     <span class="muted text-xs">{{ item.owner }}</span>
                   </div>
                   <p>{{ item.action }}</p>
                 </div>
               </div>
               <div v-else class="healthy-note">
                 当前公司主链路已打通，可以直接进入评分、风控和核验能力。
               </div>
             </article>

             <!-- Company Coverage -->
             <article class="glass-panel p-panel">
               <div class="matrix-header">
                 <h3 class="panel-sm-title mb-4">公司级覆盖矩阵</h3>
                 <span class="muted text-xs">
                   {{ selectedIssueCode ? `已筛选: ${selectedIssueCode}` : `展示全部 ${filteredCompanies.length} 家` }}
                 </span>
               </div>
               <div class="matrix-list">
                 <button
                   v-for="row in filteredCompanies.slice(0, 12)"
                   :key="row.company_name"
                   type="button"
                   class="matrix-card glass-panel-hover matrix-button"
                   :class="{ active: selectedCompanyName === row.company_name }"
                   @click="selectedCompanyName = row.company_name"
                 >
                   <div class="mx-head">
                     <strong class="mx-company">{{ row.company_name }}</strong>
                     <span class="mx-period inline-mr">{{ row.latest_silver_period }}</span>
                   </div>
                   <div class="mx-stats mt-2">
                     <div class="mx-stat"><span class="mx-val">{{ row.raw_report_count }}</span><span class="mx-lbl">RAW</span></div>
                     <div class="mx-stat"><span class="mx-val">{{ row.bronze_report_count }}</span><span class="mx-lbl">BRZ</span></div>
                     <div class="mx-stat"><span class="mx-val text-accent">{{ row.silver_record_count }}</span><span class="mx-lbl">SLV</span></div>
                     <div class="mx-stat"><span class="mx-val text-[#60a5fa]">{{ row.research_report_count }}</span><span class="mx-lbl">RSH</span></div>
                   </div>
                   <div class="mx-tags mt-3">
                     <span v-if="row.issues.length === 0" class="tag success-tag text-xs">OK</span>
                     <span v-for="flag in row.issues" :key="flag" class="tag risk-tag text-xs">{{ flag }}</span>
                   </div>
                 </button>
               </div>
               <div v-if="selectedIssueCode && filteredCompanies.length === 0" class="empty-matrix">
                 当前筛选下没有公司记录。
               </div>
             </article>

          </div>
        </div>

      </div>
    </div>
  </AppShell>
</template>

<style scoped>
.dashboard-wrapper { display: flex; flex-direction: column; gap: 24px; padding-bottom: 24px; overflow-y: auto; height: 100%; }

/* Metrics Strip */
.metrics-strip { display: grid; grid-template-columns: repeat(4, 1fr); padding: 16px 24px; border-radius: 16px; flex-shrink: 0; }
.metric-block { display: flex; flex-direction: column; gap: 6px; border-right: 1px solid rgba(255, 255, 255, 0.08); padding: 0 16px; }
.metric-block.border-none { border-right: none; }
.mb-label { font-size: 13px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; font-family: 'JetBrains Mono', monospace; }
.mb-value { font-size: 26px; line-height: 1; font-weight: 600; }
.mb-val-wrap { display: flex; align-items: center; gap: 10px; }
.status-dot { width: 10px; height: 10px; border-radius: 50%; background: #10b981; box-shadow: 0 0 10px #10b981; }
.status-dot.is-failed { background: #f43f5e; box-shadow: 0 0 10px #f43f5e; }
.status-dot.is-pending { background: #fbbf24; box-shadow: 0 0 10px #fbbf24; }
.text-accent { color: #10b981; }
.text-gradient { background-clip: text; -webkit-text-fill-color: transparent; background-image: linear-gradient(to right, #60a5fa, #34d399); }
.muted { color: var(--muted); }
.text-xs { font-size: 12px; }

/* Dashboard layout */
.admin-dashboard-grid { display: flex; flex-direction: column; gap: 24px; }
.admin-cols { display: grid; grid-template-columns: minmax(360px, 1fr) minmax(400px, 1.3fr); gap: 24px; }
.admin-col { display: flex; flex-direction: column; }
.scroll-area { overflow-y: auto; overflow-x: hidden; }
.scroll-area::-webkit-scrollbar { width: 4px; }
.p-panel { padding: 24px; border-radius: 20px; }
.mb-4 { margin-bottom: 16px; }
.mb-6 { margin-bottom: 24px; }
.mt-4 { margin-top: 16px; }
.mt-6 { margin-top: 24px; }
.mt-3 { margin-top: 12px; }
.mt-2 { margin-top: 8px; }

.panel-sm-title { font-size: 15px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); margin: 0; padding-bottom: 12px; border-bottom: 1px solid rgba(255,255,255,0.05); }

/* Left Col Mini Stats */
.metrics-grid-compact { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
.stat-mini { padding: 14px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.05); display: flex; flex-direction: column; gap: 6px; }
.sm-label { font-size: 12px; font-family: 'JetBrains Mono', monospace; color: var(--muted); }
.sm-value { font-size: 20px; font-weight: 600; }
.border-t-subtle { border-top: 1px solid rgba(255,255,255,0.05); }
.inline-mr { margin-right: 8px; font-size: 12px; color: var(--muted); }
.tag-row { display: flex; flex-wrap: wrap; gap: 6px; }
.bucket-filter {
  background: transparent;
  border: none;
  padding: 0;
  cursor: pointer;
}
.bucket-filter.active :deep(.tag-pill) {
  box-shadow: 0 0 0 1px rgba(244, 63, 94, 0.45);
}

.bucket-list { display: flex; flex-direction: column; gap: 12px; }
.bucket-row { display: grid; grid-template-columns: minmax(120px, 1fr) minmax(120px, 2fr) 48px; gap: 12px; align-items: center; }
.bucket-meta { display: flex; justify-content: space-between; gap: 12px; font-size: 13px; }
.bucket-bar-track { height: 8px; border-radius: 999px; background: rgba(255,255,255,0.08); overflow: hidden; }
.bucket-bar-fill { display: block; height: 100%; border-radius: inherit; background: linear-gradient(90deg, rgba(244,63,94,0.7), rgba(251,191,36,0.85)); }
.panel-head-compact { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.readiness-badge { padding: 4px 10px; border-radius: 999px; font-size: 11px; letter-spacing: 0.08em; font-family: 'JetBrains Mono', monospace; border: 1px solid rgba(255,255,255,0.1); }
.readiness-badge.is-ready { color: #10b981; border-color: rgba(16,185,129,0.35); background: rgba(16,185,129,0.12); }
.readiness-badge.is-hardening { color: #fbbf24; border-color: rgba(251,191,36,0.35); background: rgba(251,191,36,0.12); }
.readiness-badge.is-blocked { color: #f43f5e; border-color: rgba(244,63,94,0.35); background: rgba(244,63,94,0.12); }
.readiness-badge.is-bootstrapping { color: #60a5fa; border-color: rgba(96,165,250,0.35); background: rgba(96,165,250,0.12); }
.readiness-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; margin-top: 12px; }
.readiness-stat { border: 1px solid rgba(255,255,255,0.06); background: rgba(255,255,255,0.03); border-radius: 12px; padding: 14px; display: flex; flex-direction: column; gap: 8px; }
.readiness-stat span { color: var(--muted); font-size: 12px; }
.readiness-stat strong { font-size: 24px; line-height: 1; }
.readiness-actions { display: flex; flex-direction: column; gap: 12px; margin-top: 16px; }
.readiness-action-card { border: 1px solid rgba(255,255,255,0.06); background: rgba(0,0,0,0.16); border-radius: 12px; padding: 14px; }
.readiness-action-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 8px; }
.readiness-action-card p { margin: 0 0 10px; color: #cbd5e1; font-size: 13px; line-height: 1.5; }

/* Engines */
.engine-list { display: flex; flex-direction: column; gap: 12px; }
.engine-row { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; background: rgba(0,0,0,0.2); border-radius: 10px; font-size: 14px; }
.eg-val { font-family: 'JetBrains Mono', monospace; color: #f8fafc; }
.ml-1 { margin-left: 4px; }
.ml-auto { margin-left: auto; }
.minimal-stat { background: rgba(255,255,255,0.05); padding: 4px 8px; border-radius: 6px; font-size: 11px; font-family: 'JetBrains Mono', monospace; color: var(--muted); display: inline-flex; align-items: center; }

/* Jobs */
.min-h-\[300px\] { min-height: 280px; }
.job-list { display: flex; flex-direction: column; gap: 12px; }
.job-card { padding: 16px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.05); display: flex; flex-direction: column; gap: 12px; }
.jc-head { display: flex; justify-content: space-between; align-items: center; }
.jc-stage { font-family: 'JetBrains Mono', monospace; font-size: 14px; color: #fff; }
.glow-button-small { padding: 4px 12px; height: auto; min-height: 28px; font-size: 12px; border-radius: 6px; font-family: 'JetBrains Mono', monospace; }
.jc-stats { display: flex; gap: 16px; font-size: 12px; font-family: 'JetBrains Mono', monospace; background: rgba(0,0,0,0.2); padding: 8px 12px; border-radius: 8px; }
.risk-text { color: #f43f5e; }

/* Radar */
.radar-list { display: flex; flex-direction: column; gap: 12px; }
.radar-card { padding: 16px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.05); }
.rd-head { display: flex; justify-content: space-between; font-size: 11px; font-family: 'JetBrains Mono', monospace; margin-bottom: 8px; color: var(--muted); }
.rd-domain { color: #818cf8; }
.rd-title { font-size: 15px; color: #fff; margin: 0 0 12px; line-height: 1.4; }
.w-full { width: 100%; }
.block { display: block; }
.text-center { text-align: center; }

/* Terminal View */
.highlight-panel { border-color: rgba(96, 165, 250, 0.4); box-shadow: 0 0 20px rgba(96, 165, 250, 0.1); background: rgba(15, 23, 42, 0.6); }
.flex { display: flex; }
.justify-between { justify-content: space-between; }
.items-center { align-items: center; }
.border-none { border: none !important; }
.pb-0 { padding-bottom: 0 !important; }
.icon-btn { background: transparent; border: none; color: var(--muted); font-size: 24px; cursor: pointer; line-height: 1; }
.icon-btn:hover { color: #fff; }

.inspector-head { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; background: rgba(0,0,0,0.3); padding: 16px; border-radius: 12px; font-family: 'JetBrains Mono', monospace; font-size: 13px; }
.ih-row { display: flex; align-items: center; }
.w-16 { width: 60px; display: inline-block; }
.success-tag { background: rgba(16,185,129,0.1); color: #10b981; border: 1px solid rgba(16,185,129,0.3); }

.terminal-view { min-height: 380px; max-height: 500px; background: #000; border-radius: 12px; padding: 20px; font-family: 'JetBrains Mono', monospace; font-size: 13px; color: #10b981; }
.tv-block { margin-bottom: 16px; border-left: 2px solid rgba(16,185,129,0.4); padding-left: 14px; }
.tv-title { color: #60a5fa; margin-bottom: 8px; }
.tv-line { display: flex; justify-content: space-between; margin-bottom: 4px; opacity: 0.8; }
.tv-text { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; padding-right: 16px;}
.tv-page { color: #f59e0b; flex-shrink: 0;}
.flex-1 { flex: 1; }

/* Logs Grid */
.logs-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
.log-card { padding: 16px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.05); display: flex; flex-direction: column; gap: 8px; }
.lc-head { display: flex; justify-content: space-between; align-items: center; }
.lc-stage { font-size: 11px; font-family: 'JetBrains Mono', monospace; color: var(--muted); background: rgba(0,0,0,0.3); padding: 2px 6px; border-radius: 4px; }
.lc-company { margin: 0 0 2px; font-size: 15px; color: #fff; font-weight: 500; }
.lc-summary { font-size: 13px; margin: 0; line-height: 1.4; display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.lc-foot { display: flex; justify-content: space-between; align-items: center; font-size: 12px; font-family: 'JetBrains Mono', monospace; margin-top: 8px; color: var(--muted); }
.py-1 { padding-top: 4px; padding-bottom: 4px; }
.px-3 { padding-left: 12px; padding-right: 12px; }
.inline-glass-link { font-size: 12px; border-radius: 6px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); color: var(--text); text-decoration: none; transition: all 0.2s; text-align: center;}
.inline-glass-link:hover { background: rgba(59, 130, 246, 0.1); border-color: rgba(59, 130, 246, 0.3); color: #60a5fa; }

/* Matrix */
.matrix-list { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 16px; }
.matrix-header { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.matrix-card { padding: 16px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.05); display: flex; flex-direction: column; }
.mx-head { display: flex; justify-content: space-between; align-items: center; }
.mx-company { font-size: 15px; color: #fff; font-weight: 500;}
.mx-period { font-size: 11px; font-family: 'JetBrains Mono', monospace; }
.mx-stats { display: flex; justify-content: space-between; background: rgba(0,0,0,0.2); border-radius: 8px; padding: 10px; }
.mx-stat { display: flex; flex-direction: column; align-items: center; gap: 4px; }
.mx-val { font-size: 15px; font-weight: bold; }
.mx-lbl { font-size: 10px; color: var(--muted); font-family: 'JetBrains Mono', monospace; }
.mx-tags { display: flex; gap: 6px; flex-wrap: wrap; }
.empty-matrix { margin-top: 16px; color: var(--muted); font-size: 13px; }
</style>
