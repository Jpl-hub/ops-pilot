<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

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
const riskLabels = computed(() => companyWorkspace.value?.top_risks?.slice(0, 3) || [])
const opportunityLabels = computed(() => companyWorkspace.value?.top_opportunities?.slice(0, 2) || [])
const watchboard = computed(() => companyWorkspace.value?.watchboard || null)

const quickQuestions = computed(() => {
  const items = store.followUps.length
    ? store.followUps
    : store.overview?.role_profile?.starter_queries || defaultQuestions
  return items.slice(0, 3)
})

const stageItems = computed(() => {
  const flow = store.agentFlow || []
  const fallback = ['明确问题', '拉取关键数据', '回到原文', '落到动作']
  if (!flow.length) return fallback.map((title, index) => ({ title, done: index === 0 }))
  return flow.slice(0, 4).map((item: any, index: number) => ({
    title: String(item?.title || item?.agent_label || fallback[index] || `步骤 ${index + 1}`),
    done: item?.status === 'done' || item?.state === 'done' || item?.completed === true,
  }))
})

const welcomeMessage = computed(() => {
  return store.messages.find((message: WorkspaceMessage) => message.role === 'assistant' && message.kind === 'welcome') || null
})

const latestUserMessage = computed(() => {
  return [...store.messages].reverse().find((message: WorkspaceMessage) => message.role === 'user' && message.kind === 'query') || null
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

const summaryLine = computed(() => {
  return (
    resultSections.value[0]?.lines[0]
    || welcomeMessage.value?.lines?.[0]
    || '围绕一个问题开始判断。'
  )
})

const evidenceLinks = computed(() => {
  const groups = store.evidenceGroups || []
  const links = groups.flatMap((group: any) => group?.items || group?.links || [])
  return links.slice(0, 3)
})

const continuationCard = computed(() => {
  if (watchboard.value?.tracked) {
    return {
      title: '把这一轮判断接到后续动作',
      detail: `当前已纳入持续跟踪，新增预警 ${Number(watchboard.value.new_alerts || 0)} 条。`,
    }
  }
  return {
    title: '把这一轮判断接到后续动作',
    detail: '当前未加入持续跟踪，适合把需要连续盯防的主体放进监测板。',
  }
})

const nextCard = computed(() => ({
  title: '把这一轮判断接到证据和模块',
  detail: latestUserMessage.value?.text || '继续回到图谱、核验或经营诊断。',
}))

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
  <AppShell title="">
    <div class="workspace-console">
      <section class="workspace-topbar">
        <div class="workspace-headline">
          <h1>多智能体协同研判</h1>
          <div class="headline-role-strip">
            <span>围绕企业经营、风险、证据和后续动作直接判断</span>
          </div>
        </div>
        <div class="workspace-topbar-right">
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
          <span class="role-chip">{{ roleLabel }}</span>
        </div>
      </section>

      <ol class="workflow-strip">
        <li v-for="(item, index) in stageItems" :key="`${index}-${item.title}`" :class="{ done: item.done }">
          <span>{{ String(index + 1).padStart(2, '0') }}</span>
          <strong>{{ item.title }}</strong>
        </li>
      </ol>

      <section class="workspace-frame">
        <div class="workspace-stream">
          <article class="message-row">
            <div class="message-mark assistant-mark">智</div>
            <div class="message-card assistant-card intro-card">
              <p>{{ welcomeMessage?.lines?.[0] || '围绕企业经营、风险、证据和后续动作直接判断。' }}</p>
            </div>
          </article>

          <article v-if="latestUserMessage" class="message-row user-row">
            <div class="message-card user-card">
              {{ latestUserMessage.text }}
            </div>
          </article>

          <article v-if="stageItems.length" class="message-row">
            <div class="message-mark assistant-mark">析</div>
            <div class="reasoning-card">
              <div class="reasoning-head">
                <strong>这一轮判断怎么往下走</strong>
              </div>
              <div class="reasoning-grid">
                <div v-for="(item, index) in stageItems" :key="`${item.title}-${index}`" class="reasoning-item">
                  <span>{{ item.title }}</span>
                  <strong>{{ item.done ? '已完成' : '处理中' }}</strong>
                </div>
              </div>
            </div>
          </article>

          <article class="message-row">
            <div class="message-mark assistant-mark">答</div>
            <div class="message-card assistant-card result-card">
              <div class="result-head">
                <span class="message-kicker">先看当前状态</span>
                <h2>{{ companyName }}</h2>
                <p>{{ summaryLine }}</p>
                <div class="meta-row">
                  <span>{{ reportPeriod ? `报期 ${reportPeriod}` : '默认主周期' }}</span>
                  <span v-if="riskLabels.length">风险 {{ riskLabels.length }}</span>
                  <span v-if="opportunityLabels.length">机会 {{ opportunityLabels.length }}</span>
                </div>
              </div>

              <div class="result-grid">
                <section v-if="riskLabels.length" class="result-panel">
                  <span class="message-kicker">当前风险</span>
                  <ul class="result-list">
                    <li v-for="item in riskLabels" :key="item">{{ item }}</li>
                  </ul>
                </section>

                <section class="result-panel">
                  <span class="message-kicker">继续往下看</span>
                  <div class="result-stack">
                    <strong>{{ continuationCard.title }}</strong>
                    <p>{{ continuationCard.detail }}</p>
                  </div>
                </section>
              </div>

              <section v-if="resultSections.length" class="result-sections">
                <article v-for="section in resultSections" :key="section.title" class="result-section">
                  <span class="message-kicker">{{ section.title }}</span>
                  <ul class="result-list">
                    <li v-for="line in section.lines" :key="line">{{ line }}</li>
                  </ul>
                </article>
              </section>

              <div v-if="evidenceLinks.length" class="evidence-row">
                <RouterLink
                  v-for="(item, index) in evidenceLinks"
                  :key="item.id || item.label || index"
                  class="evidence-link"
                  :to="{ path: item.path, query: item.query || {} }"
                >
                  {{ item.label || item.title || '回到原文继续核对' }}
                </RouterLink>
              </div>
            </div>
          </article>
        </div>

        <aside class="workspace-sidecar">
          <article class="sidecar-card">
            <span class="message-kicker">直接发问</span>
            <strong>先从这三个问题开始</strong>
            <button
              v-for="question in quickQuestions"
              :key="question"
              type="button"
              class="sidecar-question"
              @click="submitQuery(question)"
            >
              {{ question }}
            </button>
          </article>

          <article class="sidecar-card">
            <span class="message-kicker">持续跟踪</span>
            <strong>{{ continuationCard.title }}</strong>
            <p>{{ continuationCard.detail }}</p>
          </article>

          <article class="sidecar-card">
            <span class="message-kicker">继续往下看</span>
            <strong>{{ nextCard.title }}</strong>
            <p>{{ nextCard.detail }}</p>
          </article>

          <div class="composer-dock">
            <textarea
              v-model="draftQuery"
              rows="3"
              class="composer-input"
              :disabled="store.loadingTurn"
              placeholder="输入你要围绕这家公司继续判断的问题。"
              @keydown.enter.exact.prevent="submitQuery()"
            />
            <button type="button" class="composer-submit" :disabled="store.loadingTurn || !draftQuery.trim()" @click="submitQuery()">
              {{ store.loadingTurn ? '判断中' : '开始判断' }}
            </button>
          </div>
        </aside>
      </section>
    </div>
  </AppShell>
</template>

<style scoped>
.workspace-console {
  display: grid;
  gap: 16px;
  width: 100%;
  max-width: 1380px;
  margin: 0 auto;
}

.workspace-topbar {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 18px;
  padding-bottom: 14px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.workspace-headline {
  display: grid;
  gap: 6px;
}

.workspace-headline h1 {
  margin: 0;
  color: #f8fafc;
  font-size: 22px;
  line-height: 1.1;
}

.headline-role-strip {
  color: rgba(120, 143, 172, 0.82);
  font-size: 12px;
  letter-spacing: 0.08em;
}

.workspace-topbar-right {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.control-field {
  display: grid;
  gap: 6px;
}

.control-field span,
.message-kicker,
.workflow-strip span {
  color: rgba(120, 143, 172, 0.78);
  font-size: 10px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.control-field select {
  min-width: 192px;
  height: 42px;
  padding: 0 14px;
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.03);
  color: #eef2f7;
  font-size: 15px;
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

.workflow-strip {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
  flex-wrap: wrap;
}

.workflow-strip li {
  display: grid;
  gap: 4px;
  min-width: 116px;
  padding: 9px 12px;
  border-radius: 18px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(14, 18, 24, 0.9);
}

.workflow-strip li.done {
  border-color: rgba(84, 240, 186, 0.22);
  background: rgba(13, 34, 27, 0.84);
}

.workflow-strip strong {
  color: #eef2f7;
  font-size: 13px;
  font-weight: 600;
}

.workspace-frame {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) 360px;
  gap: 22px;
  align-items: start;
}

.workspace-stream {
  display: grid;
  gap: 18px;
}

.message-row {
  display: flex;
  align-items: flex-start;
  gap: 14px;
}

.user-row {
  justify-content: flex-end;
}

.message-mark {
  width: 42px;
  height: 42px;
  border-radius: 14px;
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  font-size: 13px;
  font-weight: 700;
  color: #d9fff0;
}

.assistant-mark {
  border: 1px solid rgba(52, 211, 153, 0.22);
  background: rgba(18, 62, 45, 0.82);
}

.message-card,
.reasoning-card,
.sidecar-card,
.composer-dock {
  border-radius: 22px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(15, 16, 20, 0.96);
}

.message-card,
.reasoning-card,
.sidecar-card {
  padding: 18px 20px;
}

.assistant-card {
  flex: 1;
}

.intro-card p,
.result-head p,
.sidecar-card p,
.result-stack p,
.reasoning-item span {
  margin: 0;
  color: rgba(191, 207, 228, 0.82);
  line-height: 1.65;
}

.user-card {
  max-width: 72%;
  padding: 18px 22px;
  background: rgba(26, 43, 88, 0.92);
  border-color: rgba(96, 137, 255, 0.24);
  color: #f8fbff;
  font-size: 16px;
  line-height: 1.55;
}

.reasoning-card {
  flex: 1;
  display: grid;
  gap: 14px;
}

.reasoning-head strong,
.sidecar-card strong,
.result-stack strong {
  color: #f8fafc;
  font-size: 16px;
}

.reasoning-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.reasoning-item {
  display: grid;
  gap: 6px;
  padding: 14px;
  border-radius: 16px;
  border: 1px solid rgba(255, 255, 255, 0.05);
  background: rgba(255, 255, 255, 0.02);
}

.reasoning-item strong {
  color: #6de8bd;
  font-size: 12px;
}

.result-card {
  display: grid;
  gap: 18px;
}

.result-head {
  display: grid;
  gap: 8px;
}

.result-head h2 {
  margin: 0;
  color: #f8fafc;
  font-size: 44px;
  line-height: 0.96;
  letter-spacing: -0.05em;
}

.meta-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.meta-row span {
  min-height: 34px;
  padding: 0 12px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  background: rgba(255, 255, 255, 0.04);
  color: rgba(237, 242, 248, 0.9);
  font-size: 13px;
}

.result-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.result-panel,
.result-section {
  display: grid;
  gap: 10px;
  padding: 16px 18px;
  border-radius: 18px;
  border: 1px solid rgba(255, 255, 255, 0.05);
  background: rgba(255, 255, 255, 0.02);
}

.result-sections {
  display: grid;
  gap: 14px;
}

.result-list {
  margin: 0;
  padding-left: 18px;
  display: grid;
  gap: 8px;
  color: #edf3fb;
  line-height: 1.65;
}

.evidence-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.evidence-link {
  min-height: 38px;
  padding: 0 14px;
  border-radius: 999px;
  border: 1px solid rgba(132, 244, 202, 0.14);
  background: rgba(15, 44, 33, 0.82);
  color: #8ef6cf;
  display: inline-flex;
  align-items: center;
  text-decoration: none;
  font-size: 13px;
}

.workspace-sidecar {
  display: grid;
  gap: 16px;
  align-content: start;
}

.sidecar-card {
  display: grid;
  gap: 12px;
}

.sidecar-question {
  width: 100%;
  min-height: 50px;
  padding: 0 16px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.02);
  color: #edf2f8;
  font-size: 15px;
  text-align: center;
}

.composer-dock {
  display: grid;
  gap: 12px;
  padding: 14px;
}

.composer-input {
  width: 100%;
  min-height: 116px;
  resize: none;
  border: 0;
  outline: none;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.02);
  color: #f8fafc;
  font-size: 15px;
  line-height: 1.65;
  padding: 16px 18px;
}

.composer-input::placeholder {
  color: rgba(160, 174, 192, 0.66);
}

.composer-submit {
  width: 100%;
  min-height: 54px;
  border-radius: 18px;
  border: 1px solid rgba(84, 240, 186, 0.16);
  background: rgba(17, 63, 44, 0.96);
  color: #f7fff9;
  font-size: 18px;
  font-weight: 700;
}

.composer-submit:disabled {
  opacity: 0.58;
}

@media (max-width: 1280px) {
  .workspace-frame {
    grid-template-columns: 1fr 320px;
  }
}

@media (max-width: 1120px) {
  .workspace-topbar,
  .workspace-frame,
  .result-grid,
  .reasoning-grid {
    grid-template-columns: 1fr;
  }

  .workspace-topbar {
    display: grid;
    justify-content: stretch;
  }

  .workspace-topbar-right {
    justify-content: flex-start;
  }

  .user-card {
    max-width: 100%;
  }
}

@media (max-width: 760px) {
  .workspace-console {
    gap: 14px;
  }

  .workspace-headline h1,
  .result-head h2 {
    font-size: 30px;
  }

  .message-row {
    gap: 10px;
  }

  .message-mark {
    width: 36px;
    height: 36px;
    border-radius: 12px;
  }

  .control-field,
  .control-field select {
    min-width: 100%;
    width: 100%;
  }
}
</style>
