<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import AppShell from '@/components/AppShell.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingState from '@/components/LoadingState.vue'
import TagPill from '@/components/TagPill.vue'
import { useAsyncState } from '@/composables/useAsyncState'
import { get, post } from '@/lib/api'

type GraphInferenceStep = {
  step: number
  title: string
  detail: string
}

type GraphFocalNode = {
  id: string
  label: string
  type: string
}

const overviewState = useAsyncState<any>()
const graphState = useAsyncState<any>()
const streamState = useAsyncState<any>()
const runsState = useAsyncState<any>()
const route = useRoute()

const selectedCompany = ref('')
const selectedPeriod = ref('')
const graphIntent = ref('碳酸锂价格下跌对下游盈利和风险的影响传导')
const graphIntentDraft = ref(graphIntent.value)
const activePathStep = ref(0)
let graphTicker: number | null = null

const companies = computed(() => overviewState.data.value?.companies || [])
const focalNodes = computed<GraphFocalNode[]>(() => graphState.data.value?.focal_nodes || [])
const inferencePath = computed<GraphInferenceStep[]>(() => graphState.data.value?.inference_path || [])
const activePathId = computed(() => inferencePath.value[activePathStep.value]?.step ?? null)
const phaseTrack = computed(() => graphState.data.value?.phase_track || [])
const signalStream = computed(() => graphState.data.value?.signal_stream || [])
const graphLiveFrames = computed(() => graphState.data.value?.graph_live_frames || [])
const activePhaseIndex = computed(() =>
  phaseTrack.value.length ? activePathStep.value % phaseTrack.value.length : 0,
)
const activeGraphFrame = computed(
  () => graphLiveFrames.value[activePathStep.value] || graphLiveFrames.value[0] || null,
)
const activeRun = computed(() => runsState.data.value?.runs?.[0] || null)

const graphCanvasNodes = computed(() => {
  const activeNodes = new Set(activeGraphFrame.value?.active_nodes || [])
  const pathNodes = inferencePath.value.map((item: GraphInferenceStep, index: number) => ({
    id: `path-${item.step}`,
    label: item.title,
    detail: item.detail,
    kind: index === 0 ? 'source' : index === inferencePath.value.length - 1 ? 'impact' : 'core',
    x: [10, 30, 50, 72][index] ?? 72,
    y: [54, 33, 55, 78][index] ?? 78,
    step: item.step,
    active: activeNodes.has(`path-${item.step}`),
  }))
  const supportNodes = focalNodes.value.slice(0, 4).map((node: GraphFocalNode, index: number) => ({
    id: node.id,
    label: node.label,
    detail: node.type,
    kind: ['risk_label', 'alert'].includes(node.type) ? 'risk' : 'support',
    x: [16, 34, 56, 82][index] ?? 82,
    y: 86,
    step: null,
    active: activeNodes.has(node.id),
  }))
  return [...pathNodes, ...supportNodes]
})

const graphCanvasLinks = computed(() =>
  inferencePath.value.slice(0, -1).map((item: GraphInferenceStep, index: number) => ({
    id: `link-${item.step}`,
    active: (activeGraphFrame.value?.active_links || []).includes(`link-${item.step}`),
    x1: [10, 30, 50, 72][index] ?? 72,
    y1: [54, 33, 55, 78][index] ?? 78,
    x2: [10, 30, 50, 72][index + 1] ?? 72,
    y2: [54, 33, 55, 78][index + 1] ?? 78,
  })),
)

async function loadGraph() {
  const company = selectedCompany.value
  if (!company) return
  const params = new URLSearchParams({ company_name: company })
  if (selectedPeriod.value) params.set('report_period', selectedPeriod.value)
  await Promise.all([
    graphState.execute(() =>
      post('/company/graph-query', {
        company_name: company,
        report_period: selectedPeriod.value || null,
        user_role: 'management',
        intent: graphIntent.value,
      }),
    ),
    streamState.execute(() => get(`/company/execution-stream?${params.toString()}&user_role=management&limit=8`)),
    runsState.execute(() =>
      get(`/graph-query/runs?${params.toString()}&user_role=management&limit=6`),
    ),
  ])
  activePathStep.value = 0
}

