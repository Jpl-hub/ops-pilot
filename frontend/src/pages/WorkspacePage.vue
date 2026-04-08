<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import AppShell from '@/components/AppShell.vue'
import type { UserRole } from '@/lib/api'
import { useSession } from '@/lib/session'
import { persistWorkflowContext, resolveWorkflowContext } from '@/lib/workflowContext'
import { useWorkspaceStore } from '@/stores/workspace'
import type { WorkspaceMessage } from '@/stores/workspace'

type ResultSection = {
  title: string
  lines: string[]
}

const store = useWorkspaceStore()
const session = useSession()
const route = useRoute()

const bootstrapping = ref(false)
const syncingFromRoute = ref(false)
const draftQuery = ref('')

const defaultQuestions = [
  '这家公司当前最值得警惕的风险是什么？',
  '把这家公司和同子行业头部公司做一下对比。',
  '最新研报和真实财报有没有偏差？',
]

const roleLabelMap: Record<UserRole, string> = {
  investor: '投资者',
  management: '管理层',
  regulator: '监管风控',
}

const currentRole = computed<UserRole>(() => (session.activeRole.value || 'investor') as UserRole)
const roleLabel = computed(() => roleLabelMap[currentRole.value] || '投资者')
const companies = computed(() => store.companies)
const periodOptions = computed(() => store.availablePeriods)
const latestPayload = computed(() => store.latestPayload || {})
const companyWorkspace = computed(() => store.companyWorkspace || null)
const companyName = computed(() => companyWorkspace.value?.company_name || store.selectedCompany || '请选择公司')
const reportPeriod = computed(() => companyWorkspace.value?.report_period || store.selectedPeriod || '')
const watchboard = computed(() => companyWorkspace.value?.watchboard || null)

const quickQuestions = computed(() => {
  const items = store.followUps.length
    ? store.followUps
    : store.overview?.role_profile?.starter_queries || defaultQuestions
  return items.slice(0, 3)
})

const stageItems = computed(() => {
  const flow = store.agentFlow || []
  if (!flow.length) return ['明确问题', '拉取关键数据', '回到原文', '落到动作']
  return flow.slice(0, 4).map((item: any, index: number) => ({
    title: String(item?.title || item?.agent_label || `步骤 ${index + 1}`),
    done: item?.status === 'done' || item?.state === 'done' || item?.completed === true,
  }))
})

const latestUserMessage = computed(() => {
  return [...store.messages].reverse().find((message: WorkspaceMessage) => message.role === 'user' && message.kind === 'query') || null
})

const welcomeMessage = computed(() => {
  return store.messages.find((message: WorkspaceMessage) => message.role === 'assistant' && message.kind === 'welcome') || null
})

