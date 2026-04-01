<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

import AppShell from '@/components/AppShell.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingState from '@/components/LoadingState.vue'
import { useAsyncState } from '@/composables/useAsyncState'
import { get, post } from '@/lib/api'

type GraphInferenceStep = { step: number; title: string; detail: string; type?: string }
type GraphSignal = { label: string; value: string; tone?: string }
type GraphFocalNode = { id: string; label: string; type: string }
type GraphNode = { id: string; label: string; type: string; meta?: Record<string, unknown> }
type GraphEdge = { source: string; target: string; label: string }

const overviewState = useAsyncState<any>()
const graphState = useAsyncState<any>()
const route = useRoute()

const selectedCompany = ref('')
const selectedPeriod = ref('')
const graphIntent = ref('碳酸锂价格下跌对下游盈利和风险的影响传导')
const graphIntentDraft = ref(graphIntent.value)
const activePathStep = ref(0)
const selectedNodeId = ref<string | null>(null)
const graphStageRef = ref<HTMLElement | null>(null)
const nodeLayout = ref<Record<string, { x: number; y: number }>>({})
const dragNodeId = ref<string | null>(null)
let graphTicker: number | null = null
let moveHandler: ((event: PointerEvent) => void) | null = null
let upHandler: ((event: PointerEvent) => void) | null = null

const companies = computed(() => overviewState.data.value?.companies || [])
const availablePeriods = computed(() => overviewState.data.value?.available_periods || [])
const hasCompanies = computed(() => companies.value.length > 0)
const canSubmitIntent = computed(() => !!selectedCompany.value && !!graphIntentDraft.value.trim())
const focalNodes = computed<GraphFocalNode[]>(() => graphState.data.value?.focal_nodes || [])
const inferencePath = computed<GraphInferenceStep[]>(() => graphState.data.value?.inference_path || [])
const activePathId = computed(() => inferencePath.value[activePathStep.value]?.step ?? null)
const rawGraphNodes = computed<GraphNode[]>(() => graphState.data.value?.graph?.nodes || [])
const rawGraphEdges = computed<GraphEdge[]>(() => graphState.data.value?.graph?.edges || [])
const signalStream = computed<GraphSignal[]>(() => graphState.data.value?.signal_stream || [])
const evidenceNavigation = computed(() => graphState.data.value?.evidence_navigation?.links || [])
const executionStream = computed(() => graphState.data.value?.execution_stream || [])
const summary = computed(() => graphState.data.value?.summary || {})
const graphSummary = computed(() => graphState.data.value?.graph?.summary || {})
const graphCommandSurface = computed(() => graphState.data.value?.graph_command_surface || null)
const graphLiveFrames = computed(() => graphState.data.value?.graph_live_frames || [])
const currentFrame = computed(() => graphLiveFrames.value[activePathStep.value] || null)
const pathEvidenceLinks = computed(() => evidenceNavigation.value.slice(0, 2))
const visibleNodeIds = computed(() => {
  const nodes = rawGraphNodes.value
  const edges = rawGraphEdges.value
  if (!nodes.length) return new Set<string>()

  const focalSet = new Set(focalNodes.value.map((item) => item.id))
  const selected = selectedNodeId.value
  if (selected) focalSet.add(selected)
  if (!focalSet.size && nodes[0]) focalSet.add(nodes[0].id)

  const visible = new Set<string>(focalSet)
  edges.forEach((edge) => {
    if (focalSet.has(edge.source) || focalSet.has(edge.target)) {
      visible.add(edge.source)
      visible.add(edge.target)
    }
  })

  if (visible.size < 8) {
    edges.forEach((edge) => {
      if (visible.has(edge.source) || visible.has(edge.target)) {
        visible.add(edge.source)
        visible.add(edge.target)
      }
    })
  }

  if (visible.size > 12) {
    const ordered = nodes.filter((node) => visible.has(node.id)).slice(0, 12)
    return new Set(ordered.map((node) => node.id))
  }

  return visible
})

