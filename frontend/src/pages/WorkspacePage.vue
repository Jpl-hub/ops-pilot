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
  executionBus,
  workspaceHistory,
  companyRuntimeCapsule,
  companyRuntimeBus,
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

const workflowLanes = computed(() =>
  agentFlow.value.map((item: any) => ({
    key: `${item.step}-${item.agent}`,
    step: item.step,
    agent: item.agent,
    title: item.title,
    status: item.status === 'completed' ? '已完成' : '处理中',
  })),
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

async function dispatchAlert(alertId: string) {
  await workspace.dispatchAlertToTask(alertId, session.activeRole.value || 'management')
}

function canNavigate(path?: string) {
  return Boolean(path && path.startsWith('/') && !path.startsWith('/api/'))
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

watch(selectedCompany, async (company, previous) => {
  if (!company || company === previous) return
  await workspace.loadCompanyWorkspace(session.activeRole.value || 'investor')
})
</script>

<template>
  <AppShell
    title="多智能体协同"
    subtitle="协同分析台"
    compact
  >
    <section class="workspace-stage">
      <section class="panel chat-thread-shell chat-thread-shell-wide">
        <div class="chat-topbar">
          <label class="field">
            <span>目标公司</span>
            <select v-model="selectedCompany">
              <option v-for="company in companies" :key="company" :value="company">{{ company }}</option>
            </select>
          </label>
          <div class="chat-topbar-card">
            <span>当前任务</span>
            <strong>{{ selectedCompany }} · {{ roleCopy.label }}</strong>
          </div>
        </div>

        <div class="chat-quick-stats">
          <div class="mission-stat"><span>预警</span><strong>{{ overviewSummary?.total_alerts || 0 }}</strong></div>
          <div class="mission-stat"><span>在办任务</span><strong>{{ taskSummary?.in_progress || 0 }}</strong></div>
          <div class="mission-stat"><span>执行总线</span><strong>{{ executionBus.length }}</strong></div>
        </div>

        <div v-if="controlPlane || workflowLanes.length" class="chat-runbar">
          <div v-if="controlPlane" class="chat-runbar-summary">
            <div class="signal-code">分析链</div>
            <strong>{{ controlPlane.session_label }}</strong>
            <span>{{ controlPlane.steps_completed }}/{{ controlPlane.step_total }} 个阶段完成</span>
          </div>
          <div class="chat-runbar-track">
            <div
              v-for="lane in workflowLanes.slice(0, 4)"
              :key="lane.key"
              class="chat-runbar-lane"
            >
              <div class="signal-code">STEP {{ lane.step }}</div>
              <strong>{{ lane.agent }}</strong>
              <span>{{ lane.title }}</span>
              <em>{{ lane.status }}</em>
            </div>
          </div>
        </div>

        <div class="chat-thread-frame">
        <div class="chat-thread" ref="threadRef">
          <div v-if="messages.length <= 1 && !loadingTurn" class="chat-empty-state">
            <div class="chat-empty-mark">◌</div>
            <div class="chat-empty-copy">
              <strong>围绕一个问题发起协同分析</strong>
            </div>
          </div>
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
        </div>

        <div class="chat-composer chat-composer-docked">
          <div class="chat-prompt-row">
            <button
              v-for="item in starterQueries.slice(0, 3)"
              :key="`prompt-${item}`"
              type="button"
              class="chat-prompt-chip"
              @click="runQuery(`${selectedCompany}${item}`)"
            >
              {{ item }}
            </button>
          </div>
          <div class="chat-input-wrap chat-input-wrap-wide">
            <textarea
              v-model="query"
              class="text-area chat-input"
              placeholder="输入任务，例如：评估 TCL中环 当前经营风险，并给出证据链与建议动作。"
              @keydown.enter.exact.prevent="runQuery()"
            />
            <button class="button-primary chat-send" :disabled="loadingTurn || loadingOverview" @click="runQuery()">开始分析</button>
          </div>
        </div>
      </section>

      <aside class="workspace-rail">
        <section class="panel rail-section rail-section-primary">
          <div class="panel-header">
            <div>
              <h3>分析上下文</h3>
            </div>
          </div>
          <div class="detail-list compact-list">
            <div class="detail-row"><span>公司</span><strong>{{ selectedCompany }}</strong></div>
            <div class="detail-row"><span>视角</span><strong>{{ roleCopy.label }}</strong></div>
            <div class="detail-row"><span>消息</span><strong>{{ messages.length }}</strong></div>
            <div v-if="taskSummary" class="detail-row"><span>在办任务</span><strong>{{ taskSummary.in_progress }}</strong></div>
            <div v-if="overviewSummary" class="detail-row"><span>覆盖</span><strong>{{ overviewSummary.active_companies }}</strong></div>
          </div>
          <div class="timeline-list compact-timeline">
            <button
              v-for="item in starterQueries.slice(0, 4)"
              :key="item"
              type="button"
              class="timeline-item interactive-card"
              @click="runQuery(`${selectedCompany}${item}`)"
            >
              <strong>{{ item }}</strong>
            </button>
          </div>
            <div v-if="followUps.length" class="timeline-list compact-timeline">
              <button
                v-for="item in followUps.slice(0, 3)"
              :key="`follow-${item}`"
              type="button"
              class="timeline-item interactive-card"
              @click="runQuery(item)"
            >
              <strong>{{ item }}</strong>
              </button>
            </div>
          </section>

        <section v-if="companyRuntimeBus.length || companyRuntimeCapsule?.modules?.length" class="panel rail-section rail-section-primary">
          <div class="panel-header">
            <div>
              <h3>运行胶囊</h3>
            </div>
          </div>
          <div class="timeline-list compact-timeline">
            <RouterLink
              v-for="item in (companyRuntimeBus.length ? companyRuntimeBus : companyRuntimeCapsule?.modules || [])"
              :key="item.module_key"
              class="timeline-item interactive-card"
              :to="{ path: item.route.path, query: item.route.query || {} }"
            >
              <div class="execution-head">
                <strong>{{ item.label }}</strong>
                <span>{{ item.status === 'ready' ? '已运行' : '待运行' }}</span>
              </div>
              <div class="execution-title">{{ item.headline || item.summary }}</div>
              <span v-if="item.signal">{{ item.signal }}</span>
              <span v-else-if="item.details?.length">{{ item.details.join(' · ') }}</span>
            </RouterLink>
          </div>
        </section>

        <section class="panel rail-section rail-section-primary">
          <div class="panel-header">
            <div>
              <h3>运行轨迹</h3>
            </div>
          </div>
          <div class="timeline-list execution-list compact-timeline">
            <div v-for="agent in agentFlow.slice(0, 4)" :key="`${agent.step}-${agent.agent}`" class="timeline-item execution-item">
              <div class="execution-head">
                <strong>{{ agent.agent }}</strong>
                <span>{{ agent.status === 'completed' ? '已完成' : '处理中' }}</span>
              </div>
              <div class="execution-title">{{ agent.title }}</div>
              <span>{{ agent.summary }}</span>
              <RouterLink
                v-if="agent.route"
                class="inline-link execution-link"
                :to="{ path: agent.route.path, query: agent.route.query || {} }"
              >
                {{ agent.route.label }}
              </RouterLink>
            </div>
          </div>
        </section>
        <section v-if="workspaceHistory.length || alertQueue.length || evidenceGroups.length" class="panel rail-section rail-section-primary">
          <div class="panel-header">
            <div>
              <h3>关注事项</h3>
            </div>
          </div>
          <div v-if="alertQueue.length" class="timeline-list compact-timeline">
            <div
              v-for="item in alertQueue.slice(0, 2)"
              :key="item.alert_id || item.title"
              class="timeline-item interactive-card"
            >
              <strong>{{ item.title }}</strong>
              <span>{{ item.summary }}</span>
              <div class="tag-row" style="margin-top: 6px;">
                <button
                  v-if="item.alert_id && item.status === 'new'"
                  type="button"
                  class="button-secondary"
                  @click="dispatchAlert(item.alert_id)"
                >
                  派发任务
                </button>
                <RouterLink
                  class="inline-link"
                  :to="{ path: item.route.path, query: item.route.query || {} }"
                >
                  查看
                </RouterLink>
              </div>
            </div>
          </div>
          <div v-if="workspaceHistory.length" class="timeline-list compact-timeline">
            <div
              v-for="item in workspaceHistory.slice(0, 2)"
              :key="`${item.type}-${item.id}`"
              class="timeline-item"
            >
              <strong>{{ item.title }}</strong>
              <span>{{ item.type_label }} · {{ item.status_label }}</span>
              <RouterLink
                v-if="canNavigate(item.route?.path)"
                class="inline-link"
                :to="{ path: item.route.path, query: item.route.query || {} }"
              >
                查看
              </RouterLink>
            </div>
          </div>
          <div v-if="evidenceGroups.length" class="timeline-list compact-timeline">
            <div v-for="group in evidenceGroups.slice(0, 2)" :key="group.code" class="timeline-item">
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
        </section>
      </aside>
    </section>

    <section v-if="charts.length" class="chart-grid">
      <ChartPanel v-for="chart in charts" :key="chart.title" :title="chart.title" :options="chart.options" />
    </section>
  </AppShell>
</template>
