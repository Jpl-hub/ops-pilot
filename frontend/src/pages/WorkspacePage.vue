<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AppShell from '@/components/AppShell.vue'
import { useSession } from '@/lib/session'
import { persistWorkflowContext, resolveWorkflowContext } from '@/lib/workflowContext'
import { useWorkspaceStore } from '@/stores/workspace'
import type { UserRole } from '@/lib/api'

type ResultSection = {
  title: string
  lines: string[]
}

const store = useWorkspaceStore()
const session = useSession()
const route = useRoute()
const router = useRouter()

const draftQuery = ref('')
const bootstrapping = ref(false)
const syncingFromRoute = ref(false)
const currentRole = computed(() => session.activeRole.value || 'investor')

const roleLabelMap: Record<UserRole, string> = {
  investor: '投资者',
  management: '管理层',
  regulator: '监管风控',
}

const defaultQuestions = [
  '这家公司当前最值得警惕的风险是什么？',
  '把这家公司和同子行业头部公司做一下对比。',
  '最新研报和真实财报有没有偏差？',
]

const roleLabel = computed(() => roleLabelMap[currentRole.value] || '投资者')
const companies = computed(() => store.companies)
const periodOptions = computed(() => store.availablePeriods)
const latestPayload = computed(() => store.latestPayload || {})
const companyWorkspace = computed(() => store.companyWorkspace || null)
const scoreSummary = computed(() => companyWorkspace.value?.score_summary || null)
const watchboard = computed(() => companyWorkspace.value?.watchboard || null)
const companyName = computed(() => companyWorkspace.value?.company_name || store.selectedCompany || '请选择公司')
const reportPeriod = computed(() => companyWorkspace.value?.report_period || store.selectedPeriod || '')

