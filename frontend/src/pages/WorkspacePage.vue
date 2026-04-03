<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute } from 'vue-router'

import AppShell from '@/components/AppShell.vue'
import ErrorState from '@/components/ErrorState.vue'
import { useWorkspaceRole } from '@/composables/useWorkspaceRole'
import type { UserRole } from '@/lib/api'
import { useSession } from '@/lib/session'
import { useWorkspaceStore } from '@/stores/workspace'

type AnswerBlock = {
  title: string
  paragraphs: string[]
  bullets: string[]
}

type QuickMetric = {
  label: string
  value: string | number
  hint?: string
}

const route = useRoute()
const session = useSession()
const workspace = useWorkspaceStore()
const {
  companies,
  selectedCompany,
  selectedPeriod,
  query,
  messages,
  latestPayload,
  overview,
  companyWorkspace,
  availablePeriods,
  loadingCompanies,
  loadingOverview,
  loadingCompanyWorkspace,
  loadingTurn,
  companiesError,
  overviewError,
  companyWorkspaceError,
  turnError,
} = storeToRefs(workspace)

const appliedScenarioKey = ref('')
const bootstrapping = ref(false)
const syncingFromRoute = ref(false)
const workflowActionPending = ref('')
const workflowActionError = ref('')

const currentRole = computed<UserRole>(() => session.activeRole.value || 'investor')
const { roleCopy } = useWorkspaceRole(() => currentRole.value)

const starterQueries = computed(
  () =>
    overview.value?.role_profile?.starter_queries ||
    latestPayload.value?.role_profile?.starter_queries ||
    roleCopy.value.fallbackQueries,
)

const roleLabel = computed(() => {
  const map: Record<UserRole, string> = {
    investor: '投资者',
    management: '管理层',
    regulator: '监管风控',
  }
  return map[currentRole.value] ?? '投资者'
})

const latestAnswer = computed(() => {
  const results = messages.value.filter((message) => message.kind === 'result')
  return results.length ? results[results.length - 1].payload : null
})

const latestUserMessage = computed(() => {
  const queries = messages.value.filter((message) => message.kind === 'query')
  return queries.length ? queries[queries.length - 1] : null
})

const workflowSteps = computed<any[]>(() => workspace.agentFlow || [])
const controlPlane = computed<any>(() => workspace.controlPlane || latestAnswer.value?.control_plane || null)
const insightNumbers = computed<any[]>(() => (latestAnswer.value?.insight_cards || []).slice(0, 3))
const latestActionCards = computed<any[]>(() => (latestAnswer.value?.action_cards || []).slice(0, 3))
const latestEvidenceGroups = computed<any[]>(() => (latestAnswer.value?.evidence_groups || []).slice(0, 2))

const answerBlocks = computed<AnswerBlock[]>(() =>
  parseAnswerMarkdown(latestAnswer.value?.answer_markdown || '', latestAnswer.value?.answer_sections || []),
)

const hasCompanies = computed(() => companies.value.length > 0)
const canRunQuery = computed(() => !!selectedCompany.value && !!query.value.trim() && !loadingTurn.value)
const companyWorkspaceReady = computed(
  () => !loadingCompanyWorkspace.value && !!companyWorkspace.value?.company_name,
)

const companySelectPlaceholder = computed(() => {
  if (loadingCompanies.value) return '正在载入公司池'
  if (companiesError.value) return '公司池加载失败'
  if (!companies.value.length) return '当前无公司'
  return '选择公司'
})
const periodOptions = computed(() =>
  (availablePeriods.value || [])
    .map((period) => {
      const value = String(period || '').trim()
      return value ? { value, label: value } : null
    })
    .filter(Boolean) as Array<{ value: string; label: string }>,
)

const overviewPulseCards = computed<QuickMetric[]>(() => {
  const executionSummary = overview.value?.execution_bus_summary
  return [
    {
      label: '重点监测',
      value: overview.value?.watchboard?.summary?.tracked_companies ?? 0,
      hint: '已纳入持续跟踪的主体',
    },
    {
      label: '活跃任务',
      value: executionSummary?.tasks?.active ?? 0,
      hint: '待开工与处理中任务',
    },
    {
      label: '新增预警',
      value: executionSummary?.alerts?.new ?? 0,
      hint: '当前报期待派发事项',
    },
    {
      label: '执行记录',
      value: executionSummary?.history?.total ?? 0,
      hint: '最近沉淀到运行历史',
    },
  ]
})

const companyPulseCards = computed<QuickMetric[]>(() => {
  const summary = companyWorkspace.value?.score_summary
  const tasks = companyWorkspace.value?.tasks?.summary
  if (!summary) return []
  return [
    {
      label: '经营总分',
      value: `${summary.total_score} / ${summary.grade}`,
      hint: summary.subindustry
        ? `${summary.subindustry} · ${summary.subindustry_percentile} 分位`
        : '当前主周期',
    },
    {
      label: '风险标签',
      value: summary.risk_count,
      hint: '需要立刻跟踪的问题数',
    },
    {
      label: '机会标签',
      value: summary.opportunity_count,
      hint: '可继续放大的经营亮点',
    },
    {
      label: '当前任务',
      value: tasks?.total ?? 0,
      hint: tasks?.in_progress ? `${tasks.in_progress} 项处理中` : '等待派发',
    },
  ]
})

const decisionMetrics = computed(() => {
  if (insightNumbers.value.length) return insightNumbers.value
  return companyPulseCards.value.map((item) => ({
    label: item.label,
    value: item.value,
    unit: '',
  }))
})

