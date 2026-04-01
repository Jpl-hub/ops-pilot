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
      label: '数据状态',
      value: companyWorkspace.value?.timeline?.snapshots?.length ? '已接入' : '待补齐',
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

const analysisStages = computed(() => {
  const sourceLine = controlPlane.value?.data_sources?.length
    ? controlPlane.value.data_sources.join('、')
    : '评分、图谱、压力、核验等真实服务'
  const riskLine = companyTopRisks.value[0] || '回放证据与风险标签'
  return [
    {
      index: '01',
      meta: '任务识别',
      title: '识别问题类型',
      detail: latestUserMessage.value
        ? `锁定 ${selectedCompany.value || '目标企业'} 的判断问题`
        : '锁定问题意图、公司主体和目标报期',
      status: latestUserMessage.value ? 'completed' : 'pending',
    },
    {
      index: '02',
      meta: '数据分析',
      title: '拉取真实数据与工具',
      detail: `调取 ${sourceLine}`,
      status: latestAnswer.value || loadingTurn.value ? 'completed' : 'pending',
    },
    {
      index: '03',
      meta: '证据核验',
      title: '校验证据与风险',
      detail: latestEvidenceGroups.value.length
        ? `已挂接 ${latestEvidenceGroups.value.length} 组证据，重点围绕 ${riskLine}`
        : `围绕 ${riskLine} 回放证据与风险`,
      status: latestEvidenceGroups.value.length ? 'completed' : loadingTurn.value ? 'running' : 'pending',
    },
    {
      index: '04',
      meta: '策略生成',
      title: '生成角色动作',
      detail: latestActionCards.value.length
        ? `输出 ${roleLabel.value} 视角下的下一步动作`
        : `按 ${roleLabel.value} 视角生成动作`,
      status: latestActionCards.value.length ? 'completed' : loadingTurn.value ? 'running' : 'pending',
    },
  ]
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
    completed: '完成',
    done: '完成',
    active: '进行中',
    running: '进行中',
    failed: '异常',
    blocked: '阻断',
  }
  return map[(status || '').toLowerCase()] || '完成'
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
      <ErrorState v-if="pageLoadError" :message="pageLoadError" class="workspace-state" />
      <section v-else-if="!hasCompanies && !loadingCompanies" class="workspace-state workspace-empty">
        <span class="console-kicker">工作台未就绪</span>
        <h2>公司池尚未就绪</h2>
        <p>先把正式公司池接入，再开始协同分析。</p>
      </section>

      <section v-else class="console-board">
        <header class="board-topbar">
          <div class="board-title">
            <div class="board-mark">⎔</div>
            <strong>协同分析</strong>
            <span class="board-subtitle">{{ roleFocusTitle }}</span>
          </div>

          <div class="board-topbar-meta">
            <label class="board-select">
              <span>公司</span>
              <select v-model="selectedCompany" :disabled="loadingCompanies || !companies.length">
                <option value="" disabled>{{ companySelectPlaceholder }}</option>
                <option v-for="company in companies" :key="company" :value="company">{{ company }}</option>
              </select>
            </label>
            <span class="board-role-chip">{{ roleLabel }}</span>
          </div>
        </header>

        <section class="board-flow">
          <article
            v-for="stage in analysisStages"
            :key="stage.index"
            class="flow-card"
            :class="`is-${stage.status}`"
          >
            <div class="flow-meta">
              <span>{{ stage.index }}</span>
              <em>{{ stage.meta }}</em>
            </div>
            <strong>{{ stage.title }}</strong>
            <p>{{ stage.detail }}</p>
          </article>
        </section>

        <section class="board-body">
          <div class="board-canvas">
            <header class="canvas-head">
              <div>
                <span class="canvas-kicker">正在判断</span>
                <strong>{{ latestUserMessage?.text || '从一个判断问题开始' }}</strong>
              </div>
              <div class="canvas-head-meta">
                <span>{{ selectedCompany || '未选择公司' }}</span>
                <span>{{ consoleSyncLabel }}</span>
              </div>
            </header>

            <div v-if="loadingTurn" class="canvas-loading">
              <div class="canvas-loading-card">
                <strong>正在调度真实服务</strong>
                <p>评分、图谱、证据校验和动作规划已经开始运行。</p>
                <div class="loading-steps">
                  <div v-for="step in workflowSteps.slice(0, 4)" :key="step.step" class="loading-step">
                    <span>[{{ step.agent_label || step.agent }}]</span>
                    <strong>{{ displayFlowStatus(step.status) }}</strong>
                  </div>
                </div>
              </div>
            </div>

            <div v-else-if="latestAnswer" class="canvas-content">
              <section class="canvas-summary">
                <h2>{{ latestAnswer.summary || '已生成当前轮次研判' }}</h2>
                <div class="analysis-meta">
                  <span v-for="item in workspaceStatus" :key="item">{{ item }}</span>
                  <span v-if="controlPlane?.steps_completed">流程 {{ controlPlane.steps_completed }}/{{ controlPlane.step_total }}</span>
                  <span v-if="controlPlane?.execution_ms">耗时 {{ formatExecutionMs(controlPlane.execution_ms) }}</span>
                </div>
              </section>

              <div class="canvas-copy">
                <section v-for="block in answerBlocks" :key="block.title" class="analysis-block">
                  <h3>{{ block.title }}</h3>
                  <p v-for="line in block.paragraphs" :key="line">{{ line }}</p>
                  <ul v-if="block.bullets.length">
                    <li v-for="line in block.bullets" :key="line">{{ line }}</li>
                  </ul>
                </section>
              </div>
            </div>

            <div v-else class="canvas-empty">
              <div class="empty-flag">↓</div>
              <div class="empty-copy">
                <strong>当前还没有可分析内容</strong>
                <p>先完成正式公司池和页级指标接入，再发起协同分析。</p>

                <div class="empty-signal-row">
                  <span v-for="item in companySignals" :key="item.label" class="signal-chip">
                    <em>{{ item.label }}</em>
                    <strong>{{ item.value }}</strong>
                  </span>
                </div>
              </div>
            </div>
          </div>

          <aside class="result-rail">
            <header class="rail-head">
              <strong>本轮结果</strong>
              <span>{{ roleLabel }}</span>
            </header>

            <div v-if="latestAnswer" class="rail-body">
              <section class="rail-section summary-card">
                <span class="rail-label">结论</span>
                <strong>{{ selectedCompany || '未选择公司' }}</strong>
                <p>{{ latestAnswer.summary || '已生成当前结论。' }}</p>
                <p v-if="latestUserMessage?.text" class="rail-question">{{ latestUserMessage.text }}</p>
              </section>

              <section v-if="insightNumbers.length" class="rail-section">
                <span class="rail-label">关键数字</span>
                <div class="metric-grid">
                  <article v-for="item in insightNumbers" :key="item.label" class="metric-row">
                    <span>{{ item.label }}</span>
                    <strong>{{ displayMetricValue(item) }}</strong>
                  </article>
                </div>
              </section>

              <section v-if="latestActionCards.length" class="rail-section">
                <span class="rail-label">下一步动作</span>
                <div class="action-list">
                  <article v-for="item in latestActionCards" :key="item.title" class="action-row">
                    <em>{{ item.priority || '动作' }}</em>
                    <strong>{{ item.title }}</strong>
                    <p>{{ item.action || item.reason }}</p>
                  </article>
                </div>
              </section>

              <section v-if="latestEvidenceGroups.length" class="rail-section">
                <span class="rail-label">这轮证据</span>
                <article v-for="group in latestEvidenceGroups" :key="group.title || group.code" class="evidence-row">
                  <strong>{{ group.title || group.group_type || '证据组' }}</strong>
                  <p>{{ group.subtitle || '真实证据已挂接到当前判断。' }}</p>
                  <ul v-if="group.items?.length">
                    <li v-for="item in group.items.slice(0, 2)" :key="item.chunk_id || item.source_title">
                      {{ item.source_title }} · 第{{ item.page }}页
                    </li>
                  </ul>
                </article>
              </section>

              <section v-if="resultLinks.length" class="rail-section">
                <span class="rail-label">继续下钻</span>
                <div class="rail-link-row">
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

            <div v-else class="rail-empty">
              <div class="rail-empty-icon">▤</div>
              <p>发起分析后结果将展示于此</p>
            </div>
          </aside>
        </section>

        <footer class="board-composer">
          <div class="composer-prompts">
            <button
              v-for="question in starterQueries.slice(0, 2)"
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

          <ErrorState v-if="turnError" :message="turnError" />
        </footer>
      </section>
    </div>
  </AppShell>
</template>

<style scoped>
.workspace-console {
  min-height: 100%;
  display: grid;
  gap: 16px;
  width: 100%;
  max-width: 1380px;
  margin: 0 auto;
}

.console-kicker,
.board-select span,
.canvas-kicker,
.rail-label,
.signal-chip em {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}

.console-kicker {
  color: rgba(94, 234, 212, 0.72);
}

.workspace-state,
.console-board {
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

.console-board {
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr) auto;
  overflow: hidden;
}

.board-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 16px 10px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.board-title {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  flex-wrap: wrap;
}

.board-mark {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  border: 1px solid rgba(52, 211, 153, 0.22);
  background: rgba(18, 62, 45, 0.92);
  display: grid;
  place-items: center;
  color: #73f0c7;
}

.board-title strong,
.canvas-head strong,
.canvas-summary h2,
.analysis-block h3,
.evidence-card strong,
.rail-head strong,
.metric-row strong,
.action-row strong,
.empty-copy strong,
.canvas-loading-card strong,
.loading-step strong {
  color: #f8fafc;
}

.board-title strong {
  font-size: 24px;
  letter-spacing: -0.04em;
}

.board-subtitle {
  color: rgba(120, 143, 172, 0.88);
  font-size: 12px;
}

.board-topbar-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.board-select {
  display: grid;
  gap: 6px;
}

.board-select span,
.canvas-kicker,
.rail-label,
.signal-chip em {
  color: rgba(120, 143, 172, 0.82);
  font-style: normal;
}

.board-select select {
  min-width: 168px;
  min-height: 42px;
  padding: 0 14px;
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.03);
  color: #eef2f7;
}

