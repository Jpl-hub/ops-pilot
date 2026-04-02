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
const qualityBlockers = computed(() => qualitySummary.value?.blockers?.slice(0, 1) || [])
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

function displayQualityStatus(status?: string) {
  const map: Record<string, string> = {
    ready: '已达标',
    warning: '需补强',
    blocked: '待补齐',
  }
  return map[status || ''] || status || '-'
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
    <div class="vision-page">
      <section class="glass-panel control-bar">
        <div class="control-left">
          <div class="glow-icon">文</div>
          <div class="control-copy">
            <span class="control-kicker">文档复核</span>
            <h3 class="company-name text-gradient">{{ selectedCompany || '文档复核' }}</h3>
            <p class="control-meta">{{ selectedPeriod || '选定公司后开始查看结果' }}</p>
          </div>
        </div>

        <div class="inline-context">
          <label class="inline-field">
            <span class="subtle-label">公司</span>
            <select v-model="selectedCompany" class="glass-select">
              <option v-for="c in companies" :key="c" :value="c">{{ c }}</option>
            </select>
          </label>
          <label class="inline-field">
            <span class="subtle-label">报期</span>
            <select v-model="selectedPeriod" class="glass-select">
              <option value="">默认主周期</option>
              <option v-for="p in periodOptions" :key="p.value" :value="p.value">{{ p.label }}</option>
            </select>
          </label>
          <button
            class="button-primary glow-button"
            :disabled="!canRunPipeline || pipelineRunning"
            @click="runPipeline"
          >
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

      <div v-else class="vision-grid">
        <aside class="vision-sidebar">
          <article class="glass-panel sidebar-section">
            <div class="section-headline">
              <span class="section-kicker">当前结果</span>
              <h2>{{ selectedResult?.headline || '等待当前结果' }}</h2>
              <p class="muted">{{ runtimeSummary?.next_action || selectedResult?.status_label || '等待复核' }}</p>
            </div>

            <div v-if="selectedResult" class="status-row">
              <TagPill :label="selectedResult.status_label || '就绪'" tone="success" />
              <TagPill v-if="qualitySummary" :label="qualitySummary.label" :tone="qualityTone(qualitySummary.status)" />
            </div>

            <p v-if="sourcePreviewText" class="context-copy">{{ sourcePreviewText }}</p>
          </article>

          <article v-if="qualitySummary" class="glass-panel sidebar-section">
            <div class="section-headline">
              <span class="section-kicker">先看质量</span>
              <h3>这次能不能直接用</h3>
            </div>
            <p class="context-copy"><strong>{{ qualitySummary.headline }}</strong></p>
            <p class="muted">{{ qualitySummary.summary }}</p>

            <div class="metric-strip">
              <div v-for="item in qualityMetrics" :key="`${item.label}-${item.value}`" class="metric-pill">
                <span>{{ item.label }}</span>
                <strong>{{ item.value }}</strong>
              </div>
            </div>

            <div v-if="qualityBlockers.length" class="blocker-list">
              <div v-for="item in qualityBlockers" :key="item.title" class="blocker-row">
                <strong>{{ item.title }}</strong>
                <p class="muted">{{ item.detail }}</p>
              </div>
            </div>
          </article>

          <article v-if="recentRuns.length" class="glass-panel sidebar-section">
            <div class="section-headline">
              <span class="section-kicker">最近结果</span>
              <h3>最近两次复核</h3>
            </div>
            <div class="run-list">
              <div v-for="item in recentRuns" :key="item.run_id" class="run-row" @click="openVisionRun(item.run_id)">
                <div class="run-row-head">
                  <strong>{{ item.company_name }}</strong>
                  <TagPill :label="item.status_label || displayJobStatus(item.status) || '已完成'" tone="success" />
                </div>
                <p class="muted">{{ item.headline || item.status_label || '-' }}</p>
              </div>
            </div>
          </article>
        </aside>

        <section class="vision-main">
          <article v-if="activeJob" class="glass-panel main-section">
            <div class="section-headline">
              <span class="section-kicker">当前产物</span>
              <h3>现在能直接看什么</h3>
            </div>
            <div class="artifact-strip">
              <div class="artifact-pill">
                <span>环节</span>
                <strong>{{ displayPipelineStage(activeJob.stage) }}</strong>
              </div>
              <div class="artifact-pill">
                <span>原文</span>
                <strong>{{ activeJob.report_id }}</strong>
              </div>
              <div class="artifact-pill">
                <span>状态</span>
                <strong>{{ displayJobStatus(activeJob.status) }}</strong>
              </div>
            </div>
            <p class="context-copy">{{ activeJob.artifact_summary || '当前产物尚无结构摘要。' }}</p>
          </article>

          <article v-if="analysisLog.length" class="glass-panel main-section">
            <div class="section-headline">
              <span class="section-kicker">提炼结果</span>
              <h3>这次提炼出了什么</h3>
            </div>
            <div class="flow-list">
              <div v-for="item in visibleAnalysisLog" :key="`log-${item.step}`" class="flow-row">
                <div class="flow-step">{{ item.step }}</div>
                <div class="flow-body">
                  <strong>{{ item.title }}</strong>
                  <p class="muted">{{ item.detail }}</p>
                </div>
              </div>
            </div>
          </article>

          <article v-if="visibleSections.length" class="glass-panel main-section">
            <div class="section-headline">
              <span class="section-kicker">页块结果</span>
              <h3>这次抽出来的页块</h3>
            </div>
            <div class="result-list">
              <div v-for="section in visibleSections" :key="section.section_type" class="result-row">
                <div class="result-row-head">
                  <strong>{{ section.title }}</strong>
                  <span class="muted">{{ section.count }} 条</span>
                </div>
                <div class="result-sublist">
                  <div v-for="it in section.items.slice(0, 3)" :key="JSON.stringify(it)" class="result-subrow">
                    <span>{{ it.text || it.title || it.reason || '条目' }}</span>
                    <span class="muted">P{{ it.page || it.to_page || '-' }}</span>
                  </div>
                </div>
              </div>
            </div>
          </article>

          <article v-else-if="visibleResultItems.length" class="glass-panel main-section">
            <div class="section-headline">
              <span class="section-kicker">提取条目</span>
              <h3>这次抽出来了什么</h3>
            </div>
            <div class="result-list">
              <div v-for="item in visibleResultItems" :key="`${item.kind}-${item.title}`" class="result-row">
                <strong>{{ item.title }}</strong>
                <p class="muted">{{ item.summary }}</p>
              </div>
            </div>
          </article>

          <article v-if="selectedResult?.evidence_navigation?.links?.length" class="glass-panel main-section">
            <div class="section-headline">
              <span class="section-kicker">回到原文</span>
              <h3>继续顺着原文和页块往下看</h3>
            </div>
            <div class="evidence-links">
              <RouterLink
                v-for="link in selectedResult.evidence_navigation.links"
                :key="link.label + link.path"
                class="inline-glass-link"
                :to="{ path: link.path, query: link.query || {} }"
              >
                {{ link.label }}
              </RouterLink>
            </div>
          </article>

          <article v-if="!selectedResult && !activeJob" class="glass-panel empty-panel">
            <div class="empty-content">
              <h3 class="text-gradient">等待文档结果</h3>
              <p class="muted">选择公司后点击「重新复核」，直接回看原文和表格。</p>
            </div>
          </article>
        </section>
      </div>
    </div>
  </AppShell>
</template>

<style scoped>
.vision-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  height: 100%;
  width: 100%;
  max-width: 1280px;
  margin: 0 auto;
  overflow: hidden;
}

