<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, RouterLink } from 'vue-router'

import AppShell from '@/components/AppShell.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingState from '@/components/LoadingState.vue'
import TagPill from '@/components/TagPill.vue'
import { useAsyncState } from '@/composables/useAsyncState'
import { get, getText, post } from '@/lib/api'

const state = useAsyncState<any>()
const deliveryReportState = useAsyncState<any>()
const pipelineRunState = useAsyncState<any>()
const resultsState = useAsyncState<any>()
const detailState = useAsyncState<any>()
const runningStage = ref('')
const exportingReport = ref<'markdown' | 'json' | ''>('')
const selectedIssueCode = ref('')
const selectedCompanyName = ref('')
const selectedArtifactSource = ref('')
const selectedContractStatus = ref('')
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
const issueLabelMap = computed(() => {
  return Object.fromEntries(issueBuckets.value.map((bucket: any) => [bucket.code, bucket.label]))
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
    '缺页级解析': { owner: '文档解析', action: '检查原始层页级结果是否生成并成功回填清单。' },
    '缺结构化指标': { owner: '指标抽取', action: '回看指标层抽取结果与异常拦截规则。' },
    '缺研报': { owner: '研究接入', action: '补齐公司研报源，避免核验与横评能力失效。' },
    '缺主周期': { owner: '主周期治理', action: '补齐主报期数据，避免当前周期无法评估。' },
  }
  return row.issues.map((issue: string) => ({
    issue,
    owner: guideMap[issue]?.owner || '数据治理',
    action: guideMap[issue]?.action || '需要补充对应链路数据。',
  }))
})

const deliveryReport = computed(() => deliveryReportState.data.value)
const workspaceRuntimeAudit = computed(() => state.data.value?.workspace_runtime_audit || null)
const topSummaryCards = computed(() => {
  const data = state.data.value
  if (!data) return []
  const health = data.health || {}
  const report = deliveryReport.value
  const streamingRuntime = data.streaming_runtime || {}
  const contractAudit = data.document_pipeline?.cell_trace?.contract_audit || {}
  return [
    {
      label: '系统状态',
      value: health.status || '-',
      hint: health.env || '未识别环境',
      tone: health.status === 'ok' ? 'success' : 'risk',
    },
    {
      label: '主评估周期',
      value: health.preferred_period || '-',
      hint: `公司池 ${health.companies || 0} 家`,
      tone: 'default',
    },
    {
      label: '稳定可用企业',
      value: String(report?.summary_cards?.ready_company_count ?? data.delivery_readiness?.ready_company_count ?? 0),
      hint: `待治理 ${report?.summary_cards?.blocked_company_count ?? data.delivery_readiness?.blocked_company_count ?? 0} 家`,
      tone: 'success',
    },
    {
      label: '实时外部信号',
      value: String(streamingRuntime.message_count ?? data.data_status?.bronze_signal_events?.record_count ?? 0),
      hint: streamingRuntime.freshness_label || '等待最新消息',
      tone: streamingRuntime.status === 'stale' || streamingRuntime.status === 'unavailable' ? 'risk' : 'default',
    },
    {
      label: 'OCR 结构契约',
      value: `${contractAudit.ready || 0}/${contractAudit.total || 0}`,
      hint: `缺失 ${contractAudit.missing || 0} · 不合格 ${contractAudit.invalid || 0}`,
      tone: (contractAudit.missing || 0) + (contractAudit.invalid || 0) > 0 ? 'risk' : 'success',
    },
    {
      label: '运行阻断',
      value: String(report?.summary_cards?.runtime_blocked_count ?? data.runtime_readiness?.blocked_count ?? 0),
      hint: `关键检查 ${report?.summary_cards?.acceptance_passed ?? data.acceptance_checklist?.passed ?? 0}/${report?.summary_cards?.acceptance_total ?? data.acceptance_checklist?.total ?? 0}`,
      tone: (report?.summary_cards?.runtime_blocked_count ?? data.runtime_readiness?.blocked_count ?? 0) > 0 ? 'risk' : 'default',
    },
  ]
})
const priorityActions = computed(() => state.data.value?.delivery_readiness?.priority_actions?.slice(0, 3) || [])
const focusedRuntimeChecks = computed(() => {
  const checks = state.data.value?.runtime_readiness?.checks || []
  return [...checks]
    .sort((left: any, right: any) => Number(right.status === 'blocked') - Number(left.status === 'blocked'))
    .slice(0, 4)
})
const focusedAcceptanceItems = computed(() => {
  const items = state.data.value?.acceptance_checklist?.items || []
  return [...items]
    .sort((left: any, right: any) => Number(right.status !== 'pass') - Number(left.status !== 'pass'))
    .slice(0, 5)
})
const focusedIssueBuckets = computed(() => deliveryReport.value?.issue_buckets?.slice(0, 4) || [])
const focusedRemediationRuns = computed(() => deliveryReport.value?.recent_remediation_runs?.slice(0, 3) || [])
const focusedContractSamples = computed(() => state.data.value?.document_pipeline?.cell_trace?.contract_audit?.samples?.slice(0, 3) || [])
const focusedResults = computed(() => (resultsState.data.value?.results || []).slice(0, 8))
const focusedWorkspaceHistory = computed(() => (state.data.value?.workspace_history?.records || []).slice(0, 4))
const focusedAuditCompanies = computed(() => workspaceRuntimeAudit.value?.company_heat?.slice(0, 3) || [])
const focusedAuditRuns = computed(() => workspaceRuntimeAudit.value?.recent_runs?.slice(0, 4) || [])