.board-role-chip {
  min-height: 34px;
  padding: 0 12px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  background: rgba(72, 51, 107, 0.46);
  color: #e5def8;
  font-size: 13px;
}

.board-flow {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  padding: 8px 14px 10px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.flow-card {
  display: grid;
  gap: 6px;
  min-height: 84px;
  padding: 10px 11px 9px;
  border-radius: 16px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.02);
}

.flow-card.is-completed {
  border-color: rgba(52, 211, 153, 0.16);
}

.flow-card.is-running {
  border-color: rgba(96, 165, 250, 0.18);
}

.flow-meta {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.08em;
}

.flow-meta span {
  color: #73f0c7;
}

.flow-meta em {
  color: rgba(120, 143, 172, 0.8);
  font-style: normal;
}

.flow-card strong {
  font-size: 14px;
}

.flow-card p {
  margin: 0;
  color: rgba(161, 174, 193, 0.88);
  line-height: 1.5;
  font-size: 12px;
}

.board-body {
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 392px;
}

.board-canvas {
  min-height: 0;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  border-right: 1px solid rgba(255, 255, 255, 0.06);
}

.canvas-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px 10px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.canvas-head strong {
  display: block;
  margin-top: 6px;
  font-size: 16px;
  line-height: 1.45;
  letter-spacing: -0.02em;
}

