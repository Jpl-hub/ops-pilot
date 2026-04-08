<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute } from 'vue-router'

import AppShell from '@/components/AppShell.vue'
import ErrorState from '@/components/ErrorState.vue'
import { useWorkspaceRole } from '@/composables/useWorkspaceRole'
import type { UserRole } from '@/lib/api'
import { useSession } from '@/lib/session'
import { persistWorkflowContext, resolveWorkflowContext } from '@/lib/workflowContext'
import { useWorkspaceStore } from '@/stores/workspace'

type AnswerBlock = {
  title: string
  paragraphs: string[]
  bullets: string[]
}

type SignalCard = {
  label: string
  title: string
  detail: string
  route: { path: string; query?: Record<string, string> } | null
}

type SurfaceLink = {
  label: string
  path: string
  query?: Record<string, string>
}

type EvidenceCard = {
  title: string
  subtitle: string
  items: Array<{
    label: string
    path: string
    query?: Record<string, string>
  }>
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
  () => overview.value?.role_profile?.starter_queries || roleCopy.value.fallbackQueries,
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

const workflowSteps = computed<any[]>(() => workspace.agentFlow || [])
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

const currentStateLines = computed(() => {
  const items = [
    ...(companyWorkspace.value?.top_risks || []).slice(0, 2),
    ...(companyWorkspace.value?.top_opportunities || []).slice(0, 1),
  ]
  return items.filter(Boolean)
})

const primaryActionCards = computed<any[]>(() => {
  if (latestActionCards.value.length) return latestActionCards.value
  return (companyWorkspace.value?.action_cards || []).slice(0, 3)
})
const watchboardActionLabel = computed(() =>
  companyWorkspace.value?.watchboard?.tracked ? '移出持续跟踪' : '加入持续跟踪',
)
const watchboardSummary = computed(() => {
  const watchboard = companyWorkspace.value?.watchboard
  if (!selectedCompany.value) return '先选择公司，再决定是否持续跟踪。'
  if (!watchboard?.tracked) return '当前未加入持续跟踪，适合把需要连续盯防的主体放进监测板。'
  return `已加入持续跟踪 · ${watchboard.new_alerts || 0} 条新增预警 / ${watchboard.task_count || 0} 项在板任务`
})

const latestEvidenceCards = computed<EvidenceCard[]>(() =>
  latestEvidenceGroups.value
    .map((group: any) => ({
      title: group.title || '证据',
      subtitle: group.subtitle || '',
      items: (group.items || [])
        .slice(0, 2)
        .map((item: any) => ({
          label: describeEvidenceItem(item),
          path: item?.path || (item?.chunk_id ? `/evidence/${item.chunk_id}` : ''),
          query:
            item?.query ||
            (item?.chunk_id
              ? {
                  context: group.title || '证据',
                  anchors: (group.anchor_terms || []).join('|'),
                }
              : undefined),
        }))
        .filter((item: any) => item.path),
    }))
    .filter((group) => group.subtitle || group.items.length),
)

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

const pageLoadError = computed(
  () => companiesError.value || overviewError.value || companyWorkspaceError.value || '',
)

const briefHeadline = computed(() => {
  if (!selectedCompany.value) return '先选择公司，再发起一轮判断'
  if (!companyWorkspace.value?.score_summary) return '正在回收这家公司的真实运行态'
  if ((companyWorkspace.value?.alerts?.summary?.new || 0) > 0) {
    return '当前有新增预警，适合先围绕最急的问题做判断'
  }
  if ((companyWorkspace.value?.tasks?.summary?.in_progress || 0) > 0) {
    return '当前有在途动作，适合继续把这一轮判断推进完'
  }
  return '当前运行态已经就绪，可以直接围绕一个问题开始判断'
})

const surfaceTitle = computed(() => selectedCompany.value || '先选择公司')

const surfaceSummary = computed(() => latestAnswer.value?.summary || briefHeadline.value)

const latestUserQuery = computed(() => {
  const queries = messages.value.filter((message) => message.kind === 'query')
  return queries.length ? queries[queries.length - 1].text : query.value.trim()
})

const latestRunSummary = computed(() => {
  const latestRun = (companyWorkspace.value?.recent_runs?.items || []).slice(0, 1)[0]
  if (!latestRun) return ''
  return `${formatRelativeTime(latestRun.created_at)} · ${latestRun.query || latestRun.title || '最近一次判断'}`
})

const researchSummary = computed(() => {
  const research = companyWorkspace.value?.research
  if (!research) return '当前没有可核验研报。'
  if (research.status === 'ready') {
    return `${research.institution || '机构'} · ${research.claim_matches || 0} 条匹配 / ${research.claim_mismatches || 0} 条分歧`
  }
  return research.detail || '当前没有可核验研报。'
})

const analysisStages = computed(() => [
  {
    index: '01',
    title: '明确问题',
    status: latestAnswer.value || loadingTurn.value ? 'completed' : 'pending',
  },
  {
    index: '02',
    title: '拉取关键数据',
    status: latestAnswer.value || loadingTurn.value ? 'completed' : 'pending',
  },
  {
    index: '03',
    title: '回到原文',
    status: latestEvidenceCards.value.length ? 'completed' : loadingTurn.value ? 'running' : 'pending',
  },
  {
    index: '04',
    title: '落到动作',
    status: primaryActionCards.value.length ? 'completed' : loadingTurn.value ? 'running' : 'pending',
  },
])

const scoreSummary = computed(() => companyWorkspace.value?.score_summary || null)
const riskLines = computed(() => (companyWorkspace.value?.top_risks || []).filter(Boolean).slice(0, 3))
const opportunityLines = computed(() => (companyWorkspace.value?.top_opportunities || []).filter(Boolean).slice(0, 3))
const scoreCards = computed(() => {
  const totalScore = Number(scoreSummary.value?.total_score)
  const grade = String(scoreSummary.value?.grade || '').trim()
  return [
    {
      label: '经营总分',
      value: Number.isFinite(totalScore) ? `${totalScore.toFixed(2)} / ${grade || '--'}` : `-- / ${grade || '--'}`,
    },
    {
      label: '风险标签',
      value: String(scoreSummary.value?.risk_count ?? riskLines.value.length ?? 0),
    },
    {
      label: '机会标签',
      value: String(scoreSummary.value?.opportunity_count ?? opportunityLines.value.length ?? 0),
    },
  ]
})
const actionLead = computed(() => primaryActionCards.value[0] || null)
const evidenceLead = computed(() => latestEvidenceCards.value[0] || null)
const nextRouteLead = computed(() => continuationLinks.value[0] || null)
const latestRunCardTitle = computed(() => (latestRunSummary.value ? '这一轮可以从这里接着看' : '先把这一轮判断跑起来'))
const latestRunCardText = computed(() => latestRunSummary.value || researchSummary.value || '先从右侧问题开始，系统会把这一轮判断接到证据和模块。')

const continuationLinks = computed<SurfaceLink[]>(() => {
  const seen = new Set<string>()
  const links: SurfaceLink[] = []
  const pushLink = (link: SurfaceLink | null | undefined) => {
    if (!link?.path) return
    const key = `${link.path}-${JSON.stringify(link.query || {})}`
    if (seen.has(key)) return
    seen.add(key)
    links.push(link)
  }

  resultLinks.value.forEach((item) => pushLink(item))

  if (selectedCompany.value && companyWorkspace.value?.research?.report_title) {
    pushLink({
      label: '去核验这份研报',
      path: '/verify',
      query: buildCompanyRouteQuery({ report_title: companyWorkspace.value.research.report_title }),
    })
  }

  return links.slice(0, 3)
})

const continuationSummary = computed(
  () => latestRunSummary.value || researchSummary.value || '把这一轮判断接到证据和模块。',
)

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

function normalizeRoute(routeLike: any) {
  if (!routeLike?.path || String(routeLike.path).startsWith('/api')) return null
  return {
    path: String(routeLike.path),
    query: routeLike.query || {},
  }
}

function buildCompanyRouteQuery(extra: Record<string, string | null | undefined> = {}) {
  const query: Record<string, string> = {}
  const company = selectedCompany.value || companyWorkspace.value?.company_name
  const period = companyWorkspace.value?.report_period || selectedPeriod.value || overview.value?.preferred_period
  if (company) {
    query.company = company
  }
  if (period) {
    query.period = period
  }
  Object.entries(extra).forEach(([key, value]) => {
    const normalized = typeof value === 'string' ? value.trim() : ''
    if (normalized) {
      query[key] = normalized
    }
  })
  return query
}

function resolveExecutionRoute(record: any) {
  const companyName = record?.company_name || selectedCompany.value
  const reportPeriod =
    record?.report_period
    || companyWorkspace.value?.report_period
    || selectedPeriod.value
    || overview.value?.preferred_period
  const role = record?.user_role || currentRole.value
  const metaRoute = normalizeRoute(record?.meta?.route)
  if (metaRoute) return metaRoute
  if (record?.run_id && record?.query) {
    return companyName
      ? { path: '/workspace', query: { company: companyName, period: reportPeriod, role, run_id: record.run_id } }
      : { path: '/workspace', query: { role, run_id: record.run_id } }
  }
  if (record?.run_id && record?.intent) {
    return companyName
      ? { path: '/graph', query: { company: companyName, period: reportPeriod, role, run_id: record.run_id } }
      : null
  }
  if (
    record?.run_id
    && (
      record?.stream_type === 'claim_verify'
      || record?.history_type === 'claim_verify'
      || record?.meta?.report_title
      || record?.meta?.source_name
    )
  ) {
    return companyName
      ? {
          path: '/verify',
          query: {
            company: companyName,
            period: reportPeriod,
            role,
            run_id: record.run_id,
            report_title: record?.meta?.report_title || '',
          },
        }
      : null
  }
  if (record?.run_id && record?.scenario) {
    return companyName
      ? { path: '/stress', query: { company: companyName, period: reportPeriod, role, run_id: record.run_id } }
      : null
  }
  if (record?.run_id && (record?.headline || record?.status_label)) {
    return companyName
      ? { path: '/vision', query: { company: companyName, period: reportPeriod, role, run_id: record.run_id } }
      : null
  }
  switch (record?.stream_type || record?.history_type || record?.module_key) {
    case 'analysis_run':
    case 'analysis':
      return companyName
        ? { path: '/workspace', query: { company: companyName, period: reportPeriod, role } }
        : { path: '/workspace', query: { role } }
    case 'graph_query':
    case 'graph':
      return companyName ? { path: '/graph', query: { company: companyName, period: reportPeriod, role } } : null
    case 'stress_test':
    case 'stress':
      return companyName ? { path: '/stress', query: { company: companyName, period: reportPeriod, role } } : null
    case 'vision_analyze':
    case 'vision':
      return companyName ? { path: '/vision', query: { company: companyName, period: reportPeriod, role } } : null
    default:
      return companyName ? { path: '/score', query: { company: companyName, period: reportPeriod } } : null
  }
}

function describeEvidenceItem(item: any) {
  const text =
    item?.anchor_text ||
    item?.snippet ||
    item?.quote ||
    item?.title ||
    item?.text ||
    item?.chunk_id ||
    '打开原文'
  return String(text).replace(/\s+/g, ' ').trim().slice(0, 72)
}

function displayModuleStatus(status?: string) {
  const map: Record<string, string> = {
    ready: '已就绪',
    idle: '待运行',
    running: '运行中',
    blocked: '已阻断',
    completed: '已完成',
  }
  return map[(status || '').toLowerCase()] || status || '待运行'
}

function moduleTone(status?: string) {
  const normalized = (status || '').toLowerCase()
  if (normalized === 'ready' || normalized === 'completed') return 'success'
  if (normalized === 'running') return 'accent'
  if (normalized === 'blocked') return 'risk'
  return 'default'
}

function displayExecutionStatus(status?: string) {
  const map: Record<string, string> = {
    queued: '待处理',
    new: '新增',
    dispatched: '已派发',
    in_progress: '处理中',
    done: '已完成',
    resolved: '已解决',
    dismissed: '已忽略',
    completed: '已完成',
    tracked: '跟踪中',
    blocked: '已阻断',
  }
  return map[(status || '').toLowerCase()] || status || '已记录'
}

function displayExecutionType(streamType?: string) {
  const map: Record<string, string> = {
    alert: '预警',
    task: '任务',
    watchboard: '监测',
    document_upgrade: '文档升级',
    claim_verify: '观点核验',
    stress_test: '压力测试',
    graph_query: '图谱检索',
    vision_analyze: '文档复核',
    analysis_run: '协同分析',
  }
  return map[streamType || ''] || '运行记录'
}

function describeExecutionMeta(record: any) {
  const meta = record?.meta || {}
  const details = [
    meta.priority,
    meta.owner,
    meta.reason,
    meta.note,
    meta.report_title,
    meta.source_name,
    meta.scenario,
    meta.severity,
    meta.intent,
    meta.headline,
    meta.query_type,
    meta.stage,
  ]
    .map((item) => String(item || '').trim())
    .filter(Boolean)
  if (details.length) {
    return details.join(' · ')
  }
  return record?.created_at ? formatRelativeTime(record.created_at) : '继续打开这条运行记录。'
}

async function primeScenarioFromRoute() {
  const targetRole = parseRoleQuery(route.query.role)
  if (targetRole && session.activeRole.value !== targetRole) {
    session.setActiveRole(targetRole)
    return
  }

  const workflowContext = resolveWorkflowContext(route.query)
  const prompt = readQueryString(route.query.prompt)
  const targetRunId = readQueryString(route.query.run_id)
  const targetCompany = workflowContext.company
  const targetPeriod = workflowContext.period
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

  if (targetRunId) {
    const runKey = `run:${targetRunId}`
    if (appliedScenarioKey.value === runKey && latestAnswer.value?.run_id === targetRunId) {
      return
    }
    appliedScenarioKey.value = runKey
    resetWorkspaceConversation()
    await workspace.loadRunDetail(targetRunId, currentRole.value)
    return
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
}

function handleComposerKeydown(event: KeyboardEvent) {
  if ((event.ctrlKey || event.metaKey) && event.key === 'Enter' && canRunQuery.value) {
    event.preventDefault()
    runQuery()
  }
}

function workflowPendingKey(scope: string, value: string) {
  return `${scope}:${value}`
}

function isWorkflowPending(scope: string, value: string) {
  return workflowActionPending.value === workflowPendingKey(scope, value)
}

async function createTaskFromCard(card: any) {
  if (!selectedCompany.value) return
  const actionKey = workflowPendingKey('task-create', `${card?.title || 'task'}`)
  workflowActionPending.value = actionKey
  workflowActionError.value = ''
  try {
    await workspace.createTaskFromAction(card, currentRole.value)
  } catch (error) {
    workflowActionError.value = error instanceof Error ? error.message : '写入任务板失败'
  } finally {
    if (workflowActionPending.value === actionKey) {
      workflowActionPending.value = ''
    }
  }
}

async function setTaskStatus(taskId: string, status: 'queued' | 'in_progress' | 'done' | 'blocked') {
  const actionKey = workflowPendingKey('task-status', `${taskId}:${status}`)
  workflowActionPending.value = actionKey
  workflowActionError.value = ''
  try {
    await workspace.updateTaskStatus(taskId, status, currentRole.value)
  } catch (error) {
    workflowActionError.value = error instanceof Error ? error.message : '更新任务状态失败'
  } finally {
    if (workflowActionPending.value === actionKey) {
      workflowActionPending.value = ''
    }
  }
}

async function toggleWatchboardTracking() {
  if (!selectedCompany.value) return
  const actionKey = workflowPendingKey('watchboard', selectedCompany.value)
  workflowActionPending.value = actionKey
  workflowActionError.value = ''
  try {
    if (companyWorkspace.value?.watchboard?.tracked) {
      await workspace.removeCurrentCompanyFromWatchboard(currentRole.value)
    } else {
      await workspace.addCurrentCompanyToWatchboard(currentRole.value, `${roleLabel.value}持续跟踪`)
    }
  } catch (error) {
    workflowActionError.value = error instanceof Error ? error.message : '更新持续跟踪失败'
  } finally {
    if (workflowActionPending.value === actionKey) {
      workflowActionPending.value = ''
    }
  }
}

onMounted(async () => {
  bootstrapping.value = true
  const initialRole = parseRoleQuery(route.query.role)
  if (initialRole && session.activeRole.value !== initialRole) session.setActiveRole(initialRole)
  const initialWorkflowContext = resolveWorkflowContext(route.query)
  const initialPeriod = initialWorkflowContext.period
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
    const workflowContext = resolveWorkflowContext(route.query)
    const targetPeriod = workflowContext.period
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
    <div class="workspace-console">
      <LoadingState v-if="loadingOverview || loadingCompanies || loadingCompanyWorkspace" class="workspace-empty" />
      <ErrorState
        v-else-if="pageLoadError"
        class="workspace-empty"
        title="协同分析暂时不可用"
        :message="pageLoadError"
      />
      <section v-else class="workspace-shell">
        <header class="workspace-topbar">
          <div class="workspace-topbar-left">
            <span class="workspace-kicker">协同分析</span>
          </div>

          <div class="workspace-topbar-right">
            <label class="control-field">
              <span>公司</span>
              <select v-model="selectedCompany">
                <option :value="''" disabled>{{ companySelectPlaceholder }}</option>
                <option v-for="company in companies" :key="company" :value="company">{{ company }}</option>
              </select>
            </label>

            <label class="control-field" v-if="periodOptions.length">
              <span>报期</span>
              <select v-model="selectedPeriod">
                <option v-for="period in periodOptions" :key="period.value" :value="period.value">{{ period.label }}</option>
              </select>
            </label>

            <span class="role-chip">{{ roleLabel }}</span>
          </div>
        </header>

        <section class="workspace-stage-strip">
          <article v-for="stage in analysisStages" :key="stage.index" class="stage-chip" :class="`is-${stage.status}`">
            <em>{{ stage.index }}</em>
            <strong>{{ stage.title }}</strong>
          </article>
        </section>

        <section class="workspace-frame">
          <div class="workspace-main">
            <section class="surface-header">
              <span class="surface-kicker">先看当前状态</span>
              <h1>{{ surfaceTitle }}</h1>
              <p>{{ surfaceSummary }}</p>
              <div class="surface-pills">
                <span class="surface-pill">报期 {{ companyWorkspace?.report_period || selectedPeriod || '待定' }}</span>
              </div>
            </section>

            <section class="score-strip">
              <article v-for="item in scoreCards" :key="item.label" class="score-card">
                <span>{{ item.label }}</span>
                <strong>{{ item.value }}</strong>
              </article>
            </section>

            <section class="workspace-grid">
              <article class="workspace-panel workspace-panel-wide">
                <span class="panel-kicker">本轮判断</span>
                <div v-if="loadingTurn" class="panel-loading">
                  <strong>正在整理这一轮结果</strong>
                  <p>真实服务正在回收数字、证据和下一步建议。</p>
                </div>
                <div v-else-if="latestAnswer" class="answer-stack">
                  <article v-for="block in answerBlocks.slice(0, 2)" :key="block.title" class="answer-block">
                    <h3>{{ block.title }}</h3>
                    <p v-for="line in block.paragraphs" :key="line" v-html="renderInlineMarkdown(line)"></p>
                    <ul v-if="block.bullets.length" class="answer-list">
                      <li v-for="line in block.bullets" :key="line" v-html="renderInlineMarkdown(line)"></li>
                    </ul>
                  </article>
                </div>
                <div v-else class="answer-stack">
                  <article class="answer-block">
                    <h3>先看这一轮的核心判断</h3>
                    <p>{{ surfaceSummary }}</p>
                  </article>
                </div>
              </article>

              <article class="workspace-panel">
                <span class="panel-kicker">当前风险</span>
                <ul v-if="riskLines.length" class="answer-list">
                  <li v-for="item in riskLines" :key="item">{{ item }}</li>
                </ul>
                <p v-else class="panel-muted">当前没有显著风险标签。</p>
              </article>

              <article class="workspace-panel">
                <span class="panel-kicker">可继续放大</span>
                <ul v-if="opportunityLines.length" class="answer-list">
                  <li v-for="item in opportunityLines" :key="item">{{ item }}</li>
                </ul>
                <p v-else class="panel-muted">当前没有显著机会标签。</p>
              </article>

              <article class="workspace-panel workspace-panel-wide">
                <span class="panel-kicker">这一轮可以从这里接着看</span>
                <strong class="panel-title">{{ latestRunCardTitle }}</strong>
                <p class="panel-summary">{{ latestRunCardText }}</p>
              </article>
            </section>
          </div>

          <aside class="workspace-side">
            <article class="side-card">
              <span class="panel-kicker">直接发问</span>
              <strong class="side-title">先从这三个问题开始</strong>
              <div class="prompt-list">
                <button
                  v-for="question in starterQueries.slice(0, 3)"
                  :key="question"
                  type="button"
                  class="prompt-button"
                  @click="pickStarterQuery(question)"
                >
                  {{ question }}
                </button>
              </div>
            </article>

            <article class="side-card">
              <span class="panel-kicker">持续跟踪</span>
              <strong class="side-title">把这一轮判断接到后续动作</strong>
              <p>{{ watchboardSummary }}</p>
              <button
                type="button"
                class="panel-button"
                :disabled="!selectedCompany || isWorkflowPending('watchboard', selectedCompany)"
                @click="toggleWatchboardTracking()"
              >
                {{
                  selectedCompany && isWorkflowPending('watchboard', selectedCompany)
                    ? '处理中...'
                    : watchboardActionLabel
                }}
              </button>
            </article>

            <article class="side-card" v-if="actionLead || evidenceLead || nextRouteLead">
              <span class="panel-kicker">继续往下看</span>
              <div v-if="actionLead" class="side-detail">
                <strong>{{ actionLead.title }}</strong>
                <p>{{ actionLead.action || actionLead.reason }}</p>
                <button
                  type="button"
                  class="panel-button is-secondary"
                  :disabled="isWorkflowPending('task-create', actionLead.title || 'task')"
                  @click="createTaskFromCard(actionLead)"
                >
                  {{ isWorkflowPending('task-create', actionLead.title || 'task') ? '写入中...' : '写入任务板' }}
                </button>
              </div>
              <RouterLink
                v-else-if="evidenceLead"
                class="footer-link"
                :to="{ path: evidenceLead.items[0]?.path || '/workspace', query: evidenceLead.items[0]?.query || {} }"
              >
                <strong>{{ evidenceLead.title }}</strong>
                <span>{{ evidenceLead.subtitle }}</span>
              </RouterLink>
              <RouterLink
                v-else-if="nextRouteLead"
                class="footer-link"
                :to="{ path: nextRouteLead.path, query: nextRouteLead.query || {} }"
              >
                <strong>{{ nextRouteLead.label }}</strong>
              </RouterLink>
            </article>
          </aside>
        </section>

        <section class="composer-dock">
          <textarea
            v-model="query"
            :disabled="loadingCompanies || !hasCompanies"
            :placeholder="selectedCompany ? `输入你要围绕 ${selectedCompany} 继续判断的问题` : '先选择公司，再发起协同研判'"
            rows="3"
            @keydown="handleComposerKeydown"
          />
          <button type="button" class="composer-button" :disabled="!canRunQuery" @click="runQuery()">
            {{ loadingTurn ? '处理中...' : '开始判断' }}
          </button>
        </section>
        <p v-if="workflowActionError || turnError" class="panel-error composer-error">{{ workflowActionError || turnError }}</p>
      </section>
    </div>
  </AppShell>
</template>

<style scoped>
.workspace-console {
  width: 100%;
  max-width: 1320px;
  min-height: 100%;
  margin: 0 auto;
}

.workspace-empty {
  min-height: 420px;
  display: grid;
  place-items: center;
}

.workspace-shell {
  display: grid;
  gap: 16px;
  min-height: calc(100vh - 64px);
}

.workspace-topbar {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 18px;
  padding-bottom: 14px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.workspace-kicker,
.panel-kicker,
.control-field span,
.stage-chip em {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: rgba(120, 143, 172, 0.82);
}

.workspace-topbar-right {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.control-field {
  display: grid;
  gap: 6px;
}

.control-field select {
  min-width: 220px;
  min-height: 44px;
  padding: 0 14px;
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.03);
  color: #eef2f7;
}

.role-chip {
  min-height: 34px;
  padding: 0 14px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  background: rgba(18, 62, 45, 0.88);
  border: 1px solid rgba(52, 211, 153, 0.18);
  color: #d9fff0;
  font-size: 13px;
}

.workspace-stage-strip {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}

.stage-chip {
  min-height: 48px;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 0 16px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.02);
}

.stage-chip strong,
.surface-header h1,
.score-card strong,
.answer-block h3,
.panel-title,
.side-title,
.footer-link strong {
  margin: 0;
  color: #f8fafc;
}

.stage-chip strong {
  font-size: 14px;
}

.stage-chip.is-completed {
  border-color: rgba(52, 211, 153, 0.22);
}

.stage-chip.is-running {
  border-color: rgba(96, 165, 250, 0.24);
}

.workspace-frame {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(300px, 0.78fr);
  gap: 18px;
}

.workspace-main,
.workspace-side,
.workspace-grid,
.surface-header,
.score-strip,
.side-card,
.answer-block {
  display: grid;
  gap: 14px;
}

.surface-header {
  gap: 8px;
}

.surface-header h1 {
  font-size: clamp(30px, 4vw, 54px);
  line-height: 0.95;
  letter-spacing: -0.05em;
}

.surface-header p,
.panel-summary,
.panel-muted,
.side-card p,
.answer-block p,
.footer-link span {
  margin: 0;
  color: rgba(209, 219, 230, 0.78);
  line-height: 1.65;
}

.surface-pills {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.surface-pill {
  min-height: 34px;
  padding: 0 14px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  background: rgba(255, 255, 255, 0.04);
  color: #dfe7f2;
}

.score-strip {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.score-card,
.workspace-panel,
.side-card,
.composer-dock {
  border-radius: 22px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: linear-gradient(180deg, rgba(15, 16, 20, 0.98), rgba(11, 12, 17, 0.96));
}

.score-card,
.workspace-panel,
.side-card {
  padding: 20px 22px;
}

.score-card {
  gap: 8px;
}

.score-card span {
  color: rgba(168, 179, 194, 0.76);
}

.score-card strong {
  font-size: 22px;
}

.workspace-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.workspace-panel-wide {
  grid-column: 1 / -1;
}

.answer-stack {
  display: grid;
  gap: 16px;
}

.answer-block {
  gap: 10px;
}

.answer-block h3,
.panel-title,
.side-title {
  font-size: 20px;
  line-height: 1.18;
}

.answer-list {
  margin: 0;
  padding-left: 20px;
  display: grid;
  gap: 10px;
  color: #eef2f7;
}

.workspace-side {
  align-content: start;
}

.prompt-list,
.side-detail {
  display: grid;
  gap: 12px;
}

.prompt-button {
  width: 100%;
  min-height: 52px;
  padding: 0 18px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.02);
  color: #eef2f7;
  text-align: left;
}

.panel-button,
.composer-button {
  min-height: 52px;
  border-radius: 18px;
  border: 1px solid rgba(52, 211, 153, 0.22);
  background: rgba(18, 62, 45, 0.88);
  color: #effff6;
}

.panel-button.is-secondary {
  min-height: 42px;
  border-radius: 14px;
}

.footer-link {
  display: grid;
  gap: 4px;
  text-decoration: none;
}

.composer-dock {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 200px;
  gap: 14px;
  padding: 18px;
}

.composer-dock textarea {
  width: 100%;
  min-height: 112px;
  padding: 16px 18px;
  border-radius: 18px;
  border: 0;
  background: rgba(7, 10, 18, 0.94);
  color: #edf2f7;
  resize: vertical;
}

.panel-error {
  color: #fda4af;
}

.panel-loading {
  display: grid;
  gap: 8px;
}

.panel-loading strong {
  color: #f8fafc;
}

@media (max-width: 1240px) {
  .workspace-frame {
    grid-template-columns: 1fr;
  }

  .workspace-side {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 920px) {
  .workspace-topbar {
    flex-direction: column;
    align-items: stretch;
  }

  .workspace-topbar-right,
  .workspace-stage-strip,
  .score-strip,
  .workspace-grid,
  .workspace-side,
  .composer-dock {
    grid-template-columns: 1fr;
    flex-direction: column;
    justify-content: flex-start;
  }

  .workspace-frame {
    grid-template-columns: 1fr;
  }
}
</style>
