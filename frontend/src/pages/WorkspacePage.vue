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

const route = useRoute()
const session = useSession()
const workspace = useWorkspaceStore()
const {
  companies,
  selectedCompany,
  query,
  messages,
  latestPayload,
  overview,
  companyWorkspace,
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
const watchBusy = ref(false)
const scanBusy = ref(false)

const { roleCopy } = useWorkspaceRole(() => session.activeRole.value || 'investor')

const starterQueries = computed(
  () => overview.value?.role_profile?.starter_queries || latestPayload.value?.role_profile?.starter_queries || roleCopy.value.fallbackQueries,
)
const roleFocusTitle = computed(
  () => overview.value?.role_profile?.focus_title || roleCopy.value.title,
)

const roleLabel = computed(() => {
  const map: Record<string, string> = {
    investor: '投资者',
    management: '管理层',
    regulator: '监管风控',
  }
  return map[session.activeRole.value || 'investor'] ?? '投资者'
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
const aiAssurance = computed<any>(() => latestAnswer.value?.ai_assurance || null)
const insightNumbers = computed<any[]>(() => (latestAnswer.value?.insight_cards || []).slice(0, 4))
const latestActionCards = computed<any[]>(() => (latestAnswer.value?.action_cards || []).slice(0, 3))
const latestEvidenceGroups = computed<any[]>(() => (latestAnswer.value?.evidence_groups || []).slice(0, 3))

const companySummary = computed(() => companyWorkspace.value?.score_summary ?? null)
const companyTopRisks = computed(() => companyWorkspace.value?.top_risks ?? [])
const companyActions = computed(() => (companyWorkspace.value?.action_cards ?? []).slice(0, 3))
const companyWatch = computed(() => companyWorkspace.value?.watchboard ?? { tracked: false })
const companyResearch = computed(() => companyWorkspace.value?.research ?? null)
const timelineSnapshot = computed(() => companyWorkspace.value?.timeline?.snapshots?.[0] ?? null)

const answerBlocks = computed<AnswerBlock[]>(() =>
  parseAnswerMarkdown(latestAnswer.value?.answer_markdown || '', latestAnswer.value?.answer_sections || []),
)

const resultLinks = computed(() => {
  const seen = new Set<string>()
  const links: Array<{ label: string; path: string; query?: Record<string, string> }> = []
  for (const step of workflowSteps.value) {
    const route = step?.route
    if (!route?.path) continue
    const key = `${route.path}-${JSON.stringify(route.query || {})}`
    if (seen.has(key)) continue
    seen.add(key)
    links.push({
      label: route.label || step.title || '进入下钻',
      path: route.path,
      query: route.query || {},
    })
  }
  return links.slice(0, 4)
})

const companySignals = computed(() => {
  const snapshotLabel = timelineSnapshot.value?.score_delta === undefined
    ? '等待刷新'
    : timelineSnapshot.value.score_delta > 0
      ? `较上期 +${timelineSnapshot.value.score_delta}`
      : timelineSnapshot.value.score_delta < 0
        ? `较上期 ${timelineSnapshot.value.score_delta}`
        : '较上期持平'

  return [
    {
      label: '当前评级',
      value: companySummary.value ? `${companySummary.value.total_score} / ${companySummary.value.grade}` : '--',
    },
    {
      label: '重点风险',
      value: companyTopRisks.value[0] || '等待识别',
    },
    {
      label: '报期状态',
      value: snapshotLabel,
    },
    {
      label: '持续跟踪',
      value: companyWatch.value?.tracked ? '已纳入' : '未纳入',
    },
  ]
})

const workspaceStatus = computed(() => [
  controlPlane.value?.report_period ? `报期 ${controlPlane.value.report_period}` : '',
  controlPlane.value?.data_sources?.length ? controlPlane.value.data_sources.join(' · ') : '',
  aiAssurance.value?.label ? aiAssurance.value.label : '',
].filter(Boolean))

const pageLoadError = computed(() => companiesError.value || overviewError.value || companyWorkspaceError.value || '')
const hasCompanies = computed(() => companies.value.length > 0)
const canRunQuery = computed(() => !!selectedCompany.value && !!query.value.trim() && !loadingTurn.value)

const companySelectPlaceholder = computed(() => {
  if (loadingCompanies.value) return '正在载入公司池'
  if (companiesError.value) return '公司池加载失败'
  if (!companies.value.length) return '当前无公司'
  return '选择公司'
})

const consoleSyncLabel = computed(() => {
  if (loadingCompanies.value) return '公司池载入中'
  if (loadingOverview.value) return '协同面同步中'
  if (loadingCompanyWorkspace.value) return '企业状态刷新中'
  if (pageLoadError.value) return '数据载入异常'
  if (selectedCompany.value) return `${selectedCompany.value} · ${roleLabel.value}`
  return roleLabel.value
})

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
    if (line.startsWith('### ')) {
      if (current.paragraphs.length || current.bullets.length || blocks.length === 0) {
        blocks.push(current)
      }
      current = { title: line.replace(/^###\s+/, ''), paragraphs: [], bullets: [] }
      continue
    }
    if (line.startsWith('- ')) {
      current.bullets.push(line.replace(/^- /, ''))
      continue
    }
    current.paragraphs.push(line)
  }

  if (current.title || current.paragraphs.length || current.bullets.length) {
    blocks.push(current)
  }

  return blocks.filter((block) => block.paragraphs.length || block.bullets.length)
}

function displayFlowStatus(status?: string) {
  const map: Record<string, string> = {
    completed: 'Done',
    done: 'Done',
    active: 'Live',
    running: 'Live',
    failed: 'Error',
    blocked: 'Blocked',
  }
  return map[(status || '').toLowerCase()] || 'Done'
}

function displayMetricValue(item: any) {
  if (item?.unit) return `${item.value}${item.unit}`
  return `${item?.value ?? '--'}`
}

function formatExecutionMs(value?: number) {
  if (!value) return ''
  if (value >= 1000) return `${(value / 1000).toFixed(1)}s`
  return `${Math.round(value)}ms`
}

function readQueryString(value: unknown) {
  const normalized = Array.isArray(value) ? value[0] : value
  return typeof normalized === 'string' ? normalized.trim() : ''
}

function parseRoleQuery(value: unknown): UserRole | null {
  const normalized = readQueryString(value)
  if (normalized === 'investor' || normalized === 'management' || normalized === 'regulator') return normalized
  return null
}

async function primeScenarioFromRoute() {
  const targetRole = parseRoleQuery(route.query.role)
  if (targetRole && session.activeRole.value !== targetRole) {
    session.setActiveRole(targetRole)
    return
  }

  const prompt = readQueryString(route.query.prompt)
  const targetCompany = readQueryString(route.query.company)
  if (targetCompany && companies.value.includes(targetCompany) && selectedCompany.value !== targetCompany) {
    selectedCompany.value = targetCompany
  }

  if (!prompt) return
  query.value = prompt

  const shouldAutoRun = readQueryString(route.query.auto_run) === '1'
  const scenarioKey = `${route.fullPath}::${selectedCompany.value || ''}`
  if (!shouldAutoRun || !selectedCompany.value || loadingTurn.value || appliedScenarioKey.value === scenarioKey) return
  appliedScenarioKey.value = scenarioKey
  await runQuery(prompt)
}

async function runQuery(inputQuery?: string) {
  if (inputQuery) query.value = inputQuery
  await workspace.sendQuery(session.activeRole.value || 'investor', query.value)
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

async function toggleWatchCompany() {
  if (!selectedCompany.value) return
  watchBusy.value = true
  try {
    if (companyWatch.value.tracked) {
      await workspace.removeCurrentCompanyFromWatchboard(session.activeRole.value || 'investor')
    } else {
      await workspace.addCurrentCompanyToWatchboard(session.activeRole.value || 'investor', `${roleLabel.value}持续跟踪`)
    }
  } finally {
    watchBusy.value = false
  }
}

async function scanTrackedCompanies() {
  scanBusy.value = true
  try {
    await workspace.scanWatchboard(session.activeRole.value || 'investor')
  } finally {
    scanBusy.value = false
  }
}

onMounted(async () => {
  const initialRole = parseRoleQuery(route.query.role)
  if (initialRole && session.activeRole.value !== initialRole) session.setActiveRole(initialRole)
  workspace.resetConversation(roleCopy.value.title, roleCopy.value.label)
  try {
    await workspace.bootstrap(session.activeRole.value || 'investor')
    await primeScenarioFromRoute()
  } catch {
    // 错误已写入 store。
  }
})

watch(
  () => session.activeRole.value,
  async () => {
    workspace.resetConversation(roleCopy.value.title, roleCopy.value.label)
    try {
      await workspace.bootstrap(session.activeRole.value || 'investor')
      await primeScenarioFromRoute()
    } catch {
      // 错误已写入 store。
    }
  },
)

watch(() => route.fullPath, async () => {
  await primeScenarioFromRoute()
})

watch(selectedCompany, async (company, previous) => {
  if (!company || company === previous || loadingCompanies.value) return
  await workspace.loadCompanyWorkspace(session.activeRole.value || 'investor')
})
</script>

<template>
  <AppShell title="">
    <div class="workspace-console">
      <section class="console-header">
        <div class="console-heading">
          <span class="console-kicker">Data x Risk x Strategy x Self-Reflection</span>
          <h1>多智能体协同研判</h1>
          <p>{{ consoleSyncLabel }}</p>
        </div>

        <div class="console-toolbar">
          <label class="toolbar-select">
            <span>企业</span>
            <select v-model="selectedCompany" :disabled="loadingCompanies || !companies.length">
              <option value="" disabled>{{ companySelectPlaceholder }}</option>
              <option v-for="company in companies" :key="company" :value="company">{{ company }}</option>
            </select>
          </label>
          <button type="button" class="toolbar-button is-primary" :disabled="!selectedCompany || watchBusy" @click="toggleWatchCompany">
            {{ watchBusy ? '处理中...' : companyWatch.tracked ? '移出跟踪' : '加入跟踪' }}
          </button>
          <button type="button" class="toolbar-button" :disabled="scanBusy || !hasCompanies" @click="scanTrackedCompanies">
            {{ scanBusy ? '刷新中...' : '刷新' }}
          </button>
        </div>
      </section>

      <ErrorState v-if="pageLoadError" :message="pageLoadError" class="workspace-state" />
      <section v-else-if="!hasCompanies && !loadingCompanies" class="workspace-state workspace-empty">
        <span class="console-kicker">Workspace Offline</span>
        <h2>公司池尚未就绪。</h2>
        <p>先把真实公司数据接进来，再开始协同研判。</p>
      </section>

      <section v-else class="console-stage">
        <div class="console-stream">
          <article class="console-message is-assistant">
            <div class="message-glyph">AI</div>
            <div class="message-panel intro-panel">
              <strong>你好，我是协同研判台。</strong>
              <p>
                围绕 {{ selectedCompany || '目标企业' }} 的收益质量、风险暴露、证据链和下一步动作，直接给出一轮可继续追问的判断。
              </p>

              <div class="intro-signal-row">
                <span v-for="item in companySignals" :key="item.label" class="signal-chip">
                  <em>{{ item.label }}</em>
                  <strong>{{ item.value }}</strong>
                </span>
              </div>
            </div>
          </article>

          <article v-if="latestUserMessage" class="console-message is-user">
            <div class="user-query-panel">
              <span>本轮问题</span>
              <strong>{{ latestUserMessage.text }}</strong>
            </div>
          </article>

          <article v-if="loadingTurn" class="console-message is-assistant">
            <div class="message-glyph">AI</div>
            <div class="message-stack">
              <section class="workflow-panel">
                <div class="workflow-head">
                  <span>Executing Multi-Agent Workflow</span>
                  <strong>Running</strong>
                </div>
                <p>正在检索真实评分、风险扫描、证据链与动作建议。</p>
              </section>
            </div>
          </article>

          <article v-else-if="latestAnswer" class="console-message is-assistant">
            <div class="message-glyph">AI</div>
            <div class="message-stack">
              <section class="workflow-panel">
                <div class="workflow-head">
                  <span>Executing Multi-Agent Workflow</span>
                  <strong>{{ aiAssurance?.label || 'Done' }}</strong>
                </div>

                <div class="workflow-list">
                  <div v-for="step in workflowSteps" :key="step.step" class="workflow-row">
                    <div class="workflow-copy">
                      <strong>[{{ step.agent_label || step.agent }}]</strong>
                      <p>{{ step.summary }}</p>
                    </div>
                    <em>{{ displayFlowStatus(step.status) }}</em>
                  </div>
                </div>
              </section>

              <section class="analysis-sheet">
                <div class="analysis-head">
                  <span>当前结论</span>
                  <h2>{{ latestAnswer.summary || '已生成当前轮次研判' }}</h2>
                  <div class="analysis-meta">
                    <span v-for="item in workspaceStatus" :key="item">{{ item }}</span>
                    <span v-if="controlPlane?.steps_completed">流程 {{ controlPlane.steps_completed }}/{{ controlPlane.step_total }}</span>
                    <span v-if="controlPlane?.execution_ms">耗时 {{ formatExecutionMs(controlPlane.execution_ms) }}</span>
                  </div>
                </div>

                <div class="analysis-grid">
                  <div class="analysis-copy">
                    <section v-for="block in answerBlocks" :key="block.title" class="analysis-block">
                      <h3>{{ block.title }}</h3>
                      <p v-for="line in block.paragraphs" :key="line">{{ line }}</p>
                      <ul v-if="block.bullets.length">
                        <li v-for="line in block.bullets" :key="line">{{ line }}</li>
                      </ul>
                    </section>
                  </div>

                  <aside class="analysis-side">
                    <section v-if="insightNumbers.length" class="side-stack">
                      <span class="side-label">关键数字</span>
                      <article v-for="item in insightNumbers" :key="item.label" class="metric-row">
                        <span>{{ item.label }}</span>
                        <strong>{{ displayMetricValue(item) }}</strong>
                      </article>
                    </section>

                    <section v-if="latestActionCards.length" class="side-stack">
                      <span class="side-label">下一步动作</span>
                      <article v-for="item in latestActionCards" :key="item.title" class="action-row">
                        <em>{{ item.priority || 'Action' }}</em>
                        <strong>{{ item.title }}</strong>
                        <p>{{ item.action || item.reason }}</p>
                      </article>
                    </section>
                  </aside>
                </div>
              </section>

              <section v-if="latestEvidenceGroups.length || resultLinks.length" class="evidence-dock">
                <div v-if="latestEvidenceGroups.length" class="evidence-groups">
                  <article v-for="group in latestEvidenceGroups" :key="group.title || group.code" class="evidence-group">
                    <strong>{{ group.title || group.group_type || '证据组' }}</strong>
                    <p>{{ group.subtitle || '真实证据已挂接到当前判断。' }}</p>
                    <ul v-if="group.items?.length">
                      <li v-for="item in group.items.slice(0, 2)" :key="item.chunk_id || item.source_title">
                        {{ item.source_title }} · 第{{ item.page }}页
                      </li>
                    </ul>
                  </article>
                </div>

                <div v-if="resultLinks.length" class="evidence-links">
                  <RouterLink
                    v-for="link in resultLinks"
                    :key="`${link.label}-${link.path}`"
                    :to="{ path: link.path, query: link.query || {} }"
                    class="evidence-link"
                  >
                    <span>{{ link.label }}</span>
                    <strong>进入</strong>
                  </RouterLink>
                </div>
              </section>
            </div>
          </article>

          <article v-else class="console-message is-assistant">
            <div class="message-glyph">AI</div>
            <div class="message-panel prep-panel">
              <strong>从一个判断问题开始。</strong>
              <p>我会调用真实评分、行业风险扫描、证据校验和动作规划，把结果压成一轮结论。</p>

              <div class="prep-grid">
                <article class="prep-cell">
                  <span>当前研报</span>
                  <strong>{{ companyResearch?.status === 'ready' ? companyResearch.report_title : '等待核验' }}</strong>
                </article>
                <article class="prep-cell">
                  <span>重点风险</span>
                  <strong>{{ companyTopRisks[0] || '等待识别' }}</strong>
                </article>
                <article class="prep-cell">
                  <span>优先动作</span>
                  <strong>{{ companyActions[0]?.title || '等待生成' }}</strong>
                </article>
              </div>
            </div>
          </article>
        </div>

        <div class="console-composer">
          <div class="composer-shell">
            <textarea
              v-model="query"
              :disabled="loadingCompanies || !hasCompanies"
              :placeholder="selectedCompany ? `输入你要围绕 ${selectedCompany} 继续判断的问题` : '先选择公司，再发起协同研判'"
              rows="4"
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

          <ErrorState v-if="turnError" :message="turnError" />
        </div>
      </section>
    </div>
  </AppShell>
</template>

<style scoped>
.workspace-console {
  min-height: 100%;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  gap: 18px;
  width: 100%;
  max-width: 1480px;
  margin: 0 auto;
}

.console-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 18px;
  padding-bottom: 14px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.console-heading {
  display: grid;
  gap: 8px;
}

.console-kicker,
.toolbar-select span,
.user-query-panel span,
.workflow-head span,
.side-label,
.signal-chip em,
.prep-cell span {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}

.console-kicker {
  color: rgba(94, 234, 212, 0.72);
}

.console-heading h1,
.analysis-head h2,
.analysis-block h3 {
  margin: 0;
  letter-spacing: -0.05em;
  color: #f8fafc;
}

.console-heading h1 {
  font-size: clamp(30px, 3.4vw, 40px);
  line-height: 0.98;
}

.console-heading p {
  margin: 0;
  color: rgba(148, 163, 184, 0.92);
  font-size: 13px;
}

.console-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.toolbar-select {
  display: grid;
  gap: 8px;
}

.toolbar-select span {
  color: rgba(120, 143, 172, 0.82);
}

.toolbar-select select {
  min-width: 220px;
  min-height: 46px;
  padding: 0 14px;
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.03);
  color: #eef2f7;
}

.toolbar-button {
  min-height: 46px;
  padding: 0 16px;
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.03);
  color: #d7dee8;
  cursor: pointer;
}

.toolbar-button.is-primary {
  border-color: rgba(52, 211, 153, 0.24);
  background: rgba(18, 62, 45, 0.9);
  color: #f0fdf4;
}

.toolbar-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.workspace-state,
.console-stage {
  min-height: 0;
  border-radius: 22px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: linear-gradient(180deg, rgba(16, 17, 20, 0.98), rgba(12, 13, 17, 0.98));
}

.workspace-empty {
  display: grid;
  place-items: center;
  gap: 10px;
  padding: 60px 24px;
  text-align: center;
}

.workspace-empty h2,
.workspace-empty p {
  margin: 0;
}

.workspace-empty p {
  color: rgba(148, 163, 184, 0.88);
}

.console-stage {
  display: grid;
  grid-template-rows: minmax(0, 1fr) auto;
  overflow: hidden;
}

.console-stream {
  min-height: 0;
  overflow-y: auto;
  padding: 18px 18px 8px;
  display: grid;
  gap: 16px;
}

.console-message {
  display: grid;
  gap: 16px;
}

.console-message.is-assistant {
  grid-template-columns: 44px minmax(0, 1fr);
  align-items: flex-start;
}

.message-glyph {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  border: 1px solid rgba(52, 211, 153, 0.22);
  background: rgba(18, 62, 45, 0.92);
  color: #73f0c7;
  display: grid;
  place-items: center;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
}

.message-panel,
.workflow-panel,
.analysis-sheet,
.evidence-dock,
.user-query-panel {
  border-radius: 18px;
  border: 1px solid rgba(255, 255, 255, 0.07);
  background: rgba(255, 255, 255, 0.02);
}

.message-panel {
  padding: 16px 18px;
  display: grid;
  gap: 10px;
}

.message-panel strong,
.workflow-copy strong,
.action-row strong,
.prep-cell strong,
.signal-chip strong {
  color: #f8fafc;
}

.message-panel p,
.workflow-copy p,
.analysis-block p,
.analysis-block li,
.action-row p,
.evidence-group p,
.evidence-group li,
.prep-cell strong {
  margin: 0;
  color: rgba(221, 228, 238, 0.9);
  line-height: 1.75;
}

.intro-signal-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.signal-chip {
  display: grid;
  gap: 6px;
  min-width: 108px;
  padding: 10px 12px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.03);
}

.signal-chip em,
.workflow-head span,
.side-label,
.prep-cell span,
.user-query-panel span {
  color: rgba(120, 143, 172, 0.86);
  font-style: normal;
}

.user-query-panel {
  margin-left: auto;
  max-width: min(700px, 76%);
  padding: 16px 18px;
  display: grid;
  gap: 8px;
  background: rgba(27, 43, 108, 0.72);
  border-color: rgba(82, 118, 255, 0.24);
}

.user-query-panel strong {
  color: #f8fafc;
  font-size: 18px;
  line-height: 1.45;
}

.message-stack {
  display: grid;
  gap: 16px;
}

.workflow-panel {
  padding: 16px 18px;
  display: grid;
  gap: 12px;
}

.workflow-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.workflow-head strong {
  color: #73f0c7;
  font-size: 14px;
}

.workflow-panel > p {
  margin: 0;
  color: rgba(148, 163, 184, 0.88);
}

.workflow-list {
  display: grid;
  gap: 10px;
}

.workflow-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.workflow-copy {
  display: grid;
  gap: 6px;
}

.workflow-row em {
  color: #73f0c7;
  font-style: normal;
  white-space: nowrap;
}

.analysis-sheet {
  padding: 18px 20px;
  display: grid;
  gap: 16px;
}

.analysis-head {
  display: grid;
  gap: 10px;
}

.analysis-head > span {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: rgba(120, 143, 172, 0.86);
}

.analysis-head h2 {
  font-size: clamp(24px, 2.6vw, 34px);
  line-height: 1.02;
}

.analysis-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.analysis-meta span {
  min-height: 32px;
  padding: 0 12px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  background: rgba(255, 255, 255, 0.04);
  color: rgba(203, 213, 225, 0.88);
  font-size: 12px;
}

.analysis-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.3fr) minmax(260px, 0.7fr);
  gap: 16px;
}