function nodeKind(type: string) {
  if (type === 'company') return 'company'
  if (type === 'report_period') return 'period'
  if (type === 'risk_label') return 'risk'
  if (type === 'alert') return 'alert'
  if (type === 'task') return 'task'
  if (type === 'signal_event' || type === 'subindustry_signal') return 'signal'
  if (type === 'watchboard') return 'watch'
  if (['execution_stream', 'workspace_run'].includes(type)) return 'stream'
  if (['document_artifact', 'artifact_evidence', 'research_report'].includes(type)) return 'evidence'
  return 'support'
}

function nodeAnchor(kind: string) {
  if (kind === 'company') return { x: 18, y: 48 }
  if (kind === 'period') return { x: 38, y: 22 }
  if (kind === 'risk') return { x: 58, y: 28 }
  if (kind === 'alert') return { x: 80, y: 28 }
  if (kind === 'task') return { x: 82, y: 50 }
  if (kind === 'signal') return { x: 54, y: 66 }
  if (kind === 'watch') return { x: 26, y: 74 }
  if (kind === 'stream') return { x: 82, y: 72 }
  if (kind === 'evidence') return { x: 54, y: 82 }
  return { x: 34, y: 78 }
}

function nodeDetail(node: GraphNode) {
  const meta = node.meta || {}
  if (typeof meta.summary === 'string' && meta.summary) return meta.summary
  if (typeof meta.path === 'string' && meta.path) return meta.path
  if (typeof meta.status === 'string' && meta.status) return `状态：${meta.status}`
  if (typeof meta.priority === 'string' && meta.priority) return `优先级：${meta.priority}`
  if (typeof meta.grade === 'string' && meta.grade) return `评级：${meta.grade}`
  if (typeof meta.report_period === 'string' && meta.report_period) return `报期：${meta.report_period}`
  return node.type
}

function displayNodeType(type: string) {
  const map: Record<string, string> = {
    company: '企业',
    report_period: '报期',
    risk_label: '风险',
    alert: '预警',
    task: '动作',
    signal_event: '信号',
    subindustry_signal: '信号',
    watchboard: '观察',
    execution_stream: '执行',
    workspace_run: '执行',
    document_artifact: '文档',
    artifact_evidence: '证据',
    research_report: '研报',
  }
  return map[type] || '节点'
}

function initializeGraphLayout() {
  const grouped = new Map<string, GraphNode[]>()
  rawGraphNodes.value.forEach((node) => {
    const kind = nodeKind(node.type)
    grouped.set(kind, [...(grouped.get(kind) || []), node])
  })

  const nextLayout: Record<string, { x: number; y: number }> = {}
  Array.from(grouped.entries()).forEach(([kind, nodes]) => {
    const anchor = nodeAnchor(kind)
    nodes.forEach((node, index) => {
      const spread = nodes.length === 1 ? 0 : index - (nodes.length - 1) / 2
      const verticalOffset = spread * 11
      const horizontalOffset = (Math.abs(spread) % 2) * 5
      nextLayout[node.id] = {
        x: Math.max(8, Math.min(92, anchor.x + horizontalOffset)),
        y: Math.max(10, Math.min(90, anchor.y + verticalOffset)),
      }
    })
  })

  nodeLayout.value = nextLayout
  selectedNodeId.value = focalNodes.value[0]?.id || rawGraphNodes.value[0]?.id || null
}

const graphCanvasNodes = computed(() =>
  rawGraphNodes.value
    .filter((node) => visibleNodeIds.value.has(node.id))
    .map((node) => {
      const position = nodeLayout.value[node.id] || { x: 50, y: 50 }
      return {
        ...node,
        kind: nodeKind(node.type),
        detail: nodeDetail(node),
        x: position.x,
        y: position.y,
        isFocal: focalNodes.value.some((item) => item.id === node.id),
        isSelected: selectedNodeId.value === node.id,
      }
    }),
)

