<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'

import AppShell from '@/components/AppShell.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingState from '@/components/LoadingState.vue'
import TagPill from '@/components/TagPill.vue'
import { useAsyncState } from '@/composables/useAsyncState'
import { get, post } from '@/lib/api'

const overviewState = useAsyncState<any>()
const visionState = useAsyncState<any>()
const runtimeState = useAsyncState<any>()
const runsState = useAsyncState<any>()
const pipelineRunning = ref(false)
const actionError = ref('')
const bootstrapping = ref(false)
const selectedJobKey = ref('')

const companies = computed(() => overviewState.data.value?.companies || [])
const selectedCompany = ref('')
const selectedPeriod = ref('')

const availablePeriods = computed(() => overviewState.data.value?.available_periods || [])
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

const resultItems = computed(() => visionState.data.value?.result?.items || runtimeState.data.value?.vision?.items || [])
const selectedResult = computed(() => visionState.data.value?.result || runtimeState.data.value?.vision || null)
const analysisLog = computed(() => selectedResult.value?.analysis_log || [])
const qualitySummary = computed(() => selectedResult.value?.quality_summary || null)
const qualityMetrics = computed(() => qualitySummary.value?.metrics?.slice(0, 2) || [])
const qualityBlockers = computed(() => qualitySummary.value?.blockers?.slice(0, 2) || [])
const recentRuns = computed(() => (runsState.data.value?.runs || []).slice(0, 2))
const visibleAnalysisLog = computed(() => analysisLog.value.slice(0, 3))
const visibleSections = computed(() => selectedResult.value?.sections?.slice(0, 3) || [])
const visibleResultItems = computed(() => resultItems.value.slice(0, 4))
const sourcePreviewText = computed(() => {
  const preview = selectedResult.value?.source_preview
  if (!preview) return ''
  if (typeof preview === 'string') return preview
  const parts: string[] = []
  if (preview.summary) parts.push(preview.summary)
  if (Array.isArray(preview.tables) && preview.tables.length) parts.push(`预览表格 ${preview.tables.length} 个`)
  if (Array.isArray(preview.cells) && preview.cells.length) parts.push(`预览单元格 ${preview.cells.length} 条`)
  if (Array.isArray(preview.headings) && preview.headings.length) parts.push(`预览标题 ${preview.headings.length} 个`)
  return parts.join(' · ')
})
const runtimeSummary = computed(() => runtimeState.data.value?.runtime || null)
const pipelineJobs = computed(() => runtimeState.data.value?.latest_jobs || [])
const canRunPipeline = computed(() => !!selectedCompany.value)
const preferredJob = computed(() =>
  [...pipelineJobs.value].sort((left: any, right: any) => {
    const rank = (stage?: string) => ({ cross_page_merge: 1, title_hierarchy: 2, cell_trace: 3 }[stage || ''] || 0)
    return rank(right.stage) - rank(left.stage)
  })[0] || null,
)
const activeJob = computed(() =>
  pipelineJobs.value.find((item: any) => `${item.stage}-${item.report_id}` === selectedJobKey.value)
  || preferredJob.value
  || null,
)

function displayJobStatus(status?: string) {
  const map: Record<string, string> = {
    done: '已完成',
    completed: '已完成',
    pending: '待执行',
    blocked: '已阻断',
    ready: '就绪',
    running: '处理中',
  }
  return map[status || ''] || status || '-'
}

function displayPipelineStage(stage?: string) {
  const map: Record<string, string> = {
    cross_page_merge: '跨页拼接',
    title_hierarchy: '标题层级',
    cell_trace: '单元格溯源',
  }
  return map[stage || ''] || stage || '-'
}

function qualityTone(status?: string): 'default' | 'risk' | 'success' {
  if (status === 'ready') return 'success'
  if (status === 'blocked') return 'risk'
  return 'default'
}

async function loadVision() {
  if (!selectedCompany.value) return
  actionError.value = ''
  visionState.data.value = null
  const params = new URLSearchParams({ company_name: selectedCompany.value, user_role: 'management' })
  if (selectedPeriod.value) params.set('report_period', selectedPeriod.value)
  await Promise.all([
    runtimeState.execute(() => get(`/company/vision-runtime?${params.toString()}`)),
    runsState.execute(() => get(`/vision-analyze/runs?${params.toString()}&limit=6`)),
  ])
}

async function runPipeline() {
  if (!selectedCompany.value || pipelineRunning.value) return
  pipelineRunning.value = true
  try {
    await post('/company/vision-pipeline', {
      company_name: selectedCompany.value,
      report_period: selectedPeriod.value || null,
      user_role: 'management',
    })
    await loadVision()
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : '刷新解析链失败'
  } finally {
    pipelineRunning.value = false
  }
}

async function openVisionRun(runId: string) {
  await visionState.execute(() => get(`/vision-analyze/runs/${encodeURIComponent(runId)}`))
}