.canvas-head-meta,
.analysis-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.canvas-head-meta span,
.analysis-meta span {
  min-height: 30px;
  padding: 0 10px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  background: rgba(255, 255, 255, 0.04);
  color: rgba(203, 213, 225, 0.84);
  font-size: 12px;
}

.canvas-loading,
.canvas-empty {
  min-height: 0;
  display: grid;
  place-items: center;
  padding: 24px;
}

.canvas-loading-card,
.empty-copy {
  display: grid;
  gap: 10px;
  justify-items: center;
  text-align: center;
}

.canvas-loading-card {
  min-width: min(420px, 100%);
  padding: 20px;
  border-radius: 18px;
  border: 1px solid rgba(52, 211, 153, 0.14);
  background: rgba(18, 62, 45, 0.18);
}

.canvas-loading-card strong,
.empty-copy strong {
  font-size: 20px;
}

.canvas-loading-card p,
.empty-copy p,
.analysis-block p,
.analysis-block li,
.evidence-card p,
.evidence-card li,
.rail-section p,
.action-row p {
  margin: 0;
  color: rgba(221, 228, 238, 0.88);
  line-height: 1.75;
}

.loading-steps {
  display: flex;
  flex-wrap: wrap;
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
  color: rgba(218, 226, 236, 0.88);
  font-size: 12px;
}

.loading-step span {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: rgba(120, 143, 172, 0.82);
}

.loading-step strong {
  color: #73f0c7;
  font-size: 12px;
}