.control-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding: 12px 16px;
  border-radius: 16px;
  flex-shrink: 0;
}

.control-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.control-copy {
  display: grid;
  gap: 4px;
}

.glow-icon {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  background: rgba(168, 85, 247, 0.15);
  border: 1px solid rgba(168, 85, 247, 0.4);
  color: #c084fc;
  font-size: 18px;
  font-weight: 700;
}

.control-kicker {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--muted);
}

.company-name {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}

.text-gradient {
  background-clip: text;
  -webkit-text-fill-color: transparent;
  background-image: linear-gradient(to right, #a855f7, #60a5fa);
}

.control-meta {
  margin: 0;
  font-size: 12px;
  color: var(--muted);
}

.inline-context {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}

.inline-field {
  display: flex;
  align-items: center;
  gap: 8px;
}

.subtle-label {
  font-size: 12px;
  color: var(--muted);
  text-transform: uppercase;
}

.glass-select {
  min-height: 36px;
  padding: 0 12px;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.05);
  color: #fff;
}

.glow-button {
  min-height: 36px;
  border-radius: 10px;
}

.glow-button:disabled {
  opacity: 0.56;
  cursor: not-allowed;
}

.state-container {
  flex: 1;
}

.vision-grid {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 16px;
  min-height: 0;
  flex: 1;
}

