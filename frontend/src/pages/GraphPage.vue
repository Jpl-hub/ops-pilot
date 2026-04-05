<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

import AppShell from '@/components/AppShell.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingState from '@/components/LoadingState.vue'
import { useAsyncState } from '@/composables/useAsyncState'
import { get, post, type UserRole } from '@/lib/api'
import { useSession } from '@/lib/session'
import { persistWorkflowContext, resolveWorkflowContext } from '@/lib/workflowContext'

type GraphInferenceStep = { step: number; title: string; detail: string; type?: string }
type GraphFocalNode = { id: string; label: string; type: string }
type GraphNode = { id: string; label: string; type: string; meta?: Record<string, unknown> }
type GraphEdge = { source: string; target: string; label: string }

const overviewState = useAsyncState<any>()
const graphState = useAsyncState<any>()
const runsState = useAsyncState<any>()
const companyState = useAsyncState<any>()
const route = useRoute()
const session = useSession()

const selectedCompany = ref('')
const selectedPeriod = ref('')
const graphIntent = ref('碳酸锂价格下跌对下游盈利和风险的影响传导')
const graphIntentDraft = ref(graphIntent.value)
const activePathStep = ref(0)
const selectedNodeId = ref<string | null>(null)
const graphStageRef = ref<HTMLElement | null>(null)
const nodeLayout = ref<Record<string, { x: number; y: number }>>({})
const dragNodeId = ref<string | null>(null)
const bootstrapping = ref(false)
const syncingFromRoute = ref(false)
const actionPending = ref('')
const actionError = ref('')
let graphTicker: number | null = null
let moveHandler: ((event: PointerEvent) => void) | null = null
let upHandler: ((event: PointerEvent) => void) | null = null

const companies = computed(() => overviewState.data.value?.companies || [])
const availablePeriods = computed(() => overviewState.data.value?.available_periods || [])
const activeRole = computed(() => session.activeRole.value || 'investor')
const activeRoleLabel = computed(() => {
  const map: Record<string, string> = {
    investor: '投资者视角',
    management: '管理层视角',
    regulator: '监管风控视角',
  }
  return map[activeRole.value] || '投资者视角'
})
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
const hasCompanies = computed(() => companies.value.length > 0)
const canSubmitIntent = computed(() => !!selectedCompany.value && !!graphIntentDraft.value.trim())
const focalNodes = computed<GraphFocalNode[]>(() => graphState.data.value?.focal_nodes || [])
const inferencePath = computed<GraphInferenceStep[]>(() => (graphState.data.value?.inference_path || []).slice(0, 3))
const activePathId = computed(() => inferencePath.value[activePathStep.value]?.step ?? null)
const rawGraphNodes = computed<GraphNode[]>(() => graphState.data.value?.graph?.nodes || [])
const rawGraphEdges = computed<GraphEdge[]>(() => graphState.data.value?.graph?.edges || [])
const evidenceNavigation = computed(() => graphState.data.value?.evidence_navigation?.links || [])
const graphCommandSurface = computed(() => graphState.data.value?.graph_command_surface || null)
const graphLiveFrames = computed(() => graphState.data.value?.graph_live_frames || [])
const currentFrame = computed(() => graphLiveFrames.value[activePathStep.value] || null)
const pathEvidenceLinks = computed(() => evidenceNavigation.value.slice(0, 1))
const graphEvidenceLinks = computed(() => evidenceNavigation.value.slice(0, 4))
const graphRelatedRoutes = computed(() => graphState.data.value?.related_routes || [])
const currentRunId = computed(() => graphState.data.value?.run_id || graphState.data.value?.run_meta?.run_id || '')
const companyWorkspace = computed(() => companyState.data.value || null)
const recentRuns = computed(() => (runsState.data.value?.runs || []).slice(0, 4))
const workflowTasks = computed(() => companyWorkspace.value?.tasks?.items?.slice(0, 3) || [])
const activeGraphFocus = computed(
  () => inferencePath.value[activePathStep.value] || inferencePath.value[0] || null,
)
const watchboardActionLabel = computed(() =>
  companyWorkspace.value?.watchboard?.tracked ? '移出持续跟踪' : '加入持续跟踪',
)
const watchboardSummary = computed(() => {
  if (!selectedCompany.value) return '先选择公司，再把这条链路纳入持续跟踪。'
  if (companyWorkspace.value?.watchboard?.tracked) {
    return `已纳入持续跟踪，当前 ${Number(companyWorkspace.value.watchboard.new_alerts || 0)} 条新增预警，${Number(companyWorkspace.value.watchboard.task_count || 0)} 项相关任务。`
  }
  return '当前还未进入持续跟踪，可把这次图谱链路继续放进监测板。'
})
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
  if (kind === 'company') return { x: 16, y: 46 }
  if (kind === 'period') return { x: 32, y: 22 }
  if (kind === 'watch') return { x: 32, y: 72 }
  if (kind === 'risk') return { x: 50, y: 28 }
  if (kind === 'signal') return { x: 50, y: 66 }
  if (kind === 'evidence') return { x: 68, y: 76 }
  if (kind === 'alert') return { x: 82, y: 28 }
  if (kind === 'task') return { x: 82, y: 50 }
  if (kind === 'stream') return { x: 82, y: 72 }
  return { x: 66, y: 84 }
}