.empty-flag {
  width: 64px;
  height: 64px;
  border-radius: 18px;
  display: grid;
  place-items: center;
  font-size: 32px;
  color: #73f0c7;
  border: 1px solid rgba(52, 211, 153, 0.18);
  background: rgba(18, 62, 45, 0.16);
}

.empty-signal-row {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 10px;
  margin-top: 4px;
}

.signal-chip {
  display: grid;
  gap: 6px;
  min-width: 108px;
  padding: 10px 12px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.03);
}

.signal-chip strong {
  font-size: 13px;
}

.canvas-content {
  min-height: 0;
  overflow-y: auto;
  padding: 18px;
  display: grid;
  gap: 16px;
}

.canvas-summary {
  display: grid;
  gap: 10px;
}

.canvas-summary h2 {
  font-size: clamp(20px, 2.1vw, 26px);
  line-height: 1.08;
  letter-spacing: -0.04em;
}

.canvas-copy {
  display: grid;
  gap: 14px;
}

.analysis-block {
  display: grid;
  gap: 9px;
  padding: 0 0 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.analysis-block:last-child {
  padding-bottom: 0;
  border-bottom: none;
}

.analysis-block h3 {
  font-size: 16px;
  letter-spacing: -0.02em;
}

.analysis-block ul,
.evidence-card ul {
  margin: 0;
  padding-left: 18px;
  display: grid;
  gap: 6px;
}

.result-rail {
  min-height: 0;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
}

.rail-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 14px 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.rail-head strong {
  font-size: 17px;
}

.rail-head span {
  color: rgba(120, 143, 172, 0.86);
  font-size: 12px;
}

.rail-body {
  min-height: 0;
  overflow-y: auto;
  padding: 14px;
  display: grid;
  gap: 12px;
}

.rail-section {
  display: grid;
  gap: 8px;
  padding-bottom: 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.rail-section:last-child {
  padding-bottom: 0;
  border-bottom: none;
}

.summary-card {
  gap: 10px;
}

.summary-card strong {
  font-size: 20px;
  letter-spacing: -0.04em;
  color: #f8fafc;
}

.rail-question {
  color: rgba(148, 163, 184, 0.92);
  font-size: 12px;
}

.metric-row,
.action-row,
.evidence-row {
  display: grid;
  gap: 6px;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.metric-row span {
  color: rgba(148, 163, 184, 0.82);
  font-size: 12px;
}

.metric-row strong {
  font-size: 18px;
  letter-spacing: -0.04em;
}

.metric-row {
  min-height: 52px;
  padding: 10px 12px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.025);
  border: 1px solid rgba(255, 255, 255, 0.05);
}

.action-list,
.rail-link-row {
  display: grid;
  gap: 10px;
}

.action-row em {
  font-family: 'JetBrains Mono', monospace;
  font-style: normal;
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: #73f0c7;
}

.evidence-row ul {
  margin: 0;
  padding-left: 18px;
  display: grid;
  gap: 6px;
  color: rgba(221, 228, 238, 0.88);
}

.evidence-link strong {
  color: #73f0c7;
  font-size: 12px;
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
  justify-content: space-between;
  gap: 10px;
}

.rail-empty {
  min-height: 0;
  display: grid;
  place-items: center;
  padding: 24px 16px;
  gap: 12px;
  text-align: center;
  color: rgba(120, 143, 172, 0.78);
}

.rail-empty-icon {
  font-size: 32px;
  color: rgba(120, 143, 172, 0.6);
}

.composer-submit:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.board-composer {
  padding: 8px 14px 12px;
  display: grid;
  gap: 6px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.composer-shell {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 96px;
  gap: 10px;
  padding: 4px 8px;
  border-radius: 12px;
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
  line-height: 1.5;
  min-height: 30px;
  padding-top: 4px;
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

.composer-prompts {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.prompt-chip {
  min-height: 30px;
  padding: 0 12px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.025);
  color: #dbe7f3;
  cursor: pointer;
  font-size: 12px;
}

@media (max-width: 1180px) {
  .board-flow,
  .board-body,
  .canvas-columns {
    grid-template-columns: 1fr;
  }

  .board-canvas {
    border-right: none;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  }
}

@media (max-width: 820px) {
  .board-topbar,
  .board-topbar-meta,
  .canvas-head {
    flex-direction: column;
    align-items: stretch;
  }

  .composer-shell {
    grid-template-columns: 1fr;
  }
}
</style>