.vision-sidebar,
.vision-main {
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.vision-sidebar {
  overflow-y: auto;
  padding-right: 4px;
}

.vision-sidebar::-webkit-scrollbar {
  width: 4px;
}

.vision-sidebar::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.12);
  border-radius: 999px;
}

.sidebar-section,
.main-section {
  padding: 18px;
  border-radius: 20px;
}

.section-headline {
  display: grid;
  gap: 6px;
}

.section-kicker {
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--muted);
}

.section-headline h2,
.section-headline h3 {
  margin: 0;
  font-size: 18px;
  line-height: 1.28;
  color: #f8fafc;
}

.status-row,
.context-links,
.evidence-links {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.context-copy,
.muted {
  color: var(--muted);
}

.context-copy {
  margin: 0;
  font-size: 13px;
  line-height: 1.65;
}

.metric-strip,
.artifact-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.metric-pill,
.artifact-pill {
  display: grid;
  gap: 4px;
  padding: 10px 12px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.025);
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.metric-pill span,
.artifact-pill span {
  font-size: 11px;
  color: var(--muted);
}

.metric-pill strong,
.artifact-pill strong {
  font-size: 15px;
  color: #f8fafc;
}

.blocker-list,
.run-list,
.flow-list,
.result-list {
  display: grid;
  gap: 10px;
}

.blocker-row,
.run-row,
.flow-row,
.result-row {
  padding-top: 10px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.blocker-row strong,
.run-row-head strong,
.flow-body strong,
.result-row strong {
  color: #f8fafc;
}

.blocker-row p,
.run-row p,
.flow-body p,
.result-row p {
  margin: 4px 0 0;
  font-size: 12px;
  line-height: 1.6;
}

.run-row {
  cursor: pointer;
}

.run-row-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.vision-main {
  overflow-y: auto;
  padding-right: 4px;
}

.vision-main::-webkit-scrollbar {
  width: 4px;
}

.vision-main::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.12);
  border-radius: 999px;
}

.flow-row {
  display: grid;
  grid-template-columns: 32px minmax(0, 1fr);
  gap: 12px;
  align-items: flex-start;
}

.flow-step {
  width: 32px;
  height: 32px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  font-size: 12px;
  font-weight: 700;
  color: #c084fc;
  background: rgba(168, 85, 247, 0.12);
  border: 1px solid rgba(168, 85, 247, 0.28);
}

.result-row-head,
.result-subrow {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.result-sublist {
  display: grid;
  gap: 8px;
  margin-top: 8px;
}

.result-subrow {
  font-size: 12px;
}

.inline-glass-link {
  padding: 6px 12px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.04);
  color: var(--muted);
  font-size: 11px;
  text-decoration: none;
  transition: all 0.2s ease;
}

.inline-glass-link:hover {
  color: #c084fc;
  background: rgba(168, 85, 247, 0.1);
  border-color: rgba(168, 85, 247, 0.3);
}

.empty-panel {
  display: grid;
  place-items: center;
  flex: 1;
  border-radius: 20px;
}

.empty-content {
  text-align: center;
  display: grid;
  gap: 8px;
}

.empty-content h3 {
  margin: 0;
}

@media (max-width: 1180px) {
  .vision-grid {
    grid-template-columns: 1fr;
  }

  .vision-sidebar,
  .vision-main {
    overflow: visible;
  }
}

@media (max-width: 900px) {
  .control-bar,
  .inline-context {
    flex-direction: column;
    align-items: stretch;
  }

  .inline-field,
  .glass-select {
    width: 100%;
  }

  .metric-strip,
  .artifact-strip {
    grid-template-columns: 1fr;
  }
}
</style>
