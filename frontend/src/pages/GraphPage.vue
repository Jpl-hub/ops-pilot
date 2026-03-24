<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

import AppShell from '@/components/AppShell.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingState from '@/components/LoadingState.vue'
import { useAsyncState } from '@/composables/useAsyncState'
import { get, post } from '@/lib/api'

type GraphInferenceStep = { step: number; title: string; detail: string; type?: string }
type GraphRouteBand = { step: number; headline: string; detail: string; tone?: string; signal?: string; intensity?: number }
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
const routeBands = computed<GraphRouteBand[]>(() => graphState.data.value?.graph_route_bands || [])
const signalStream = computed<GraphSignal[]>(() => graphState.data.value?.signal_stream || [])
const evidenceNavigation = computed(() => graphState.data.value?.evidence_navigation?.links || [])
const relatedRoutes = computed(() => graphState.data.value?.related_routes || [])
const summary = computed(() => graphState.data.value?.summary || {})

function nodeKind(type: string) {
  if (type === 'company') return 'company'
  if (type === 'report_period') return 'period'
  if (type === 'risk_label') return 'risk'
  if (type === 'alert') return 'alert'
  if (type === 'task') return 'task'
  if (['execution_stream', 'workspace_run'].includes(type)) return 'stream'
  if (['document_artifact', 'artifact_evidence', 'research_report'].includes(type)) return 'evidence'
  return 'support'
}