function nodeDetail(node: GraphNode) {
  const meta = node.meta || {}
  if (typeof meta.summary === 'string' && meta.summary) return meta.summary
  if (typeof meta.path === 'string' && meta.path) return meta.path
  if (typeof meta.status === 'string' && meta.status) return `状态：${meta.status}`
  if (typeof meta.priority === 'string' && meta.priority) return `优先级：${meta.priority}`
  if (typeof meta.grade === 'string' && meta.grade) return `评级：${meta.grade}`
  if (typeof meta.report_period === 'string' && meta.report_period) return `报期：${meta.report_period}`
  return `类型：${displayNodeType(node.type)}`
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

function readQueryString(value: unknown) {
  const normalized = Array.isArray(value) ? value[0] : value
  return typeof normalized === 'string' ? normalized.trim() : ''
}

function formatTimestamp(value?: string) {
  if (!value) return '刚刚'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function displayTaskStatus(status?: string) {
  const map: Record<string, string> = {
    queued: '待开工',
    in_progress: '处理中',
    done: '已完成',
    blocked: '已阻断',
  }
  return map[(status || '').toLowerCase()] || '已记录'
}

function parseRoleQuery(value: unknown): UserRole | null {
  const normalized = readQueryString(value)
  if (normalized === 'investor' || normalized === 'management' || normalized === 'regulator') {
    return normalized
  }
  return null
}

function buildGraphTaskTitle() {
  const title = activeGraphFocus.value?.title || selectedNode.value?.label || '图谱链路'
  return `跟进${title}`.slice(0, 60)
}

function buildGraphTaskSummary() {
  const detail = activeGraphFocus.value?.detail || selectedNode.value?.detail || graphIntent.value
  return `继续围绕图谱链路核对：${detail}`.replace(/\s+/g, ' ').slice(0, 220)
}

function buildGraphTaskPriority() {
  const nodeType = selectedNode.value?.type || ''
  const riskLike = ['risk_label', 'alert', 'task'].includes(nodeType)
  return riskLike || /风险|预警|处置/.test(buildGraphTaskSummary()) ? 'P1' : 'P2'
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
      const verticalOffset = spread * 9
      const horizontalOffset = (Math.abs(spread) % 2) * 3
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
      const midX = Number(((source.x + target.x) / 2).toFixed(2))
      return {
        id: `edge-${index}-${edge.source}-${edge.target}`,
        pathData: `M ${source.x} ${source.y} L ${midX} ${source.y} L ${midX} ${target.y} L ${target.x} ${target.y}`,
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
      user_role: activeRole.value,
      intent: graphIntent.value,
    }),
  )
  activePathStep.value = 0
  await Promise.allSettled([loadGraphRuns(), loadCompanyWorkspace()])
}

async function openGraphRun(runId: string) {
  const normalizedRunId = runId.trim()
  if (!normalizedRunId) return
  await graphState.execute(() => get(`/graph-query/runs/${encodeURIComponent(normalizedRunId)}`))
  const payload = graphState.data.value
  if (!payload) return
  const meta = payload.run_meta || {}
  syncingFromRoute.value = true
  try {
    if (typeof meta.company_name === 'string' && meta.company_name.trim()) {
      selectedCompany.value = meta.company_name.trim()
    }
    if (typeof meta.report_period === 'string' && meta.report_period.trim()) {
      selectedPeriod.value = meta.report_period.trim()
    }
  } finally {
    syncingFromRoute.value = false
  }
  graphIntent.value = String(meta.intent || payload.intent || graphIntent.value)
  graphIntentDraft.value = graphIntent.value
  activePathStep.value = 0
  await Promise.allSettled([loadGraphRuns(), loadCompanyWorkspace()])
}