const graphCanvasLinks = computed(() =>
  rawGraphEdges.value
    .filter((edge) => visibleNodeIds.value.has(edge.source) && visibleNodeIds.value.has(edge.target))
    .map((edge, index) => {
      const source = graphCanvasNodes.value.find((node) => node.id === edge.source)
      const target = graphCanvasNodes.value.find((node) => node.id === edge.target)
      if (!source || !target) return null
      const midX = (source.x + target.x) / 2
      const midY = (source.y + target.y) / 2
      const curve = Math.max(10, Math.abs(target.x - source.x) * 0.16)
      return {
        id: `edge-${index}-${edge.source}-${edge.target}`,
        pathData: `M ${source.x} ${source.y} C ${source.x + curve} ${source.y}, ${target.x - curve} ${target.y}, ${target.x} ${target.y}`,
        label: edge.label,
        midX,
        midY,
        isActive: selectedNodeId.value === source.id || selectedNodeId.value === target.id,
      }
    })
    .filter(Boolean),
)

const selectedNode = computed(() =>
  graphCanvasNodes.value.find((node) => node.id === selectedNodeId.value) || null,
)

async function loadGraph() {
  if (!selectedCompany.value) return
  await graphState.execute(() =>
    post('/company/graph-query', {
      company_name: selectedCompany.value,
      report_period: selectedPeriod.value || null,
      user_role: 'management',
      intent: graphIntent.value,
    }),
  )
  activePathStep.value = 0
}

function submitIntent() {
  graphIntent.value = graphIntentDraft.value.trim() || graphIntent.value
  loadGraph()
}

function updateNodePosition(event: PointerEvent) {
  if (!dragNodeId.value || !graphStageRef.value) return
  const rect = graphStageRef.value.getBoundingClientRect()
  const x = ((event.clientX - rect.left) / rect.width) * 100
  const y = ((event.clientY - rect.top) / rect.height) * 100
  nodeLayout.value = {
    ...nodeLayout.value,
    [dragNodeId.value]: {
      x: Math.max(6, Math.min(94, x)),
      y: Math.max(8, Math.min(92, y)),
    },
  }
}

function stopDrag() {
  dragNodeId.value = null
  if (moveHandler) {
    window.removeEventListener('pointermove', moveHandler)
    moveHandler = null
  }
  if (upHandler) {
    window.removeEventListener('pointerup', upHandler)
    upHandler = null
  }
}

function beginDrag(nodeId: string, event: PointerEvent) {
  event.preventDefault()
  selectedNodeId.value = nodeId
  dragNodeId.value = nodeId
  moveHandler = (moveEvent: PointerEvent) => updateNodePosition(moveEvent)
  upHandler = () => stopDrag()
  window.addEventListener('pointermove', moveHandler)
  window.addEventListener('pointerup', upHandler)
}

function toneClass(tone?: string) {
  if (tone === 'risk' || tone === 'warning') return 'is-risk'
  if (tone === 'success') return 'is-success'
  if (tone === 'accent') return 'is-accent'
  return 'is-default'
}

onMounted(async () => {
  await overviewState.execute(() => get('/workspace/companies'))
  selectedCompany.value =
    (typeof route.query.company === 'string' ? route.query.company : '') || companies.value[0] || ''
  selectedPeriod.value = typeof route.query.period === 'string' && route.query.period
    ? route.query.period
    : (overviewState.data.value?.preferred_period || '')
  await loadGraph()

  graphTicker = window.setInterval(() => {
    if (!inferencePath.value.length) return
    activePathStep.value = (activePathStep.value + 1) % inferencePath.value.length
  }, 3000)
})

onBeforeUnmount(() => {
  if (graphTicker) {
    window.clearInterval(graphTicker)
    graphTicker = null
  }
  stopDrag()
})

watch(() => graphState.data.value?.run_id, () => {
  if (!rawGraphNodes.value.length) return
  initializeGraphLayout()
})

watch(selectedCompany, async () => { await loadGraph() })
watch(selectedPeriod, async () => { await loadGraph() })
</script>