onMounted(() => {
  void refreshAdminState()
  void loadResults()
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
  await pipelineRunState.execute(() =>
    post('/admin/document-pipeline/run', {
      stage,
      limit: 5,
      artifact_source: stage === 'cell_trace' && selectedArtifactSource.value ? selectedArtifactSource.value : null,
      contract_status: stage === 'cell_trace' && selectedContractStatus.value ? selectedContractStatus.value : null,
    }),
  )
  await refreshAdminState()
  await loadResults(stage)
  runningStage.value = ''
}

async function refreshAdminState() {
  await Promise.all([
    state.execute(() => get('/admin/overview')),
    deliveryReportState.execute(() => get('/admin/delivery-report')),
  ])
}

function toggleIssueFilter(issueCode: string) {
  selectedIssueCode.value = selectedIssueCode.value === issueCode ? '' : issueCode
}

async function loadResults(stage = '') {
  const params = new URLSearchParams({ limit: '12' })
  if (stage) params.set('stage', stage)
  if (selectedArtifactSource.value) params.set('artifact_source', selectedArtifactSource.value)
  if (selectedContractStatus.value) params.set('contract_status', selectedContractStatus.value)
  await resultsState.execute(() => get(`/admin/document-pipeline/results?${params.toString()}`))
}

async function applyContractFilter(contractStatus = '', artifactSource = '') {
  selectedContractStatus.value = contractStatus
  selectedArtifactSource.value = artifactSource
  await loadResults('cell_trace')
}

async function clearPipelineFilter() {
  selectedContractStatus.value = ''
  selectedArtifactSource.value = ''
  await loadResults()
}

const canRerunFilteredCellTrace = computed(() => {
  return selectedContractStatus.value === 'missing' || selectedContractStatus.value === 'invalid'
})

function displayReadinessStage(stage?: string) {
  const map: Record<string, string> = {
    bootstrapping: '建设期',
    hardening: '优化期',
    blocked: '待处理',
    ready: '稳定',
    pass: '通过',
  }
  return map[stage || ''] || stage || '-'
}

function displayJobStatus(status?: string) {
  const map: Record<string, string> = {
    completed: '已完成',
    pending: '待执行',
    blocked: '已阻断',
    ready: '就绪',
    invalid: '不合格',
    missing: '缺失',
    pass: '通过',
  }
  return map[status || ''] || status || '-'
}

function displayPipelineStage(stage?: string) {
  const map: Record<string, string> = {
    cross_page_merge: '跨页拼接',
    title_hierarchy: '标题恢复',
    cell_trace: '单元格追踪',
  }
  return map[stage || ''] || stage || '-'
}

function displayArtifactSource(source?: string) {
  const map: Record<string, string> = {
    standard_ocr: '标准 OCR',
    geometric_fallback: '非正式历史产物',
  }
  return map[source || ''] || source || '-'
}

function displayHistoryType(historyType?: string) {
  const map: Record<string, string> = {
    document_pipeline_run: '治理运行',
    artifact: '产物记录',
    query: '查询记录',
  }
  return map[historyType || ''] || historyType || '-'
}

function formatMilliseconds(value?: number | null) {
  if (value === undefined || value === null) return '-'
  if (value < 1000) return `${Math.round(value)} ms`
  return `${(value / 1000).toFixed(2)} s`
}

function formatDecimal(value?: number | null) {
  if (value === undefined || value === null) return '-'
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}

async function exportDeliveryReport(format: 'markdown' | 'json') {
  exportingReport.value = format
  try {
    const content =
      format === 'markdown'
        ? await getText('/admin/delivery-report?format=markdown')
        : JSON.stringify(await get('/admin/delivery-report'), null, 2)
    const blob = new Blob([content], { type: format === 'markdown' ? 'text/markdown;charset=utf-8' : 'application/json;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = format === 'markdown' ? 'ops_runtime_report.md' : 'ops_runtime_report.json'
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(url)
  } finally {
    exportingReport.value = ''
  }
}
</script>

<template>
  <AppShell title="运营保障中心" subtitle="数据覆盖、解析质量与运行稳定性" compact>
    <div class="dashboard-wrapper">
      <LoadingState v-if="state.loading.value" class="state-container" />
      <ErrorState v-else-if="state.error.value" :message="state.error.value" class="state-container" />
      
      <div v-else-if="state.data.value" class="admin-dashboard-grid">
        
        <!-- Top Health Strip -->
        <section class="glass-panel metrics-strip">
          <div
            v-for="card in topSummaryCards"
            :key="card.label"
            class="metric-block"
            :class="`is-${card.tone}`"
          >
            <span class="mb-label">{{ card.label }}</span>
            <strong class="mb-value">{{ card.value }}</strong>
            <span class="muted text-xs">{{ card.hint }}</span>
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
                <h3 class="panel-sm-title mb-4">交付摘要</h3>
                <div class="flex gap-2">
                  <button
                    class="inline-glass-link py-1 px-3"
                    type="button"
                    :disabled="deliveryReportState.loading.value || exportingReport !== ''"
                    @click="exportDeliveryReport('markdown')"
                  >{{ exportingReport === 'markdown' ? '导出中' : '导出 Markdown' }}</button>
                  <button
                    class="inline-glass-link py-1 px-3"
                    type="button"
                    :disabled="deliveryReportState.loading.value || exportingReport !== ''"
                    @click="exportDeliveryReport('json')"
                  >{{ exportingReport === 'json' ? '导出中' : '导出 JSON' }}</button>
                </div>
              </div>
              <div v-if="deliveryReport" class="runtime-check-list">
                <div class="runtime-check-card" :class="deliveryReport.overall_status === 'ready' ? 'is-ready' : 'is-blocked'">
                  <div class="runtime-check-head">
                    <strong>{{ deliveryReport.overall_label }}</strong>
                    <span class="tag" :class="deliveryReport.overall_status === 'ready' ? 'success-tag' : 'risk-tag'">{{ deliveryReport.summary_cards.acceptance_passed }}/{{ deliveryReport.summary_cards.acceptance_total }}</span>
                  </div>
                  <p v-for="line in deliveryReport.executive_summary" :key="line">{{ line }}</p>
                  <code>{{ deliveryReport.generated_at }} · 主周期 {{ deliveryReport.preferred_period || '-' }}</code>
                </div>
                <div class="readiness-grid">
                  <div class="readiness-stat">
                    <span>正式公司池</span>
                    <strong>{{ deliveryReport.summary_cards.pool_companies }}</strong>
                  </div>
                  <div class="readiness-stat">
                    <span>稳定可用</span>
                    <strong>{{ deliveryReport.summary_cards.ready_company_count }}</strong>
                  </div>
                  <div class="readiness-stat">
                    <span>待治理公司</span>
                    <strong>{{ deliveryReport.summary_cards.blocked_company_count }}</strong>
                  </div>
                  <div class="readiness-stat">
                    <span>运行时阻断</span>
                    <strong>{{ deliveryReport.summary_cards.runtime_blocked_count }}</strong>
                  </div>
                </div>
                <div class="report-grid">
                  <div class="runtime-check-card" :class="deliveryReport.runtime_readiness.blocked_checks.length ? 'is-blocked' : 'is-ready'">
                    <div class="runtime-check-head">
                      <strong>运行阻断项</strong>
                      <span class="tag" :class="deliveryReport.runtime_readiness.blocked_checks.length ? 'risk-tag' : 'success-tag'">
                        {{ deliveryReport.runtime_readiness.blocked_checks.length || 0 }}
                      </span>
                    </div>
                    <div v-if="deliveryReport.runtime_readiness.blocked_checks.length" class="runtime-check-list compact-stack">
                      <div v-for="item in deliveryReport.runtime_readiness.blocked_checks.slice(0, 3)" :key="item.label" class="report-list-card">
                        <strong>{{ item.label }}</strong>
                        <p>{{ item.summary }}</p>
                        <code>{{ item.detail }}</code>
                        <p v-if="item.remediation" class="runtime-remediation">{{ item.remediation }}</p>
                      </div>
                    </div>
                    <p v-else>当前运行时检查已经清零，没有影响业务使用的阻断项。</p>
                  </div>
                  <div class="runtime-check-card" :class="deliveryReport.acceptance_checklist.blocked_items.length ? 'is-blocked' : 'is-ready'">
                    <div class="runtime-check-head">
                      <strong>当前待处理项</strong>
                      <span class="tag" :class="deliveryReport.acceptance_checklist.blocked_items.length ? 'risk-tag' : 'success-tag'">
                        {{ deliveryReport.acceptance_checklist.blocked_items.length || 0 }}
                      </span>
                    </div>
                    <div v-if="deliveryReport.acceptance_checklist.blocked_items.length" class="runtime-check-list compact-stack">
                      <div v-for="item in deliveryReport.acceptance_checklist.blocked_items.slice(0, 3)" :key="item.label" class="report-list-card">
                        <strong>{{ item.label }}</strong>
                        <p>{{ item.detail }}</p>
                      </div>
                    </div>
                    <p v-else>当前关键检查项已全部通过，系统处于稳定可用状态。</p>
                  </div>
                </div>
                <div class="report-grid">
                  <div class="runtime-check-card">
                    <div class="runtime-check-head">
                      <strong>当前问题簇</strong>
                      <span class="tag subtle-tag">{{ deliveryReport.issue_buckets.length }} 类</span>
                    </div>
                    <div v-if="focusedIssueBuckets.length" class="tag-row compact-tags">
                      <span
                        v-for="bucket in focusedIssueBuckets"
                        :key="bucket.label"
                        class="tag risk-tag text-xs"
                      >{{ bucket.label }} {{ bucket.count }}</span>
                    </div>
                    <p v-else>当前没有新增问题簇，覆盖诊断已趋于稳定。</p>
                  </div>
                  <div class="runtime-check-card">
                    <div class="runtime-check-head">
                      <strong>最近治理轨迹</strong>
                      <span class="tag subtle-tag">{{ deliveryReport.recent_remediation_runs.length }} 条</span>
                    </div>
                    <div v-if="focusedRemediationRuns.length" class="runtime-check-list compact-stack">
                      <div
                        v-for="item in focusedRemediationRuns"
                        :key="`${item.title}-${item.created_at}`"
                        class="report-list-card"
                      >
                        <strong>{{ item.title }}</strong>
                        <p>{{ item.headline || '已完成一次治理执行。' }}</p>
                        <code>{{ item.created_at || '-' }} · 修复 {{ item.fixed_count || 0 }} · 剩余 {{ item.remaining_count || 0 }}</code>
                      </div>
                    </div>
                    <p v-else>当前还没有形成正式治理轨迹。</p>
                  </div>
                </div>
              </div>
            </article>

            <article class="glass-panel p-panel mt-6">
              <div class="panel-head-compact">
                <h3 class="panel-sm-title mb-4">系统就绪度</h3>
                <span class="readiness-badge" :class="`is-${state.data.value.delivery_readiness.stage}`">
                  {{ displayReadinessStage(state.data.value.delivery_readiness.stage) }}
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
                  <span>OCR 结构契约</span>
                  <strong>{{ state.data.value.delivery_readiness.contract_ratio }}%</strong>
                </div>
                <div class="readiness-stat">
                  <span>稳定可用</span>
                  <strong>{{ state.data.value.delivery_readiness.ready_company_count }}</strong>
                </div>
              </div>
              <div class="readiness-actions">
                <div
                  v-for="item in priorityActions"
                  :key="item.title"
                  class="readiness-action-card"
                >
                  <div class="readiness-action-head">
                    <strong>{{ item.title }}</strong>
                    <span class="muted text-xs">{{ item.companies.length ? `${item.companies.length} 家公司` : '系统级' }}</span>
                  </div>
                  <p>{{ item.summary }}</p>
                  <div v-if="item.companies.length" class="tag-row compact-tags">
                    <span v-for="company in item.companies" :key="company" class="tag subtle-tag text-xs">{{ company }}</span>
                  </div>
                </div>
              </div>
            </article>

            <article class="glass-panel p-panel mt-6">
              <div class="panel-head-compact">
                <h3 class="panel-sm-title mb-4">当前阻断</h3>
                <span class="readiness-badge" :class="`is-${state.data.value.runtime_readiness.status}`">
                  {{ displayReadinessStage(state.data.value.runtime_readiness.status) }}
                </span>
              </div>
              <div class="runtime-check-list">
                <div
                  v-for="item in focusedRuntimeChecks"
                  :key="item.key"
                  class="runtime-check-card"
                  :class="`is-${item.status}`"
                >
                  <div class="runtime-check-head">
                    <strong>{{ item.label }}</strong>
                    <span class="tag" :class="item.status === 'ready' ? 'success-tag' : 'risk-tag'">{{ displayJobStatus(item.status) }}</span>
                  </div>
                  <p>{{ item.summary }}</p>
                  <code>{{ item.detail }}</code>
                  <p v-if="item.remediation" class="runtime-remediation">{{ item.remediation }}</p>
                </div>
              </div>
            </article>

            <article class="glass-panel p-panel mt-6">
              <div class="panel-head-compact">
                <h3 class="panel-sm-title mb-4">关键检查清单</h3>
                <span class="readiness-badge" :class="`is-${state.data.value.acceptance_checklist.status}`">
                  {{ state.data.value.acceptance_checklist.passed }}/{{ state.data.value.acceptance_checklist.total }}
                </span>
              </div>
              <div class="runtime-check-list">
                <div
                  v-for="item in focusedAcceptanceItems"
                  :key="item.key"
                  class="runtime-check-card"
                  :class="item.status === 'pass' ? 'is-ready' : 'is-blocked'"
                >
                  <div class="runtime-check-head">
                    <strong>{{ item.label }}</strong>
                    <span class="tag" :class="item.status === 'pass' ? 'success-tag' : 'risk-tag'">{{ displayJobStatus(item.status) }}</span>
                  </div>
                  <p>{{ item.detail }}</p>
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
                  <span class="tag subtle-tag ml-auto" :class="state.data.value.document_pipeline.ocr_runtime_enabled ? 'text-accent' : 'risk-text'">{{ state.data.value.document_pipeline.ocr_runtime_enabled ? '已接通' : '未接通' }}</span>
                </div>
                <div class="engine-row">
                  <span class="muted">跨页拼接</span>
                  <strong class="eg-val">{{ displayJobStatus(state.data.value.document_pipeline.cross_page_merge.status) }}</strong>
                </div>
                <div class="engine-row">
                  <span class="muted">标题恢复</span>
                  <strong class="eg-val">{{ displayJobStatus(state.data.value.document_pipeline.title_hierarchy.status) }}</strong>
                </div>
                <div class="engine-row">
                  <span class="muted">OCR 结构契约</span>
                  <strong class="eg-val">{{ displayJobStatus(state.data.value.document_pipeline.cell_trace.contract_audit.status) }}</strong>
                  <span class="tag subtle-tag ml-auto">
                    {{ state.data.value.document_pipeline.cell_trace.contract_audit.ready }}/{{ state.data.value.document_pipeline.cell_trace.contract_audit.total || 0 }}
                  </span>
                </div>
              </div>
              
              <div class="mt-4 flex gap-2">
                <span v-for="item in state.data.value.document_pipeline.coverage" :key="item.label" class="minimal-stat">
                   {{ item.label }} <strong class="ml-1">{{ item.value }}{{ item.unit }}</strong>
                </span>
              </div>
            </article>

            <article class="glass-panel p-panel mt-6" v-if="state.data.value.document_pipeline.cell_trace.contract_audit.total">
              <div class="panel-head-compact">
                <h3 class="panel-sm-title mb-4">OCR 结构契约巡检</h3>
                <div class="flex gap-2">
                  <button
                    v-if="canRerunFilteredCellTrace"
                    class="inline-glass-link py-1 px-3"
                    type="button"
                    @click="runStage('cell_trace')"
                  >重跑当前筛选</button>
                  <button class="inline-glass-link py-1 px-3" type="button" @click="clearPipelineFilter">清除筛选</button>
                </div>
              </div>
              <div class="readiness-grid">
                <button class="readiness-stat" type="button" @click="applyContractFilter('ready', 'standard_ocr')">
                  <span>达标</span>
                  <strong>{{ state.data.value.document_pipeline.cell_trace.contract_audit.ready }}</strong>
                </button>
                <button class="readiness-stat" type="button" @click="applyContractFilter('missing')">
                  <span>缺失</span>
                  <strong>{{ state.data.value.document_pipeline.cell_trace.contract_audit.missing }}</strong>
                </button>
                <button class="readiness-stat" type="button" @click="applyContractFilter('invalid')">
                  <span>不合格</span>
                  <strong>{{ state.data.value.document_pipeline.cell_trace.contract_audit.invalid }}</strong>
                </button>
                <div class="readiness-stat">
                  <span>总数</span>
                  <strong>{{ state.data.value.document_pipeline.cell_trace.contract_audit.total }}</strong>
                </div>
              </div>
              <div class="runtime-check-list mt-4">
                <div
                  v-for="item in focusedContractSamples"
                  :key="`${item.report_id}-${item.path}`"
                  class="runtime-check-card"
                  :class="`is-${item.status === 'ready' ? 'ready' : 'blocked'}`"
                  >
                    <div class="runtime-check-head">
                      <strong>{{ item.company_name }} · {{ item.report_id }}</strong>
                      <span class="tag" :class="item.status === 'ready' ? 'success-tag' : 'risk-tag'">{{ displayJobStatus(item.status) }}</span>
                    </div>
                    <p>{{ item.detail }}</p>
                    <div class="mt-3">
                      <button class="inline-glass-link py-1 px-3" type="button" @click="applyContractFilter(item.status, item.status === 'ready' ? 'standard_ocr' : '')">筛到结果日志</button>
                    </div>
                  </div>
              </div>
            </article>

            <article class="glass-panel p-panel mt-6 min-h-[300px]">
              <h3 class="panel-sm-title mb-4">执行作业队列</h3>
              <div v-if="pipelineRunState.data.value?.execution_feedback" class="runtime-check-list mb-4">
                <div class="runtime-check-card is-ready">
                  <div class="runtime-check-head">
                    <strong>最近一次执行反馈</strong>
                    <span class="tag success-tag">{{ pipelineRunState.data.value.execution_feedback.processed }}</span>
                  </div>
                  <p>{{ pipelineRunState.data.value.execution_feedback.headline }}</p>
                  <code>修复 {{ pipelineRunState.data.value.execution_feedback.fixed_count || 0 }} · 剩余 {{ pipelineRunState.data.value.execution_feedback.remaining_count || 0 }}</code>
                </div>
              </div>
              <div class="job-list">
                <div
                  v-for="item in state.data.value.document_pipeline_jobs.stage_summary"
                  :key="item.stage"
                  class="job-card glass-panel-hover"
                >
                  <div class="jc-head">
                    <strong class="jc-stage">{{ item.stage }}</strong>
                    <button
                      v-if="item.pending > 0"
                      class="button-secondary glow-button-small"
                      :disabled="runningStage === item.stage"
                      @click="runStage(item.stage)"
                    >
                      {{ runningStage === item.stage ? '执行中' : item.stage === 'cell_trace' && canRerunFilteredCellTrace ? '重跑当前筛选' : '批量执行' }}
                    </button>
                    <span v-else class="text-xs muted">
                      已完成
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
            
          </div>

          <!-- RIGHT COLUMN -->
          <div class="admin-col">

             <!-- Detail Inspector -->
             <article v-if="detailState.data.value" class="glass-panel p-panel highlight-panel mb-6">
                <div class="panel-header flex justify-between items-center mb-4">
                  <h3 class="panel-sm-title m-0 border-none pb-0">解析核验终端</h3>
                  <button class="icon-btn" @click="$router.push({ query: {} })">×</button>
                </div>
                <div class="inspector-head mb-4">
                  <div class="ih-row"><span class="muted w-16">工序</span><strong class="text-gradient">{{ displayPipelineStage(detailState.data.value.job.stage) }}</strong></div>
                  <div class="ih-row"><span class="muted w-16">公司</span><strong>{{ detailState.data.value.job.company_name }}</strong></div>
                  <div class="ih-row"><span class="muted w-16">报期</span><strong>{{ detailState.data.value.job.report_period || '-' }}</strong></div>
                  <div class="ih-row"><span class="muted w-16">状态</span><span class="tag" :class="detailState.data.value.job.status === 'completed' ? 'success-tag' : detailState.data.value.job.status === 'blocked' ? 'risk-tag' : 'subtle-tag'">{{ displayJobStatus(detailState.data.value.job.status) }}</span></div>
                  <div class="ih-row"><span class="muted w-16">来源</span><span class="tag subtle-tag">{{ displayArtifactSource(detailState.data.value.job.artifact_source || detailState.data.value.artifact?.source) }}</span></div>
                </div>

                <div class="runtime-check-list mb-4" v-if="detailState.data.value.remediation?.length">
                  <div
                    v-for="item in detailState.data.value.remediation"
                    :key="item.title"
                    class="runtime-check-card is-blocked"
                  >
                    <div class="runtime-check-head">
                      <strong>{{ item.title }}</strong>
                    </div>
                    <p class="runtime-remediation">{{ item.detail }}</p>
                  </div>
                </div>

                <div class="terminal-view scroll-area">
                  <div v-for="section in (detailState.data.value.consumable_sections || [])" :key="section.section_type" class="tv-block">
                     <div class="tv-title">> {{ section.title }} ({{ section.count }})</div>
                     <div v-for="(item, i) in section.items.slice(0, 5)" :key="i" class="tv-line">
                       <span class="tv-text">{{ String(item.text || item.title || item.reason || item.source || 'ITEM').substring(0, 60) }}...</span>
                       <span class="tv-page">{{ item.source || `p.${item.page || item.level || item.to_page || '--'}` }}</span>
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
               <div class="panel-head-compact">
                 <h3 class="panel-sm-title mb-4">近期升级结果</h3>
                 <span class="muted text-xs">
                   {{ selectedContractStatus ? `结构契约=${displayJobStatus(selectedContractStatus)}` : '全部结构契约状态' }}
                   {{ selectedArtifactSource ? ` · 来源=${displayArtifactSource(selectedArtifactSource)}` : '' }}
                 </span>
               </div>
               <div class="logs-grid">
                  <div v-for="job in focusedResults" :key="`${job.report_id}-${job.stage}`" class="log-card glass-panel-hover">
                     <div class="lc-head">
                       <span class="lc-stage">{{ displayPipelineStage(job.stage) }}</span>
                       <span class="status-dot" :class="`is-${job.status}`"></span>
                     </div>
                     <h4 class="lc-company">{{ job.company_name }}</h4>
                     <p class="lc-summary muted">{{ job.artifact_summary || '尚未生成摘要' }}</p>
                     <div class="lc-foot">
                       <span>{{ job.report_period || '-' }} · {{ displayArtifactSource(job.artifact_source) }} · {{ displayJobStatus(job.contract_status) }}</span>
                       <RouterLink class="inline-glass-link py-1 px-3" :to="{ path: '/admin', query: { stage: job.stage, report_id: job.report_id } }">查看详情</RouterLink>
                     </div>
                  </div>
               </div>
             </article>

             <article class="glass-panel p-panel mb-6">
               <h3 class="panel-sm-title mb-4">近期治理轨迹</h3>
               <div class="runtime-check-list">
                 <div
                   v-for="item in focusedWorkspaceHistory"
                   :key="`${item.history_type}-${item.id}`"
                   class="runtime-check-card"
                   :class="item.history_type === 'document_pipeline_run' ? 'is-ready' : ''"
                 >
                   <div class="runtime-check-head">
                     <strong>{{ item.title }}</strong>
                     <span class="tag subtle-tag">{{ displayHistoryType(item.history_type) }}</span>
                   </div>
                   <p>{{ item.meta?.headline || item.meta?.artifact_summary || item.meta?.query_type || '已记录运行轨迹。' }}</p>
                   <code>{{ item.created_at || '-' }} · {{ item.company_name || item.report_period || '-' }}</code>
                 </div>
               </div>
             </article>

             <article v-if="workspaceRuntimeAudit" class="glass-panel p-panel mb-6">
               <div class="panel-head-compact">
                 <h3 class="panel-sm-title mb-4">智能分析审计</h3>
                 <span class="readiness-badge" :class="`is-${workspaceRuntimeAudit.status}`">
                   {{ workspaceRuntimeAudit.label }}
                 </span>
               </div>
               <div class="readiness-grid">
                 <div class="readiness-stat">
                   <span>审计运行</span>
                   <strong>{{ workspaceRuntimeAudit.audited_runs }}/{{ workspaceRuntimeAudit.window_size }}</strong>
                 </div>
                 <div class="readiness-stat">
                   <span>强支撑占比</span>
                   <strong>{{ workspaceRuntimeAudit.summary_cards.grounded_ratio }}%</strong>
                 </div>
                 <div class="readiness-stat">
                   <span>完整轨迹占比</span>
                   <strong>{{ workspaceRuntimeAudit.summary_cards.trace_ratio }}%</strong>
                 </div>
                 <div class="readiness-stat">
                   <span>平均执行耗时</span>
                   <strong>{{ formatMilliseconds(workspaceRuntimeAudit.summary_cards.avg_execution_ms) }}</strong>
                 </div>
                 <div class="readiness-stat">
                   <span>平均工具调用</span>
                   <strong>{{ formatDecimal(workspaceRuntimeAudit.summary_cards.avg_tool_call_count) }}</strong>
                 </div>
                 <div class="readiness-stat">
                   <span>平均证据条数</span>
                   <strong>{{ formatDecimal(workspaceRuntimeAudit.summary_cards.avg_evidence_count) }}</strong>
                 </div>
               </div>
               <div class="report-grid">
                 <div class="report-list-card">
                   <strong>高频公司</strong>
                   <div v-if="focusedAuditCompanies.length" class="runtime-check-list compact-stack mt-2">
                     <div v-for="item in focusedAuditCompanies" :key="item.company_name" class="audit-company-row">
                       <div>
                         <strong>{{ item.company_name }}</strong>
                         <p>{{ item.run_count }} 次运行 · 强支撑 {{ item.grounded_count }} 次</p>
                       </div>
                       <code>{{ formatMilliseconds(item.avg_execution_ms) }}</code>
                     </div>
                   </div>
                   <p v-else>当前没有形成高频公司样本。</p>
                 </div>
                 <div class="report-list-card">
                   <strong>常用分析工具</strong>
                   <div v-if="workspaceRuntimeAudit.tool_mix.length" class="tag-row compact-tags mt-2">
                     <span v-for="item in workspaceRuntimeAudit.tool_mix.slice(0, 5)" :key="item.label" class="tag subtle-tag text-xs">
                       {{ item.label }} {{ item.count }}
                     </span>
                   </div>
                   <p v-else>当前样本里还没有工具调用记录。</p>
                 </div>
               </div>
               <div class="runtime-check-list">
                 <div
                   v-for="item in focusedAuditRuns"
                   :key="item.run_id"
                   class="runtime-check-card"
                   :class="item.assurance_status === 'grounded' ? 'is-ready' : ''"
                 >
                   <div class="runtime-check-head">
                     <strong>{{ item.company_name || '行业视图' }} · {{ item.query_type_label }}</strong>
                     <span class="tag" :class="item.assurance_status === 'grounded' ? 'success-tag' : 'subtle-tag'">
                       {{ item.assurance_label }}
                     </span>
                   </div>
                   <p>{{ item.query }}</p>
                   <div class="audit-meta-row">
                     <span>{{ item.role_label }}</span>
                     <span>{{ item.model || '未记录模型' }}</span>
                     <span>工具 {{ item.tool_call_count }}</span>
                     <span>证据 {{ item.evidence_count ?? '-' }}</span>
                     <span>{{ item.trace_status_label }}</span>
                   </div>
                   <div v-if="item.tool_labels.length" class="tag-row compact-tags mt-2">
                     <span v-for="label in item.tool_labels" :key="`${item.run_id}-${label}`" class="tag subtle-tag text-xs">{{ label }}</span>
                   </div>
                   <code>{{ item.created_at || '-' }} · 总耗时 {{ formatMilliseconds(item.execution_ms) }} · LLM {{ formatMilliseconds(item.llm_elapsed_ms) }} · 工具 {{ formatMilliseconds(item.tool_elapsed_ms) }}</code>
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
                     <span>最新指标层: {{ selectedCompanyDetail.latest_silver_period || '-' }}</span>
                   </div>
                 </div>
                 <div class="detail-health" :class="{ healthy: selectedCompanyDetail.issues.length === 0 }">
                   {{ selectedCompanyDetail.issues.length === 0 ? '已就绪' : `${selectedCompanyDetail.issues.length} 项阻断` }}
                 </div>
               </div>
               <div class="detail-stats">
                 <div class="detail-stat">
                   <span>原始</span>
                   <strong>{{ selectedCompanyDetail.raw_report_count }}</strong>
                 </div>
                 <div class="detail-stat">
                   <span>页级</span>
                   <strong>{{ selectedCompanyDetail.bronze_report_count }}</strong>
                 </div>
                 <div class="detail-stat">
                   <span>指标</span>
                   <strong>{{ selectedCompanyDetail.silver_record_count }}</strong>
                 </div>
                 <div class="detail-stat">
                   <span>研报</span>
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
                   {{ selectedIssueCode ? `已筛选: ${issueLabelMap[selectedIssueCode] || selectedIssueCode}` : `展示全部 ${filteredCompanies.length} 家` }}
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
                     <div class="mx-stat"><span class="mx-val">{{ row.raw_report_count }}</span><span class="mx-lbl">原始</span></div>
                     <div class="mx-stat"><span class="mx-val">{{ row.bronze_report_count }}</span><span class="mx-lbl">页级</span></div>
                     <div class="mx-stat"><span class="mx-val text-accent">{{ row.silver_record_count }}</span><span class="mx-lbl">指标</span></div>
                     <div class="mx-stat"><span class="mx-val text-[#60a5fa]">{{ row.research_report_count }}</span><span class="mx-lbl">研报</span></div>
                   </div>
                   <div class="mx-tags mt-3">
                     <span v-if="row.issues.length === 0" class="tag success-tag text-xs">已打通</span>
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
.metrics-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
  padding: 16px 24px;
  border-radius: 16px;
  flex-shrink: 0;
}
.metric-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-height: 108px;
  padding: 14px 16px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 14px;
  background: linear-gradient(180deg, rgba(15, 23, 42, 0.42), rgba(2, 6, 23, 0.18));
}
.metric-block.is-success {
  border-color: rgba(16, 185, 129, 0.22);
  box-shadow: inset 0 0 0 1px rgba(16, 185, 129, 0.04);
}
.metric-block.is-risk {
  border-color: rgba(244, 63, 94, 0.22);
  box-shadow: inset 0 0 0 1px rgba(244, 63, 94, 0.04);
}
.mb-label { font-size: 12px; color: var(--muted); letter-spacing: 0.04em; }
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
.readiness-badge.is-stable { color: #10b981; border-color: rgba(16,185,129,0.35); background: rgba(16,185,129,0.12); }
.readiness-badge.is-warming { color: #fbbf24; border-color: rgba(251,191,36,0.35); background: rgba(251,191,36,0.12); }
.readiness-badge.is-review,
.readiness-badge.is-unavailable { color: #94a3b8; border-color: rgba(148,163,184,0.28); background: rgba(148,163,184,0.1); }
.readiness-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; margin-top: 12px; }
.readiness-stat { border: 1px solid rgba(255,255,255,0.06); background: rgba(255,255,255,0.03); border-radius: 12px; padding: 14px; display: flex; flex-direction: column; gap: 8px; }
.readiness-stat span { color: var(--muted); font-size: 12px; }
.readiness-stat strong { font-size: 24px; line-height: 1; }
.audit-company-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 0; border-bottom: 1px dashed rgba(148, 163, 184, 0.18); }
.audit-company-row:last-child { border-bottom: none; padding-bottom: 0; }
.audit-company-row strong { display: block; margin-bottom: 4px; }
.audit-company-row p { margin: 0; color: #cbd5e1; font-size: 12px; }
.audit-meta-row { display: flex; flex-wrap: wrap; gap: 12px; font-size: 12px; color: #94a3b8; font-family: 'JetBrains Mono', monospace; }
.readiness-actions { display: flex; flex-direction: column; gap: 12px; margin-top: 16px; }
.readiness-action-card { border: 1px solid rgba(255,255,255,0.06); background: rgba(0,0,0,0.16); border-radius: 12px; padding: 14px; }
.readiness-action-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 8px; }
.readiness-action-card p { margin: 0 0 10px; color: #cbd5e1; font-size: 13px; line-height: 1.5; }
.runtime-check-list { display: flex; flex-direction: column; gap: 12px; margin-top: 12px; }
.compact-stack { gap: 8px; margin-top: 0; }
.runtime-check-card { border: 1px solid rgba(255,255,255,0.06); background: rgba(255,255,255,0.03); border-radius: 12px; padding: 14px; }
.runtime-check-card.is-blocked { border-color: rgba(244,63,94,0.28); background: rgba(244,63,94,0.06); }
.runtime-check-card.is-ready { border-color: rgba(16,185,129,0.24); background: rgba(16,185,129,0.05); }
.runtime-check-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 8px; }
.runtime-check-card p { margin: 0 0 8px; color: #cbd5e1; font-size: 13px; line-height: 1.5; }
.runtime-check-card code { display: block; font-size: 11px; color: #94a3b8; word-break: break-all; font-family: 'JetBrains Mono', monospace; }
.runtime-remediation { margin-top: 10px; padding-top: 10px; border-top: 1px dashed rgba(148, 163, 184, 0.18); color: #f8fafc; }
.report-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.report-list-card { border: 1px solid rgba(255,255,255,0.06); background: rgba(0,0,0,0.16); border-radius: 10px; padding: 12px; }
.report-list-card strong { display: block; margin-bottom: 6px; }

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
