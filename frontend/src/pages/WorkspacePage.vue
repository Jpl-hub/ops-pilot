<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { RouterLink } from 'vue-router'

import AppShell from '@/components/AppShell.vue'
import ChartPanel from '@/components/ChartPanel.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingState from '@/components/LoadingState.vue'
import TagPill from '@/components/TagPill.vue'
import { useWorkspaceRole } from '@/composables/useWorkspaceRole'
import { buildEvidenceLink } from '@/lib/format'
import { useSession } from '@/lib/session'
import { useWorkspaceStore } from '@/stores/workspace'

const session = useSession()
const workspace = useWorkspaceStore()
const {
  companies,
  selectedCompany,
  query,
  messages,
  taskQueue,
  taskSummary,
  alertQueue,
  alertWorkflowSummary,
  overviewSummary,
  followUps,
  agentFlow,
  controlPlane,
  evidenceGroups,
  charts,
  formulas,
  latestPayload,
  loadingOverview,
  loadingTurn,
  overviewError,
  turnError,
} = storeToRefs(workspace)
const threadRef = ref<HTMLElement | null>(null)
const { roleCopy } = useWorkspaceRole(() => session.activeRole.value || 'investor')

const starterQueries = computed(
  () => latestPayload.value?.role_profile?.starter_queries || roleCopy.value.fallbackQueries,
)

function appendWelcomeMessage() {
  workspace.resetConversation(roleCopy.value.title, roleCopy.value.label)
}

async function runQuery(inputQuery?: string) {
  await workspace.sendQuery(session.activeRole.value || 'investor', inputQuery)
  if (!workspace.turnError) {
    await nextTick()
    threadRef.value?.scrollTo({ top: threadRef.value.scrollHeight, behavior: 'smooth' })
  }
}

onMounted(async () => {
  appendWelcomeMessage()
  await workspace.loadOverview(session.activeRole.value || 'investor')
  if (!companies.value.includes(selectedCompany.value)) {
    selectedCompany.value = companies.value[0]
  }
})

watch(
  () => session.activeRole.value,
  async () => {
    appendWelcomeMessage()
    await workspace.loadOverview(session.activeRole.value || 'investor')
  },
)
</script>

<template>
  <AppShell
    title="工作台"
    subtitle="任务控制台"
    compact
  >
    <section class="metrics-grid workspace-overview-strip">
      <article class="signal-card">
        <div class="signal-code">视角</div>
        <h4>{{ roleCopy.label }}</h4>
      </article>
      <article class="signal-card">
        <div class="signal-code">预警</div>
        <h4>{{ overviewSummary?.total_alerts || 0 }}</h4>
      </article>
      <article class="signal-card">
        <div class="signal-code">覆盖</div>
        <h4>{{ overviewSummary?.active_companies || 0 }}</h4>
      </article>
    </section>

    <section class="chat-workspace">
      <aside class="panel chat-sidebar">
        <div class="panel-header">
          <div>
            <div class="eyebrow">任务面板</div>
            <h3>会话状态</h3>
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
          <div v-if="overviewSummary" class="detail-row">
            <span>主周期预警</span>
            <strong>{{ overviewSummary.total_alerts }}</strong>
          </div>
          <div v-if="taskSummary" class="detail-row">
            <span>处理中任务</span>
            <strong>{{ taskSummary.in_progress }}</strong>
          </div>
          <div v-if="alertWorkflowSummary" class="detail-row">
            <span>待分发预警</span>
            <strong>{{ alertWorkflowSummary.new }}</strong>
          </div>
        </div>
        <div v-if="taskQueue.length" class="subsection-label" style="margin-top: 18px;">待处理任务</div>
        <div class="timeline-list">
          <RouterLink
            v-for="item in taskQueue.slice(0, 4)"
            :key="`${item.company_name}-${item.report_period}`"
            class="timeline-item interactive-card"
            :to="{ path: item.route.path, query: item.route.query || {} }"
          >
            <strong>{{ item.priority }} {{ item.title }}</strong>
            <span>{{ item.summary }}</span>
          </RouterLink>
        </div>
        <div class="subsection-label" style="margin-top: 18px;">快捷任务</div>
        <div class="timeline-list">
          <button
            v-for="item in starterQueries"
            :key="item"
            type="button"
            class="timeline-item interactive-card"
            @click="runQuery(`${selectedCompany}${item}`)"
          >
            <strong>{{ item }}</strong>
            <span>{{ selectedCompany }}</span>
          </button>
        </div>

        <div v-if="followUps.length" class="subsection-label" style="margin-top: 18px;">追问建议</div>
        <div class="timeline-list">
          <button
            v-for="item in followUps"
            :key="`follow-${item}`"
            type="button"
            class="timeline-item interactive-card"
            @click="runQuery(item)"
          >
            <strong>{{ item }}</strong>
            <span>继续深入</span>
          </button>
        </div>
      </aside>

      <section class="panel chat-thread-shell">
        <div class="chat-thread" ref="threadRef">
          <LoadingState v-if="loadingTurn" />
          <ErrorState v-else-if="turnError" :message="turnError" />
          <ErrorState v-else-if="overviewError" :message="overviewError" />
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
              placeholder="输入一个任务，例如：先给结论，再拆原因，再回放证据。"
              @keydown.enter.exact.prevent="runQuery()"
            />
            <button class="button-primary chat-send" :disabled="loadingTurn || loadingOverview" @click="runQuery()">发送问题</button>
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
          <p class="command-copy">{{ controlPlane.steps_completed }}/{{ controlPlane.step_total }} 个阶段完成</p>
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

        <div v-if="alertQueue.length" class="subsection-label" style="margin-top: 18px;">预警队列</div>
        <div class="timeline-list">
          <RouterLink
            v-for="item in alertQueue.slice(0, 3)"
            :key="item.alert_id || item.title"
            class="timeline-item interactive-card"
            :to="{ path: item.route.path, query: item.route.query || {} }"
          >
            <strong>{{ item.title }}</strong>
            <span>{{ item.summary }}</span>
          </RouterLink>
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

    <section v-if="charts.length" class="chart-grid">
      <ChartPanel v-for="chart in charts" :key="chart.title" :title="chart.title" :options="chart.options" />
    </section>
  </AppShell>
</template>