const resultSections = computed<ResultSection[]>(() => {
  const sections = latestPayload.value?.answer_sections
  if (Array.isArray(sections) && sections.length) {
    return sections
      .slice(0, 3)
      .map((item: any) => ({
        title: String(item?.title || '当前判断'),
        lines: Array.isArray(item?.lines)
          ? item.lines.map((line: unknown) => String(line || '').trim()).filter(Boolean)
          : [],
      }))
      .filter((item) => item.lines.length)
  }

  const raw = String(latestPayload.value?.answer_markdown || '').trim()
  if (!raw) return [{ title: '当前判断', lines: ['先围绕一个问题发起判断。'] }]

  const lines = raw
    .replace(/[*#>`-]/g, ' ')
    .split(/\r?\n+/)
    .map((line) => line.trim())
    .filter(Boolean)
  return [{ title: '当前判断', lines: lines.slice(0, 3) }]
})

const summaryLine = computed(() => {
  return resultSections.value[0]?.lines[0] || '先围绕一个问题发起判断。'
})

const statCards = computed(() => [
  {
    label: '经营总分',
    value: scoreSummary.value
      ? `${scoreSummary.value.total_score ?? '--'}${scoreSummary.value.grade ? ` / ${scoreSummary.value.grade}` : ''}`
      : '--',
  },
  {
    label: '风险标签',
    value: `${scoreSummary.value?.risk_count ?? 0}`,
  },
  {
    label: '机会标签',
    value: `${scoreSummary.value?.opportunity_count ?? 0}`,
  },
])

const riskLines = computed(() => {
  const items = companyWorkspace.value?.top_risks?.slice(0, 3) || []
  return items.length ? items : ['当前没有显著新增风险标签。']
})

const opportunityLines = computed(() => {
  const items = companyWorkspace.value?.top_opportunities?.slice(0, 3) || []
  return items.length ? items : ['当前没有显著机会标签。']
})

const quickQuestions = computed(() => {
  const items = store.followUps.length
    ? store.followUps
    : store.overview?.role_profile?.starter_queries || defaultQuestions
  return items.slice(0, 3)
})

const actionTitle = computed(() => {
  const firstAction = latestPayload.value?.action_cards?.[0]
  if (firstAction?.title) return String(firstAction.title)
  if (watchboard.value?.tracked) return '这轮判断已经接到持续跟踪'
  return '把这一轮判断接到后续动作'
})

const actionBody = computed(() => {
  const firstAction = latestPayload.value?.action_cards?.[0]
  if (firstAction?.reason) return String(firstAction.reason)
  if (firstAction?.action) return String(firstAction.action)
  if (watchboard.value?.tracked) {
    return `当前已纳入持续跟踪，新增预警 ${Number(watchboard.value.new_alerts || 0)} 条，相关任务 ${Number(watchboard.value.task_count || 0)} 项。`
  }
  return '当前未加入持续跟踪，适合把需要继续盯防的主体放进监测板。'
})

const continuationCards = computed(() => [
  {
    label: '把这一轮判断接到证据和模块',
    detail: companyWorkspace.value?.recent_runs?.items?.[0]?.query || '继续回到原文、图谱和经营诊断。',
    to: '/graph',
  },
  {
    label: '继续往下看',
    detail: '把这轮判断带到图谱检索、观点核验或经营诊断。',
    to: '/verify',
  },
])

const stageItems = computed(() => {
  const flow = store.agentFlow
  if (!flow.length) {
    return ['明确问题', '拉取关键数据', '回到原文', '落到动作']
  }
  return flow.slice(0, 4).map((item: any) => String(item?.title || item?.agent_label || '当前步骤'))
})

async function bootstrapPage() {
  if (bootstrapping.value) return
  bootstrapping.value = true
  try {
    if (!store.messages.length) {
      store.resetConversation('协同分析', '围绕问题直接判断')
    }
    await store.loadCompanies()

    const workflow = resolveWorkflowContext(route.query)
    const roleQuery = readQuery(route.query.role)
    if (roleQuery === 'investor' || roleQuery === 'management' || roleQuery === 'regulator') {
      session.setActiveRole(roleQuery)
    }

    syncingFromRoute.value = true
    if (workflow.company) {
      store.selectedCompany = workflow.company
    } else if (!store.selectedCompany && store.companies.length) {
      store.selectedCompany = store.companies[0]
    }
    if (workflow.period) {
      store.selectedPeriod = workflow.period
    }
    syncingFromRoute.value = false

    await store.loadOverview(currentRole.value)
    if (!store.selectedPeriod) {
      store.selectedPeriod = store.preferredPeriod || store.availablePeriods[0] || ''
    }
    if (store.selectedCompany) {
      persistWorkflowContext({ company: store.selectedCompany, period: store.selectedPeriod })
      await store.loadCompanyWorkspace(currentRole.value)
    }
  } finally {
    bootstrapping.value = false
  }
}

function readQuery(value: unknown): string {
  const normalized = Array.isArray(value) ? value[0] : value
  return typeof normalized === 'string' ? normalized.trim() : ''
}

async function submitQuery(query?: string) {
  const content = (query || draftQuery.value).trim()
  if (!content || !store.selectedCompany) return
  await store.sendQuery(currentRole.value, content)
  draftQuery.value = ''
}

async function toggleWatchboard() {
  if (!store.selectedCompany) return
  if (watchboard.value?.tracked) {
    await store.removeCurrentCompanyFromWatchboard(currentRole.value)
  } else {
    await store.addCurrentCompanyToWatchboard(currentRole.value)
  }
}

function openContinuation(path: string) {
  router.push({
    path,
    query: {
      company: store.selectedCompany,
      period: store.selectedPeriod,
      role: currentRole.value,
    },
  })
}

watch(
  currentRole,
  async (next, previous) => {
    if (next === previous) return
    store.resetConversation('协同分析', '围绕问题直接判断')
    await bootstrapPage()
  },
)

watch(
  () => [route.query.company, route.query.period, route.query.role],
  async () => {
    await bootstrapPage()
  },
)

watch(
  () => [store.selectedCompany, store.selectedPeriod] as const,
  async ([company, period], [previousCompany, previousPeriod]) => {
    if (syncingFromRoute.value) return
    if (!company || (company === previousCompany && period === previousPeriod)) return
    persistWorkflowContext({ company, period })
    if (period && period !== previousPeriod) {
      await store.loadOverview(currentRole.value)
    }
    await store.loadCompanyWorkspace(currentRole.value)
  },
)

onMounted(async () => {
  await bootstrapPage()
})
</script>

<template>
  <AppShell title="协同分析" compact>
    <div class="workspace-shell">
      <header class="workspace-topbar">
        <div class="workspace-topbar-fields">
          <label class="field">
            <span>公司</span>
            <select v-model="store.selectedCompany">
              <option v-for="company in companies" :key="company" :value="company">{{ company }}</option>
            </select>
          </label>
          <label class="field">
            <span>报期</span>
            <select v-model="store.selectedPeriod">
              <option v-for="period in periodOptions" :key="period" :value="period">{{ period }}</option>
            </select>
          </label>
          <span class="role-chip">{{ roleLabel }}</span>
        </div>
        <ol class="stage-strip">
          <li v-for="(item, index) in stageItems" :key="item">
            <span>{{ String(index + 1).padStart(2, '0') }}</span>
            <strong>{{ item }}</strong>
          </li>
        </ol>
      </header>

      <div class="workspace-grid">
        <section class="workspace-main">
          <div class="hero-block">
            <p class="eyebrow">先看当前状态</p>
            <h1>{{ companyName }}</h1>
            <p class="summary">{{ summaryLine }}</p>
            <div class="meta-row">
              <span>报期 {{ reportPeriod || '未选择' }}</span>
            </div>
          </div>

          <div class="stat-row">
            <article v-for="item in statCards" :key="item.label" class="stat-panel">
              <span>{{ item.label }}</span>
              <strong>{{ item.value }}</strong>
            </article>
          </div>

          <div class="signal-grid">
            <article class="signal-panel">
              <span>当前风险</span>
              <ul>
                <li v-for="item in riskLines" :key="item">{{ item }}</li>
              </ul>
            </article>
            <article class="signal-panel">
              <span>可继续放大</span>
              <ul>
                <li v-for="item in opportunityLines" :key="item">{{ item }}</li>
              </ul>
            </article>
          </div>

          <article v-for="section in resultSections" :key="section.title" class="result-panel">
            <span>{{ section.title }}</span>
            <ul>
              <li v-for="line in section.lines" :key="line">{{ line }}</li>
            </ul>
          </article>
        </section>

        <aside class="workspace-side">
          <section class="side-panel">
            <span>直接发问</span>
            <h2>先从这三个问题开始</h2>
            <button
              v-for="question in quickQuestions"
              :key="question"
              type="button"
              class="question-button"
              @click="submitQuery(question)"
            >
              {{ question }}
            </button>
          </section>

          <section class="side-panel action-panel">
            <span>持续跟踪</span>
            <h2>{{ actionTitle }}</h2>
            <p>{{ actionBody }}</p>
            <button type="button" class="watch-button" @click="toggleWatchboard">
              {{ watchboard?.tracked ? '移出持续跟踪' : '加入持续跟踪' }}
            </button>
          </section>

          <section class="side-panel">
            <span>继续往下看</span>
            <button
              v-for="item in continuationCards"
              :key="item.label"
              type="button"
              class="continuation-card"
              @click="openContinuation(item.to)"
            >
              <strong>{{ item.label }}</strong>
              <p>{{ item.detail }}</p>
            </button>
          </section>
        </aside>
      </div>

      <footer class="composer">
        <textarea
          v-model="draftQuery"
          rows="2"
          placeholder="输入你要围绕这家公司继续判断的问题"
          @keydown.enter.exact.prevent="submitQuery()"
        />
        <button type="button" @click="submitQuery()">开始判断</button>
      </footer>
    </div>
  </AppShell>
</template>

<style scoped>
.workspace-shell {
  min-height: 100vh;
  padding: 24px 28px 28px;
  background: #0c1116;
  color: #eef2f7;
}

.workspace-topbar,
.workspace-main,
.workspace-side > .side-panel,
.composer {
  border: 1px solid rgba(255, 255, 255, 0.07);
  background: rgba(16, 19, 25, 0.92);
}

.workspace-topbar {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 28px;
  padding: 20px 24px;
  border-radius: 26px;
}

.workspace-topbar-fields {
  display: flex;
  align-items: center;
  gap: 16px;
}

.field {
  display: grid;
  gap: 6px;
  min-width: 200px;
}

.field span,
.eyebrow,
.result-panel span,
.side-panel > span,
.stat-panel span,
.signal-panel > span {
  color: rgba(168, 179, 194, 0.76);
  font-size: 13px;
}

.field select {
  height: 68px;
  padding: 0 20px;
  border-radius: 22px;
  border: 1px solid rgba(255, 255, 255, 0.07);
  background: rgba(18, 22, 29, 0.96);
  color: #f8fafc;
  font-size: 18px;
}

.role-chip {
  margin-top: 27px;
  display: inline-flex;
  align-items: center;
  height: 48px;
  padding: 0 20px;
  border-radius: 999px;
  background: rgba(33, 84, 60, 0.72);
  color: #d4ffe9;
  font-weight: 600;
}

.stage-strip {
  display: flex;
  gap: 14px;
  list-style: none;
  padding: 0;
  margin: 0;
}

.stage-strip li {
  display: grid;
  gap: 6px;
  min-width: 132px;
  padding: 14px 18px;
  border-radius: 20px;
  border: 1px solid rgba(120, 255, 196, 0.12);
  background: rgba(16, 24, 20, 0.72);
}

.stage-strip li span {
  color: #7cf0bd;
  font-size: 12px;
}

.stage-strip li strong {
  font-size: 15px;
}

.workspace-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 360px;
  gap: 24px;
  margin-top: 24px;
}

.workspace-main {
  display: grid;
  gap: 22px;
  padding: 28px;
  border-radius: 30px;
}

.hero-block h1 {
  margin: 10px 0 0;
  font-size: 62px;
  line-height: 0.96;
}

.summary {
  margin: 16px 0 0;
  max-width: 880px;
  font-size: 28px;
  line-height: 1.18;
}

.meta-row {
  margin-top: 18px;
  display: flex;
  gap: 12px;
}

.meta-row span {
  padding: 10px 14px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.05);
  color: #eef2f7;
}