const companyTopRisks = computed(() => companyWorkspace.value?.top_risks || [])
const companyTopOpportunities = computed(() => companyWorkspace.value?.top_opportunities || [])
const primaryActionCards = computed(
  () =>
    latestActionCards.value.length || !companyWorkspace.value?.action_cards?.length
      ? latestActionCards.value
      : companyWorkspace.value.action_cards.slice(0, 3),
)
const activeTasks = computed<any[]>(() => (companyWorkspace.value?.tasks?.items || []).slice(0, 3))
const activeAlerts = computed<any[]>(() => (companyWorkspace.value?.alerts?.items || []).slice(0, 3))
const runtimeModules = computed<any[]>(
  () =>
    companyWorkspace.value?.intelligence_runtime?.module_pulses?.slice(0, 4) ||
    companyWorkspace.value?.runtime_capsule?.modules?.slice(0, 4) ||
    [],
)
const executionRecords = computed<any[]>(() => (companyWorkspace.value?.execution_stream?.records || []).slice(0, 4))
const recentRuns = computed<any[]>(() => (companyWorkspace.value?.recent_runs?.items || []).slice(0, 3))

const resultLinks = computed(() => {
  const seen = new Set<string>()
  const links: Array<{ label: string; path: string; query?: Record<string, string> }> = []
  for (const step of workflowSteps.value) {
    const stepRoute = normalizeRoute(step?.route)
    if (!stepRoute?.path) continue
    const key = `${stepRoute.path}-${JSON.stringify(stepRoute.query || {})}`
    if (seen.has(key)) continue
    seen.add(key)
    links.push({
      label: step?.route?.label || step?.title || '继续下钻',
      path: stepRoute.path,
      query: stepRoute.query || {},
    })
  }
  return links.slice(0, 2)
})

const workspaceStatus = computed(() =>
  [
    controlPlane.value?.report_period ? `报期 ${controlPlane.value.report_period}` : '',
    companyWorkspace.value?.watchboard?.tracked ? '已纳入监测板' : '',
    companyWorkspace.value?.research?.status === 'ready' ? '研报核验已就绪' : '',
  ].filter(Boolean),
)

const pageLoadError = computed(
  () => companiesError.value || overviewError.value || companyWorkspaceError.value || '',
)

const briefHeadline = computed(() => {
  const summary = companyWorkspace.value?.score_summary
  if (!selectedCompany.value) return '先选择公司，再发起一轮判断'
  if (!summary) return `正在回收 ${selectedCompany.value} 的运行态`
  if ((companyWorkspace.value?.tasks?.summary?.in_progress || 0) > 0) {
    return `${selectedCompany.value} 当前有在途任务，适合直接接着推进`
  }
  if ((companyWorkspace.value?.alerts?.summary?.new || 0) > 0) {
    return `${selectedCompany.value} 当前有新增预警，建议先做一轮判断`
  }
  return `${selectedCompany.value} 当前运行态已就绪，可以围绕具体问题继续判断`
})

const researchSummary = computed(() => {
  const research = companyWorkspace.value?.research
  if (!research) return '研报核验尚未加载'
  if (research.status === 'ready') {
    return `${research.institution || '机构'} · ${research.claim_matches || 0} 条匹配 / ${research.claim_mismatches || 0} 条偏差`
  }
  return research.detail || '当前没有可核验研报'
})

const analysisStages = computed(() => [
  {
    index: '01',
    title: '明确问题',
    status: latestUserMessage.value ? 'completed' : 'pending',
  },
  {
    index: '02',
    title: '拉取数据',
    status: latestAnswer.value || loadingTurn.value ? 'completed' : 'pending',
  },
  {
    index: '03',
    title: '核对原文',
    status: latestEvidenceGroups.value.length ? 'completed' : loadingTurn.value ? 'running' : 'pending',
  },
  {
    index: '04',
    title: '推进动作',
    status:
      primaryActionCards.value.length || activeTasks.value.length
        ? 'completed'
        : loadingTurn.value
          ? 'running'
          : 'pending',
  },
])