onMounted(async () => {
  await overviewState.execute(() => get('/workspace/overview?user_role=management'))
  selectedCompany.value =
    (typeof route.query.company === 'string' ? route.query.company : '') || companies.value[0] || ''
  selectedPeriod.value = typeof route.query.period === 'string' ? route.query.period : ''
  await loadGraph()
  graphTicker = window.setInterval(() => {
    if (!inferencePath.value.length) return
    activePathStep.value = (activePathStep.value + 1) % inferencePath.value.length
  }, 1800)
})

onBeforeUnmount(() => {
  if (graphTicker) {
    window.clearInterval(graphTicker)
    graphTicker = null
  }
})

watch(selectedCompany, async () => {
  await loadGraph()
})

watch(selectedPeriod, async () => {
  await loadGraph()
})

async function submitIntent() {
  graphIntent.value = graphIntentDraft.value.trim() || graphIntent.value
  await loadGraph()
}

function focusStep(index: number) {
  activePathStep.value = index
}

async function openGraphRun(runId: string) {
  await graphState.execute(() => get(`/graph-query/runs/${encodeURIComponent(runId)}`))
  graphIntent.value = graphState.data.value?.intent || graphIntent.value
  graphIntentDraft.value = graphIntent.value
  activePathStep.value = 0
}
</script>

