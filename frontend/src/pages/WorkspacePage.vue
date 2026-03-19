<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'

import AppShell from '@/components/AppShell.vue'
import ChartPanel from '@/components/ChartPanel.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingState from '@/components/LoadingState.vue'
import TagPill from '@/components/TagPill.vue'
import { useAsyncState } from '@/composables/useAsyncState'
import { get, post } from '@/lib/api'
import { buildEvidenceLink } from '@/lib/format'
import { useSession } from '@/lib/session'

type WorkspaceMessage =
  | { id: string; role: 'assistant'; kind: 'welcome'; title: string; lines: string[] }
  | { id: string; role: 'user'; kind: 'query'; text: string; company: string }
  | { id: string; role: 'assistant'; kind: 'result'; payload: any }

const session = useSession()
const companies = ref<string[]>([])
const selectedCompany = ref('TCL中环')
const query = ref('')
const messages = ref<WorkspaceMessage[]>([])
const threadRef = ref<HTMLElement | null>(null)
const workspaceState = useAsyncState<any>()

const roleCopy = computed(() => {
  const role = session.activeRole.value || 'investor'
  if (role === 'management') {
    return {
      label: '企业管理者',
      title: '围绕经营动作展开分析',
      copy: '先识别瓶颈，再拆经营链条，最后给出整改动作。',
      fallbackQueries: [
        '给我一份当前经营体检和整改优先级。',
        '现金、应收和库存哪个环节最拖后腿？',
        '当前最先要修复的经营问题是什么？',
      ],
    }
  }
  if (role === 'regulator') {
    return {
      label: '监管 / 风控角色',
      title: '围绕风险巡检展开分析',
      copy: '优先识别新增风险、事件信号和研报偏差。',
      fallbackQueries: [
        '当前主周期哪些公司风险抬升最快？',
        '这家公司有哪些需要重点跟踪的事件信号？',
        '这家公司和研报观点有明显偏差吗？',
      ],
    }
  }
  return {
    label: '投资者',
    title: '围绕收益质量展开分析',
    copy: '优先看结论、同业位置、研报分歧和证据。',
    fallbackQueries: [
      '这家公司当前最值得警惕的风险是什么？',
      '把这家公司和同业头部公司做一下对比。',
      '最新研报和真实财报有没有偏差？',
    ],
  }
})

const latestPayload = computed(() => {
  const latest = [...messages.value].reverse().find((item) => item.kind === 'result')
  return latest && latest.kind === 'result' ? latest.payload : null
})

const starterQueries = computed(() => {
  return latestPayload.value?.role_profile?.starter_queries || roleCopy.value.fallbackQueries
})

const followUps = computed(() => latestPayload.value?.follow_up_questions || [])
const agentFlow = computed(() => latestPayload.value?.agent_flow || [])
const controlPlane = computed(() => latestPayload.value?.control_plane || null)
const insightCards = computed(() => latestPayload.value?.insight_cards || [])
const evidenceGroups = computed(() => latestPayload.value?.evidence_groups || [])
const charts = computed(() => latestPayload.value?.charts || [])
const formulas = computed(() => latestPayload.value?.formula_cards || [])
const firstEvidenceLink = computed(() => {
  const group = evidenceGroups.value.find((item: any) => item.items?.length)
  if (!group) {
    return '/admin'
  }
  return buildEvidenceLink(group.items[0].chunk_id, group.title, group.anchor_terms)
})

function appendWelcomeMessage() {
  messages.value = [
    {
      id: 'welcome',
      role: 'assistant',
      kind: 'welcome',
      title: roleCopy.value.title,
      lines: [
        `${roleCopy.value.label}模式已就绪。`,
        roleCopy.value.copy,
        '先发一个具体问题，我会用总控调度、信号分析、证据审计、动作生成四个模块同步展开。',
      ],
    },
  ]
}

async function loadCompanies() {
  const risk = await get<any>('/industry/risk-scan')
  companies.value = risk.risk_board.map((item: any) => item.company_name)
}

async function runQuery(inputQuery?: string) {
  const actualQuery = (inputQuery || query.value).trim()
  if (!actualQuery) return
  messages.value.push({
    id: `user-${Date.now()}`,
    role: 'user',
    kind: 'query',
    text: actualQuery,
    company: selectedCompany.value,
  })
  query.value = ''
  await workspaceState.execute(() =>
    post('/chat/turn', {
      query: actualQuery,
      company_name: selectedCompany.value,
      user_role: session.activeRole.value || 'investor',
    }),
  )
  if (workspaceState.data.value) {
    messages.value.push({
      id: `assistant-${Date.now()}`,
      role: 'assistant',
      kind: 'result',
      payload: workspaceState.data.value,
    })
    await nextTick()
    threadRef.value?.scrollTo({ top: threadRef.value.scrollHeight, behavior: 'smooth' })
  }
}

