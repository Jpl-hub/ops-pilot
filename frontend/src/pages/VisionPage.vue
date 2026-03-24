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

const companies = computed(() => overviewState.data.value?.companies || [])
const selectedCompany = ref('')
const selectedPeriod = ref('')

const availablePeriods = computed(() => overviewState.data.value?.available_periods || [])

const resultItems = computed(() => visionState.data.value?.result?.items || runtimeState.data.value?.vision?.items || [])
const selectedResult = computed(() => visionState.data.value?.result || runtimeState.data.value?.vision || null)
const phaseTrack = computed(() => runtimeState.data.value?.stages || selectedResult.value?.phase_track || [])
const extractionStream = computed(() => selectedResult.value?.extraction_stream || [])
const analysisLog = computed(() => selectedResult.value?.analysis_log || [])
const runtimeSummary = computed(() => runtimeState.data.value?.runtime || null)
const pipelineJobs = computed(() => runtimeState.data.value?.latest_jobs || [])
const canRunPipeline = computed(() => !!selectedCompany.value)

async function loadVision() {
  if (!selectedCompany.value) return
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
  } finally {
    pipelineRunning.value = false
  }
}

async function openVisionRun(runId: string) {
  await visionState.execute(() => get(`/vision-analyze/runs/${encodeURIComponent(runId)}`))
}

onMounted(async () => {
  await overviewState.execute(() => get('/workspace/companies'))
  selectedCompany.value = companies.value[0] || ''
  selectedPeriod.value = overviewState.data.value?.preferred_period || ''
  await loadVision()
})

watch(selectedCompany, async () => { await loadVision() })
watch(selectedPeriod, async () => { await loadVision() })
</script>