<template>
  <AppShell title="图谱检索" compact>
    <LoadingState v-if="overviewState.loading.value && !graphState.data.value" />
    <ErrorState
      v-else-if="overviewState.error.value || graphState.error.value || streamState.error.value"
      :message="String(overviewState.error.value || graphState.error.value || streamState.error.value)"
    />
    <template v-else>
      <section class="mode-stage graph-mode-stage">
        <article class="panel mode-main-panel graph-main-stage">
          <div class="mode-query-panel">
            <div class="graph-search-icon">⌕</div>
            <div class="mode-query-copy">
              <strong>当前问题</strong>
              <span>{{ graphState.data.value?.intent || graphIntent }}</span>
            </div>
            <div class="mode-query-metrics">
              <TagPill :label="`Nodes ${graphState.data.value?.graph?.node_count || 0}`" />
              <TagPill :label="`Edges ${graphState.data.value?.graph?.edge_count || 0}`" />
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

          <div class="chat-composer graph-query-composer">
            <div class="chat-input-wrap-wide">
              <textarea
                v-model="graphIntentDraft"
                class="text-area chat-input"
                placeholder="输入一个问题，例如：碳酸锂价格下跌会怎样影响下游盈利。"
              />
              <button class="button-primary chat-send" @click="submitIntent">开始检索</button>
            </div>
          </div>

          <div class="graph-stage graph-stage-dynamic">
            <section class="graph-canvas-panel">
              <div class="graph-stage-banner">
                <div class="graph-stage-banner-copy">
                  <span>图谱推演</span>
                  <strong>{{ phaseTrack[activePhaseIndex]?.headline || '等待推演' }}</strong>
                </div>
                <div class="graph-stage-banner-metric">
                  {{ phaseTrack[activePhaseIndex]?.metric || 'GRAPH' }}
                </div>
              </div>
              <div class="graph-phase-track">
                <div
                  v-for="(phase, index) in phaseTrack"
                  :key="phase.phase"
                  class="graph-phase-card"
                  :class="{ active: index === activePhaseIndex }"
                >
                  <span>{{ phase.phase }}</span>
                  <strong>{{ phase.headline }}</strong>
                  <small>{{ phase.metric }}</small>
                </div>
              </div>
              <div class="graph-canvas">
                <div class="graph-canvas-grid" />
                <svg class="graph-canvas-links" viewBox="0 0 100 100" preserveAspectRatio="none">
                  <line
                    v-for="link in graphCanvasLinks"
                    :key="link.id"
                    class="graph-link"
                    :class="{ active: link.active }"
                    :x1="link.x1"
                    :y1="link.y1"
                    :x2="link.x2"
                    :y2="link.y2"
                  />
                </svg>
                <div
                  v-for="node in graphCanvasNodes"
                  :key="node.id"
                  class="graph-floating-node"
                  :class="[`kind-${node.kind}`, { active: node.active }]"
                  :style="{ left: `${node.x}%`, top: `${node.y}%` }"
                  @mouseenter="node.step ? focusStep(node.step - 1) : undefined"
                >
                  <strong>{{ node.label }}</strong>
                  <span>{{ node.detail }}</span>
                </div>
              </div>
            </section>

            <div class="graph-support-strip graph-support-strip-dynamic">
              <section class="graph-support-card graph-frame-console">
                <div class="signal-code">当前推演帧</div>
                <div class="graph-frame-console-body">
                  <div class="graph-frame-copy">
                    <strong>{{ activeGraphFrame?.headline || '等待推演' }}</strong>
                    <span>{{ activeGraphFrame?.detail || '图谱推理正在准备阶段帧。' }}</span>
                  </div>
                  <div class="graph-frame-meter">
                    <div class="graph-frame-meter-label">
                      <span>Intensity</span>
                      <strong>{{ activeGraphFrame?.intensity || 0 }}</strong>
                    </div>
                    <div class="graph-frame-meter-track">
                      <i :style="{ width: `${activeGraphFrame?.intensity || 0}%` }" />
                    </div>
                  </div>
                  <div v-if="activeGraphFrame?.signal" class="graph-frame-signal">
                    <span>{{ activeGraphFrame.signal.label }}</span>
                    <strong>{{ activeGraphFrame.signal.value }}</strong>
                  </div>
                </div>
              </section>

              <section class="graph-support-card">
                <div class="signal-code">影响路径</div>
                <div class="graph-path-ribbon">
                  <div
                    v-for="item in inferencePath"
                    :key="`ribbon-${item.step}`"
                    class="graph-ribbon-step"
                    :class="{ active: item.step === activePathId }"
                    @mouseenter="focusStep(item.step - 1)"
                  >
                    <em>0{{ item.step }}</em>
                    <strong>{{ item.title }}</strong>
                    <span>{{ item.detail }}</span>
                    <i v-if="item.step !== inferencePath[inferencePath.length - 1]?.step">→</i>
                  </div>
                </div>
              </section>

              <section class="graph-support-card">
                <div class="signal-code">实时信号</div>
                <div class="graph-signal-stream">
                  <div
                    v-for="item in signalStream"
                    :key="item.label + item.value"
                    class="graph-signal-chip"
                    :class="`tone-${item.tone || 'accent'}`"
                  >
                    <span>{{ item.label }}</span>
                    <strong>{{ item.value }}</strong>
                  </div>
                </div>
              </section>

              <section class="graph-support-card">
                <div class="signal-code">继续查看</div>
                <div class="timeline-list compact-timeline">
                  <RouterLink
                    v-for="item in graphState.data.value?.evidence_navigation?.links || []"
                    :key="item.label + item.path"
                    class="timeline-item interactive-card"
                    :to="{ path: item.path, query: item.query || {} }"
                  >
                    <strong>{{ item.label }}</strong>
                  </RouterLink>
                </div>
              </section>

              <section class="graph-support-card">
                <div class="signal-code">最近检索</div>
                <div v-if="activeRun" class="graph-run-highlight">
                  <strong>{{ activeRun.company_name }}</strong>
                  <span>{{ activeRun.intent }}</span>
                </div>
                <div class="timeline-list compact-timeline">
                  <div
                    v-for="item in runsState.data.value?.runs || []"
                    :key="item.run_id"
                    class="timeline-item interactive-card"
                    @click="openGraphRun(item.run_id)"
                  >
                    <strong>{{ item.company_name }}</strong>
                    <span>{{ item.intent }}</span>
                  </div>
                </div>
                <div class="timeline-list compact-timeline">
                  <div v-for="item in streamState.data.value?.records || []" :key="item.id" class="timeline-item">
                    <strong>{{ item.title }}</strong>
                    <span>{{ item.stream_type }} · {{ item.status }}</span>
                  </div>
                </div>
              </section>
            </div>
          </div>
        </article>
      </section>
    </template>
  </AppShell>
</template>