const resultSections = computed<ResultSection[]>(() => {
  const sections = latestPayload.value?.answer_sections
  if (Array.isArray(sections) && sections.length) {
    return sections
      .map((item: any) => ({
        title: String(item?.title || '当前判断'),
        lines: Array.isArray(item?.lines)
          ? item.lines.map((line: unknown) => String(line || '').trim()).filter(Boolean)
          : [],
      }))
      .filter((item) => item.lines.length)
      .slice(0, 3)
  }

  const raw = String(latestPayload.value?.answer_markdown || '').trim()
  if (!raw) return []
  const cleaned = raw
    .replace(/[`*_>#-]/g, ' ')
    .split(/\r?\n+/)
    .map((line) => line.trim())
    .filter(Boolean)
    .slice(0, 6)

  if (!cleaned.length) return []
  return [{ title: '当前判断', lines: cleaned }]
})

const actionCard = computed(() => latestPayload.value?.action_cards?.[0] || null)
const evidenceLinks = computed(() => {
  const groups = store.evidenceGroups || []
  const links = groups.flatMap((group: any) => group?.items || group?.links || [])
  return links.slice(0, 3)
})

const continuationLinks = computed(() => [
  {
    title: watchboard.value?.tracked ? '继续跟踪' : '把这一轮判断接到后续动作',
    detail: watchboard.value?.tracked
      ? `当前已纳入持续跟踪，新增预警 ${Number(watchboard.value.new_alerts || 0)} 条。`
      : '把需要继续盯防的主体放进监测板。',
  },
  {
    title: '继续往下看',
    detail: latestUserMessage.value?.text || '继续回到图谱、核验或经营诊断。',
  },
])

async function bootstrapPage() {
  if (bootstrapping.value) return
  bootstrapping.value = true
  try {
    if (!store.messages.length) {
      store.resetConversation('多智能体协同研判', '围绕问题直接判断')
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
  if (!content || !store.selectedCompany || store.loadingTurn) return
  await store.sendQuery(currentRole.value, content)
  draftQuery.value = ''
}

watch(
  currentRole,
  async (next, previous) => {
    if (next === previous) return
    store.resetConversation('多智能体协同研判', '围绕问题直接判断')
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
      <header class="workspace-header">
        <div class="workspace-header-main">
          <div class="workspace-title">
            <h1>多智能体协同研判</h1>
            <p>{{ roleLabel }} · {{ companyName }}<span v-if="reportPeriod"> · {{ reportPeriod }}</span></p>
          </div>
          <ol class="workflow-strip">
            <li v-for="(item, index) in stageItems" :key="`${index}-${typeof item === 'string' ? item : item.title}`" :class="{ done: typeof item !== 'string' && item.done }">
              <span>{{ String(index + 1).padStart(2, '0') }}</span>
              <strong>{{ typeof item === 'string' ? item : item.title }}</strong>
            </li>
          </ol>
        </div>

        <div class="workspace-controls">
          <label class="control-field">
            <span>公司</span>
            <select v-model="store.selectedCompany">
              <option v-for="company in companies" :key="company" :value="company">{{ company }}</option>
            </select>
          </label>
          <label class="control-field">
            <span>报期</span>
            <select v-model="store.selectedPeriod">
              <option v-for="period in periodOptions" :key="period" :value="period">{{ period }}</option>
            </select>
          </label>
        </div>
      </header>

      <section class="thread-shell">
        <article v-if="welcomeMessage" class="thread-row assistant-row">
          <div class="thread-avatar">研</div>
          <div class="thread-bubble assistant-bubble intro-bubble">
            <p class="intro-title">{{ welcomeMessage.title }}</p>
            <p v-for="line in welcomeMessage.lines" :key="line">{{ line }}</p>
          </div>
        </article>

        <article v-if="latestUserMessage" class="thread-row user-row">
          <div class="thread-bubble user-bubble">
            {{ latestUserMessage.text }}
          </div>
          <div class="thread-avatar user-avatar">问</div>
        </article>

        <article v-if="store.agentFlow.length" class="thread-row assistant-row">
          <div class="thread-avatar">流</div>
          <div class="thread-bubble workflow-bubble">
            <p class="panel-label">当前执行</p>
            <ul class="workflow-list">
              <li v-for="item in store.agentFlow.slice(0, 4)" :key="item.id || item.title || item.agent_label">
                <strong>{{ item.title || item.agent_label || '当前步骤' }}</strong>
                <span>{{ item.detail || item.summary || '已纳入本轮判断。' }}</span>
              </li>
            </ul>
          </div>
        </article>

        <article class="thread-row assistant-row">
          <div class="thread-avatar">答</div>
          <div class="thread-bubble result-bubble">
            <template v-if="resultSections.length">
              <section v-for="section in resultSections" :key="section.title" class="result-section">
                <h2>{{ section.title }}</h2>
                <ul>
                  <li v-for="line in section.lines" :key="line">{{ line }}</li>
                </ul>
              </section>
            </template>
            <section v-else class="result-section">
              <h2>当前判断</h2>
              <ul>
                <li>先围绕一个问题发起判断。</li>
              </ul>
            </section>

            <section v-if="actionCard" class="action-section">
              <span>这轮动作</span>
              <strong>{{ actionCard.title || '把这轮判断接到后续动作' }}</strong>
              <p>{{ actionCard.reason || actionCard.action || '当前还没有额外动作建议。' }}</p>
            </section>
          </div>
        </article>

        <section class="workspace-sidecar">
          <article class="sidecar-panel">
            <span>直接发问</span>
            <strong>先从这三个问题开始</strong>
            <button
              v-for="question in quickQuestions"
              :key="question"
              type="button"
              class="quick-question"
              @click="submitQuery(question)"
            >
              {{ question }}
            </button>
          </article>

          <article class="sidecar-panel">
            <span>持续跟踪</span>
            <strong>{{ continuationLinks[0].title }}</strong>
            <p>{{ continuationLinks[0].detail }}</p>
          </article>

          <article class="sidecar-panel">
            <span>继续往下看</span>
            <strong>{{ continuationLinks[1].title }}</strong>
            <p>{{ continuationLinks[1].detail }}</p>
            <ul v-if="evidenceLinks.length" class="evidence-list">
              <li v-for="(item, index) in evidenceLinks" :key="item.id || item.label || index">
                {{ item.label || item.title || item.text || '回到原文继续核对' }}
              </li>
            </ul>
          </article>
        </section>
      </section>

      <footer class="composer-shell">
        <div class="prompt-row">
          <button
            v-for="question in quickQuestions"
            :key="`prompt-${question}`"
            type="button"
            class="prompt-chip"
            @click="submitQuery(question)"
          >
            {{ question }}
          </button>
        </div>
        <div class="composer-row">
          <textarea
            v-model="draftQuery"
            rows="2"
            class="composer-input"
            :disabled="store.loadingTurn"
            placeholder="输入你要围绕这家公司继续判断的问题。"
            @keydown.enter.exact.prevent="submitQuery()"
          />
          <button type="button" class="composer-submit" :disabled="store.loadingTurn || !draftQuery.trim()" @click="submitQuery()">
            {{ store.loadingTurn ? '判断中' : '开始判断' }}
          </button>
        </div>
      </footer>
    </div>
  </AppShell>
</template>

<style scoped>
.workspace-shell {
  display: grid;
  gap: 18px;
  min-height: calc(100vh - 72px);
}

.workspace-header {
  display: grid;
  gap: 16px;
  padding: 8px 4px 0;
}

.workspace-header-main {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 20px;
  align-items: end;
}

.workspace-title {
  display: grid;
  gap: 6px;
}

.workspace-title h1 {
  margin: 0;
  color: #f8fafc;
  font-size: 22px;
  font-weight: 700;
  letter-spacing: 0.01em;
}

.workspace-title p {
  margin: 0;
  color: rgba(160, 174, 192, 0.76);
  font-size: 12px;
}

.workspace-controls {
  display: flex;
  justify-content: flex-end;
  gap: 14px;
}

.control-field {
  display: grid;
  gap: 8px;
  min-width: 220px;
}

.control-field span {
  color: rgba(160, 174, 192, 0.72);
  font-size: 11px;
}

.control-field select {
  width: 100%;
  height: 68px;
  padding: 0 18px;
  border-radius: 24px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(13, 18, 24, 0.94);
  color: #f8fafc;
  font-size: 17px;
}

.workflow-strip {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.workflow-strip li {
  display: grid;
  gap: 6px;
  min-width: 116px;
  padding: 14px 16px;
  border-radius: 22px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(14, 18, 24, 0.92);
}

.workflow-strip li.done {
  border-color: rgba(84, 240, 186, 0.24);
  background: rgba(13, 34, 27, 0.88);
}

.workflow-strip span {
  color: rgba(84, 240, 186, 0.72);
  font-size: 11px;
  font-family: 'JetBrains Mono', monospace;
}

.workflow-strip strong {
  color: #eef2f7;
  font-size: 14px;
  font-weight: 600;
}

.thread-shell {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: 28px;
  align-items: start;
}

.thread-row {
  display: flex;
  gap: 16px;
  align-items: flex-start;
}

.assistant-row {
  justify-content: flex-start;
}

.user-row {
  justify-content: flex-end;
}

.thread-avatar {
  width: 44px;
  height: 44px;
  display: grid;
  place-items: center;
  border-radius: 14px;
  border: 1px solid rgba(84, 240, 186, 0.22);
  background: rgba(13, 34, 27, 0.82);
  color: #79f7c8;
  font-size: 14px;
  font-weight: 700;
  flex-shrink: 0;
}

.user-avatar {
  border-color: rgba(76, 132, 255, 0.2);
  background: rgba(18, 32, 62, 0.86);
  color: #9fb7ff;
}

.thread-bubble {
  max-width: 940px;
  border-radius: 26px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(13, 17, 22, 0.94);
}

.intro-bubble,
.workflow-bubble,
.result-bubble {
  padding: 24px 26px;
}

.intro-title,
.panel-label {
  margin: 0 0 10px;
  color: rgba(84, 240, 186, 0.82);
  font-size: 12px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  font-family: 'JetBrains Mono', monospace;
}

.intro-bubble p:last-child {
  margin-bottom: 0;
}

.intro-bubble p {
  margin: 0 0 8px;
  color: #e7edf5;
  font-size: 18px;
  line-height: 1.65;
}

.user-bubble {
  max-width: 820px;
  padding: 22px 28px;
  background: rgba(17, 30, 75, 0.92);
  border-color: rgba(76, 132, 255, 0.18);
  color: #f8fbff;
  font-size: 17px;
  line-height: 1.6;
}

.workflow-list,
.result-section ul,
.evidence-list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.workflow-list {
  display: grid;
  gap: 16px;
}

.workflow-list li {
  display: grid;
  gap: 6px;
}

.workflow-list strong,
.result-section h2,
.action-section strong,
.sidecar-panel strong {
  color: #f4f7fb;
}

.workflow-list strong {
  font-size: 16px;
}

.workflow-list span,
.result-section li,
.action-section p,
.sidecar-panel p,
.evidence-list li {
  color: rgba(220, 228, 239, 0.82);
  font-size: 15px;
  line-height: 1.7;
}

.result-bubble {
  display: grid;
  gap: 22px;
}

.result-section {
  display: grid;
  gap: 10px;
}

.result-section h2,
.action-section strong {
  margin: 0;
  font-size: 16px;
}

.result-section ul {
  display: grid;
  gap: 8px;
}

.action-section {
  display: grid;
  gap: 8px;
  padding-top: 6px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

.action-section span,
.sidecar-panel span {
  color: rgba(160, 174, 192, 0.7);
  font-size: 11px;
  letter-spacing: 0.08em;
}

.workspace-sidecar {
  display: grid;
  gap: 18px;
}

.sidecar-panel {
  display: grid;
  gap: 14px;
  padding: 22px 22px 24px;
  border-radius: 24px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(13, 17, 22, 0.94);
}

.quick-question,
.prompt-chip {
  width: 100%;
  min-height: 54px;
  padding: 0 18px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.02);
  color: #edf2f8;
  font-size: 15px;
  text-align: center;
  transition: border-color 0.18s ease, background 0.18s ease;
}

.quick-question:hover,
.prompt-chip:hover {
  border-color: rgba(84, 240, 186, 0.24);
  background: rgba(13, 34, 27, 0.3);
}

.evidence-list {
  display: grid;
  gap: 8px;
}

.composer-shell {
  display: grid;
  gap: 14px;
  margin-top: auto;
  padding-top: 10px;
}

.prompt-row {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.prompt-chip {
  width: auto;
  min-height: 44px;
  padding: 0 18px;
  font-size: 14px;
}

.composer-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 190px;
  gap: 18px;
  align-items: stretch;
  padding: 18px;
  border-radius: 28px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(13, 17, 22, 0.96);
}

.composer-input {
  width: 100%;
  min-height: 96px;
  resize: none;
  border: 0;
  outline: none;
  background: transparent;
  color: #f8fafc;
  font-size: 18px;
  line-height: 1.7;
}

.composer-input::placeholder {
  color: rgba(160, 174, 192, 0.66);
}

.composer-submit {
  width: 100%;
  border-radius: 24px;
  border: 1px solid rgba(84, 240, 186, 0.16);
  background: rgba(17, 63, 44, 0.96);
  color: #f7fff9;
  font-size: 18px;
  font-weight: 700;
}

.composer-submit:disabled {
  opacity: 0.58;
}

@media (max-width: 1400px) {
  .thread-shell {
    grid-template-columns: minmax(0, 1fr);
  }

  .workspace-sidecar {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 1100px) {
  .workspace-header-main {
    grid-template-columns: minmax(0, 1fr);
  }

  .workspace-controls {
    justify-content: flex-start;
    flex-wrap: wrap;
  }

  .workflow-strip {
    flex-wrap: wrap;
  }

  .workspace-sidecar {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .composer-row {
    grid-template-columns: 1fr;
  }

  .control-field {
    min-width: 100%;
  }

  .thread-bubble {
    max-width: 100%;
  }
}
</style>