<template>
  <AppShell title="多模态解析">
    <div class="dashboard-wrapper">

      <!-- Control Bar -->
      <section class="glass-panel control-bar">
        <div class="control-left">
          <div class="glow-icon">视</div>
          <div>
            <h3 class="company-name text-gradient">{{ selectedCompany || '选择公司' }}</h3>
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
              <option v-for="p in availablePeriods" :key="p" :value="p">{{ p }}</option>
            </select>
          </label>
          <button
            class="button-primary glow-button"
            :disabled="!canRunPipeline || pipelineRunning"
            @click="runPipeline"
          >
            {{ pipelineRunning ? '处理中…' : '刷新解析链' }}
          </button>
        </div>
      </section>

      <LoadingState v-if="overviewState.loading.value || runtimeState.loading.value" class="state-container" />
      <ErrorState
        v-else-if="overviewState.error.value || visionState.error.value"
        :message="String(overviewState.error.value || visionState.error.value)"
        class="state-container"
      />

      <div v-else class="dashboard-grid">
        <!-- Left Col -->
        <div class="dashboard-col left-col">

          <!-- Status Hero -->
          <article class="glass-panel hero-panel">
            <div class="hero-top">
              <div class="eyebrow">当前报告</div>
              <h2 class="hero-title compact">{{ selectedResult?.headline || '等待解析结果' }}</h2>
              <p class="hero-text text-sm muted">{{ runtimeSummary?.next_action || selectedResult?.status_label || '就绪' }}</p>
            </div>
            <div v-if="selectedResult" class="status-badge-row">
              <TagPill :label="selectedResult.status_label || '就绪'" tone="success" />
              <TagPill v-if="selectedResult.company_name" :label="selectedResult.company_name" />
            </div>

            <!-- Phase Track -->
            <div class="phase-track" v-if="phaseTrack.length">
              <div
                v-for="(phase, idx) in phaseTrack"
                :key="phase.phase || phase.stage || idx"
                class="phase-step"
                :class="{ done: phase.status === 'done' || phase.status === 'completed', active: idx === 0 }"
              >
                <div class="phase-dot"></div>
                <div class="phase-body">
                  <span class="phase-label">{{ phase.phase || phase.stage || phase.label }}</span>
                  <strong class="phase-headline">{{ phase.headline || phase.summary || '等待运行' }}</strong>
                  <small class="muted">{{ phase.metric || phase.status || '-' }}</small>
                </div>
              </div>
            </div>
          </article>

          <!-- Extraction Stream -->
          <article class="glass-panel stream-panel" v-if="extractionStream.length">
            <h3 class="panel-sm-title">结构抽取信号</h3>
            <div class="stream-chips">
              <div
                v-for="item in extractionStream"
                :key="item.label + item.value"
                class="stream-chip"
                :class="`tone-${item.tone || 'accent'}`"
              >
                <span class="chip-label">{{ item.label }}</span>
                <strong class="chip-val">{{ item.value }}</strong>
              </div>
            </div>
          </article>

          <!-- History Runs -->
          <article class="glass-panel runs-panel scroll-area" v-if="(runsState.data.value?.runs || []).length">
            <h3 class="panel-sm-title">历史解析记录</h3>
            <div class="runs-list">
              <div
                v-for="item in runsState.data.value?.runs || []"
                :key="item.run_id"
                class="run-item glass-panel-hover"
                @click="openVisionRun(item.run_id)"
              >
                <div class="run-head">
                  <strong class="run-company">{{ item.company_name }}</strong>
                  <TagPill :label="item.status_label || item.stage || 'done'" tone="success" />
                </div>
                <p class="run-summary muted">{{ item.headline || item.status_label || '-' }}</p>
              </div>
            </div>
          </article>
        </div>

        <!-- Right Col -->
        <div class="dashboard-col right-col">

          <!-- Pipeline Jobs -->
          <article class="glass-panel jobs-panel" v-if="pipelineJobs.length">
            <h3 class="panel-sm-title">解析工序流水</h3>
            <div class="jobs-grid">
              <div
                v-for="job in pipelineJobs"
                :key="`${job.stage}-${job.report_id}`"
                class="job-card glass-panel-hover"
              >
                <div class="job-head">
                  <span class="job-stage">{{ job.stage }}</span>
                  <span class="job-status" :class="job.status === 'done' ? 'text-accent' : 'muted'">{{ job.status }}</span>
                </div>
                <strong class="job-company">{{ job.company_name }}</strong>
                <p class="job-summary muted">{{ job.artifact_summary || '等待摘要' }}</p>
              </div>
            </div>
          </article>

          <!-- Analysis Log -->
          <article class="glass-panel log-panel scroll-area flex-1" v-if="analysisLog.length">
            <h3 class="panel-sm-title">解析过程追踪</h3>
            <div class="log-list">
              <div
                v-for="item in analysisLog"
                :key="`log-${item.step}`"
                class="log-item"
              >
                <div class="log-step-badge">{{ item.step }}</div>
                <div class="log-body">
                  <strong>{{ item.title }}</strong>
                  <p class="muted">{{ item.detail }}</p>
                </div>
              </div>
            </div>
          </article>

          <!-- Sections from Result -->
          <article class="glass-panel sections-panel scroll-area flex-1" v-else-if="selectedResult?.sections?.length">
            <h3 class="panel-sm-title">结构化抽取结果</h3>
            <div class="sections-grid">
              <div
                v-for="section in selectedResult.sections"
                :key="section.section_type"
                class="section-card glass-panel-hover"
              >
                <div class="section-head">
                  <span class="section-type-badge">{{ section.title }}</span>
                  <strong class="text-accent">{{ section.count }} 条</strong>
                </div>
                <div class="section-items">
                  <div v-for="it in section.items.slice(0, 4)" :key="JSON.stringify(it)" class="section-row">
                    <span>{{ it.text || it.title || it.reason || '条目' }}</span>
                    <span class="muted">P{{ it.page || it.to_page || '-' }}</span>
                  </div>
                </div>
              </div>
            </div>
          </article>

          <!-- Result Items -->
          <article class="glass-panel items-panel scroll-area flex-1" v-else-if="resultItems.length">
            <h3 class="panel-sm-title">解析条目清单</h3>
            <div class="items-list">
              <div v-for="item in resultItems" :key="`${item.kind}-${item.title}`" class="item-row glass-panel-hover">
                <strong>{{ item.title }}</strong>
                <span class="muted">{{ item.summary }}</span>
              </div>
            </div>
          </article>

          <!-- Empty -->
          <article v-else class="glass-panel empty-panel">
            <div class="empty-content">
              <h3 class="text-gradient mb-2">等待解析结果</h3>
              <p class="muted">选择公司后点击「刷新解析链」触发多模态解析流水线。</p>
            </div>
          </article>

          <!-- Evidence Links -->
          <article class="glass-panel evidence-panel" v-if="selectedResult?.evidence_navigation?.links?.length">
            <h3 class="panel-sm-title">证据入口</h3>
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
        </div>
      </div>
    </div>
  </AppShell>