.stat-row,
.signal-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 18px;
}

.signal-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.stat-panel,
.signal-panel,
.result-panel {
  padding: 24px 26px;
  border-radius: 26px;
  border: 1px solid rgba(255, 255, 255, 0.07);
  background: rgba(17, 20, 27, 0.96);
}

.stat-panel strong {
  margin-top: 12px;
  display: block;
  font-size: 30px;
}

.signal-panel ul,
.result-panel ul {
  margin: 16px 0 0;
  padding-left: 22px;
  display: grid;
  gap: 12px;
  font-size: 18px;
  line-height: 1.5;
}

.workspace-side {
  display: grid;
  gap: 20px;
  align-content: start;
}

.side-panel {
  display: grid;
  gap: 14px;
  padding: 24px;
  border-radius: 26px;
}

.side-panel h2 {
  margin: 0;
  font-size: 28px;
  line-height: 1.15;
}

.question-button,
.continuation-card,
.watch-button {
  width: 100%;
  text-align: left;
  border: 1px solid rgba(255, 255, 255, 0.07);
  background: rgba(17, 20, 27, 0.95);
  color: #eef2f7;
  border-radius: 22px;
}

.question-button {
  padding: 18px 20px;
  font-size: 20px;
}

.action-panel p,
.continuation-card p {
  margin: 0;
  color: rgba(216, 224, 235, 0.82);
  line-height: 1.6;
}

.watch-button {
  padding: 18px 20px;
  text-align: center;
  font-size: 24px;
  background: rgba(42, 96, 69, 0.88);
}

.continuation-card {
  display: grid;
  gap: 10px;
  padding: 18px 20px;
}

.continuation-card strong {
  font-size: 20px;
}

.composer {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 180px;
  gap: 18px;
  margin-top: 24px;
  padding: 18px;
  border-radius: 28px;
}

.composer textarea {
  width: 100%;
  min-height: 110px;
  resize: none;
  border: 0;
  outline: none;
  border-radius: 20px;
  background: rgba(17, 20, 27, 0.96);
  color: #eef2f7;
  padding: 18px 20px;
  font-size: 22px;
  line-height: 1.5;
}

.composer button {
  border: 0;
  border-radius: 22px;
  background: rgba(42, 96, 69, 0.92);
  color: #f2fff8;
  font-size: 32px;
  font-weight: 700;
}

@media (max-width: 1400px) {
  .workspace-grid {
    grid-template-columns: 1fr;
  }

  .workspace-side {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
</style>