onMounted(async () => {
  bootstrapping.value = true
  try {
    await overviewState.execute(() => get('/workspace/companies'))
    selectedCompany.value = companies.value[0] || ''
    const preferredPeriod = overviewState.data.value?.preferred_period
    selectedPeriod.value = typeof preferredPeriod === 'string'
      ? preferredPeriod
      : String(preferredPeriod?.value || preferredPeriod?.period || preferredPeriod?.report_period || preferredPeriod?.label || '')
    try {
      await loadVision()
    } catch {
      // 请求错误由状态容器接管
    }
  } finally {
    bootstrapping.value = false
  }
})

watch([selectedCompany, selectedPeriod], async () => {
  if (bootstrapping.value) return
  try {
    await loadVision()
  } catch {
    // 请求错误由状态容器接管
  }
})

watch(
  pipelineJobs,
  (jobs) => {
    if (!jobs.length) {
      selectedJobKey.value = ''
      return
    }
    const exists = jobs.some((item: any) => `${item.stage}-${item.report_id}` === selectedJobKey.value)
    if (!exists && preferredJob.value) {
      selectedJobKey.value = `${preferredJob.value.stage}-${preferredJob.value.report_id}`
    }
  },
  { immediate: true },
)
</script>

<template>
  <AppShell title="">
    <div class="page-shell">
      <section class="glass-panel control-bar">
        <div class="control-copy">
          <h1>{{ selectedCompany || '文档复核' }}</h1>
          <p>{{ selectedPeriod || '查看当前结果' }}</p>
        </div>
        <div class="control-fields">
          <select v-model="selectedCompany" class="glass-select">
            <option v-for="c in companies" :key="c" :value="c">{{ c }}</option>
          </select>
          <select v-model="selectedPeriod" class="glass-select">
            <option value="">默认主周期</option>
            <option v-for="p in periodOptions" :key="p.value" :value="p.value">{{ p.label }}</option>
          </select>
          <button class="button-primary action-button" :disabled="!canRunPipeline || pipelineRunning" @click="runPipeline">
            {{ pipelineRunning ? '复核中…' : '重新复核' }}
          </button>
        </div>
      </section>

      <LoadingState v-if="overviewState.loading.value || runtimeState.loading.value" class="state-container" />
      <ErrorState
        v-else-if="overviewState.error.value || runtimeState.error.value || runsState.error.value || visionState.error.value || actionError"
        :message="String(overviewState.error.value || runtimeState.error.value || runsState.error.value || visionState.error.value || actionError)"
        class="state-container"
      />

      <template v-else>
        <section class="glass-panel summary-panel">
          <div class="summary-head">
            <div>
              <h2>{{ selectedResult?.headline || '等待当前结果' }}</h2>
              <p>{{ runtimeSummary?.next_action || selectedResult?.status_label || '等待复核' }}</p>
            </div>
            <div class="status-row" v-if="selectedResult">
              <TagPill :label="selectedResult.status_label || '就绪'" tone="success" />
              <TagPill v-if="qualitySummary" :label="qualitySummary.label" :tone="qualityTone(qualitySummary.status)" />
            </div>
          </div>

          <p v-if="sourcePreviewText" class="summary-copy">{{ sourcePreviewText }}</p>

          <div class="summary-grid">
            <div v-if="qualitySummary" class="summary-card">
              <strong>{{ qualitySummary.headline }}</strong>
              <div class="metric-row">
                <div v-for="item in qualityMetrics" :key="`${item.label}-${item.value}`" class="metric-card">
                  <span>{{ item.label }}</span>
                  <strong>{{ item.value }}</strong>
                </div>
              </div>
              <div v-if="qualityBlockers.length" class="blocker-list">
                <div v-for="item in qualityBlockers" :key="item.title" class="blocker-item">
                  <strong>{{ item.title }}</strong>
                  <p>{{ item.detail }}</p>
                </div>
              </div>
            </div>

            <div v-if="recentRuns.length" class="summary-card">
              <strong>最近两次复核</strong>
              <div class="run-list">
                <div v-for="item in recentRuns" :key="item.run_id" class="run-item" @click="openVisionRun(item.run_id)">
                  <div class="run-item-head">
                    <span>{{ item.company_name }}</span>
                    <TagPill :label="item.status_label || displayJobStatus(item.status) || '已完成'" tone="success" />
                  </div>
                  <p>{{ item.headline || item.status_label || '-' }}</p>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section class="content-grid">
          <article v-if="activeJob" class="glass-panel side-section">
            <h3>现在能直接看什么</h3>
            <div class="artifact-list">
              <div class="artifact-item">
                <span>环节</span>
                <strong>{{ displayPipelineStage(activeJob.stage) }}</strong>
              </div>
              <div class="artifact-item">
                <span>原文</span>
                <strong>{{ activeJob.report_id }}</strong>
              </div>
              <div class="artifact-item">
                <span>状态</span>
                <strong>{{ displayJobStatus(activeJob.status) }}</strong>
              </div>
            </div>
            <p class="side-copy">{{ activeJob.artifact_summary || '当前产物尚无结构摘要。' }}</p>
          </article>

          <article class="glass-panel main-section">
            <div class="main-head">
              <div>
                <h3>这次提炼出了什么</h3>
              </div>
            </div>

            <div v-if="analysisLog.length" class="flow-list">
              <div v-for="item in visibleAnalysisLog" :key="`log-${item.step}`" class="flow-item">
                <div class="flow-step">{{ item.step }}</div>
                <div class="flow-body">
                  <strong>{{ item.title }}</strong>
                  <p>{{ item.detail }}</p>
                </div>
              </div>
            </div>

            <div v-else-if="visibleSections.length" class="result-list">
              <div v-for="section in visibleSections" :key="section.section_type" class="result-item">
                <div class="result-item-head">
                  <strong>{{ section.title }}</strong>
                  <span>{{ section.count }} 条</span>
                </div>
                <div class="result-sublist">
                  <div v-for="it in section.items.slice(0, 3)" :key="JSON.stringify(it)" class="result-subrow">
                    <span>{{ it.text || it.title || it.reason || '条目' }}</span>
                    <span>P{{ it.page || it.to_page || '-' }}</span>
                  </div>
                </div>
              </div>
            </div>

            <div v-else-if="visibleResultItems.length" class="result-list">
              <div v-for="item in visibleResultItems" :key="`${item.kind}-${item.title}`" class="result-item">
                <strong>{{ item.title }}</strong>
                <p>{{ item.summary }}</p>
              </div>
            </div>

            <div v-if="selectedResult?.evidence_navigation?.links?.length" class="evidence-block">
              <h4>回到原文</h4>
              <div class="evidence-links">
                <RouterLink
                  v-for="link in selectedResult.evidence_navigation.links"
                  :key="link.label + link.path"
                  class="inline-link"
                  :to="{ path: link.path, query: link.query || {} }"
                >
                  {{ link.label }}
                </RouterLink>
              </div>
            </div>
          </article>
        </section>

        <section v-if="!selectedResult && !activeJob" class="glass-panel empty-panel">
          <div class="empty-content">
            <h2>等待文档结果</h2>
            <p>选择公司后点击「重新复核」，直接回看原文和表格。</p>
          </div>
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

