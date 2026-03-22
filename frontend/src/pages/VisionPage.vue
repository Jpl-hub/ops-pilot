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
  await overviewState.execute(() => get('/workspace/overview?user_role=management'))
  selectedCompany.value = companies.value[0] || ''
  await loadVision()
})

watch(selectedCompany, async () => {
  await loadVision()
})

watch(selectedPeriod, async () => {
  await loadVision()
})
</script>

<template>
  <AppShell title="多模态解析" compact>
    <LoadingState v-if="overviewState.loading.value && !visionState.data.value" />
    <ErrorState
      v-else-if="overviewState.error.value || visionState.error.value"
      :message="String(overviewState.error.value || visionState.error.value)"
    />
    <template v-else>
      <section class="mode-stage vision-mode-stage" style="height: auto; min-height: 800px;">
        <article class="glass-panel mode-main-panel vision-main-panel">
          <div class="mode-query-panel">
            <div class="vision-drop-icon">⇪</div>
            <div class="mode-query-copy">
              <strong>当前报告</strong>
              <span>{{ selectedResult?.headline || '等待选择报告' }}</span>
            </div>
            <div class="mode-query-metrics">
              <TagPill v-if="selectedResult?.status_label" :label="selectedResult.status_label" />
              <button class="mode-action-button" :disabled="!canRunPipeline || pipelineRunning" @click="runPipeline">
                {{ pipelineRunning ? '处理中' : '刷新解析链' }}
              </button>
            </div>
          </div>

          <div class="graph-context-bar">
            <label class="field">
              <span>公司</span>
              <select v-model="selectedCompany">
                <option v-for="company in companies" :key="company" :value="company">{{ company }}</option>
              </select>
            </label>
            <label class="field">
              <span>报期</span>
              <input v-model="selectedPeriod" class="text-input" placeholder="默认主周期" />
            </label>
          </div>

          <div class="vision-layout">
            <section class="vision-input-zone">
              <div class="vision-dropzone vision-dropzone-terminal">
                <div class="vision-drop-icon">◫</div>
                <strong>{{ selectedResult?.headline || '等待解析结果' }}</strong>
                <span>{{ runtimeSummary?.next_action || selectedResult?.status_label || 'pending' }}</span>
              </div>
              <div class="graph-phase-track vision-phase-track">
                <div
                  v-for="(phase, index) in phaseTrack"
                  :key="phase.phase || phase.stage"
                  class="graph-phase-card"
                  :class="{ active: index === 0 || phase.status === 'completed' }"
                >
                  <span>{{ phase.label || phase.phase || phase.stage }}</span>
                  <strong>{{ phase.headline || phase.summary || '等待运行' }}</strong>
                  <small>{{ phase.metric || phase.status || '-' }}</small>
                </div>
              </div>
              <div class="graph-signal-stream vision-signal-stream">
                <div
                  v-for="item in extractionStream"
                  :key="item.label + item.value"
                  class="graph-signal-chip"
                  :class="`tone-${item.tone || 'accent'}`"
                >
                  <span>{{ item.label }}</span>
                  <strong>{{ item.value }}</strong>
                </div>
              </div>
              <div class="timeline-list compact-timeline">
                <div
                  v-for="item in resultItems"
                  :key="`${item.kind}-${item.title}`"
                  class="timeline-item"
                >
                  <strong>{{ item.title }}</strong>
                  <span>{{ item.summary }}</span>
                </div>
              </div>
              <div class="timeline-list compact-timeline">
                <div
                  v-for="job in pipelineJobs"
                  :key="`${job.stage}-${job.report_id}`"
                  class="timeline-item"
                >
                  <strong>{{ job.company_name }} · {{ job.stage }}</strong>
                  <span>{{ job.artifact_summary || job.status }}</span>
                </div>
              </div>
              <div class="timeline-list compact-timeline">
                <div
                  v-for="item in runsState.data.value?.runs || []"
                  :key="item.run_id"
                  class="timeline-item interactive-card"
                  @click="openVisionRun(item.run_id)"
                >
                  <strong>{{ item.company_name }}</strong>
                  <span>{{ item.headline || item.status_label }}</span>
                </div>
              </div>
            </section>

            <section class="vision-result-zone">
              <div class="panel-header">
                <div>
                  <div class="signal-code">分析结果</div>
                  <h3>{{ selectedResult?.company_name || '等待选择报告' }}</h3>
                </div>
              </div>
              <div v-if="selectedResult" class="vision-sections">
                <article
                  v-for="section in selectedResult.sections || []"
                  :key="section.section_type"
                  class="vision-section-card"
                >
                  <div class="signal-code">{{ section.title }}</div>
                  <strong>{{ section.count }} 条</strong>
                  <div class="metric-list">
                    <div v-for="item in section.items.slice(0, 5)" :key="JSON.stringify(item)" class="metric-row">
                      <span>{{ item.text || item.title || item.reason || '条目' }}</span>
                      <strong>{{ item.page || item.level || item.to_page || '-' }}</strong>
                    </div>
                  </div>
                </article>
              </div>
              <div v-if="analysisLog.length" class="timeline-list compact-timeline vision-analysis-log">
                <div
                  v-for="item in analysisLog"
                  :key="`analysis-${item.step}`"
                  class="timeline-item"
                >
                  <strong>{{ item.step }}. {{ item.title }}</strong>
                  <span>{{ item.detail }}</span>
                </div>
              </div>
              <div v-else class="vision-empty">
                <span>等待分析结果</span>
              </div>
            </section>
          </div>

          <div class="graph-support-strip">
            <section class="graph-support-card">
              <div class="signal-code">证据入口</div>
              <div class="timeline-list compact-timeline">
                <RouterLink
                  v-for="item in selectedResult?.evidence_navigation?.links || []"
                  :key="item.label + item.path"
                  class="timeline-item interactive-card"
                  :to="{ path: item.path, query: item.query || {} }"
                >
                  <strong>{{ item.label }}</strong>
                </RouterLink>
              </div>
            </section>
          </div>
        </article>
      </section>
    </template>
  </AppShell>
</template>