<template>
  <AppShell title="">
    <div class="graph-console">
      <section class="graph-header">
        <div class="graph-heading">
          <span class="graph-kicker">证据链图谱工作台</span>
          <h1>图谱检索</h1>
          <p>{{ selectedCompany || '选择公司' }} · {{ graphCommandSurface?.focus_label || '沿证据、风险与执行链路继续追下去' }}</p>
        </div>

        <div class="graph-controls">
          <label class="graph-select">
            <span>公司</span>
            <select v-model="selectedCompany">
              <option v-if="!companies.length" value="">暂无公司</option>
              <option v-for="company in companies" :key="company" :value="company">{{ company }}</option>
            </select>
          </label>
          <label class="graph-select">
            <span>报期</span>
            <select v-model="selectedPeriod">
              <option value="">默认主周期</option>
              <option v-for="period in availablePeriods" :key="period" :value="period">{{ period }}</option>
            </select>
          </label>
        </div>
      </section>

      <section class="graph-query-strip">
        <div class="query-strip-main">
            <div class="query-strip-icon">图</div>
            <div>
              <h2>{{ graphIntent }}</h2>
              <p>{{ currentFrame?.detail || graphCommandSurface?.headline || '先看主链，再决定沿哪条证据继续追。' }}</p>
            </div>
          </div>

        <div class="query-strip-meta">
          <span>{{ selectedCompany || '未选择公司' }}</span>
          <span v-if="selectedPeriod">{{ selectedPeriod }}</span>
        </div>
      </section>

      <section class="graph-intent-dock">
        <textarea
          v-model="graphIntentDraft"
          class="intent-textarea"
          :disabled="graphState.loading.value || !selectedCompany"
          :placeholder="selectedCompany ? '输入你要追问的传导问题，例如：价格下跌如何传到盈利和风险' : '当前无可检索企业，请先完成公司池接入'"
        />
        <button class="intent-submit" :disabled="graphState.loading.value || !canSubmitIntent" @click="submitIntent">
          {{ graphState.loading.value ? '检索中...' : '开始检索' }}
        </button>
      </section>

      <LoadingState v-if="overviewState.loading.value || graphState.loading.value" class="graph-state" />
      <ErrorState v-else-if="graphState.error.value" :message="String(graphState.error.value)" class="graph-state" />
      <section v-else-if="!hasCompanies" class="graph-state graph-empty">
        <p>当前无可检索企业，请先完成正式公司池和图谱数据接入。</p>
      </section>

      <template v-else>
        <section class="graph-stage" ref="graphStageRef">
          <div class="stage-summary">
            <span>当前聚焦</span>
            <strong>{{ currentFrame?.headline || graphCommandSurface?.title || '关键证据链路' }}</strong>
            <p>{{ graphCommandSurface?.headline || '只保留这一轮真正相关的节点和主链。' }}</p>
          </div>

          <div class="stage-signal-row">
            <span
              v-for="item in signalStream.slice(0, 2)"
              :key="`${item.label}-${item.value}`"
              class="stage-signal"
              :class="toneClass(item.tone)"
            >
              {{ item.label }} · {{ item.value }}
            </span>
          </div>

          <svg class="graph-svg" viewBox="0 0 100 100" preserveAspectRatio="none">
            <defs>
              <marker id="graph-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" fill="rgba(148,163,184,0.72)" />
              </marker>
            </defs>
            <g v-for="link in graphCanvasLinks" :key="link!.id">
              <path :d="link!.pathData" class="graph-link" :class="{ 'is-active': link!.isActive }" marker-end="url(#graph-arrow)" />
              <text :x="link!.midX" :y="link!.midY" class="graph-link-label">{{ link!.label }}</text>
            </g>
          </svg>

          <button
            v-for="node in graphCanvasNodes"
            :key="node.id"
            class="graph-node"
            :class="[`node-${node.kind}`, { 'is-focal': node.isFocal, 'is-selected': node.isSelected }]"
            :style="{ left: `${node.x}%`, top: `${node.y}%` }"
            @click="selectedNodeId = node.id"
            @pointerdown="beginDrag(node.id, $event)"
          >
            <span class="node-pill" :class="`kind-${node.kind}`"></span>
            <span class="node-name">{{ node.label }}</span>
            <span class="node-type">{{ displayNodeType(node.type) }}</span>
          </button>

          <div v-if="selectedNode" class="selected-node-panel">
            <span>当前节点</span>
            <strong>{{ selectedNode.label }}</strong>
            <p>{{ selectedNode.detail }}</p>
            <div v-if="pathEvidenceLinks.length || executionStream.length" class="selected-node-links">
              <RouterLink
                v-for="item in pathEvidenceLinks"
                :key="`${item.label}-${item.path}`"
                :to="{ path: item.path, query: item.query || {} }"
                class="selected-node-link"
              >
                {{ item.label }}
              </RouterLink>
              <span
                v-for="item in executionStream.slice(0, 1)"
                :key="item.id"
                class="selected-node-link is-muted"
              >
                {{ item.title }}
              </span>
            </div>
          </div>

          <div v-if="!graphCanvasNodes.length" class="stage-empty">
            <p>输入检索意图后点击“开始检索”生成真实图谱。</p>
          </div>
        </section>

        <section class="path-dock">
          <div class="path-dock-head">
            <span>关键链路</span>
            <strong>推理主链</strong>
          </div>

          <div class="path-track">
            <button
              v-for="(item, idx) in inferencePath"
              :key="item.step"
              class="path-step"
              :class="{ 'is-active': item.step === activePathId || idx <= activePathStep }"
              @click="activePathStep = idx"
            >
              <em>{{ item.step }}</em>
              <strong>{{ item.title }}</strong>
              <p>{{ item.detail }}</p>
            </button>
          </div>
        </section>

      </template>
    </div>
  </AppShell>