.control-copy,
.summary-head > div,
.main-head > div {
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
.summary-copy,
.side-copy,
.run-item p,
.blocker-item p,
.flow-body p,
.result-item p,
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
  min-width: 160px;
  min-height: 40px;
  padding: 0 14px;
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.04);
  color: #fff;
}

.action-button {
  min-height: 40px;
  border-radius: 12px;
}

.state-container {
  min-height: 420px;
}

.summary-panel,
.side-section,
.main-section,
.empty-panel {
  padding: 24px;
  border-radius: 24px;
}

.summary-head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
}

.status-row,
.evidence-links {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.summary-grid,
.content-grid {
  display: grid;
  gap: 20px;
  margin-top: 18px;
}

.summary-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.content-grid {
  grid-template-columns: 360px minmax(0, 1fr);
}

.summary-card,
.artifact-item {
  display: grid;
  gap: 10px;
}

.summary-card strong,
.artifact-item strong,
.flow-body strong,
.result-item strong,
.blocker-item strong,
.run-item-head span {
  color: #f8fafc;
}

.metric-row {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.metric-card,
.artifact-item {
  padding: 16px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.025);
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.metric-card span,
.artifact-item span,
.result-item-head span,
.result-subrow span:last-child {
  color: var(--muted);
}

.metric-card strong {
  font-size: 20px;
  color: #f8fafc;
}

.blocker-list,
.run-list,
.artifact-list,
.flow-list,
.result-list {
  display: grid;
  gap: 14px;
}

.blocker-item,
.run-item,
.flow-item,
.result-item {
  padding-top: 14px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.blocker-item:first-child,
.run-item:first-child,
.flow-item:first-child,
.result-item:first-child {
  padding-top: 0;
  border-top: none;
}

.run-item {
  cursor: pointer;
}

.run-item-head,
.result-item-head,
.result-subrow {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.flow-item {
  display: grid;
  grid-template-columns: 48px minmax(0, 1fr);
  gap: 16px;
}

.flow-step {
  width: 48px;
  height: 48px;
  border-radius: 16px;
  display: grid;
  place-items: center;
  font-size: 14px;
  font-weight: 700;
  color: #c084fc;
  background: rgba(168, 85, 247, 0.12);
  border: 1px solid rgba(168, 85, 247, 0.28);
}

.result-sublist {
  display: grid;
  gap: 8px;
  margin-top: 10px;
}

.evidence-block {
  display: grid;
  gap: 12px;
  padding-top: 18px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.evidence-block h4 {
  margin: 0;
  color: #f8fafc;
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
  color: #c084fc;
  background: rgba(168, 85, 247, 0.1);
  border-color: rgba(168, 85, 247, 0.3);
}

.empty-panel {
  min-height: 360px;
  display: grid;
  place-items: center;
}

.empty-content {
  text-align: center;
  display: grid;
  gap: 10px;
}

@media (max-width: 1180px) {
  .summary-grid,
  .content-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 960px) {
  .control-bar,
  .control-fields,
  .summary-head {
    flex-direction: column;
    align-items: stretch;
  }

  .glass-select {
    width: 100%;
    min-width: 0;
  }

  .metric-row {
    grid-template-columns: 1fr;
  }
}
</style>