</template>

<style scoped>
.dashboard-wrapper { display: flex; flex-direction: column; gap: 16px; height: 100%; overflow: hidden; }

.control-bar { display: flex; justify-content: space-between; align-items: center; padding: 16px 24px; border-radius: 16px; flex-shrink: 0; }
.control-left { display: flex; align-items: center; gap: 16px; }
.glow-icon { width: 40px; height: 40px; border-radius: 12px; background: rgba(168,85,247,0.15); border: 1px solid rgba(168,85,247,0.4); color: #a855f7; display: grid; place-items: center; font-weight: bold; font-size: 18px; box-shadow: 0 0 15px rgba(168,85,247,0.2); }
.company-name { margin: 0; font-size: 20px; font-weight: 600; }
.text-gradient { background-clip: text; -webkit-text-fill-color: transparent; background-image: linear-gradient(to right, #a855f7, #60a5fa); }
.inline-context { display: flex; align-items: center; gap: 16px; }
.inline-field { display: flex; align-items: center; gap: 8px; }
.subtle-label { font-size: 12px; color: var(--muted); text-transform: uppercase; }
.glass-select { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); min-height: 36px; padding: 0 12px; border-radius: 8px; color: #fff; }
.glass-input { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); min-height: 36px; padding: 0 12px; border-radius: 8px; color: #fff; width: 120px; outline: none; }
.glow-button { min-height: 36px; border-radius: 8px; box-shadow: 0 0 15px rgba(168,85,247,0.2); }
.glow-button:disabled { opacity: 0.5; cursor: not-allowed; }
.state-container { flex: 1; }

/* Grid */
.dashboard-grid { display: grid; grid-template-columns: 320px 1fr; gap: 16px; flex: 1; min-height: 0; }
.dashboard-col { display: flex; flex-direction: column; gap: 16px; min-height: 0; }
.left-col { overflow-y: auto; }
.left-col::-webkit-scrollbar { width: 4px; }
.left-col::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 2px; }
.right-col { overflow: hidden; }
.scroll-area { overflow-y: auto; }
.scroll-area::-webkit-scrollbar { width: 4px; }
.scroll-area::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 2px; }
.flex-1 { flex: 1; min-height: 0; }

/* Hero Panel */
.hero-panel { padding: 24px; border-radius: 20px; display: flex; flex-direction: column; gap: 16px; flex-shrink: 0; }
.hero-top { display: flex; flex-direction: column; gap: 4px; }
.hero-title { font-size: 18px; font-weight: 600; margin: 0; color: #fff; }
.hero-title.compact { font-size: 16px; }
.hero-text { font-size: 13px; margin: 0; }
.eyebrow { font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); margin-bottom: 4px; }
.status-badge-row { display: flex; gap: 8px; flex-wrap: wrap; }
.muted { color: var(--muted); }
.text-sm { font-size: 13px; }
.text-accent { color: #10b981; }

/* Phase Track */
.phase-track { display: flex; flex-direction: column; gap: 0; border-left: 2px solid rgba(168,85,247,0.2); margin-left: 8px; padding-left: 16px; }
.phase-step { display: flex; align-items: flex-start; gap: 12px; padding: 10px 0; position: relative; }
.phase-dot { width: 10px; height: 10px; border-radius: 50%; background: rgba(168,85,247,0.3); border: 2px solid rgba(168,85,247,0.5); flex-shrink: 0; margin-top: 4px; position: absolute; left: -22px; }
.phase-step.done .phase-dot { background: #a855f7; border-color: #a855f7; box-shadow: 0 0 8px rgba(168,85,247,0.5); }
.phase-step.active .phase-dot { background: rgba(168,85,247,0.6); border-color: #a855f7; }
.phase-body { display: flex; flex-direction: column; gap: 2px; }
.phase-label { font-size: 11px; color: var(--muted); text-transform: uppercase; }
.phase-headline { font-size: 13px; color: #fff; }

/* Stream */
.stream-panel { padding: 20px; border-radius: 20px; flex-shrink: 0; }
.stream-chips { display: flex; flex-wrap: wrap; gap: 8px; }
.stream-chip { display: flex; flex-direction: column; align-items: center; padding: 10px 14px; border-radius: 10px; min-width: 80px; }
.stream-chip.tone-accent { background: rgba(16,185,129,0.1); border: 1px solid rgba(16,185,129,0.2); }
.stream-chip.tone-success { background: rgba(59,130,246,0.1); border: 1px solid rgba(59,130,246,0.2); }
.stream-chip.tone-warning { background: rgba(245,158,11,0.1); border: 1px solid rgba(245,158,11,0.2); }
.chip-label { font-size: 11px; color: var(--muted); }
.chip-val { font-size: 14px; font-weight: 600; color: #fff; }

/* Runs */
.runs-panel { padding: 20px; border-radius: 20px; }
.runs-list { display: flex; flex-direction: column; gap: 8px; }
.run-item { padding: 12px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.05); cursor: pointer; }
.run-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
.run-company { font-size: 14px; color: #fff; }
.run-summary { font-size: 12px; margin: 0; }

/* Jobs Grid */
.jobs-panel { padding: 20px; border-radius: 20px; flex-shrink: 0; }
.jobs-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; }
.job-card { padding: 14px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.05); }
.job-head { display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 6px; }
.job-stage { color: #818cf8; font-family: 'JetBrains Mono', monospace; }
.job-status { }
.job-company { font-size: 14px; color: #fff; display: block; margin-bottom: 4px; }
.job-summary { font-size: 12px; margin: 0; line-height: 1.5; }

/* Log */
.log-panel { padding: 20px; border-radius: 20px; }
.log-list { display: flex; flex-direction: column; gap: 12px; }
.log-item { display: flex; gap: 14px; align-items: flex-start; }
.log-step-badge { width: 28px; height: 28px; border-radius: 50%; background: rgba(168,85,247,0.15); border: 1px solid rgba(168,85,247,0.3); color: #a855f7; display: grid; place-items: center; font-size: 12px; font-weight: 700; flex-shrink: 0; }
.log-body { display: flex; flex-direction: column; gap: 2px; }
.log-body strong { font-size: 14px; color: #fff; }
.log-body p { font-size: 13px; margin: 0; }

/* Sections */
.sections-panel { padding: 20px; border-radius: 20px; }
.sections-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; }
.section-card { padding: 14px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.05); }
.section-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.section-type-badge { font-size: 11px; font-family: 'JetBrains Mono', monospace; background: rgba(0,0,0,0.3); padding: 3px 8px; border-radius: 4px; color: var(--muted); }
.section-items { display: flex; flex-direction: column; gap: 6px; }
.section-row { display: flex; justify-content: space-between; font-size: 12px; color: #e2e8f0; }

/* Items */
.items-panel { padding: 20px; border-radius: 20px; }
.items-list { display: flex; flex-direction: column; gap: 8px; }
.item-row { padding: 12px 14px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.05); display: flex; flex-direction: column; gap: 4px; }
.item-row strong { font-size: 14px; color: #fff; }
.item-row span { font-size: 12px; }

/* Empty */
.empty-panel { display: grid; place-items: center; flex: 1; border-radius: 20px; }
.empty-content { text-align: center; }
.mb-2 { margin-bottom: 8px; }

/* Evidence */
.evidence-panel { padding: 16px 20px; border-radius: 16px; flex-shrink: 0; }
.evidence-links { display: flex; gap: 8px; flex-wrap: wrap; }
.inline-glass-link { font-size: 12px; padding: 6px 12px; border-radius: 6px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); color: var(--muted); text-decoration: none; transition: all 0.2s; }
.inline-glass-link:hover { background: rgba(168,85,247,0.1); border-color: rgba(168,85,247,0.3); color: #a855f7; }

/* Common */
.panel-sm-title { font-size: 13px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); margin: 0 0 14px; padding-bottom: 10px; border-bottom: 1px solid rgba(255,255,255,0.05); }
</style>