</template>

<style scoped>
.graph-console {
  min-height: 100%;
  display: grid;
  grid-template-rows: auto auto auto minmax(0, 1fr) auto;
  gap: 16px;
  width: 100%;
  max-width: 1320px;
  margin: 0 auto;
}

.graph-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 18px;
  padding-bottom: 14px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.graph-heading {
  display: grid;
  gap: 8px;
}

.graph-kicker,
.graph-select span,
.query-strip-meta span,
.stage-summary span,
.path-dock-head span,
.bottom-head span,
.selected-node-panel span,
.path-step em {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}

.graph-kicker {
  color: rgba(96, 165, 250, 0.78);
}

.graph-heading h1,
.query-strip-main h2,
.stage-summary strong {
  margin: 0;
  color: #f8fafc;
  letter-spacing: -0.05em;
}

.graph-heading h1 {
  font-size: clamp(24px, 2.4vw, 30px);
  line-height: 1.02;
}

.graph-heading p,
.query-strip-main p,
.stage-summary p,
.selected-node-panel p,
.path-step p,
.bottom-link p {
  margin: 0;
  color: rgba(148, 163, 184, 0.9);
  line-height: 1.7;
  font-size: 13px;
}

.graph-controls {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.graph-select {
  display: grid;
  gap: 8px;
}

.graph-select span,
.path-step em,
.bottom-head span,
.selected-node-panel span {
  color: rgba(120, 143, 172, 0.84);
}

.graph-select select {
  min-width: 180px;
  min-height: 44px;
  padding: 0 14px;
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.03);
  color: #eef2f7;
}

.graph-query-strip,
.graph-intent-dock,
.graph-stage,
.path-dock,
.bottom-panel,
.graph-state {
  border-radius: 20px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: linear-gradient(180deg, rgba(16, 17, 20, 0.98), rgba(12, 13, 17, 0.98));
}

.graph-query-strip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 14px;
}

.query-strip-main {
  display: flex;
  align-items: center;
  gap: 16px;
  min-width: 0;
}

