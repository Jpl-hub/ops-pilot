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

type QuickMetric = {
  label: string
  value: string | number
  hint?: string
  unit?: string
}

type FocusColumn = {
  label: string
  items: string[]
  empty: string
}

type SignalCard = {
  label: string
  title: string
  detail: string
  route: { path: string; query?: Record<string, string> } | null
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

const companySnapshotMetrics = computed<QuickMetric[]>(() => {
  const summary = companyWorkspace.value?.score_summary
  if (!summary) return []
  return [
    {
      label: '经营总分',
      value: summary.total_score,
      unit: ` / ${summary.grade}`,
      hint: summary.subindustry ? `${summary.subindustry} · ${summary.subindustry_percentile} 分位` : '当前主周期',
    },
    {
      label: '风险标签',
      value: summary.risk_count,
      hint: '需要先处理的问题数',
    },
    {
      label: '机会标签',
      value: summary.opportunity_count,
      hint: '可以继续放大的亮点',
    },
  ]
})

const decisionMetrics = computed(() => {
  if (insightNumbers.value.length) return insightNumbers.value
  return companySnapshotMetrics.value.map((item) => ({
    label: item.label,
    value: item.value,
    unit: item.unit || '',
  }))
})

const focusColumns = computed<FocusColumn[]>(() => [
  {
    label: '当前风险',
    items: (companyWorkspace.value?.top_risks || []).slice(0, 3),
    empty: '当前没有额外高风险标签。',
  },
  {
    label: '可继续放大',
    items: (companyWorkspace.value?.top_opportunities || []).slice(0, 3),
    empty: '当前没有显著机会标签。',
  },
])

const primaryActionCards = computed<any[]>(() => {
  if (latestActionCards.value.length) return latestActionCards.value
  return (companyWorkspace.value?.action_cards || []).slice(0, 3)
})
const liveTasks = computed<any[]>(() => (companyWorkspace.value?.tasks?.items || []).slice(0, 4))
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

const workspaceStatus = computed(() =>
  [
    companyWorkspace.value?.report_period || overview.value?.preferred_period
      ? `报期 ${companyWorkspace.value?.report_period || overview.value?.preferred_period}`
      : '',
    companyWorkspace.value?.watchboard?.tracked ? '已加入持续跟踪' : '',
    companyWorkspace.value?.research?.status === 'ready' ? '可直接核验研报' : '',
  ].filter(Boolean),
)

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

const companySignals = computed<SignalCard[]>(() => {
  const cards: SignalCard[] = []
  const research = companyWorkspace.value?.research
  if (research?.report_title) {
    cards.push({
      label: '当前可核验研报',
      title: research.report_title,
      detail: researchSummary.value,
      route: selectedCompany.value ? { path: '/verify', query: { company: selectedCompany.value } } : null,
    })
  }
  const latestRun = (companyWorkspace.value?.recent_runs?.items || []).slice(0, 1)[0]
  if (latestRun) {
    cards.push({
      label: '最近一次运行',
      title: latestRun.query || latestRun.title || '最近判断',
      detail: `${formatRelativeTime(latestRun.created_at)} · ${latestRun.meta?.headline || latestRun.meta?.query_type || '已写入运行流'}`,
      route: resolveExecutionRoute(latestRun),
    })
  }
  return cards.slice(0, 2)
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
  const role = currentRole.value
  const metaRoute = normalizeRoute(record?.meta?.route)
  if (metaRoute) return metaRoute
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

async function primeScenarioFromRoute() {
  const targetRole = parseRoleQuery(route.query.role)
  if (targetRole && session.activeRole.value !== targetRole) {
    session.setActiveRole(targetRole)
    return
  }

  const workflowContext = resolveWorkflowContext(route.query)
  const prompt = readQueryString(route.query.prompt)
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
      await workspace.addCurrentCompanyToWatchboard(currentRole.value, '来自协同分析持续跟踪')
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
          </div>
        </header>

        <section class="analysis-strip">
          <article
            v-for="stage in analysisStages"
            :key="stage.index"
            class="analysis-step"
            :class="`is-${stage.status}`"
          >
            <em>{{ stage.index }}</em>
            <strong>{{ stage.title }}</strong>
          </article>
        </section>

        <section class="workspace-body">
          <section class="main-surface">
            <header class="surface-head">
              <div class="surface-headline">
                <span class="surface-kicker">{{ latestAnswer ? '当前判断' : '先看当前状态' }}</span>
                <strong>{{ surfaceTitle }}</strong>
                <p class="surface-summary">{{ surfaceSummary }}</p>
              </div>
              <div class="surface-meta">
                <span v-for="item in workspaceStatus" :key="item">{{ item }}</span>
              </div>
            </header>

            <div v-if="loadingTurn" class="surface-loading">
              <strong>正在整理这一轮结果</strong>
              <p>真实服务正在回收数字、证据和下一步建议。</p>
            </div>

            <div v-else-if="companyWorkspaceReady" class="surface-stack">
              <section class="summary-strip">
                <article v-for="item in companySnapshotMetrics" :key="item.label" class="summary-chip">
                  <span>{{ item.label }}</span>
                  <strong>{{ displayMetricValue(item) }}</strong>
                  <p v-if="item.hint">{{ item.hint }}</p>
                </article>
              </section>

              <template v-if="latestAnswer">
                <section v-for="block in answerBlocks" :key="block.title" class="answer-block">
                  <h3>{{ block.title }}</h3>
                  <p v-for="line in block.paragraphs" :key="line" v-html="renderInlineMarkdown(line)"></p>
                  <ul v-if="block.bullets.length" class="focus-list">
                    <li v-for="line in block.bullets" :key="line" v-html="renderInlineMarkdown(line)"></li>
                  </ul>
                </section>

                <section v-if="primaryActionCards.length" class="flow-surface">
                  <div class="section-head">
                    <span>下一步</span>
                    <strong>先把动作说清楚</strong>
                  </div>
                  <div class="inline-grid">
                    <article v-for="item in primaryActionCards" :key="item.title" class="action-card">
                      <em>{{ item.priority || '动作' }}</em>
                      <strong>{{ item.title }}</strong>
                      <p>{{ item.action || item.reason }}</p>
                      <div class="card-actions">
                        <button
                          type="button"
                          class="surface-action"
                          :disabled="isWorkflowPending('task-create', item.title || 'task')"
                          @click="createTaskFromCard(item)"
                        >
                          {{ isWorkflowPending('task-create', item.title || 'task') ? '写入中…' : '写入任务板' }}
                        </button>
                      </div>
                    </article>
                  </div>
                </section>

                <section v-if="latestEvidenceCards.length" class="flow-surface">
                  <div class="section-head">
                    <span>回到原文</span>
                    <strong>先看最关键的证据</strong>
                  </div>
                  <div class="inline-grid">
                    <article v-for="group in latestEvidenceCards" :key="group.title" class="evidence-card">
                      <strong>{{ group.title }}</strong>
                      <p>{{ group.subtitle }}</p>
                      <div class="evidence-links">
                        <RouterLink
                          v-for="item in group.items"
                          :key="`${group.title}-${item.path}-${item.label}`"
                          :to="{ path: item.path, query: item.query || {} }"
                          class="surface-link"
                        >
                          {{ item.label }}
                        </RouterLink>
                      </div>
                    </article>
                  </div>
                </section>
              </template>

              <template v-else>
                <section class="snapshot-surface">
                  <article v-for="column in focusColumns" :key="column.label" class="snapshot-column">
                    <span class="focus-label">{{ column.label }}</span>
                    <ul v-if="column.items.length" class="focus-list">
                      <li v-for="item in column.items" :key="item">{{ item }}</li>
                    </ul>
                    <p v-else class="inline-empty">{{ column.empty }}</p>
                  </article>
                </section>

                <article class="snapshot-note">
                  <span class="focus-label">这一轮可以从这里接着看</span>
                  <p>{{ researchSummary }}</p>
                  <p v-if="latestRunSummary">{{ latestRunSummary }}</p>
                </article>
              </template>

              <section class="flow-surface">
                <div class="section-head">
                  <span>推进执行</span>
                  <strong>把这一轮判断落进任务和持续跟踪</strong>
                </div>

                <div class="workflow-toolbar">
                  <button
                    type="button"
                    class="surface-action"
                    :disabled="!selectedCompany || isWorkflowPending('watchboard', selectedCompany)"
                    @click="toggleWatchboardTracking()"
                  >
                    {{
                      selectedCompany && isWorkflowPending('watchboard', selectedCompany)
                        ? '处理中…'
                        : watchboardActionLabel
                    }}
                  </button>
                  <p class="workflow-summary">{{ watchboardSummary }}</p>
                </div>

                <div v-if="liveTasks.length" class="inline-grid">
                  <article v-for="task in liveTasks" :key="task.task_id" class="task-card">
                    <div class="task-topline">
                      <em>{{ task.priority || task.task_source_label || '任务' }}</em>
                      <span class="task-status" :class="`is-${task.status}`">{{ task.status_label || task.status }}</span>
                    </div>
                    <strong>{{ task.title }}</strong>
                    <p>{{ task.summary }}</p>
                    <p class="task-caption">
                      {{ task.task_source_label || '任务板' }} · {{ formatRelativeTime(task.updated_at || task.created_at) }}
                    </p>
                    <div class="card-actions">
                      <button
                        v-if="task.status === 'queued'"
                        type="button"
                        class="surface-action"
                        :disabled="isWorkflowPending('task-status', `${task.task_id}:in_progress`)"
                        @click="setTaskStatus(task.task_id, 'in_progress')"
                      >
                        {{
                          isWorkflowPending('task-status', `${task.task_id}:in_progress`)
                            ? '处理中…'
                            : '开始推进'
                        }}
                      </button>
                      <button
                        v-if="task.status === 'in_progress'"
                        type="button"
                        class="surface-action"
                        :disabled="isWorkflowPending('task-status', `${task.task_id}:done`)"
                        @click="setTaskStatus(task.task_id, 'done')"
                      >
                        {{ isWorkflowPending('task-status', `${task.task_id}:done`) ? '处理中…' : '标记完成' }}
                      </button>
                      <button
                        v-if="task.status !== 'done' && task.status !== 'blocked'"
                        type="button"
                        class="surface-action is-secondary"
                        :disabled="isWorkflowPending('task-status', `${task.task_id}:blocked`)"
                        @click="setTaskStatus(task.task_id, 'blocked')"
                      >
                        {{
                          isWorkflowPending('task-status', `${task.task_id}:blocked`)
                            ? '处理中…'
                            : '标记阻断'
                        }}
                      </button>
                      <RouterLink :to="task.route" class="surface-link task-link">查看上下文</RouterLink>
                    </div>
                  </article>
                </div>
                <p v-else class="inline-empty">当前还没有入板任务，可先把上面的动作写入任务板。</p>

                <p v-if="workflowActionError" class="composer-error">{{ workflowActionError }}</p>
              </section>
            </div>

            <div v-else class="surface-empty">
              当前公司运行态还没加载完成。
            </div>
          </section>
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
              rows="2"
              @keydown="handleComposerKeydown"
            />
            <button type="button" class="composer-submit" :disabled="!canRunQuery" @click="runQuery()">
              {{ loadingTurn ? '处理中…' : '开始判断' }}
            </button>
          </div>

          <p v-if="turnError" class="composer-error">{{ turnError }}</p>
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

.console-kicker,
.stage-select span,
.surface-kicker,
.section-head span,
.focus-label,
.summary-chip span {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: rgba(120, 143, 172, 0.82);
}

.workspace-empty p,
.answer-block p,
.answer-block li,
.action-card p,
.evidence-card p,
.task-card p,
.surface-empty,
.surface-loading p,
.inline-empty,
.composer-error,
.snapshot-note p,
.workflow-summary,
.task-caption {
  color: rgba(203, 213, 225, 0.84);
  line-height: 1.7;
}

.workspace-stage {
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr) auto;
  min-height: calc(100vh - 88px);
  overflow: hidden;
  background:
    radial-gradient(circle at top right, rgba(16, 185, 129, 0.08), transparent 28%),
    linear-gradient(180deg, rgba(13, 15, 20, 0.98), rgba(10, 12, 17, 0.98));
}

.stage-topbar,
.analysis-strip,
.board-composer {
  padding-left: 20px;
  padding-right: 20px;
}

.stage-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding-top: 20px;
  padding-bottom: 18px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.stage-title {
  display: grid;
  gap: 8px;
}

.surface-head strong,
.section-head strong,
.answer-block h3,
.summary-chip strong,
.action-card strong,
.evidence-card strong,
.surface-loading strong {
  color: #f8fafc;
}

.stage-controls {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.stage-select {
  display: grid;
  gap: 6px;
}

.stage-select select {
  min-width: 220px;
  min-height: 44px;
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

.analysis-strip {
  display: flex;
  gap: 10px;
  overflow-x: auto;
  padding-top: 14px;
  padding-bottom: 14px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.analysis-step {
  min-width: max-content;
  min-height: 40px;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 0 14px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.025);
}

.analysis-step em {
  font-style: normal;
  color: #73f0c7;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
}

.analysis-step strong {
  color: #f8fafc;
  font-size: 13px;
}

.analysis-step.is-completed {
  border-color: rgba(52, 211, 153, 0.18);
  background: rgba(18, 62, 45, 0.34);
}

.analysis-step.is-running {
  border-color: rgba(96, 165, 250, 0.18);
  background: rgba(20, 37, 58, 0.4);
}

.workspace-body {
  min-height: 0;
  padding: 20px;
}

.main-surface {
  min-height: 0;
  display: grid;
  gap: 18px;
  align-content: start;
}

.surface-head {
  display: grid;
  gap: 12px;
}

.surface-headline {
  display: grid;
  gap: 8px;
}

.surface-head strong {
  font-size: clamp(34px, 4vw, 52px);
  line-height: 1.02;
  letter-spacing: -0.05em;
  max-width: 980px;
}

.surface-summary {
  margin: 0;
  max-width: 840px;
  color: rgba(203, 213, 225, 0.82);
  font-size: 17px;
  line-height: 1.65;
}

.surface-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.surface-meta span {
  min-height: 30px;
  padding: 0 10px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  background: rgba(255, 255, 255, 0.04);
  color: rgba(203, 213, 225, 0.84);
  font-size: 12px;
}

.surface-stack {
  min-height: 0;
  display: grid;
  gap: 20px;
  align-content: start;
}

.surface-loading,
.surface-empty {
  display: grid;
  place-items: center;
  align-content: center;
  min-height: 320px;
  padding: 32px;
  text-align: center;
  border-radius: 22px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.025);
}

.surface-loading strong {
  font-size: 22px;
}

.answer-block {
  display: grid;
  gap: 10px;
  padding-bottom: 18px;
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

.summary-strip,
.snapshot-surface,
.inline-grid,
.evidence-links {
  display: grid;
  gap: 14px;
}

.summary-strip {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.snapshot-surface {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.summary-chip,
.snapshot-column,
.snapshot-note,
.action-card,
.evidence-card,
.task-card,
.surface-link {
  border-radius: 18px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.025);
}

.summary-chip,
.snapshot-column,
.snapshot-note,
.action-card,
.evidence-card,
.task-card {
  display: grid;
  gap: 8px;
  padding: 18px;
}

.summary-chip strong {
  font-size: 28px;
  line-height: 1.05;
  letter-spacing: -0.04em;
}

.summary-chip p {
  margin: 0;
  color: rgba(148, 163, 184, 0.86);
  font-size: 12px;
  line-height: 1.55;
}

.action-card strong,
.evidence-card strong,
.task-card strong {
  font-size: 16px;
  line-height: 1.35;
}

.snapshot-column,
.snapshot-note {
  min-height: 200px;
  align-content: start;
}

.section-head {
  display: grid;
  gap: 6px;
}

.section-head strong {
  font-size: 18px;
  line-height: 1.2;
  letter-spacing: -0.03em;
}

.action-card em,
.task-topline em {
  font-style: normal;
  color: #73f0c7;
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  font-family: 'JetBrains Mono', monospace;
}

.task-topline {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.task-status {
  min-height: 26px;
  padding: 0 10px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  font-size: 12px;
  color: #dbe7f3;
  background: rgba(255, 255, 255, 0.05);
}

.task-status.is-queued {
  background: rgba(30, 41, 59, 0.78);
}

.task-status.is-in_progress {
  background: rgba(83, 52, 13, 0.82);
  color: #fef3c7;
}

.task-status.is-done {
  background: rgba(18, 62, 45, 0.88);
  color: #dcfce7;
}

.task-status.is-blocked {
  background: rgba(69, 10, 10, 0.82);
  color: #fecaca;
}

.surface-link {
  min-height: 40px;
  padding: 0 14px;
  color: #dbe7f3;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
}

.surface-link {
  width: fit-content;
}

.card-actions,
.workflow-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}

.workflow-toolbar {
  justify-content: space-between;
}

.workflow-summary {
  margin: 0;
}

.surface-action {
  min-height: 38px;
  padding: 0 14px;
  border-radius: 12px;
  border: 1px solid rgba(52, 211, 153, 0.24);
  background: rgba(18, 62, 45, 0.72);
  color: #ecfdf5;
  cursor: pointer;
  font: inherit;
}

.surface-action.is-secondary {
  border-color: rgba(148, 163, 184, 0.18);
  background: rgba(15, 23, 42, 0.72);
  color: #dbe7f3;
}

.surface-action:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.task-link {
  min-height: 38px;
}

.board-composer {
  display: grid;
  gap: 10px;
  padding-top: 12px;
  padding-bottom: 18px;
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
  grid-template-columns: minmax(0, 1fr) 140px;
  gap: 10px;
  padding: 8px;
  border-radius: 16px;
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
  min-height: 54px;
  padding: 10px 8px 0;
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

.composer-error {
  margin: 0;
}

@media (max-width: 1240px) {
  .summary-strip,
  .snapshot-surface,
  .inline-grid {
    grid-template-columns: 1fr;
  }

  .surface-head strong {
    font-size: clamp(28px, 8vw, 40px);
  }
}

@media (max-width: 900px) {
  .stage-topbar {
    align-items: start;
    flex-direction: column;
  }

  .stage-controls {
    width: 100%;
    justify-content: stretch;
  }

  .stage-select {
    width: 100%;
  }

  .stage-select select {
    width: 100%;
  }

  .composer-shell {
    grid-template-columns: 1fr;
  }

  .composer-submit {
    min-height: 44px;
  }

  .workflow-toolbar {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