onMounted(async () => {
  appendWelcomeMessage()
  await loadCompanies()
  if (!companies.value.includes(selectedCompany.value)) {
    selectedCompany.value = companies.value[0]
  }
})

watch(
  () => session.activeRole.value,
  () => {
    appendWelcomeMessage()
  },
)
</script>

<template>
  <AppShell
    title="对话分析台"
    subtitle="围绕一个问题完成分析、核验和取证"
    compact
  >
    <section class="command-grid" style="margin-bottom: 18px;">
      <article class="command-card-shell role-card">
        <div class="signal-code">当前视角</div>
        <h3>{{ roleCopy.label }}</h3>
        <p class="command-copy">{{ latestPayload?.role_profile?.focus_title || roleCopy.copy }}</p>
      </article>
      <button
        v-for="starter in starterQueries"
        :key="starter"
        type="button"
        class="command-card interactive-card compact-command-card"
        @click="runQuery(`${selectedCompany}${starter}`)"
      >
        <div class="signal-code">快捷问题</div>
        <div class="command-title">{{ starter }}</div>
        <div class="command-meta">{{ selectedCompany }}</div>
      </button>
    </section>

    <section class="chat-workspace">
      <aside class="panel chat-sidebar">
        <div class="panel-header">
          <div>
            <div class="eyebrow">任务面板</div>
            <h3>工作台状态</h3>
          </div>
        </div>
        <div class="detail-list">
          <div class="detail-row">
            <span>当前公司</span>
            <strong>{{ selectedCompany }}</strong>
          </div>
          <div class="detail-row">
            <span>会话角色</span>
            <strong>{{ roleCopy.label }}</strong>
          </div>
          <div class="detail-row">
            <span>消息数</span>
            <strong>{{ messages.length }}</strong>
          </div>
        </div>
        <div class="subsection-label" style="margin-top: 18px;">下一步建议</div>
        <div class="timeline-list">
          <button
            v-for="item in followUps"
            :key="item"
            type="button"
            class="timeline-item interactive-card"
            @click="runQuery(item)"
          >
            <strong>{{ item }}</strong>
            <span>点击继续分析</span>
          </button>
        </div>
      </aside>

      <section class="panel chat-thread-shell">
        <div class="chat-thread" ref="threadRef">
          <LoadingState v-if="workspaceState.loading.value" />
          <ErrorState v-else-if="workspaceState.error.value" :message="workspaceState.error.value" />
          <template v-for="message in messages" :key="message.id">
            <div v-if="message.kind === 'welcome'" class="chat-row assistant">
              <div class="chat-avatar">OP</div>
              <div class="chat-bubble assistant">
                <div class="chat-title">{{ message.title }}</div>
                <div class="chat-copy">
                  <div v-for="line in message.lines" :key="line">{{ line }}</div>
                </div>
              </div>
            </div>

            <div v-else-if="message.kind === 'query'" class="chat-row user">
              <div class="chat-bubble user">
                <div class="chat-meta">{{ message.company }}</div>
                <div class="chat-copy">{{ message.text }}</div>
              </div>
            </div>

            <div v-else class="chat-row assistant">
              <div class="chat-avatar">AI</div>
              <div class="chat-bubble assistant rich">
                <div class="chat-title">
                  {{ message.payload.company_name || '行业视图' }}
                  <span v-if="message.payload.report_period" class="chat-title-meta">{{ message.payload.report_period }}</span>
                </div>
                <div class="chat-sections">
                  <section
                    v-for="section in message.payload.answer_sections"
                    :key="section.title"
                    class="chat-section"
                  >
                    <div class="signal-code">{{ section.title }}</div>
                    <ul class="bullet-list compact">
                      <li v-for="line in section.lines" :key="line">{{ line }}</li>
                    </ul>
                  </section>
                </div>
                <div v-if="message.payload.insight_cards?.length" class="chat-chip-grid">
                  <div
                    v-for="item in message.payload.insight_cards"
                    :key="`${item.label}-${item.value}`"
                    class="metric-chip"
                  >
                    <span>{{ item.label }}</span>
                    <strong>{{ item.value }}<small v-if="item.unit"> {{ item.unit }}</small></strong>
                  </div>
                </div>
                <div v-if="message.payload.action_cards?.length" class="tag-row">
                  <TagPill
                    v-for="item in message.payload.action_cards.slice(0, 3)"
                    :key="item.title"
                    :label="`${item.priority} ${item.title}`"
                    tone="success"
                  />
                </div>
              </div>
            </div>
          </template>
        </div>

        <div class="chat-composer">
          <div class="chat-composer-top">
            <label class="field">
              <span>公司</span>
              <select v-model="selectedCompany">
                <option v-for="company in companies" :key="company" :value="company">{{ company }}</option>
              </select>
            </label>
            <div class="composer-hint">
              <div class="signal-code">当前任务</div>
              <p>{{ selectedCompany }} · {{ roleCopy.label }}</p>
            </div>
          </div>
          <div class="chat-input-wrap chat-input-wrap-wide">
            <textarea
              v-model="query"
              class="text-area chat-input"
              placeholder="直接输入问题，例如：TCL中环 2025Q3 当前最需要优先处理的经营问题是什么？先给结论，再给证据。"
              @keydown.enter.exact.prevent="runQuery()"
            />
            <button class="button-primary chat-send" @click="runQuery()">发送问题</button>
          </div>
        </div>
      </section>

      <aside class="panel chat-sidebar">
        <div class="panel-header">
          <div>
            <div class="eyebrow">多智能体编排</div>
            <h3>执行看板</h3>
          </div>
        </div>
        <div v-if="controlPlane" class="control-plane-card">
          <div class="signal-code">控制平面</div>
          <h4>{{ controlPlane.session_label }}</h4>
          <p class="command-copy">当前问题已进入 {{ controlPlane.query_type }} 流程，{{ controlPlane.steps_completed }}/{{ controlPlane.step_total }} 个执行阶段完成。</p>
          <div class="tag-row">
            <TagPill v-for="source in controlPlane.data_sources" :key="source" :label="source" />
          </div>
        </div>
        <div class="timeline-list execution-list">
          <div v-for="agent in agentFlow" :key="`${agent.step}-${agent.agent}`" class="timeline-item execution-item">
            <div class="execution-head">
              <strong>STEP {{ agent.step }} · {{ agent.agent }}</strong>
              <span>{{ agent.status === 'completed' ? '已完成' : '处理中' }}</span>
            </div>
            <div class="execution-title">{{ agent.title }}</div>
            <span>{{ agent.summary }}</span>
            <div class="execution-meta">
              <div><span>来源</span><strong>{{ agent.source }}</strong></div>
              <div><span>工具</span><strong>{{ agent.tool }}</strong></div>
              <div><span>下一跳</span><strong>{{ agent.handoff }}</strong></div>
            </div>
            <div class="execution-metrics">
              <div v-for="metric in agent.metrics" :key="`${agent.agent}-${metric.label}`" class="execution-metric">
                <span>{{ metric.label }}</span>
                <strong>{{ metric.value }}</strong>
              </div>
            </div>
            <RouterLink
              v-if="agent.route"
              class="inline-link execution-link"
              :to="{ path: agent.route.path, query: agent.route.query || {} }"
            >
              {{ agent.route.label }}
            </RouterLink>
          </div>
        </div>

        <div v-if="evidenceGroups.length" class="subsection-label" style="margin-top: 18px;">证据短链</div>
        <div class="timeline-list">
          <div v-for="group in evidenceGroups.slice(0, 3)" :key="group.code" class="timeline-item">
            <strong>{{ group.title }}</strong>
            <span>{{ group.subtitle }}</span>
            <RouterLink
              v-for="item in group.items.slice(0, 2)"
              :key="item.chunk_id"
              class="inline-link"
              :to="buildEvidenceLink(item.chunk_id, group.title, group.anchor_terms)"
            >
              {{ item.source_title }} · p.{{ item.page }}
            </RouterLink>
          </div>
        </div>

        <div v-if="formulas.length" class="subsection-label" style="margin-top: 18px;">关键公式</div>
        <div class="stack-grid">
          <article v-for="formula in formulas.slice(0, 2)" :key="formula.metric_code" class="formula-card">
            <div class="signal-top">
              <div>
                <div class="signal-code">{{ formula.metric_code }}</div>
                <h4>{{ formula.title }}</h4>
              </div>
              <div class="signal-value">{{ formula.value }}</div>
            </div>
            <code class="formula-inline">{{ formula.formula }}</code>
          </article>
        </div>
      </aside>
      </section>

      <section class="metrics-grid workspace-engine-grid">
        <RouterLink class="signal-card engine-link" to="/admin">
          <div class="signal-code">AI 编排</div>
          <h4>中心化总控调度</h4>
          <p class="command-copy">总控负责拆问题、派步骤、汇结论。</p>
        </RouterLink>
        <RouterLink class="signal-card engine-link" to="/admin">
          <div class="signal-code">数据工程</div>
          <h4>真实数据统一底座</h4>
          <p class="command-copy">真实财报和研报统一进入 raw / bronze / silver。</p>
        </RouterLink>
        <RouterLink class="signal-card engine-link" :to="firstEvidenceLink">
          <div class="signal-code">可解释性</div>
          <h4>结论与证据同路返回</h4>
          <p class="command-copy">公式、指标、页码和证据片段可以逐条回放。</p>
        </RouterLink>
      </section>

    <section v-if="charts.length" class="chart-grid">
      <ChartPanel v-for="chart in charts" :key="chart.title" :title="chart.title" :options="chart.options" />
    </section>
  </AppShell>
</template>