.query-strip-main h2 {
  font-size: clamp(16px, 1.6vw, 18px);
  line-height: 1.12;
}

.query-strip-icon {
  width: 36px;
  height: 36px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  color: #60a5fa;
  border: 1px solid rgba(96, 165, 250, 0.26);
  background: rgba(27, 43, 108, 0.48);
  font-weight: 700;
}

.query-strip-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
}

.query-strip-meta span {
  min-height: 34px;
  padding: 0 12px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  background: rgba(255, 255, 255, 0.03);
  color: rgba(203, 213, 225, 0.82);
}

.graph-intent-dock {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 118px;
  gap: 12px;
  padding: 6px 10px;
}

.intent-textarea {
  width: 100%;
  min-height: 48px;
  resize: none;
  border: none;
  background: transparent;
  color: #eef2f7;
  font: inherit;
  line-height: 1.6;
  outline: none;
}

.intent-submit {
  border-radius: 14px;
  border: 1px solid rgba(52, 211, 153, 0.26);
  background: rgba(18, 62, 45, 0.92);
  color: #f0fdf4;
  font-weight: 700;
  cursor: pointer;
}

.intent-submit:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.graph-state {
  min-height: 320px;
  display: grid;
  place-items: center;
  padding: 32px;
}

.graph-empty p {
  margin: 0;
  color: rgba(148, 163, 184, 0.9);
}

.graph-stage {
  position: relative;
  min-height: 500px;
  overflow: hidden;
  background:
    radial-gradient(circle at 20% 16%, rgba(52, 211, 153, 0.08), transparent 24%),
    radial-gradient(circle at 82% 18%, rgba(96, 165, 250, 0.08), transparent 26%),
    linear-gradient(180deg, rgba(7, 9, 13, 0.98), rgba(5, 7, 10, 0.98));
}

.stage-summary,
.stage-signal-row,
.selected-node-panel {
  position: absolute;
  z-index: 3;
}

