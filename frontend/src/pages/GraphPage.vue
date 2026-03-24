<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import AppShell from '@/components/AppShell.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingState from '@/components/LoadingState.vue'
import { useAsyncState } from '@/composables/useAsyncState'
import { get, post } from '@/lib/api'

type GraphInferenceStep = { step: number; title: string; detail: string }
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
let graphTicker: number | null = null

const companies = computed(() => overviewState.data.value?.companies || [])
const availablePeriods = computed(() => overviewState.data.value?.available_periods || [])
const hasCompanies = computed(() => companies.value.length > 0)
const canSubmitIntent = computed(() => !!selectedCompany.value && !!graphIntentDraft.value.trim())
const focalNodes = computed<GraphFocalNode[]>(() => graphState.data.value?.focal_nodes || [])
const inferencePath = computed<GraphInferenceStep[]>(() => graphState.data.value?.inference_path || [])
const activePathId = computed(() => inferencePath.value[activePathStep.value]?.step ?? null)
const rawGraphNodes = computed<GraphNode[]>(() => graphState.data.value?.graph?.nodes || [])
const rawGraphEdges = computed<GraphEdge[]>(() => graphState.data.value?.graph?.edges || [])

function groupRank(type: string) {
  const map: Record<string, number> = {
    company: 0,
    report_period: 1,
    risk_label: 2,
    research_report: 3,
    document_artifact: 4,
    artifact_evidence: 5,
    alert: 6,
    task: 7,
    workspace_run: 8,
    execution_stream: 9,
    watchboard: 10,
  }
  return map[type] ?? 99
}

function nodeKind(type: string) {
  if (type === 'company') return 'source'
  if (type === 'report_period') return 'core'
  if (['risk_label', 'alert'].includes(type)) return 'risk'
  if (['document_artifact', 'artifact_evidence', 'research_report'].includes(type)) return 'impact'
  return 'support'
}

function nodeDetail(node: GraphNode) {
  const meta = node.meta || {}
  if (typeof meta.summary === 'string' && meta.summary) return meta.summary
  if (typeof meta.path === 'string' && meta.path) return meta.path
  if (typeof meta.status === 'string' && meta.status) return `状态：${meta.status}`
  if (typeof meta.priority === 'string' && meta.priority) return `优先级：${meta.priority}`
  if (typeof meta.grade === 'string' && meta.grade) return `评级：${meta.grade}`
  if (typeof meta.query_type === 'string' && meta.query_type) return `分析类型：${meta.query_type}`
  return node.type
}

const graphCanvasNodes = computed(() => {
  const groups = new Map<number, GraphNode[]>()
  rawGraphNodes.value
    .slice()
    .sort((a, b) => groupRank(a.type) - groupRank(b.type) || a.label.localeCompare(b.label, 'zh-CN'))
    .forEach((node) => {
      const rank = groupRank(node.type)
      groups.set(rank, [...(groups.get(rank) || []), node])
    })

  const columns = Array.from(groups.entries()).sort((a, b) => a[0] - b[0])
  const focalIds = new Set(focalNodes.value.map((item) => item.id))
  return columns.flatMap(([_, nodes], columnIndex) => {
    const x = columns.length === 1 ? 50 : 12 + columnIndex * (76 / Math.max(1, columns.length - 1))
    return nodes.map((node, rowIndex) => {
      const y = nodes.length === 1 ? 50 : 18 + rowIndex * (64 / Math.max(1, nodes.length - 1))
      return {
        id: node.id,
        label: node.label,
        detail: nodeDetail(node),
        kind: nodeKind(node.type),
        x,
        y,
        type: node.type,
        isFocal: focalIds.has(node.id),
      }
    })
  })
})