.analysis-copy,
.analysis-side,
.side-stack {
  display: grid;
  gap: 14px;
}

.analysis-block {
  display: grid;
  gap: 10px;
}

.analysis-block + .analysis-block {
  padding-top: 14px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.analysis-block h3 {
  font-size: 16px;
}

.analysis-block ul {
  margin: 0;
  padding-left: 18px;
  display: grid;
  gap: 8px;
}

.side-stack {
  padding: 12px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.025);
}

.metric-row,
.action-row {
  display: grid;
  gap: 6px;
}

.metric-row span {
  color: rgba(148, 163, 184, 0.82);
  font-size: 13px;
}

.metric-row strong {
  color: #f8fafc;
  font-size: 21px;
  letter-spacing: -0.04em;
}

.action-row {
  padding-top: 8px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.action-row:first-of-type {
  padding-top: 0;
  border-top: none;
}

.action-row em {
  font-family: 'JetBrains Mono', monospace;
  font-style: normal;
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: #73f0c7;
}

.evidence-dock {
  padding: 14px 16px;
  display: grid;
  gap: 12px;
}

.evidence-groups {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.evidence-group {
  display: grid;
  gap: 8px;
  padding: 12px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.03);
}

.evidence-group strong {
  color: #f8fafc;
}

.evidence-group ul {
  margin: 0;
  padding-left: 18px;
  display: grid;
  gap: 6px;
  color: rgba(203, 213, 225, 0.86);
}

.evidence-links {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.evidence-link {
  min-height: 42px;
  padding: 0 14px;
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.03);
  color: #dbe7f3;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: 10px;
}

.evidence-link strong {
  color: #73f0c7;
  font-size: 12px;
}

.prep-panel {
  gap: 14px;
}

.prep-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.prep-cell {
  display: grid;
  gap: 8px;
  padding: 12px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.03);
}

.console-composer {
  padding: 12px 18px 18px;
  display: grid;
  gap: 12px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  background: linear-gradient(180deg, rgba(12, 13, 17, 0), rgba(12, 13, 17, 0.96) 26%);
}

.composer-shell {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 148px;
  gap: 12px;
  padding: 10px;
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
  line-height: 1.7;
  outline: none;
}

.composer-submit {
  min-height: 100%;
  border-radius: 14px;
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

.composer-prompts {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.prompt-chip {
  min-height: 38px;
  padding: 0 14px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.025);
  color: #dbe7f3;
  cursor: pointer;
}

@media (max-width: 1100px) {
  .analysis-grid,
  .evidence-groups {
    grid-template-columns: 1fr;
  }

  .prep-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 800px) {
  .console-header,
  .console-toolbar {
    flex-direction: column;
    align-items: stretch;
  }

  .composer-shell {
    grid-template-columns: 1fr;
  }

  .console-stream,
  .console-composer {
    padding-left: 16px;
    padding-right: 16px;
  }

  .console-message.is-assistant {
    grid-template-columns: 1fr;
  }

  .message-glyph {
    display: none;
  }

  .user-query-panel {
    max-width: 100%;
  }
}
</style>