async function loadGraphRuns() {
  if (!selectedCompany.value) {
    runsState.data.value = { runs: [] }
    runsState.error.value = null
    runsState.loading.value = false
    return
  }
  const query = new URLSearchParams({
    company_name: selectedCompany.value,
    user_role: activeRole.value,
    limit: '6',
  })
  if (selectedPeriod.value) {
    query.set('report_period', selectedPeriod.value)
  }
  await runsState.execute(() => get(`/graph-query/runs?${query.toString()}`))
}

async function loadCompanyWorkspace() {
  if (!selectedCompany.value) {
    companyState.data.value = null
    companyState.error.value = null
    companyState.loading.value = false
    return
  }
  const query = new URLSearchParams({
    company_name: selectedCompany.value,
    user_role: activeRole.value,
  })
  if (selectedPeriod.value) {
    query.set('report_period', selectedPeriod.value)
  }
  try {
    await companyState.execute(() => get(`/company/workspace?${query.toString()}`))
  } catch {
    // 错误留给局部状态卡展示。
  }
}

function isActionPending(key: string) {
  return actionPending.value === key
}

async function runWorkflowAction(key: string, action: () => Promise<void>) {
  actionError.value = ''
  actionPending.value = key
  try {
    await action()
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : '执行失败'
  } finally {
    if (actionPending.value === key) {
      actionPending.value = ''
    }
  }
}

async function toggleWatchboardTracking() {
  if (!selectedCompany.value) return
  await runWorkflowAction(`watchboard:${selectedCompany.value}`, async () => {
    const reportPeriod = graphState.data.value?.report_period || selectedPeriod.value || null
    if (companyWorkspace.value?.watchboard?.tracked) {
      await post('/watchboard/remove', {
        company_name: selectedCompany.value,
        user_role: activeRole.value,
        report_period: reportPeriod,
      })
    } else {
      await post('/watchboard/add', {
        company_name: selectedCompany.value,
        user_role: activeRole.value,
        report_period: reportPeriod,
        note: `图谱检索跟进：${graphIntent.value}`.slice(0, 180),
      })
    }
    await loadCompanyWorkspace()
  })
}

async function createGraphTask() {
  if (!selectedCompany.value) return
  const taskKey = `task:${currentRunId.value || selectedCompany.value}:${activeGraphFocus.value?.step || selectedNode.value?.id || 'graph'}`
  await runWorkflowAction(taskKey, async () => {
    await post('/tasks/create', {
      company_name: selectedCompany.value,
      title: buildGraphTaskTitle(),
      summary: buildGraphTaskSummary(),
      priority: buildGraphTaskPriority(),
      user_role: activeRole.value,
      report_period: graphState.data.value?.report_period || selectedPeriod.value || null,
      note: `来自图谱检索：${graphIntent.value}`.slice(0, 180),
      source_run_id: currentRunId.value || null,
    })
    await loadCompanyWorkspace()
  })
}