function parseAnswerMarkdown(markdown: string, fallbackSections: any[]): AnswerBlock[] {
  const lines = markdown
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)

  if (!lines.length) {
    return fallbackSections.map((section: any) => ({
      title: section.title || '分析结果',
      paragraphs: [],
      bullets: section.lines || [],
    }))
  }

  const blocks: AnswerBlock[] = []
  let current: AnswerBlock = { title: '本轮结论', paragraphs: [], bullets: [] }

  for (const line of lines) {
    if (line.startsWith('### ') || line.startsWith('## ')) {
      if (current.paragraphs.length || current.bullets.length || blocks.length === 0) {
        blocks.push(current)
      }
      current = { title: line.replace(/^#{2,3}\s+/, ''), paragraphs: [], bullets: [] }
      continue
    }
    if (line.startsWith('- ') || line.startsWith('* ') || /^\d+\.\s+/.test(line)) {
      current.bullets.push(line.replace(/^(-|\*|\d+\.)\s+/, ''))
      continue
    }
    current.paragraphs.push(line)
  }

  if (current.title || current.paragraphs.length || current.bullets.length) {
    blocks.push(current)
  }

  return blocks.filter((block) => block.paragraphs.length || block.bullets.length)
}

function displayMetricValue(item: any) {
  return item?.unit ? `${item.value}${item.unit}` : `${item?.value ?? '--'}`
}

function renderInlineMarkdown(value: string) {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/__(.+?)__/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
}

function readQueryString(value: unknown) {
  const normalized = Array.isArray(value) ? value[0] : value
  return typeof normalized === 'string' ? normalized.trim() : ''
}

function parseRoleQuery(value: unknown): UserRole | null {
  const normalized = readQueryString(value)
  if (normalized === 'investor' || normalized === 'management' || normalized === 'regulator') {
    return normalized
  }
  return null
}

function resetWorkspaceConversation() {
  workspace.resetConversation(roleCopy.value.title, roleCopy.value.label)
}

function formatRelativeTime(value?: string | null) {
  if (!value) return '等待更新'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(parsed)
}

function displayStatusLabel(status?: string) {
  const map: Record<string, string> = {
    queued: '待开工',
    in_progress: '处理中',
    done: '已完成',
    blocked: '已阻断',
    new: '待派发',
    dispatched: '已派发',
    resolved: '已处理',
    dismissed: '已忽略',
    tracked: '监测中',
    completed: '已完成',
    ready: '已就绪',
    idle: '未运行',
  }
  return map[(status || '').toLowerCase()] || '已记录'
}

function statusTone(status?: string) {
  const normalized = (status || '').toLowerCase()
  if (['blocked', 'new'].includes(normalized)) return 'risk'
  if (['in_progress', 'dispatched'].includes(normalized)) return 'warning'
  if (['done', 'resolved', 'completed', 'ready', 'tracked'].includes(normalized)) return 'success'
  return 'neutral'
}

function normalizeRoute(routeLike: any) {
  if (!routeLike?.path || String(routeLike.path).startsWith('/api')) return null
  return {
    path: String(routeLike.path),
    query: routeLike.query || {},
  }
}

function resolveExecutionRoute(record: any) {
  const companyName = record?.company_name || selectedCompany.value
  const reportPeriod = companyWorkspace.value?.report_period || overview.value?.preferred_period
  const metaRoute = normalizeRoute(record?.meta?.route)
  if (metaRoute) return metaRoute
  switch (record?.stream_type || record?.history_type || record?.module_key) {
    case 'analysis_run':
    case 'analysis':
      return companyName
        ? { path: '/workspace', query: { company: companyName, period: reportPeriod } }
        : { path: '/workspace', query: {} }
    case 'task':
    case 'alert':
      return record?.meta?.route || (companyName ? { path: '/score', query: { company: companyName, period: reportPeriod } } : null)
    case 'watchboard':
    case 'watchboard_scan':
      return companyName
        ? { path: '/workspace', query: { company: companyName, period: reportPeriod } }
        : { path: '/workspace', query: {} }
    case 'graph_query':
    case 'graph':
      return companyName ? { path: '/graph', query: { company: companyName, period: reportPeriod } } : null
    case 'stress_test':
    case 'stress':
      return companyName ? { path: '/stress', query: { company: companyName, period: reportPeriod } } : null
    case 'vision_analyze':
    case 'vision':
      return companyName ? { path: '/vision', query: { company: companyName, period: reportPeriod } } : null
    case 'document_pipeline':
    case 'document_pipeline_run':
    case 'document_upgrade':
      return { path: '/admin', query: {} }
    default:
      return null
  }
}

function isWorkflowActionPending(key: string) {
  return workflowActionPending.value === key
}

async function runWorkflowAction(key: string, action: () => Promise<void>) {
  workflowActionError.value = ''
  workflowActionPending.value = key
  try {
    await action()
  } catch (error) {
    workflowActionError.value = error instanceof Error ? error.message : '工作流动作执行失败'
  } finally {
    workflowActionPending.value = ''
  }
}

async function refreshWorkspaceSurface() {
  await runWorkflowAction('refresh', async () => {
    await workspace.loadOverview(currentRole.value)
    await workspace.loadCompanyWorkspace(currentRole.value)
  })
}

async function toggleWatchboard() {
  await runWorkflowAction('watchboard-toggle', async () => {
    if (companyWorkspace.value?.watchboard?.tracked) {
      await workspace.removeCurrentCompanyFromWatchboard(currentRole.value)
      return
    }
    await workspace.addCurrentCompanyToWatchboard(currentRole.value)
  })
}

async function scanWatchboard() {
  await runWorkflowAction('watchboard-scan', async () => {
    await workspace.scanWatchboard(currentRole.value)
  })
}

async function dispatchWatchboardAlerts() {
  await runWorkflowAction('watchboard-dispatch', async () => {
    await workspace.dispatchWatchboard(currentRole.value, 6)
  })
}

async function advanceTask(taskId: string, status: 'in_progress' | 'done' | 'blocked') {
  await runWorkflowAction(`task:${taskId}:${status}`, async () => {
    await workspace.updateTaskStatus(taskId, status, currentRole.value)
  })
}

async function updateAlert(alertId: string, status: 'dispatched' | 'resolved' | 'dismissed') {
  await runWorkflowAction(`alert:${alertId}:${status}`, async () => {
    if (status === 'dispatched') {
      await workspace.dispatchAlertToTask(alertId, currentRole.value)
      return
    }
    await workspace.updateAlertStatus(alertId, status, currentRole.value)
  })
}

async function primeScenarioFromRoute() {
  const targetRole = parseRoleQuery(route.query.role)
  if (targetRole && session.activeRole.value !== targetRole) {
    session.setActiveRole(targetRole)
    return
  }

  const prompt = readQueryString(route.query.prompt)
  const targetCompany = readQueryString(route.query.company)
  const targetPeriod = readQueryString(route.query.period)
  let contextChanged = false

  syncingFromRoute.value = true
  try {
    if (targetPeriod && selectedPeriod.value !== targetPeriod) {
      selectedPeriod.value = targetPeriod
      contextChanged = true
    }
    if (targetCompany && companies.value.includes(targetCompany) && selectedCompany.value !== targetCompany) {
      selectedCompany.value = targetCompany
      contextChanged = true
    }
  } finally {
    syncingFromRoute.value = false
  }

  if (contextChanged) {
    resetWorkspaceConversation()
    await workspace.loadOverview(currentRole.value)
    await workspace.loadCompanyWorkspace(currentRole.value)
  }

  if (!prompt) return
  query.value = prompt

  const shouldAutoRun = readQueryString(route.query.auto_run) === '1'
  const scenarioKey = `${route.fullPath}::${selectedCompany.value || ''}::${selectedPeriod.value || ''}`
  if (!shouldAutoRun || !selectedCompany.value || loadingTurn.value || appliedScenarioKey.value === scenarioKey) {
    return
  }
  appliedScenarioKey.value = scenarioKey
  await runQuery(prompt)
}

async function runQuery(inputQuery?: string) {
  if (inputQuery) query.value = inputQuery
  await workspace.sendQuery(currentRole.value, query.value)
}

function pickStarterQuery(question: string) {
  query.value = question
  if (selectedCompany.value) runQuery(question)
}

function handleComposerKeydown(event: KeyboardEvent) {
  if ((event.ctrlKey || event.metaKey) && event.key === 'Enter' && canRunQuery.value) {
    event.preventDefault()
    runQuery()
  }
}

onMounted(async () => {
  bootstrapping.value = true
  const initialRole = parseRoleQuery(route.query.role)
  if (initialRole && session.activeRole.value !== initialRole) session.setActiveRole(initialRole)
  const initialPeriod = readQueryString(route.query.period)
  syncingFromRoute.value = true
  try {
    if (initialPeriod) {
      selectedPeriod.value = initialPeriod
    }
  } finally {
    syncingFromRoute.value = false
  }
  resetWorkspaceConversation()
  try {
    await workspace.bootstrap(currentRole.value)
    await primeScenarioFromRoute()
  } catch {
    // 错误已写入 store。
  } finally {
    bootstrapping.value = false
  }
})

watch(
  () => session.activeRole.value,
  async () => {
    bootstrapping.value = true
    const targetPeriod = readQueryString(route.query.period)
    syncingFromRoute.value = true
    try {
      if (targetPeriod) {
        selectedPeriod.value = targetPeriod
      }
    } finally {
      syncingFromRoute.value = false
    }
    resetWorkspaceConversation()
    try {
      await workspace.bootstrap(currentRole.value)
      await primeScenarioFromRoute()
    } catch {
      // 错误已写入 store。
    } finally {
      bootstrapping.value = false
    }
  },
)

watch(() => route.fullPath, async () => {
  await primeScenarioFromRoute()
})

watch(selectedCompany, async (company, previous) => {
  if (!company || company === previous || loadingCompanies.value || syncingFromRoute.value || bootstrapping.value) return
  resetWorkspaceConversation()
  await workspace.loadCompanyWorkspace(currentRole.value)
})

watch(selectedPeriod, async (period, previous) => {
  if (period === previous || syncingFromRoute.value || bootstrapping.value) return
  resetWorkspaceConversation()
  await workspace.loadOverview(currentRole.value)
  await workspace.loadCompanyWorkspace(currentRole.value)
})
</script>

<template>
  <AppShell title="">
    <div class="workspace-deck">
      <ErrorState v-if="pageLoadError" :message="pageLoadError" class="workspace-state" />
      <section v-else-if="!hasCompanies && !loadingCompanies" class="workspace-state workspace-empty">
        <span class="console-kicker">暂时还不能开始</span>
        <h2>公司池尚未就绪</h2>
        <p>先把正式公司池接入，再开始协同分析。</p>
      </section>

      <section v-else class="workspace-stage glass-panel">
        <header class="stage-topbar">
          <div class="stage-title">
            <span class="console-kicker">协同分析</span>
            <strong>围绕一个问题，直接推进到动作</strong>
          </div>

          <div class="stage-controls">
            <label class="stage-select">
              <span>公司</span>
              <select v-model="selectedCompany" :disabled="loadingCompanies || !companies.length">
                <option value="" disabled>{{ companySelectPlaceholder }}</option>
                <option v-for="company in companies" :key="company" :value="company">{{ company }}</option>
              </select>
            </label>

            <label class="stage-select">
              <span>报期</span>
              <select v-model="selectedPeriod" :disabled="loadingOverview || !periodOptions.length">
                <option v-for="period in periodOptions" :key="period.value" :value="period.value">{{ period.label }}</option>
              </select>
            </label>

            <span class="stage-role-chip">{{ roleLabel }}</span>

            <button
              type="button"
              class="button-secondary compact-button"
              :disabled="loadingOverview || loadingCompanyWorkspace || !!workflowActionPending"
              @click="refreshWorkspaceSurface"
            >
              {{ isWorkflowActionPending('refresh') ? '刷新中...' : '刷新运行态' }}
            </button>

            <button
              type="button"
              class="button-primary compact-button"
              :disabled="loadingCompanyWorkspace || !!workflowActionPending || !selectedCompany"
              @click="toggleWatchboard"
            >
              {{
                isWorkflowActionPending('watchboard-toggle')
                  ? '提交中...'
                  : companyWorkspace?.watchboard?.tracked
                    ? '移出监测板'
                    : '加入监测板'
              }}
            </button>
          </div>
        </header>

        <section class="summary-strip">
          <article v-for="item in overviewPulseCards" :key="item.label" class="summary-tile">
            <span>{{ item.label }}</span>
            <strong>{{ item.value }}</strong>
            <p>{{ item.hint }}</p>
          </article>
        </section>

        <section class="analysis-lane">
          <article
            v-for="stage in analysisStages"
            :key="stage.index"
            class="analysis-stage"
            :class="`is-${stage.status}`"
          >
            <em>{{ stage.index }}</em>
            <strong>{{ stage.title }}</strong>
          </article>
        </section>

        <section class="workspace-body">
          <div class="workspace-main">
            <header class="main-head">
              <div class="main-head-copy">
                <span class="main-kicker">当前工作面</span>
                <strong>{{ latestUserMessage?.text || briefHeadline }}</strong>
                <div class="main-meta">
                  <span>{{ selectedCompany || '未选择公司' }}</span>
                  <span v-for="item in workspaceStatus" :key="item">{{ item }}</span>
                </div>
              </div>
            </header>

            <div v-if="loadingTurn" class="canvas-loading">
              <div class="canvas-loading-card">
                <strong>正在整理这一轮结果</strong>
                <p>真实服务正在回收数字、证据和下一步建议。</p>
                <div class="loading-steps">
                  <div v-for="step in workflowSteps.slice(0, 4)" :key="step.step || step.title" class="loading-step">
                    <span>{{ step.title || step.label || '执行中' }}</span>
                    <strong>{{ displayStatusLabel(step.status) }}</strong>
                  </div>
                </div>
              </div>
            </div>

            <div v-else class="main-scroll">
              <section v-if="latestAnswer" class="main-panel">
                <div class="panel-header">
                  <span>当前判断</span>
                  <strong>{{ latestAnswer.summary || '已生成当前轮次研判' }}</strong>
                </div>

                <div class="answer-stack">
                  <section v-for="block in answerBlocks" :key="block.title" class="answer-block">
                    <h3>{{ block.title }}</h3>
                    <p v-for="line in block.paragraphs" :key="line" v-html="renderInlineMarkdown(line)"></p>
                    <ul v-if="block.bullets.length">
                      <li v-for="line in block.bullets" :key="line" v-html="renderInlineMarkdown(line)"></li>
                    </ul>
                  </section>
                </div>
              </section>

              <section v-else class="main-panel">
                <div class="panel-header">
                  <span>当前公司</span>
                  <strong>{{ briefHeadline }}</strong>
                </div>

                <div v-if="loadingCompanyWorkspace" class="inline-empty">
                  正在加载当前公司的真实运行态。
                </div>

                <template v-else-if="companyWorkspaceReady">
                  <div class="metric-strip">
                    <article v-for="item in companyPulseCards" :key="item.label" class="metric-tile">
                      <span>{{ item.label }}</span>
                      <strong>{{ item.value }}</strong>
                      <p>{{ item.hint }}</p>
                    </article>
                  </div>

                  <div class="focus-grid">
                    <section class="focus-panel">
                      <span class="focus-label">当前风险</span>
                      <ul v-if="companyTopRisks.length" class="focus-list">
                        <li v-for="item in companyTopRisks.slice(0, 4)" :key="item">{{ item }}</li>
                      </ul>
                      <p v-else class="inline-empty">当前没有额外高风险标签。</p>
                    </section>

                    <section class="focus-panel">
                      <span class="focus-label">可继续放大</span>
                      <ul v-if="companyTopOpportunities.length" class="focus-list">
                        <li v-for="item in companyTopOpportunities.slice(0, 4)" :key="item">{{ item }}</li>
                      </ul>
                      <p v-else class="inline-empty">当前没有显著机会标签。</p>
                    </section>
                  </div>

                  <section class="brief-card">
                    <span class="focus-label">研报核验</span>
                    <strong>{{ companyWorkspace?.research?.report_title || '当前没有可核验研报' }}</strong>
                    <p>{{ researchSummary }}</p>
                  </section>
                </template>
              </section>

              <section class="main-panel">
                <div class="panel-header">
                  <span>运行模块</span>
                  <strong>当前公司已经接通的真实执行入口</strong>
                </div>

                <div v-if="runtimeModules.length" class="runtime-grid">
                  <article
                    v-for="module in runtimeModules"
                    :key="module.module_key || module.label"
                    class="runtime-card"
                    :class="`tone-${statusTone(module.status)}`"
                  >
                    <div class="runtime-head">
                      <span>{{ module.label }}</span>
                      <em>{{ displayStatusLabel(module.status) }}</em>
                    </div>
                    <strong>{{ module.headline || module.summary || '等待结果' }}</strong>
                    <p>{{ module.signal || (module.details || []).join(' · ') || '可以直接进入该模块继续处理。' }}</p>
                    <RouterLink
                      v-if="resolveExecutionRoute(module)"
                      :to="resolveExecutionRoute(module)"
                      class="inline-link subtle-link"
                    >
                      进入模块
                    </RouterLink>
                  </article>
                </div>
                <p v-else class="inline-empty">当前还没有该公司的运行模块记录。</p>
              </section>

              <section class="main-panel">
                <div class="panel-header">
                  <span>最近执行</span>
                  <strong>从运行流和分析历史里继续追</strong>
                </div>

                <div v-if="executionRecords.length || recentRuns.length" class="timeline-list">
                  <article
                    v-for="item in executionRecords.length ? executionRecords : recentRuns"
                    :key="item.id || item.run_id"
                    class="timeline-item"
                  >
                    <div class="timeline-head">
                      <strong>{{ item.title || item.query || '运行记录' }}</strong>
                      <span class="status-pill" :class="`tone-${statusTone(item.status)}`">
                        {{ displayStatusLabel(item.status) }}
                      </span>
                    </div>
                    <span>{{ formatRelativeTime(item.created_at) }}</span>
                    <p>{{ item.meta?.reason || item.meta?.scenario || item.meta?.query_type || item.meta?.headline || '已写入执行流。' }}</p>
                    <RouterLink
                      v-if="resolveExecutionRoute(item)"
                      :to="resolveExecutionRoute(item)"
                      class="inline-link subtle-link"
                    >
                      继续查看
                    </RouterLink>
                  </article>
                </div>
                <p v-else class="inline-empty">发起判断后，运行记录会回流到这里。</p>
              </section>
            </div>
          </div>

          <aside class="workspace-aside">
            <section class="aside-section">
              <div class="panel-header">
                <span>这轮最关键</span>
                <strong>{{ latestAnswer ? '先看数字和动作' : '先看当前公司状态' }}</strong>
              </div>

              <div class="metric-grid">
                <article v-for="item in decisionMetrics" :key="item.label" class="metric-row">
                  <span>{{ item.label }}</span>
                  <strong>{{ displayMetricValue(item) }}</strong>
                </article>
              </div>

              <div v-if="primaryActionCards.length" class="action-list">
                <article v-for="item in primaryActionCards" :key="item.title" class="action-row">
                  <em>{{ item.priority || '动作' }}</em>
                  <strong>{{ item.title }}</strong>
                  <p>{{ item.action || item.reason }}</p>
                </article>
              </div>
            </section>

            <section class="aside-section">
              <div class="panel-header">
                <span>重点任务</span>
                <strong>直接推动闭环</strong>
              </div>

              <div v-if="activeTasks.length" class="stack-list">
                <article v-for="task in activeTasks" :key="task.task_id" class="stack-card">
                  <div class="stack-head">
                    <span class="status-pill" :class="`tone-${statusTone(task.status)}`">
                      {{ displayStatusLabel(task.status) }}
                    </span>
                    <small>{{ task.priority }}</small>
                  </div>
                  <strong>{{ task.title }}</strong>
                  <p>{{ task.summary }}</p>
                  <div class="stack-actions">
                    <button
                      type="button"
                      class="button-secondary mini-button"
                      :disabled="!!workflowActionPending"
                      @click="advanceTask(task.task_id, 'in_progress')"
                    >
                      {{ isWorkflowActionPending(`task:${task.task_id}:in_progress`) ? '提交中...' : '开工' }}
                    </button>
                    <button
                      type="button"
                      class="button-secondary mini-button"
                      :disabled="!!workflowActionPending"
                      @click="advanceTask(task.task_id, 'done')"
                    >
                      {{ isWorkflowActionPending(`task:${task.task_id}:done`) ? '提交中...' : '完成' }}
                    </button>
                    <button
                      type="button"
                      class="button-secondary mini-button"
                      :disabled="!!workflowActionPending"
                      @click="advanceTask(task.task_id, 'blocked')"
                    >
                      {{ isWorkflowActionPending(`task:${task.task_id}:blocked`) ? '提交中...' : '阻断' }}
                    </button>
                  </div>
                </article>
              </div>
              <p v-else class="inline-empty">当前没有待推进任务。</p>
            </section>

            <section class="aside-section">
              <div class="panel-header">
                <span>最新预警</span>
                <strong>按状态直接派发或关闭</strong>
              </div>

              <div v-if="activeAlerts.length" class="stack-list">
                <article v-for="alert in activeAlerts" :key="alert.alert_id" class="stack-card">
                  <div class="stack-head">
                    <span class="status-pill" :class="`tone-${statusTone(alert.status)}`">
                      {{ displayStatusLabel(alert.status) }}
                    </span>
                    <small>{{ alert.risk_delta >= 0 ? `+${alert.risk_delta}` : alert.risk_delta }}</small>
                  </div>
                  <strong>{{ alert.summary }}</strong>
                  <p>{{ (alert.new_labels || []).join('、') || `${alert.risk_count} 个风险标签待跟踪` }}</p>
                  <div class="stack-actions">
                    <button
                      type="button"
                      class="button-secondary mini-button"
                      :disabled="!!workflowActionPending || currentRole === 'investor'"
                      @click="updateAlert(alert.alert_id, 'dispatched')"
                    >
                      {{ isWorkflowActionPending(`alert:${alert.alert_id}:dispatched`) ? '提交中...' : '派发任务' }}
                    </button>
                    <button
                      type="button"
                      class="button-secondary mini-button"
                      :disabled="!!workflowActionPending || currentRole === 'investor'"
                      @click="updateAlert(alert.alert_id, 'resolved')"
                    >
                      {{ isWorkflowActionPending(`alert:${alert.alert_id}:resolved`) ? '提交中...' : '已处理' }}
                    </button>
                    <button
                      type="button"
                      class="button-secondary mini-button"
                      :disabled="!!workflowActionPending || currentRole === 'investor'"
                      @click="updateAlert(alert.alert_id, 'dismissed')"
                    >
                      {{ isWorkflowActionPending(`alert:${alert.alert_id}:dismissed`) ? '提交中...' : '忽略' }}
                    </button>
                  </div>
                </article>
              </div>
              <p v-else class="inline-empty">当前没有新增预警。</p>
            </section>

            <section class="aside-section">
              <div class="panel-header">
                <span>监测板</span>
                <strong>{{ companyWorkspace?.watchboard?.tracked ? '已加入持续监测' : '尚未纳入重点监测' }}</strong>
              </div>

              <div class="watchboard-card">
                <div class="watchboard-metrics">
                  <article>
                    <span>新增预警</span>
                    <strong>{{ companyWorkspace?.watchboard?.new_alerts || 0 }}</strong>
                  </article>
                  <article>
                    <span>处理中</span>
                    <strong>{{ companyWorkspace?.watchboard?.in_progress_alerts || 0 }}</strong>
                  </article>
                  <article>
                    <span>任务数</span>
                    <strong>{{ companyWorkspace?.watchboard?.task_count || 0 }}</strong>
                  </article>
                </div>
                <p>{{ companyWorkspace?.watchboard?.note || '把重点公司纳入持续跟踪，后续可批量扫描和派发。' }}</p>
                <div class="stack-actions">
                  <button
                    type="button"
                    class="button-secondary mini-button"
                    :disabled="!!workflowActionPending || !companyWorkspace?.watchboard?.tracked"
                    @click="scanWatchboard"
                  >
                    {{ isWorkflowActionPending('watchboard-scan') ? '扫描中...' : '扫描监测板' }}
                  </button>
                  <button
                    type="button"
                    class="button-secondary mini-button"
                    :disabled="!!workflowActionPending || !companyWorkspace?.watchboard?.tracked"
                    @click="dispatchWatchboardAlerts"
                  >
                    {{ isWorkflowActionPending('watchboard-dispatch') ? '派发中...' : '批量派发' }}
                  </button>
                </div>
              </div>
            </section>

            <section v-if="resultLinks.length" class="aside-section">
              <div class="panel-header">
                <span>继续往下看</span>
                <strong>顺着这一轮结果继续追</strong>
              </div>

              <div class="link-stack">
                <RouterLink
                  v-for="link in resultLinks"
                  :key="`${link.label}-${link.path}`"
                  :to="{ path: link.path, query: link.query || {} }"
                  class="jump-link"
                >
                  <span>{{ link.label }}</span>
                  <strong>进入</strong>
                </RouterLink>
              </div>
            </section>
          </aside>
        </section>

        <footer class="board-composer">
          <div class="composer-prompts">
            <button
              v-for="question in starterQueries.slice(0, 3)"
              :key="question"
              type="button"
              class="prompt-chip"
              @click="pickStarterQuery(question)"
            >
              {{ question }}
            </button>
          </div>

          <div class="composer-shell">
            <textarea
              v-model="query"
              :disabled="loadingCompanies || !hasCompanies"
              :placeholder="selectedCompany ? `输入你要围绕 ${selectedCompany} 继续判断的问题` : '先选择公司，再发起协同研判'"
              rows="1"
              @keydown="handleComposerKeydown"
            ></textarea>

            <button
              type="button"
              class="composer-submit"
              :disabled="!canRunQuery"
              @click="runQuery()"
            >
              {{ loadingTurn ? '研判中...' : '发起研判' }}
            </button>
          </div>

          <div v-if="turnError || workflowActionError" class="composer-error">
            <ErrorState :message="turnError || workflowActionError" />
          </div>
        </footer>
      </section>
    </div>
  </AppShell>
</template>

<style scoped>
.workspace-deck {
  width: 100%;
  max-width: 1320px;
  margin: 0 auto;
  min-height: 100%;
}

.workspace-state,
.workspace-stage {
  border-radius: 24px;
}

.workspace-empty {
  display: grid;
  gap: 10px;
  place-items: center;
  padding: 72px 24px;
  text-align: center;
  background: linear-gradient(180deg, rgba(16, 17, 20, 0.98), rgba(12, 13, 17, 0.98));
}

.workspace-empty h2,
.workspace-empty p {
  margin: 0;
}

.workspace-empty p,
.summary-tile p,
.metric-tile p,
.answer-block p,
.answer-block li,
.runtime-card p,
.stack-card p,
.watchboard-card p,
.timeline-item p,
.canvas-loading-card p,
.inline-empty {
  color: rgba(203, 213, 225, 0.84);
  line-height: 1.7;
}

.console-kicker,
.stage-select span,
.main-kicker,
.panel-header span,
.focus-label,
.summary-tile span,
.metric-tile span,
.runtime-head span,
.stack-head small,
.watchboard-metrics span {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}

.console-kicker,
.stage-select span,
.main-kicker,
.panel-header span,
.focus-label,
.summary-tile span,
.metric-tile span,
.runtime-head span,
.watchboard-metrics span {
  color: rgba(120, 143, 172, 0.82);
}

.workspace-stage {
  display: grid;
  grid-template-rows: auto auto auto minmax(0, 1fr) auto;
  min-height: calc(100vh - 88px);
  overflow: hidden;
  background:
    radial-gradient(circle at top right, rgba(16, 185, 129, 0.08), transparent 28%),
    linear-gradient(180deg, rgba(13, 15, 20, 0.98), rgba(10, 12, 17, 0.98));
}

.stage-topbar,
.summary-strip,
.analysis-lane,
.board-composer {
  padding-left: 18px;
  padding-right: 18px;
}

.stage-topbar {
  display: flex;
  justify-content: space-between;
  gap: 18px;
  align-items: center;
  padding-top: 18px;
  padding-bottom: 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.stage-title {
  display: grid;
  gap: 6px;
}

.stage-title strong,
.main-head-copy strong,
.panel-header strong,
.answer-block h3,
.runtime-card strong,
.stack-card strong,
.timeline-item strong,
.canvas-loading-card strong {
  color: #f8fafc;
}

.stage-title strong {
  font-size: 24px;
  letter-spacing: -0.04em;
}

.stage-controls {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.stage-select {
  display: grid;
  gap: 6px;
}

.stage-select select {
  min-width: 188px;
  min-height: 42px;
  padding: 0 14px;
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.03);
  color: #eef2f7;
}

.stage-role-chip {
  min-height: 34px;
  padding: 0 12px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  background: rgba(18, 62, 45, 0.88);
  border: 1px solid rgba(52, 211, 153, 0.18);
  color: #d9fff0;
  font-size: 13px;
}

.compact-button {
  min-height: 38px;
}

.summary-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  padding-top: 14px;
  padding-bottom: 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.summary-tile,
.metric-tile,
.runtime-card,
.stack-card,
.watchboard-card,
.main-panel,
.analysis-stage {
  border-radius: 18px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.025);
}

.summary-tile {
  display: grid;
  gap: 8px;
  min-height: 116px;
  padding: 14px 16px;
}

.summary-tile strong,
.metric-tile strong,
.metric-row strong,
.watchboard-metrics strong {
  font-size: 26px;
  line-height: 1;
  letter-spacing: -0.04em;
  color: #f8fafc;
}

.analysis-lane {
  display: flex;
  gap: 10px;
  overflow-x: auto;
  padding-top: 12px;
  padding-bottom: 14px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.analysis-stage {
  min-width: max-content;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 0 14px;
  min-height: 42px;
}

.analysis-stage em {
  font-style: normal;
  color: #73f0c7;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
}

.analysis-stage strong {
  font-size: 13px;
}

.analysis-stage.is-completed {
  border-color: rgba(52, 211, 153, 0.18);
  background: rgba(18, 62, 45, 0.4);
}

.analysis-stage.is-running {
  border-color: rgba(96, 165, 250, 0.18);
  background: rgba(20, 37, 58, 0.48);
}

.workspace-body {
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 420px;
}

.workspace-main {
  min-height: 0;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  border-right: 1px solid rgba(255, 255, 255, 0.06);
}

.main-head {
  padding: 18px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.main-head-copy {
  display: grid;
  gap: 8px;
}

.main-head-copy strong {
  font-size: clamp(22px, 2.6vw, 30px);
  line-height: 1.08;
  letter-spacing: -0.04em;
}

.main-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.main-meta span,
.status-pill {
  min-height: 30px;
  padding: 0 10px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  background: rgba(255, 255, 255, 0.04);
  color: rgba(203, 213, 225, 0.84);
  font-size: 12px;
}

.status-pill.tone-risk {
  background: rgba(239, 68, 68, 0.12);
  color: #fecaca;
}

.status-pill.tone-warning {
  background: rgba(245, 158, 11, 0.12);
  color: #fcd34d;
}

.status-pill.tone-success {
  background: rgba(52, 211, 153, 0.14);
  color: #bbf7d0;
}

.main-scroll,
.workspace-aside {
  min-height: 0;
  overflow-y: auto;
}

.main-scroll {
  display: grid;
  gap: 14px;
  padding: 18px;
}

.main-panel,
.aside-section {
  display: grid;
  gap: 14px;
  padding: 16px;
}

.panel-header {
  display: grid;
  gap: 6px;
}

.panel-header strong {
  font-size: 18px;
  line-height: 1.2;
  letter-spacing: -0.03em;
}

.answer-stack {
  display: grid;
  gap: 14px;
}

.answer-block {
  display: grid;
  gap: 8px;
  padding-bottom: 14px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.answer-block:last-child {
  padding-bottom: 0;
  border-bottom: none;
}

.answer-block h3 {
  margin: 0;
  font-size: 16px;
  letter-spacing: -0.02em;
}

.answer-block ul,
.focus-list {
  margin: 0;
  padding-left: 18px;
  display: grid;
  gap: 6px;
}

.metric-strip,
.focus-grid,
.runtime-grid,
.metric-grid {
  display: grid;
  gap: 10px;
}

.metric-strip,
.metric-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.focus-grid,
.runtime-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.metric-tile {
  display: grid;
  gap: 8px;
  padding: 14px 16px;
}

.focus-panel,
.brief-card {
  display: grid;
  gap: 8px;
  padding: 14px 16px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid rgba(255, 255, 255, 0.05);
}

.brief-card strong {
  color: #f8fafc;
  font-size: 16px;
}

.runtime-card {
  display: grid;
  gap: 10px;
  padding: 14px 16px;
}

.runtime-head,
.stack-head,
.timeline-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.runtime-head em,
.stack-head small {
  font-style: normal;
  color: rgba(148, 163, 184, 0.78);
  font-size: 12px;
}

.runtime-card strong {
  font-size: 15px;
  line-height: 1.35;
}

.runtime-card.tone-risk {
  border-color: rgba(239, 68, 68, 0.16);
  background: rgba(239, 68, 68, 0.05);
}

.runtime-card.tone-warning {
  border-color: rgba(245, 158, 11, 0.18);
  background: rgba(245, 158, 11, 0.05);
}

.runtime-card.tone-success {
  border-color: rgba(52, 211, 153, 0.18);
  background: rgba(18, 62, 45, 0.24);
}

.timeline-list,
.stack-list,
.action-list,
.link-stack {
  display: grid;
  gap: 10px;
}

.timeline-item,
.stack-card,
.action-row {
  display: grid;
  gap: 8px;
}

.timeline-item,
.stack-card {
  padding: 14px 16px;
}

.timeline-head strong,
.stack-card strong,
.action-row strong {
  font-size: 15px;
  line-height: 1.35;
}

.timeline-item span {
  color: rgba(148, 163, 184, 0.82);
  font-size: 12px;
}

.workspace-aside {
  padding: 18px 18px 18px 16px;
  display: grid;
  align-content: start;
  gap: 14px;
}

.metric-row {
  display: grid;
  gap: 6px;
  padding: 12px 14px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.025);
  border: 1px solid rgba(255, 255, 255, 0.05);
}

.metric-row span {
  color: rgba(148, 163, 184, 0.82);
  font-size: 12px;
}

.action-row {
  padding: 14px 16px;
  border-radius: 16px;
  border: 1px solid rgba(255, 255, 255, 0.05);
  background: rgba(255, 255, 255, 0.025);
}

.action-row em {
  font-style: normal;
  color: #73f0c7;
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  font-family: 'JetBrains Mono', monospace;
}

.stack-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.mini-button {
  min-height: 34px;
  padding: 0 12px;
  font-size: 12px;
}

.watchboard-card {
  display: grid;
  gap: 12px;
  padding: 14px 16px;
}

.watchboard-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.watchboard-metrics article {
  display: grid;
  gap: 6px;
  padding: 12px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid rgba(255, 255, 255, 0.05);
}

.jump-link,
.subtle-link {
  min-height: 40px;
  padding: 0 14px;
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.03);
  color: #dbe7f3;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.subtle-link {
  width: fit-content;
}

.jump-link strong {
  font-size: 12px;
  color: #73f0c7;
}

.canvas-loading {
  min-height: 0;
  display: grid;
  place-items: center;
  padding: 24px;
}

.canvas-loading-card {
  width: min(420px, 100%);
  display: grid;
  gap: 12px;
  padding: 22px;
  text-align: center;
  border-radius: 18px;
  border: 1px solid rgba(52, 211, 153, 0.16);
  background: rgba(18, 62, 45, 0.18);
}

.canvas-loading-card strong {
  font-size: 20px;
}

.loading-steps {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 10px;
}

.loading-step {
  min-height: 34px;
  padding: 0 12px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  background: rgba(255, 255, 255, 0.04);
}

.loading-step span {
  color: rgba(148, 163, 184, 0.78);
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
}

.loading-step strong {
  color: #73f0c7;
  font-size: 12px;
}

.inline-empty {
  margin: 0;
}

.board-composer {
  display: grid;
  gap: 10px;
  padding-top: 12px;
  padding-bottom: 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.composer-prompts {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.prompt-chip {
  min-height: 32px;
  padding: 0 12px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.025);
  color: #dbe7f3;
  cursor: pointer;
  font-size: 12px;
}

.composer-shell {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 120px;
  gap: 10px;
  padding: 6px;
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(8, 10, 14, 0.96);
}

.composer-shell textarea {
  width: 100%;
  resize: none;
  border: none;
  background: transparent;
  color: #eef2f7;
  font: inherit;
  line-height: 1.55;
  min-height: 30px;
  padding: 8px 6px 0;
  outline: none;
}

.composer-submit {
  min-height: 100%;
  border-radius: 12px;
  border: 1px solid rgba(52, 211, 153, 0.28);
  background: rgba(18, 62, 45, 0.92);
  color: #f0fdf4;
  font-weight: 700;
  cursor: pointer;
}

.composer-submit:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

@media (max-width: 1240px) {
  .workspace-body,
  .workspace-main,
  .summary-strip,
  .focus-grid,
  .runtime-grid {
    grid-template-columns: 1fr;
  }

  .workspace-main {
    border-right: none;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  }

  .workspace-aside {
    padding-left: 18px;
  }
}

@media (max-width: 920px) {
  .stage-topbar,
  .stage-controls,
  .main-head,
  .watchboard-metrics {
    grid-template-columns: 1fr;
  }

  .stage-topbar,
  .stage-controls {
    display: grid;
    align-items: stretch;
  }

  .summary-strip,
  .metric-strip,
  .metric-grid {
    grid-template-columns: 1fr 1fr;
  }

  .composer-shell {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .summary-strip,
  .metric-strip,
  .metric-grid,
  .focus-grid,
  .runtime-grid,
  .watchboard-metrics {
    grid-template-columns: 1fr;
  }

  .workspace-stage {
    min-height: 0;
  }
}
</style>