function nodeAnchor(kind: string) {
  if (kind === 'company') return { x: 18, y: 50 }
  if (kind === 'period') return { x: 42, y: 20 }
  if (kind === 'risk') return { x: 56, y: 34 }
  if (kind === 'alert') return { x: 80, y: 24 }
  if (kind === 'task') return { x: 80, y: 48 }
  if (kind === 'stream') return { x: 56, y: 70 }
  if (kind === 'evidence') return { x: 82, y: 72 }
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
      const verticalOffset = spread * 12
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
  rawGraphNodes.value.map((node) => {
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
  rawGraphEdges.value.map((edge, index) => {
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
  }).filter(Boolean),
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
  }, 2800)
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
  <AppShell title="图谱检索">
    <div class="graph-page">
      <section class="graph-toolbar glass-panel">
        <div class="toolbar-main">
          <div class="toolbar-mark">图</div>
          <div>
            <h2 class="toolbar-title">{{ selectedCompany || '选择公司' }}</h2>
            <p class="toolbar-subtitle">真实节点、真实连线、真实运行记录驱动的关系检索</p>
          </div>
        </div>
        <div class="toolbar-fields">
          <label class="toolbar-field">
            <span>公司</span>
            <select v-model="selectedCompany" class="toolbar-select">
              <option v-if="!companies.length" value="">暂无公司</option>
              <option v-for="c in companies" :key="c" :value="c">{{ c }}</option>
            </select>
          </label>
          <label class="toolbar-field">
            <span>报期</span>
            <select v-model="selectedPeriod" class="toolbar-select">
              <option value="">默认主周期</option>
              <option v-for="p in availablePeriods" :key="p" :value="p">{{ p }}</option>
            </select>
          </label>
        </div>
      </section>

      <section class="graph-intent glass-panel">
        <textarea
          v-model="graphIntentDraft"
          class="intent-textarea"
          :disabled="graphState.loading.value || !selectedCompany"
          :placeholder="selectedCompany ? '输入你要追问的传导问题，例如：价格下跌如何传到盈利和短债风险' : '当前无可检索企业，请先完成公司池接入'"
        />
        <div class="intent-meta">
          <div class="intent-stats">
            <span>节点 {{ graphState.data.value?.graph?.node_count ?? 0 }}</span>
            <span>边 {{ graphState.data.value?.graph?.edge_count ?? 0 }}</span>
            <span>风险 {{ summary.risk_count ?? 0 }}</span>
            <span>运行 {{ summary.execution_records ?? 0 }}</span>
          </div>
          <button class="button-primary" :disabled="graphState.loading.value || !canSubmitIntent" @click="submitIntent">
            {{ graphState.loading.value ? '检索中…' : '开始图谱检索' }}
          </button>
        </div>
      </section>

      <LoadingState v-if="overviewState.loading.value || graphState.loading.value" class="state-panel" />
      <ErrorState v-else-if="graphState.error.value" :message="String(graphState.error.value)" class="state-panel" />
      <section v-else-if="!hasCompanies" class="glass-panel state-panel">
        <p class="state-text">当前无可检索企业，请先完成正式公司池和图谱数据接入。</p>
      </section>

      <section v-else class="graph-body">
        <div class="graph-stage glass-panel" ref="graphStageRef">
          <div class="stage-header">
            <div>
              <h3>关系图谱舞台</h3>
              <p>节点可拖拽，右侧会联动显示当前节点与链路明细。</p>
            </div>
            <div class="stage-chip">当前路径步骤 {{ activePathId ?? '-' }}</div>
          </div>

          <svg class="graph-svg" viewBox="0 0 100 100" preserveAspectRatio="none">
            <defs>
              <marker id="graph-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" fill="rgba(148,163,184,0.75)" />
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
            <span class="node-name">{{ node.label }}</span>
            <span class="node-type">{{ node.type }}</span>
          </button>

          <div v-if="!graphCanvasNodes.length" class="stage-empty">
            <p>输入检索意图后点击“开始图谱检索”生成真实图谱。</p>
          </div>
        </div>

        <aside class="graph-side">
          <section class="glass-panel side-card">
            <div class="side-title">检索摘要</div>
            <div class="metric-grid">
              <div class="metric-card">
                <span>体检分数</span>
                <strong>{{ summary.score ?? '-' }}</strong>
              </div>
              <div class="metric-card">
                <span>评级</span>
                <strong>{{ summary.grade ?? '-' }}</strong>
              </div>
              <div class="metric-card">
                <span>风险标签</span>
                <strong>{{ summary.risk_count ?? 0 }}</strong>
              </div>
              <div class="metric-card">
                <span>执行记录</span>
                <strong>{{ summary.execution_records ?? 0 }}</strong>
              </div>
            </div>
          </section>

          <section class="glass-panel side-card">
            <div class="side-title">当前节点</div>
            <template v-if="selectedNode">
              <div class="selected-node-head">
                <strong>{{ selectedNode.label }}</strong>
                <span>{{ selectedNode.type }}</span>
              </div>
              <p class="selected-node-detail">{{ selectedNode.detail }}</p>
            </template>
            <p v-else class="muted-copy">点击图谱节点查看当前节点的真实元数据。</p>
          </section>

          <section class="glass-panel side-card">
            <div class="side-title">主传导链</div>
            <button
              v-for="(item, idx) in inferencePath"
              :key="item.step"
              class="path-card"
              :class="{ 'is-active': item.step === activePathId || idx <= activePathStep }"
              @click="activePathStep = idx"
            >
              <span class="path-step">步骤 {{ item.step }}</span>
              <strong>{{ item.title }}</strong>
              <p>{{ item.detail }}</p>
            </button>
          </section>

          <section class="glass-panel side-card">
            <div class="side-title">信号带</div>
            <div class="signal-list">
              <div v-for="band in routeBands" :key="band.step" class="signal-band" :class="toneClass(band.tone)">
                <div class="signal-band-head">
                  <strong>{{ band.headline }}</strong>
                  <span>{{ band.intensity ?? 0 }}</span>
                </div>
                <p>{{ band.detail }}</p>
              </div>
            </div>
            <div class="signal-pill-row">
              <span v-for="item in signalStream" :key="`${item.label}-${item.value}`" class="signal-pill" :class="toneClass(item.tone)">
                {{ item.label }}
              </span>
            </div>
          </section>

          <section class="glass-panel side-card">
            <div class="side-title">证据与下钻</div>
            <RouterLink
              v-for="item in [...relatedRoutes, ...evidenceNavigation]"
              :key="`${item.label}-${item.path}`"
              :to="{ path: item.path, query: item.query || {} }"
              class="route-link"
            >
              <span>{{ item.label }}</span>
              <strong>进入</strong>
            </RouterLink>
          </section>
        </aside>
      </section>
    </div>
  </AppShell>
</template>

<style scoped>
.graph-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.glass-panel {
  background: linear-gradient(180deg, rgba(9, 14, 25, 0.96), rgba(12, 18, 32, 0.9));
  border: 1px solid rgba(148, 163, 184, 0.12);
  border-radius: 18px;
  box-shadow: 0 18px 48px rgba(2, 6, 23, 0.28);
}

.graph-toolbar,
.graph-intent {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 20px;
}

.toolbar-main {
  display: flex;
  align-items: center;
  gap: 14px;
}

.toolbar-mark {
  width: 44px;
  height: 44px;
  display: grid;
  place-items: center;
  border-radius: 14px;
  background: rgba(45, 212, 191, 0.14);
  border: 1px solid rgba(45, 212, 191, 0.35);
  color: #5eead4;
  font-weight: 700;
}

.toolbar-title {
  margin: 0;
  font-size: 22px;
  color: #f8fafc;
}

.toolbar-subtitle {
  margin: 4px 0 0;
  color: #94a3b8;
  font-size: 13px;
}

.toolbar-fields {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.toolbar-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  color: #94a3b8;
  font-size: 12px;
}

.toolbar-select {
  min-width: 150px;
  min-height: 38px;
  border-radius: 10px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  background: rgba(15, 23, 42, 0.86);
  color: #f8fafc;
  padding: 0 12px;
}

.graph-intent {
  align-items: stretch;
}

.intent-textarea {
  flex: 1;
  min-height: 74px;
  border: none;
  resize: vertical;
  background: transparent;
  color: #e2e8f0;
  font-size: 14px;
  line-height: 1.65;
  outline: none;
}

.intent-meta {
  width: 280px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 16px;
}

.intent-stats {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.intent-stats span {
  padding: 10px 12px;
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.72);
  color: #cbd5e1;
  font-size: 12px;
}

.state-panel {
  min-height: 480px;
}

.state-text {
  margin: 0;
  padding: 48px 32px;
  text-align: center;
  color: #94a3b8;
}

.graph-body {
  display: grid;
  grid-template-columns: minmax(0, 1.6fr) minmax(320px, 0.9fr);
  gap: 16px;
  min-height: 720px;
}

.graph-stage {
  position: relative;
  min-height: 720px;
  padding: 18px 18px 24px;
  overflow: hidden;
  background:
    radial-gradient(circle at 24% 26%, rgba(34, 197, 94, 0.12), transparent 28%),
    radial-gradient(circle at 84% 16%, rgba(59, 130, 246, 0.14), transparent 24%),
    linear-gradient(180deg, rgba(8, 13, 22, 0.98), rgba(6, 10, 18, 0.96));
}

.stage-header {
  position: relative;
  z-index: 3;
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.stage-header h3 {
  margin: 0;
  color: #f8fafc;
  font-size: 18px;
}

.stage-header p {
  margin: 6px 0 0;
  color: #94a3b8;
  font-size: 13px;
}

.stage-chip {
  padding: 8px 12px;
  border-radius: 999px;
  background: rgba(45, 212, 191, 0.12);
  border: 1px solid rgba(45, 212, 191, 0.24);
  color: #99f6e4;
  font-size: 12px;
}

.graph-svg {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}

.graph-link {
  fill: none;
  stroke: rgba(148, 163, 184, 0.35);
  stroke-width: 0.24;
  opacity: 0.72;
}

.graph-link.is-active {
  stroke: rgba(45, 212, 191, 0.92);
  opacity: 1;
}

.graph-link-label {
  fill: rgba(226, 232, 240, 0.84);
  font-size: 2.1px;
  text-anchor: middle;
}

.graph-node {
  position: absolute;
  transform: translate(-50%, -50%);
  min-width: 118px;
  max-width: 170px;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  padding: 10px 12px;
  border-radius: 14px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  cursor: grab;
  text-align: left;
  transition: transform 0.16s ease, box-shadow 0.16s ease, border-color 0.16s ease;
  z-index: 2;
}

.graph-node:hover {
  transform: translate(-50%, -50%) scale(1.03);
}

.graph-node:active {
  cursor: grabbing;
}

.graph-node.is-focal {
  box-shadow: 0 0 0 1px rgba(45, 212, 191, 0.3), 0 16px 34px rgba(20, 184, 166, 0.18);
}

.graph-node.is-selected {
  border-color: rgba(125, 211, 252, 0.66);
  box-shadow: 0 0 0 1px rgba(125, 211, 252, 0.3), 0 18px 42px rgba(14, 165, 233, 0.18);
}

.node-company {
  background: rgba(8, 47, 73, 0.92);
  color: #e0f2fe;
}

.node-period {
  background: rgba(20, 83, 45, 0.9);
  color: #dcfce7;
}

.node-risk {
  background: rgba(127, 29, 29, 0.92);
  color: #fee2e2;
}

.node-alert {
  background: rgba(120, 53, 15, 0.92);
  color: #ffedd5;
}

.node-task {
  background: rgba(30, 41, 59, 0.96);
  color: #e2e8f0;
}

.node-stream {
  background: rgba(76, 29, 149, 0.9);
  color: #ede9fe;
}

.node-evidence {
  background: rgba(55, 48, 163, 0.9);
  color: #e0e7ff;
}

.node-support {
  background: rgba(15, 23, 42, 0.9);
  color: #cbd5e1;
}

.node-name {
  font-size: 13px;
  font-weight: 700;
  line-height: 1.35;
}

.node-type {
  font-size: 11px;
  opacity: 0.72;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.stage-empty {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  color: #94a3b8;
  z-index: 1;
}

.graph-side {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.side-card {
  padding: 16px;
}

.side-title {
  margin-bottom: 12px;
  color: #e2e8f0;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.04em;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.metric-card {
  padding: 12px;
  border-radius: 12px;
  background: rgba(15, 23, 42, 0.78);
  border: 1px solid rgba(148, 163, 184, 0.12);
}

.metric-card span {
  display: block;
  color: #94a3b8;
  font-size: 11px;
  margin-bottom: 6px;
}

.metric-card strong {
  color: #f8fafc;
  font-size: 20px;
}

.selected-node-head {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: center;
}

.selected-node-head strong {
  color: #f8fafc;
}

.selected-node-head span,
.muted-copy {
  color: #94a3b8;
  font-size: 12px;
}

.selected-node-detail {
  margin: 10px 0 0;
  color: #cbd5e1;
  font-size: 13px;
  line-height: 1.6;
}

.path-card {
  width: 100%;
  text-align: left;
  padding: 12px;
  border-radius: 14px;
  border: 1px solid rgba(148, 163, 184, 0.12);
  background: rgba(15, 23, 42, 0.72);
  color: #e2e8f0;
  margin-bottom: 10px;
  cursor: pointer;
}

.path-card.is-active {
  border-color: rgba(45, 212, 191, 0.38);
  background: rgba(13, 44, 54, 0.88);
}

.path-step {
  display: inline-block;
  margin-bottom: 6px;
  font-size: 11px;
  color: #5eead4;
}

.path-card strong {
  display: block;
  margin-bottom: 6px;
}

.path-card p {
  margin: 0;
  color: #94a3b8;
  font-size: 12px;
  line-height: 1.55;
}

.signal-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.signal-band {
  padding: 12px;
  border-radius: 12px;
  border: 1px solid rgba(148, 163, 184, 0.12);
  background: rgba(15, 23, 42, 0.7);
}

.signal-band-head {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  color: #f8fafc;
  margin-bottom: 6px;
}

.signal-band p {
  margin: 0;
  color: #cbd5e1;
  font-size: 12px;
  line-height: 1.55;
}

.signal-pill-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.signal-pill {
  padding: 6px 10px;
  border-radius: 999px;
  border: 1px solid rgba(148, 163, 184, 0.14);
  font-size: 11px;
}

.signal-band.is-risk,
.signal-pill.is-risk {
  border-color: rgba(248, 113, 113, 0.28);
  background: rgba(69, 10, 10, 0.72);
}

.signal-band.is-success,
.signal-pill.is-success {
  border-color: rgba(52, 211, 153, 0.28);
  background: rgba(6, 78, 59, 0.72);
}

.signal-band.is-default,
.signal-pill.is-default {
  border-color: rgba(148, 163, 184, 0.14);
  background: rgba(30, 41, 59, 0.72);
}

.route-link {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border-radius: 12px;
  border: 1px solid rgba(148, 163, 184, 0.12);
  background: rgba(15, 23, 42, 0.7);
  color: #e2e8f0;
  text-decoration: none;
  margin-bottom: 10px;
}

.route-link strong {
  color: #5eead4;
  font-size: 12px;
}

@media (max-width: 1180px) {
  .graph-body {
    grid-template-columns: 1fr;
  }

  .graph-stage {
    min-height: 620px;
  }
}

@media (max-width: 720px) {
  .graph-toolbar,
  .graph-intent {
    flex-direction: column;
    align-items: stretch;
  }

  .intent-meta {
    width: 100%;
  }

  .graph-stage {
    min-height: 540px;
  }

  .graph-node {
    min-width: 102px;
    max-width: 138px;
    padding: 8px 10px;
  }

  .node-name {
    font-size: 12px;
  }
}
</style>