async function primeGraphFromRoute() {
  const targetRole = parseRoleQuery(route.query.role)
  if (targetRole && session.activeRole.value !== targetRole) {
    session.setActiveRole(targetRole)
    return
  }
  const workflowContext = resolveWorkflowContext(route.query)
  const targetRunId = readQueryString(route.query.run_id)
  syncingFromRoute.value = true
  try {
    const initialCompany =
      workflowContext.company && companies.value.includes(workflowContext.company)
        ? workflowContext.company
        : companies.value[0] || ''
    selectedCompany.value = initialCompany
    const preferredPeriod = overviewState.data.value?.preferred_period
    selectedPeriod.value = workflowContext.period
      ? workflowContext.period
      : typeof preferredPeriod === 'string'
        ? preferredPeriod
        : String(preferredPeriod?.value || preferredPeriod?.period || preferredPeriod?.report_period || preferredPeriod?.label || '')
  } finally {
    syncingFromRoute.value = false
  }

  if (targetRunId) {
    await openGraphRun(targetRunId)
    return
  }
  await loadGraph()
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

onMounted(async () => {
  bootstrapping.value = true
  try {
    await overviewState.execute(() => get('/workspace/companies'))
    await primeGraphFromRoute()
  } finally {
    bootstrapping.value = false
  }

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

watch(selectedCompany, async () => {
  if (bootstrapping.value || syncingFromRoute.value) return
  await loadGraph()
})
watch(selectedPeriod, async () => {
  if (bootstrapping.value || syncingFromRoute.value) return
  await loadGraph()
})
watch(
  () => session.activeRole.value,
  async (value, oldValue) => {
    if (bootstrapping.value || !selectedCompany.value || !value || value === oldValue) return
    await primeGraphFromRoute()
  },
)
watch(
  () => [route.query.company, route.query.period, route.query.run_id, route.query.role],
  async () => {
    if (bootstrapping.value) return
    await primeGraphFromRoute()
  },
)

watch([selectedCompany, selectedPeriod], ([company, period]) => {
  if (!company && !period) return
  persistWorkflowContext({
    company,
    period,
  })
})
</script>

<template>
  <AppShell title="">
    <div class="graph-console">
      <section class="graph-header">
        <div class="graph-heading">
          <h1>图谱检索</h1>
          <p>{{ selectedCompany || '选择公司' }}<span v-if="selectedPeriod"> · {{ selectedPeriod }}</span></p>
          <span class="graph-role-pill">{{ activeRoleLabel }}</span>
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
              <option v-for="period in periodOptions" :key="period.value" :value="period.value">{{ period.label }}</option>
            </select>
          </label>
        </div>
      </section>

      <section class="graph-query-strip">
        <div class="query-strip-main">
          <div>
            <h2>{{ graphIntent }}</h2>
            <p>{{ currentFrame?.detail || graphCommandSurface?.headline || '直接沿这条链继续追下去。' }}</p>
          </div>
        </div>

        <div v-if="selectedCompany" class="query-strip-actions">
          <button
            type="button"
            class="panel-action"
            :disabled="isActionPending(`watchboard:${selectedCompany}`)"
            @click="toggleWatchboardTracking()"
          >
            {{
              isActionPending(`watchboard:${selectedCompany}`)
                ? '处理中...'
                : watchboardActionLabel
            }}
          </button>
          <button
            type="button"
            class="panel-action is-secondary"
            :disabled="isActionPending(`task:${currentRunId || selectedCompany}:${activeGraphFocus?.step || selectedNode?.id || 'graph'}`)"
            @click="createGraphTask()"
          >
            {{
              isActionPending(`task:${currentRunId || selectedCompany}:${activeGraphFocus?.step || selectedNode?.id || 'graph'}`)
                ? '写入中...'
                : '写入任务板'
            }}
          </button>
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
          <svg class="graph-svg" viewBox="0 0 100 100" preserveAspectRatio="none">
            <defs>
              <filter id="graph-link-glow" x="-50%" y="-50%" width="200%" height="200%">
                <feGaussianBlur stdDeviation="0.45" result="blur" />
                <feMerge>
                  <feMergeNode in="blur" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
              <linearGradient id="graph-link-gradient" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stop-color="rgba(96,165,250,0.16)" />
                <stop offset="55%" stop-color="rgba(103,232,249,0.24)" />
                <stop offset="100%" stop-color="rgba(94,234,212,0.18)" />
              </linearGradient>
              <linearGradient id="graph-link-gradient-active" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stop-color="rgba(125,211,252,0.58)" />
                <stop offset="50%" stop-color="rgba(110,231,255,0.84)" />
                <stop offset="100%" stop-color="rgba(167,243,208,0.64)" />
              </linearGradient>
            </defs>
            <g v-for="link in graphCanvasLinks" :key="link!.id">
              <path :d="link!.pathData" class="graph-link-glow" :class="{ 'is-active': link!.isActive }" />
              <path
                :d="link!.pathData"
                class="graph-link"
                :class="{ 'is-active': link!.isActive }"
                :filter="link!.isActive ? 'url(#graph-link-glow)' : undefined"
              />
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
          </button>

          <div v-if="!graphCanvasNodes.length" class="stage-empty">
            <p>输入问题后开始检索。</p>
          </div>
        </section>

        <section class="graph-footer">
          <div class="path-dock">
            <div class="path-dock-head">
              <strong>沿这条主链继续追</strong>
            </div>

            <div class="path-track">
              <button
                v-for="(item, idx) in inferencePath"
                :key="item.step"
                class="path-step"
                :class="{ 'is-active': item.step === activePathId || idx <= activePathStep }"
                @click="activePathStep = idx"
              >
                <strong>{{ item.title }}</strong>
                <p>{{ item.detail }}</p>
              </button>
            </div>
          </div>

          <div class="graph-side-stack">
            <div v-if="selectedNode" class="graph-node-focus">
              <span class="graph-node-kind">{{ displayNodeType(selectedNode.type) }}</span>
              <strong>{{ selectedNode.label }}</strong>
              <p>{{ selectedNode.detail }}</p>
              <div v-if="pathEvidenceLinks.length" class="selected-node-links">
                <RouterLink
                  v-for="item in pathEvidenceLinks"
                  :key="`${item.label}-${item.path}`"
                  :to="{ path: item.path, query: item.query || {} }"
                  class="selected-node-link"
                >
                  {{ item.label }}
                </RouterLink>
              </div>
            </div>

            <article class="graph-side-card">
              <div class="card-head">
                <strong>工作流状态</strong>
                <span class="subtle-copy">{{ companyWorkspace?.watchboard?.tracked ? '已跟踪' : '未跟踪' }}</span>
              </div>
              <p class="panel-copy">{{ watchboardSummary }}</p>
              <div v-if="workflowTasks.length" class="mini-list">
                <RouterLink
                  v-for="task in workflowTasks"
                  :key="task.task_id"
                  :to="task.route || { path: '/workspace', query: { company: selectedCompany, period: selectedPeriod, role: activeRole } }"
                  class="mini-item"
                >
                  <strong>{{ task.title }}</strong>
                  <span>{{ displayTaskStatus(task.status) }} · {{ task.priority || 'P1' }}</span>
                </RouterLink>
              </div>
              <div v-if="graphRelatedRoutes.length" class="selected-node-links">
                <RouterLink
                  v-for="item in graphRelatedRoutes"
                  :key="`${item.path}-${item.label}`"
                  :to="{ path: item.path, query: item.query || {} }"
                  class="selected-node-link"
                >
                  {{ item.label }}
                </RouterLink>
              </div>
              <div v-if="graphEvidenceLinks.length" class="selected-node-links">
                <RouterLink
                  v-for="item in graphEvidenceLinks"
                  :key="`${item.path}-${item.label}`"
                  :to="{ path: item.path, query: item.query || {} }"
                  class="selected-node-link"
                >
                  {{ item.label }}
                </RouterLink>
              </div>
              <p v-if="actionError" class="panel-error">{{ actionError }}</p>
            </article>

            <article v-if="recentRuns.length" class="graph-side-card">
              <div class="card-head">
                <strong>最近图谱检索</strong>
                <span class="subtle-copy">{{ activeRoleLabel }}</span>
              </div>
              <button
                v-for="item in recentRuns"
                :key="item.run_id"
                type="button"
                class="run-item-button"
                :class="{ 'is-active': currentRunId === item.run_id }"
                @click="openGraphRun(item.run_id)"
              >
                <div class="run-item-copy">
                  <strong>{{ item.intent }}</strong>
                  <p>{{ item.report_period || selectedPeriod || '默认主周期' }}</p>
                </div>
                <span>{{ formatTimestamp(item.created_at) }}</span>
              </button>
            </article>
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
  max-width: 1280px;
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

.graph-select span,
.bottom-head span {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}

.graph-heading h1,
.query-strip-main h2,
.graph-node-focus strong {
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
.graph-node-focus p,
.path-step p {
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

.graph-role-pill {
  display: inline-flex;
  align-items: center;
  width: fit-content;
  min-height: 28px;
  padding: 0 12px;
  border-radius: 999px;
  border: 1px solid rgba(96, 165, 250, 0.18);
  background: rgba(37, 99, 235, 0.12);
  color: #dbeafe;
  font-size: 12px;
}

.graph-select {
  display: grid;
  gap: 8px;
}

.graph-select span,
.bottom-head span {
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
.graph-footer,
.path-dock,
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
  gap: 12px;
  min-width: 0;
}

.query-strip-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.query-strip-main h2 {
  font-size: clamp(16px, 1.6vw, 18px);
  line-height: 1.12;
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
  min-height: 520px;
  overflow: hidden;
  background:
    radial-gradient(circle at 20% 16%, rgba(52, 211, 153, 0.06), transparent 24%),
    radial-gradient(circle at 82% 18%, rgba(96, 165, 250, 0.06), transparent 26%),
    linear-gradient(180deg, rgba(7, 9, 13, 0.98), rgba(5, 7, 10, 0.98));
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

.graph-side-stack {
  display: grid;
  gap: 12px;
  align-content: start;
}

.graph-side-card {
  display: grid;
  gap: 12px;
  padding: 12px 14px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.025);
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.card-head strong,
.mini-item strong,
.run-item-copy strong {
  color: #f8fafc;
}

.panel-copy,
.subtle-copy,
.mini-item span,
.run-item-copy p,
.run-item-button span,
.panel-error {
  margin: 0;
  color: rgba(148, 163, 184, 0.9);
  line-height: 1.6;
}

.panel-action {
  min-height: 36px;
  padding: 0 12px;
  border-radius: 999px;
  border: 1px solid rgba(52, 211, 153, 0.24);
  background: rgba(18, 62, 45, 0.78);
  color: #ecfdf5;
  cursor: pointer;
  font: inherit;
}

.panel-action.is-secondary {
  border-color: rgba(148, 163, 184, 0.18);
  background: rgba(15, 23, 42, 0.72);
  color: #dbe7f3;
}

.panel-action:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.mini-list {
  display: grid;
  gap: 10px;
}

.mini-item {
  display: grid;
  gap: 4px;
  text-decoration: none;
  color: inherit;
  padding-top: 10px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.mini-item:first-child {
  padding-top: 0;
  border-top: none;
}

.run-item-button {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  width: 100%;
  padding: 12px 14px;
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.03);
  text-align: left;
  color: inherit;
  cursor: pointer;
}

.run-item-button.is-active {
  border-color: rgba(16, 185, 129, 0.28);
  background: rgba(16, 185, 129, 0.08);
}

.run-item-copy {
  display: grid;
  gap: 4px;
}

.graph-svg {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}

.graph-link-glow,
.graph-link {
  fill: none;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.graph-link-glow {
  stroke: rgba(125, 211, 252, 0);
  stroke-width: 0.22;
  opacity: 0;
  transition: opacity 0.2s ease, stroke 0.2s ease;
}

.graph-link-glow.is-active {
  stroke: rgba(110, 231, 255, 0.06);
  opacity: 0.28;
}

.graph-link {
  stroke: url(#graph-link-gradient);
  stroke-width: 0.07;
  opacity: 0.22;
  transition: opacity 0.2s ease, stroke 0.2s ease, stroke-width 0.2s ease;
}

.graph-link.is-active {
  stroke: url(#graph-link-gradient-active);
  stroke-width: 0.12;
  opacity: 0.72;
}

.graph-node {
  position: absolute;
  transform: translate(-50%, -50%);
  min-width: 82px;
  max-width: 116px;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 3px;
  padding: 7px 8px 7px 9px;
  border-radius: 10px;
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
  font-size: 11px;
  font-weight: 700;
  line-height: 1.3;
  color: #f8fafc;
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

.graph-footer {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(260px, 0.85fr);
  gap: 12px;
  padding: 12px;
}

.graph-node-focus {
  display: grid;
  gap: 8px;
  align-content: start;
  padding: 12px 14px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.025);
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.graph-node-focus strong {
  font-size: 18px;
  line-height: 1.05;
}

.graph-node-kind {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: rgba(132, 244, 202, 0.82);
}

.path-dock-head {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 12px;
  margin-bottom: 12px;
}

.path-dock-head strong {
  color: #f8fafc;
  font-size: 14px;
  letter-spacing: -0.02em;
}

.path-track {
  display: flex;
  gap: 10px;
  overflow-x: auto;
  padding-bottom: 4px;
}

.path-step {
  min-width: 148px;
  padding: 10px 11px;
  border-radius: 16px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.02);
  text-align: left;
  cursor: pointer;
  display: grid;
  gap: 6px;
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
  .graph-footer {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 860px) {
  .graph-header,
  .graph-controls,
  .graph-query-strip,
  .query-strip-main,
  .graph-intent-dock,
  .query-strip-actions {
    flex-direction: column;
    grid-template-columns: 1fr;
    align-items: stretch;
  }

  .graph-stage {
    min-height: 500px;
  }

  .graph-node {
    min-width: 104px;
    max-width: 138px;
    padding: 8px 10px;
  }
}
</style>