const graphCanvasLinks = computed(() =>
  rawGraphEdges.value.map((edge: GraphEdge, index: number) => {
    const n1 = graphCanvasNodes.value.find(n => n.id === edge.source)
    const n2 = graphCanvasNodes.value.find(n => n.id === edge.target)
    if (!n1 || !n2) return null
    const x1 = n1.x
    const y1 = n1.y
    const x2 = n2.x
    const y2 = n2.y
    const bend = Math.max(8, Math.abs(x2 - x1) * 0.18)
    const cp1x = x1 + bend
    const cp1y = y1
    const cp2x = x2 - bend
    const cp2y = y2
    return {
      id: `edge-${index}-${edge.source}-${edge.target}`,
      pathData: `M ${x1} ${y1} C ${cp1x} ${cp1y}, ${cp2x} ${cp2y}, ${x2} ${y2}`,
      label: edge.label,
    }
  }).filter(Boolean),
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
  }, 2500)
})

onBeforeUnmount(() => {
  if (graphTicker) { window.clearInterval(graphTicker); graphTicker = null }
})

watch(selectedCompany, async () => { await loadGraph() })
watch(selectedPeriod, async () => { await loadGraph() })

function submitIntent() {
  graphIntent.value = graphIntentDraft.value.trim() || graphIntent.value
  loadGraph()
}
</script>

<template>
  <AppShell title="图谱增强检索">
    <div class="dashboard-wrapper">

      <!-- Control Bar -->
      <section class="glass-panel control-bar">
        <div class="control-left">
          <div class="glow-icon">图</div>
          <div>
            <h3 class="company-name text-gradient">{{ selectedCompany || '选择公司' }}</h3>
          </div>
        </div>
        <div class="inline-context">
          <label class="inline-field">
            <span class="subtle-label">公司</span>
            <select v-model="selectedCompany" class="glass-select">
              <option v-if="!companies.length" value="">暂无公司</option>
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
        </div>
      </section>

      <!-- Intent Search Bar -->
      <section class="glass-panel intent-bar">
        <div class="intent-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="18" height="18"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
        </div>
        <input
          v-model="graphIntentDraft"
          class="intent-input"
          :placeholder="selectedCompany ? '输入检索意图，例如：碳酸锂价格下跌对下游的影响传导' : '当前无可检索企业，请先完成公司池接入'"
          :disabled="graphState.loading.value || !selectedCompany"
          @keydown.enter="submitIntent"
        />
        <div class="intent-stats">
          <span class="stat-item">节点 <strong>{{ (graphState.data.value?.graph?.node_count ?? 0).toLocaleString() }}</strong></span>
          <span class="stat-div">|</span>
          <span class="stat-item">边 <strong>{{ (graphState.data.value?.graph?.edge_count ?? 0).toLocaleString() }}</strong></span>
        </div>
        <button class="button-primary intent-btn" :disabled="graphState.loading.value || !canSubmitIntent" @click="submitIntent">
          {{ graphState.loading.value ? '检索中…' : '图谱检索' }}
        </button>
      </section>

      <LoadingState v-if="overviewState.loading.value || graphState.loading.value" class="state-container" />
      <ErrorState v-else-if="graphState.error.value" :message="String(graphState.error.value)" class="state-container" />
      <section v-else-if="!hasCompanies" class="canvas-panel glass-panel">
        <div class="canvas-empty">
          <p class="muted">当前无可检索企业，请先完成正式公司池和图谱数据接入。</p>
        </div>
      </section>

      <!-- Graph Canvas -->
      <div v-else class="canvas-panel glass-panel">
        <!-- SVG Links -->
        <svg class="canvas-svg">
          <defs>
            <filter id="glow">
              <feGaussianBlur stdDeviation="2.5" result="coloredBlur"/>
              <feMerge><feMergeNode in="coloredBlur"/><feMergeNode in="SourceGraphic"/></feMerge>
            </filter>
          </defs>
          <path v-for="link in graphCanvasLinks" :key="link!.id" :d="link!.pathData" class="svg-link" />
        </svg>

        <!-- Nodes -->
        <div
          v-for="node in graphCanvasNodes"
          :key="node.id"
          class="graph-node"
          :class="[`node-${node.kind}`, { 'is-active': node.isFocal }]"
          :style="{ left: `${node.x}%`, top: `${node.y}%` }"
        >
          <div class="node-dot"></div>
          <span class="node-text">{{ node.label }}</span>
          <div class="node-tooltip">{{ node.detail }}</div>
        </div>

        <!-- Empty State -->
        <div v-if="!graphCanvasNodes.length && !graphState.loading.value" class="canvas-empty">
          <p class="muted">输入检索意图后点击「图谱检索」开始推理</p>
        </div>

        <!-- Inference Ribbon -->
        <div v-if="inferencePath.length" class="inference-ribbon">
          <div class="ribbon-title">推理路径</div>
          <div class="ribbon-list">
            <template v-for="(item, idx) in inferencePath" :key="item.step">
              <div class="path-item" :class="{ 'is-active': item.step === activePathId || idx <= activePathStep }">
                <span class="path-main">{{ item.title }}</span>
                <span class="path-detail muted">{{ item.detail }}</span>
              </div>
              <div v-if="idx < inferencePath.length - 1" class="path-arrow">→</div>
            </template>
          </div>
        </div>
      </div>
    </div>
  </AppShell>