.stage-summary {
  left: 18px;
  top: 18px;
  max-width: 262px;
  display: grid;
  gap: 8px;
  padding: 11px 13px;
  border-radius: 16px;
  background: rgba(9, 11, 16, 0.82);
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.stage-summary strong {
  font-size: 16px;
  line-height: 1.06;
}

.stage-signal-row {
  right: 18px;
  top: 18px;
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
  max-width: 280px;
}

.stage-signal {
  min-height: 34px;
  padding: 0 12px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  border: 1px solid rgba(255, 255, 255, 0.08);
  font-size: 12px;
}

.stage-signal.is-risk {
  background: rgba(69, 10, 10, 0.76);
  color: #fecaca;
}

.stage-signal.is-success {
  background: rgba(6, 78, 59, 0.76);
  color: #bbf7d0;
}

.stage-signal.is-accent {
  background: rgba(8, 47, 73, 0.62);
  color: #bfdbfe;
}

.stage-signal.is-default {
  background: rgba(255, 255, 255, 0.04);
  color: rgba(203, 213, 225, 0.9);
}

.selected-node-panel {
  right: 18px;
  bottom: 18px;
  max-width: 300px;
  display: grid;
  gap: 8px;
  padding: 11px 13px;
  border-radius: 16px;
  background: rgba(9, 11, 16, 0.88);
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.selected-node-panel strong {
  color: #f8fafc;
  font-size: 15px;
  line-height: 1.08;
}

.selected-node-links {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 2px;
}

.selected-node-link {
  min-height: 32px;
  padding: 0 10px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  color: #dbe7f3;
  text-decoration: none;
  font-size: 12px;
}

.selected-node-link.is-muted {
  color: rgba(148, 163, 184, 0.84);
}

.graph-svg {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}

.graph-link {
  fill: none;
  stroke: rgba(71, 85, 105, 0.46);
  stroke-width: 0.24;
  opacity: 0.62;
}

.graph-link.is-active {
  stroke: rgba(94, 234, 212, 0.96);
  opacity: 1;
}

.graph-link-label {
  fill: rgba(148, 163, 184, 0.84);
  font-size: 1.35px;
  text-anchor: middle;
}

.graph-node {
  position: absolute;
  transform: translate(-50%, -50%);
  min-width: 86px;
  max-width: 120px;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  padding: 7px 8px 7px 10px;
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(9, 11, 16, 0.92);
  backdrop-filter: blur(14px);
  cursor: grab;
  text-align: left;
  z-index: 2;
}

.graph-node:active {
  cursor: grabbing;
}

.graph-node.is-focal {
  box-shadow: 0 0 0 1px rgba(94, 234, 212, 0.18), 0 16px 30px rgba(0, 0, 0, 0.3);
}

.graph-node.is-selected {
  border-color: rgba(94, 234, 212, 0.42);
  box-shadow: 0 0 0 1px rgba(94, 234, 212, 0.2), 0 18px 38px rgba(0, 0, 0, 0.36);
}

.node-company {
  border-color: rgba(16, 185, 129, 0.2);
}

.node-period {
  border-color: rgba(59, 130, 246, 0.2);
}

.node-risk {
  border-color: rgba(244, 63, 94, 0.2);
}

.node-alert {
  border-color: rgba(251, 191, 36, 0.2);
}

.node-task {
  border-color: rgba(96, 165, 250, 0.2);
}

.node-signal {
  border-color: rgba(34, 211, 238, 0.2);
}

.node-watch,
.node-stream,
.node-evidence,
.node-support {
  border-color: rgba(148, 163, 184, 0.16);
}

.node-pill {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  margin-bottom: 3px;
}

.node-pill.kind-company {
  background: #34d399;
}

.node-pill.kind-period,
.node-pill.kind-task {
  background: #60a5fa;
}

.node-pill.kind-risk {
  background: #f43f5e;
}

.node-pill.kind-alert {
  background: #f59e0b;
}

.node-pill.kind-signal {
  background: #22d3ee;
}

.node-pill.kind-watch,
.node-pill.kind-stream,
.node-pill.kind-evidence,
.node-pill.kind-support {
  background: #94a3b8;
}

.node-name {
  font-size: 10px;
  font-weight: 700;
  line-height: 1.35;
  color: #f8fafc;
}

.node-type {
  font-size: 9px;
  color: rgba(148, 163, 184, 0.86);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.stage-empty {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  color: rgba(148, 163, 184, 0.88);
}

.path-dock {
  padding: 12px 14px;
}

.path-dock-head,
.bottom-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.path-dock-head strong,
.bottom-head strong {
  color: #f8fafc;
}

.path-track {
  display: flex;
  gap: 10px;
  overflow-x: auto;
  padding-bottom: 4px;
}

.path-step {
  min-width: 154px;
  padding: 10px 11px;
  border-radius: 16px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.02);
  text-align: left;
  cursor: pointer;
  display: grid;
  gap: 8px;
}

.path-step strong {
  color: #f8fafc;
}

.path-step p {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  margin: 0;
  color: rgba(203, 213, 225, 0.82);
  line-height: 1.55;
}

.path-step.is-active {
  border-color: rgba(94, 234, 212, 0.22);
  background: rgba(18, 62, 45, 0.84);
}

@media (max-width: 1100px) {
  .selected-node-panel {
    max-width: calc(100% - 36px);
  }
}

@media (max-width: 860px) {
  .graph-header,
  .graph-controls,
  .graph-query-strip,
  .query-strip-main,
  .graph-intent-dock {
    flex-direction: column;
    grid-template-columns: 1fr;
    align-items: stretch;
  }

  .graph-stage {
    min-height: 500px;
  }

  .stage-summary,
  .stage-signal-row,
  .selected-node-panel {
    position: static;
    margin: 16px;
  }

  .graph-node {
    min-width: 104px;
    max-width: 138px;
    padding: 8px 10px;
  }
}
</style>