</template>

<style scoped>
.dashboard-wrapper { display: flex; flex-direction: column; gap: 16px; height: 100%; overflow: hidden; }

/* Control Bar */
.control-bar { display: flex; justify-content: space-between; align-items: center; padding: 16px 24px; border-radius: 16px; flex-shrink: 0; }
.control-left { display: flex; align-items: center; gap: 16px; }
.glow-icon { width: 40px; height: 40px; border-radius: 12px; background: rgba(16,185,129,0.15); border: 1px solid rgba(16,185,129,0.4); color: #10b981; display: grid; place-items: center; font-weight: bold; font-size: 18px; box-shadow: 0 0 15px rgba(16,185,129,0.2); }
.company-name { margin: 0; font-size: 20px; font-weight: 600; }
.text-gradient { background-clip: text; -webkit-text-fill-color: transparent; background-image: linear-gradient(to right, #10b981, #60a5fa); }
.inline-context { display: flex; align-items: center; gap: 16px; }
.inline-field { display: flex; align-items: center; gap: 8px; }
.subtle-label { font-size: 12px; color: var(--muted); text-transform: uppercase; }
.glass-select { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); min-height: 36px; padding: 0 12px; border-radius: 8px; color: #fff; }
.glass-input { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); min-height: 36px; padding: 0 12px; border-radius: 8px; color: #fff; width: 100px; outline: none; }

/* Intent Bar */
.intent-bar { display: flex; align-items: center; gap: 16px; padding: 14px 20px; border-radius: 12px; flex-shrink: 0; }
.intent-icon { width: 36px; height: 36px; border-radius: 50%; background: rgba(16,185,129,0.1); border: 1px solid rgba(16,185,129,0.2); display: flex; align-items: center; justify-content: center; color: #10b981; flex-shrink: 0; }
.intent-input { flex: 1; background: transparent; border: none; font-size: 15px; color: #fff; outline: none; font-weight: 500; }
.intent-input::placeholder { color: var(--muted); }
.intent-input:disabled { opacity: 0.5; }
.intent-stats { display: flex; align-items: center; gap: 8px; font-size: 12px; font-family: 'JetBrains Mono', monospace; color: var(--muted); flex-shrink: 0; }
.stat-item strong { color: #fff; }
.stat-div { color: rgba(255,255,255,0.15); }
.intent-btn { min-height: 36px; padding: 0 16px; border-radius: 8px; font-size: 13px; flex-shrink: 0; }

.state-container { flex: 1; }

/* Canvas */
.canvas-panel { flex: 1; min-height: 0; border-radius: 16px; position: relative; overflow: hidden; background: radial-gradient(circle at 50% 50%, rgba(16,185,129,0.03) 0%, transparent 70%); }
.canvas-svg { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
.svg-link { fill: none; stroke: rgba(255,255,255,0.06); stroke-width: 1.5; stroke-dasharray: 4 4; animation: dash 30s linear infinite; }
@keyframes dash { to { stroke-dashoffset: -100; } }

.graph-node { position: absolute; transform: translate(-50%, -50%); display: inline-flex; align-items: center; gap: 8px; padding: 6px 14px; border-radius: 999px; font-size: 13px; font-weight: 500; cursor: pointer; transition: all 0.3s; z-index: 10; }
.graph-node:hover { transform: translate(-50%, -50%) scale(1.06); z-index: 20; }
.node-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.node-text { white-space: nowrap; }

.node-source { background: rgba(30,58,138,0.3); border: 1px solid rgba(59,130,246,0.4); color: #93c5fd; }
.node-source .node-dot { background: #60a5fa; box-shadow: 0 0 8px #60a5fa; }
.node-source.is-active { box-shadow: 0 0 20px rgba(59,130,246,0.4); background: rgba(30,58,138,0.6); }

.node-core { background: rgba(6,78,59,0.3); border: 1px solid rgba(16,185,129,0.4); color: #6ee7b7; }
.node-core .node-dot { background: #10b981; box-shadow: 0 0 8px #10b981; }
.node-core.is-active { box-shadow: 0 0 20px rgba(16,185,129,0.4); background: rgba(6,78,59,0.6); }

.node-impact { background: rgba(88,28,135,0.4); border: 1px solid rgba(168,85,247,0.5); color: #d8b4fe; }
.node-impact .node-dot { background: #a855f7; box-shadow: 0 0 8px #a855f7; }
.node-impact.is-active { box-shadow: 0 0 25px rgba(168,85,247,0.5); background: rgba(88,28,135,0.8); }

.node-support { background: rgba(39,39,42,0.5); border: 1px solid rgba(161,161,170,0.3); color: #d4d4d8; opacity: 0.8; }
.node-support .node-dot { background: #a1a1aa; }

.node-risk { background: rgba(127,29,29,0.3); border: 1px solid rgba(239,68,68,0.3); color: #fca5a5; }
.node-risk .node-dot { background: #ef4444; box-shadow: 0 0 8px #ef4444; }

.node-tooltip { position: absolute; top: -100%; left: 50%; transform: translateX(-50%) translateY(-8px); background: rgba(0,0,0,0.9); border: 1px solid rgba(255,255,255,0.1); padding: 8px 12px; border-radius: 8px; color: #e2e8f0; font-size: 11px; white-space: nowrap; pointer-events: none; opacity: 0; transition: all 0.2s; }
.graph-node:hover .node-tooltip { opacity: 1; transform: translateX(-50%) translateY(-8px) scale(1); }

.canvas-empty { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; }
.muted { color: var(--muted); }

/* Inference Ribbon */
.inference-ribbon { position: absolute; bottom: 20px; left: 20px; right: 20px; background: rgba(8,8,12,0.88); backdrop-filter: blur(16px); border: 1px solid rgba(255,255,255,0.06); border-radius: 10px; padding: 14px 20px; z-index: 20; }
.ribbon-title { font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: #10b981; margin-bottom: 12px; font-weight: 700; }
.ribbon-list { display: flex; align-items: center; gap: 10px; overflow-x: auto; padding-bottom: 2px; }
.ribbon-list::-webkit-scrollbar { height: 3px; }
.ribbon-list::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 2px; }

.path-item { position: relative; padding: 8px 14px; border-radius: 6px; background: rgba(88,28,135,0.1); border: 1px solid rgba(168,85,247,0.15); display: flex; flex-direction: column; gap: 2px; flex-shrink: 0; transition: all 0.3s; }
.path-item.is-active { background: rgba(88,28,135,0.25); border-color: rgba(168,85,247,0.4); box-shadow: 0 0 16px rgba(168,85,247,0.15); }
.path-item.is-active::after { content: ''; position: absolute; bottom: -1px; left: 0; height: 2px; width: 100%; background: #10b981; border-radius: 0 0 6px 6px; }
.path-main { font-size: 13px; color: #e5e7eb; font-weight: 500; white-space: nowrap; }
.path-detail { font-size: 11px; white-space: nowrap; }
.path-arrow { color: rgba(255,255,255,0.2); font-size: 16px; flex-shrink: 0; }
</style>
