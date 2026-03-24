<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'

import AppShell from '@/components/AppShell.vue'
import ErrorState from '@/components/ErrorState.vue'
import TagPill from '@/components/TagPill.vue'
import { useWorkspaceRole } from '@/composables/useWorkspaceRole'
import { useSession } from '@/lib/session'
import { useWorkspaceStore } from '@/stores/workspace'

const session = useSession()
const workspace = useWorkspaceStore()
const {
  companies,
  selectedCompany,
  query,
  messages,
  agentFlow,
  latestPayload,
  loadingTurn,
  turnError,
} = storeToRefs(workspace)

const chatScrollRef = ref<HTMLElement | null>(null)
const { roleCopy } = useWorkspaceRole(() => session.activeRole.value || 'investor')

// 快捷问题来自后端 role_profile 或本地 fallback
const starterQueries = computed(
  () => latestPayload.value?.role_profile?.starter_queries || roleCopy.value.fallbackQueries,
)

const agentBlueprint = [
  { step: 1, agent_key: 'router', agent_label: 'Router', title: '识别问题类型', hint: '锁定问题意图、公司主体和目标报期' },
  { step: 2, agent_key: 'data', agent_label: 'Data Agent', title: '拉取真实数据与工具', hint: '调取评分、图谱、压力、研报、多模态等真实服务' },
  { step: 3, agent_key: 'risk', agent_label: 'Risk Agent', title: '校验证据与风险', hint: '回放页级证据、公式链与风险标签' },
  { step: 4, agent_key: 'strategy', agent_label: 'Strategy Agent', title: '生成角色动作', hint: '按投资者、管理层、监管方视角输出下一步' },
]

const agentLane = computed(() =>
  agentBlueprint.map((blueprint, index) => {
    const matched = agentFlow.value.find((item: any) => item.agent_key === blueprint.agent_key)
    const status = loadingTurn.value
      ? 'processing'
      : matched
      ? 'completed'
      : 'idle'
    return {
      ...blueprint,
      summary: matched?.summary || blueprint.hint,
      status,
      isCurrent: loadingTurn.value && index === 1,
    }
  }),
)

// 最新一条 AI 回答
const latestAnswer = computed(() => {
  const results = messages.value.filter(m => m.kind === 'result')
  return results.length > 0 ? results[results.length - 1].payload : null
})

// 右侧面板数据
const insightCards = computed(() => latestAnswer.value?.insight_cards ?? [])
const actionCards  = computed(() => latestAnswer.value?.action_cards  ?? [])
const aiAssurance = computed(() => latestAnswer.value?.ai_assurance ?? null)
const hasCompanies = computed(() => companies.value.length > 0)
const canRunQuery = computed(() => !!selectedCompany.value && !!query.value.trim() && !loadingTurn.value)

// 角色显示
const roleLabel = computed(() => {
  const map: Record<string, string> = { investor: '投资者', management: '管理层', regulator: '监管方' }
  return map[session.activeRole.value || 'investor'] ?? '投资者'
})

const roleDot = computed(() => {
  const map: Record<string, string> = { investor: '#60a5fa', management: '#a78bfa', regulator: '#f59e0b' }
  return map[session.activeRole.value || 'investor'] ?? '#60a5fa'
})

function displayPriority(priority?: string) {
  const map: Record<string, string> = {
    high: '高优先级',
    medium: '中优先级',
    low: '低优先级',
  }
  return map[(priority || '').toLowerCase()] || priority || '待定级'
}

function displayAssuranceStatus(status?: string) {
  const map: Record<string, string> = {
    grounded: '强支撑',
    review: '待补证',
    degraded: '回退分析',
  }
  return map[status || ''] || status || '未判定'
}

// ------------------------------------------------------------------
// Input handling
// ------------------------------------------------------------------
function handleEnter(e: KeyboardEvent) {
  if (!e.shiftKey) {
    e.preventDefault()
    runQuery()
  }
}

async function runQuery(inputQuery?: string) {
  if (inputQuery) query.value = inputQuery
  await workspace.sendQuery(session.activeRole.value || 'investor', query.value)
  if (!workspace.turnError) {
    await nextTick()
    if (chatScrollRef.value) {
      chatScrollRef.value.scrollTo({ top: chatScrollRef.value.scrollHeight, behavior: 'smooth' })
    }
  }
}

onMounted(async () => {
  workspace.resetConversation(roleCopy.value.title, roleCopy.value.label)
  await workspace.loadOverview(session.activeRole.value || 'investor')
  if (!companies.value.includes(selectedCompany.value)) {
    selectedCompany.value = companies.value[0] || ''
  }
})

watch(
  () => session.activeRole.value,
  async () => {
    workspace.resetConversation(roleCopy.value.title, roleCopy.value.label)
    await workspace.loadOverview(session.activeRole.value || 'investor')
    if (!companies.value.includes(selectedCompany.value)) {
      selectedCompany.value = companies.value[0] || ''
    }
  },
)

watch(selectedCompany, async (company, previous) => {
  if (!company || company === previous) return
  await workspace.loadCompanyWorkspace(session.activeRole.value || 'investor')
})
</script>

<template>
  <AppShell title="">
    <div class="chat-shell">

      <!-- ── HEADER ─────────────────────────────────────────── -->
      <header class="chat-header">
        <div class="chat-header-left">
          <!-- logo mark -->
          <div class="chat-logo">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
            </svg>
          </div>
          <span class="chat-brand">OpsPilot-X</span>
          <div class="chat-divider"/>
          <!-- company selector -->
          <div class="chat-target">
            <span class="chat-target-label">分析公司</span>
            <select v-model="selectedCompany" class="chat-select">
              <option v-if="!companies.length" value="">暂无公司</option>
              <option v-for="c in companies" :key="c" :value="c">{{ c }}</option>
            </select>
          </div>
        </div>

        <div class="chat-header-right">
          <!-- role badge -->
          <div class="chat-role-badge">
            <span class="chat-role-dot" :style="{ background: roleDot }"/>
            {{ roleLabel }}
          </div>
        </div>
      </header>

      <!-- ── BODY ───────────────────────────────────────────── -->
      <div class="chat-body">

        <!-- LEFT/CENTER: messages + input ─────────────────── -->
        <div class="chat-main">
          <section class="chat-agent-lane">
            <div
              v-for="item in agentLane"
              :key="item.agent_key"
              class="chat-agent-card"
              :class="`is-${item.status}`"
            >
              <div class="chat-agent-card-head">
                <span class="chat-agent-step">0{{ item.step }}</span>
                <span class="chat-agent-name">{{ item.agent_label }}</span>
              </div>
              <strong class="chat-agent-title">{{ item.title }}</strong>
              <p class="chat-agent-summary">{{ item.summary }}</p>
            </div>
          </section>

          <!-- messages scroll area -->
          <div class="chat-messages" ref="chatScrollRef">

            <!-- welcome / empty state -->
            <div v-if="!hasCompanies" class="chat-welcome">
              <div class="chat-welcome-icon">
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="1.5">
                  <path d="M12 3v12"/><path d="M7 10l5 5 5-5"/><path d="M5 21h14"/>
                </svg>
              </div>
              <p class="chat-welcome-text">
                当前还没有可分析企业<br>
                <span class="chat-welcome-sub">请先完成正式公司池和页级/指标数据接入，再进入协同分析。</span>
              </p>
            </div>
            <div v-else-if="messages.length <= 1" class="chat-welcome">
              <div class="chat-welcome-icon">
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="1.5">
                  <path d="M12 2a2 2 0 0 1 2 2c0 .74-.4 1.39-1 1.73V7h1a7 7 0 0 1 7 7h1a1 1 0 0 1 1 1v3a1 1 0 0 1-1 1h-1v1a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-1H2a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1h1a7 7 0 0 1 7-7h1V5.73A2 2 0 0 1 10 4a2 2 0 0 1 2-2z"/>
                </svg>
              </div>
              <p class="chat-welcome-text">
                正在分析 <strong>{{ selectedCompany || '...' }}</strong>，作为 <strong>{{ roleLabel }}</strong> 视角<br>
                <span class="chat-welcome-sub">从下方快捷问题开始，或直接输入你的分析指令</span>
              </p>
            </div>

            <!-- message loop -->
            <template v-for="message in messages" :key="message.id">

              <!-- user query — right aligned -->
              <div v-if="message.kind === 'query'" class="chat-row chat-row-user">
                <div class="chat-bubble-user">
                  <p class="chat-bubble-text">{{ message.text }}</p>
                </div>
                <div class="chat-avatar chat-avatar-user">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M12 12c2.7 0 4.8-2.1 4.8-4.8S14.7 2.4 12 2.4 7.2 4.5 7.2 7.2 9.3 12 12 12zm0 2.4c-3.2 0-9.6 1.6-9.6 4.8v2.4h19.2v-2.4c0-3.2-6.4-4.8-9.6-4.8z"/>
                  </svg>
                </div>
              </div>

              <!-- AI result — left aligned -->
              <div v-else-if="message.kind === 'result'" class="chat-row chat-row-ai">
                <div class="chat-avatar chat-avatar-ai">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="3"/>
                    <path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83"/>
                  </svg>
                </div>

                <div class="chat-bubble-ai">
                  <!-- answer sections -->
                  <template v-if="message.payload?.answer_sections?.length">
                    <section
                      v-for="section in message.payload.answer_sections"
                      :key="section.title"
                      class="chat-answer-section"
                    >
                      <div class="chat-section-title">{{ section.title }}</div>
                      <p
                        v-for="line in section.lines"
                        :key="line"
                        class="chat-section-line"
                      >{{ line }}</p>
                    </section>
                  </template>
                  <p v-else-if="message.payload?.summary" class="chat-section-line">
                    {{ message.payload.summary }}
                  </p>

                  <!-- key numbers strip -->
                  <div v-if="message.payload?.key_numbers?.length" class="chat-key-nums">
                    <span
                      v-for="kn in message.payload.key_numbers"
                      :key="kn.label"
                      class="chat-kn-badge"
                    >
                      <span class="chat-kn-label">{{ kn.label }}</span>
                      <span class="chat-kn-value">{{ kn.value }}<em v-if="kn.unit">{{ kn.unit }}</em></span>
                    </span>
                  </div>

                  <!-- follow-up suggestions -->
                  <div v-if="message.payload?.follow_up_questions?.length" class="chat-followup">
                    <span class="chat-followup-label">追问</span>
                    <button
                      v-for="q in message.payload.follow_up_questions.slice(0, 3)"
                      :key="q"
                      class="chat-followup-btn"
                      @click="runQuery(q)"
                    >{{ q }}</button>
                  </div>
                </div>
              </div>

            </template>

            <!-- loading: live agent thinking block -->
            <div v-if="loadingTurn" class="chat-row chat-row-ai">
              <div class="chat-avatar chat-avatar-ai thinking-pulse">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <circle cx="12" cy="12" r="3"/><path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83"/>
                </svg>
              </div>
              <div class="chat-bubble-ai chat-bubble-loading">
                <div class="chat-live-flow">
                  <div class="chat-live-header">
                    <span class="chat-live-spinner"/>
                    正在执行真实分析服务，请查看上方协同工作流
                  </div>
                  <div class="chat-typing">
                    <span/><span/><span/>
                  </div>
                </div>
                <div v-if="!agentLane.length" class="chat-typing">
                  <span/><span/><span/>
                </div>
              </div>
            </div>

            <ErrorState v-if="turnError" :message="turnError" />
          </div><!-- /chat-messages -->

          <!-- input zone -->
          <footer class="chat-footer">
            <!-- quick prompts (horizontal scroll, no line break) -->
            <div class="chat-prompts">
              <button
                v-for="item in starterQueries.slice(0, 5)"
                :key="item"
                class="chat-prompt-pill"
                :disabled="!selectedCompany"
                @click="runQuery(`${selectedCompany} ${item}`)"
              >{{ item }}</button>
            </div>

            <div class="chat-input-wrap" :class="{ 'is-loading': loadingTurn }">
              <textarea
                v-model="query"
                class="chat-textarea"
                :placeholder="selectedCompany ? `向 ${selectedCompany} 发起分析，Shift+Enter 换行` : '当前无可分析企业，请先完成数据接入'"
                @keydown.enter="handleEnter"
                rows="1"
              />
              <button
                class="chat-send"
                :disabled="!canRunQuery"
                @click="runQuery()"
              >
                <svg v-if="loadingTurn" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="spin"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>
                <svg v-else width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
              </button>
            </div>
          </footer>

        </div><!-- /chat-main -->

        <!-- RIGHT PANEL: insight + charts ──────────────────── -->
        <aside class="chat-panel">
          <div class="panel-header">分析结果</div>
          <div class="panel-body">

            <template v-if="insightCards.length || actionCards.length">

              <div v-if="aiAssurance" class="panel-block">
                <div class="panel-block-title">
                  <span class="panel-dot" :style="{ background: aiAssurance.status === 'grounded' ? '#10b981' : aiAssurance.status === 'review' ? '#f59e0b' : '#f43f5e' }"/>
                  可信分析卡
                </div>
                <div class="panel-assurance-card" :class="`is-${aiAssurance.status}`">
                  <div class="panel-assurance-head">
                    <strong>{{ displayAssuranceStatus(aiAssurance.status) }}</strong>
                    <span class="panel-assurance-badge">{{ aiAssurance.tool_call_count }} 工具</span>
                  </div>
                  <p>{{ aiAssurance.summary }}</p>
                  <div class="panel-assurance-grid">
                    <span>证据 {{ aiAssurance.evidence_count }}</span>
                    <span>证据组 {{ aiAssurance.evidence_group_count }}</span>
                    <span>公式 {{ aiAssurance.formula_count }}</span>
                    <span>关键数 {{ aiAssurance.key_number_count }}</span>
                  </div>
                  <div v-if="aiAssurance.tool_labels?.length" class="panel-tags">
                    <TagPill
                      v-for="tool in aiAssurance.tool_labels"
                      :key="tool"
                      :label="tool"
                      tone="default"
                    />
                  </div>
                  <p v-if="aiAssurance.failed_tool_count" class="panel-assurance-warning">
                    本轮有 {{ aiAssurance.failed_tool_count }} 个工具未成功返回。
                  </p>
                  <p v-if="aiAssurance.retrieval_attempted" class="panel-assurance-foot">
                    文本检索补证 {{ aiAssurance.retrieval_enriched_count }} 条，状态 {{ aiAssurance.retrieval_status || '已记录' }}。
                  </p>
                </div>
              </div>

              <!-- key metrics grid -->
              <div v-if="insightCards.length" class="panel-block">
                <div class="panel-block-title">
                  <span class="panel-dot" style="background:#10b981"/>
                  核心指标
                </div>
                <div class="panel-metrics-grid">
                  <div v-for="item in insightCards" :key="item.label" class="panel-metric-card">
                    <div class="panel-metric-label">{{ item.label }}</div>
                    <div class="panel-metric-value">
                      {{ item.value }}
                      <em v-if="item.unit">{{ item.unit }}</em>
                    </div>
                  </div>
                </div>
              </div>

              <!-- action / risk tags -->
              <div v-if="actionCards.length" class="panel-block">
                <div class="panel-block-title">
                  <span class="panel-dot" style="background:#f43f5e"/>
                  风险与动作
                </div>
                <div class="panel-tags">
                  <TagPill
                    v-for="item in actionCards"
                    :key="item.title"
                    :label="`[${displayPriority(item.priority)}] ${item.title}`"
                    :tone="item.priority?.toLowerCase() === 'high' ? 'risk' : 'default'"
                  />
                </div>
              </div>

            </template>

            <!-- empty state -->
            <div v-else class="panel-empty">
              <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                <polyline points="14 2 14 8 20 8"/>
                <line x1="16" y1="13" x2="8" y2="13"/>
                <line x1="16" y1="17" x2="8" y2="17"/>
              </svg>
              <span>发起分析后结果将展示于此</span>
            </div>

          </div>
        </aside>

      </div><!-- /chat-body -->
    </div>
  </AppShell>
</template>

<style scoped>
/* ── SHELL ───────────────────────────────────────────────────── */
.chat-shell {
  display: flex;
  flex-direction: column;
  height: 100vh;
  width: 100%;
  background: #141414;
  color: #e2e8f0;
  overflow: hidden;
  margin: -16px -24px -24px;
  padding: 0;
  font-family: 'Inter', 'PingFang SC', 'Microsoft YaHei', sans-serif;
}
* { box-sizing: border-box; }

/* ── HEADER ──────────────────────────────────────────────────── */
.chat-header {
  height: 52px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  background: #1a1a1a;
  border-bottom: 1px solid rgba(255,255,255,0.07);
}
.chat-header-left { display: flex; align-items: center; gap: 12px; }
.chat-logo {
  width: 30px; height: 30px;
  background: rgba(16,185,129,0.1);
  border: 1px solid rgba(16,185,129,0.3);
  border-radius: 7px;
  display: flex; align-items: center; justify-content: center;
}
.chat-brand { font-size: 14px; font-weight: 600; color: #fff; letter-spacing: 0.02em; }
.chat-divider { width: 1px; height: 18px; background: rgba(255,255,255,0.12); }
.chat-target { display: flex; align-items: center; gap: 8px; }
.chat-target-label { font-size: 12px; color: #6b7280; }
.chat-select {
  background: rgba(255,255,255,0.06);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 6px;
  color: #10b981;
  font-size: 13px;
  font-weight: 500;
  padding: 3px 8px;
  outline: none;
  cursor: pointer;
}
.chat-select:focus { border-color: rgba(16,185,129,0.4); }
.chat-header-right { display: flex; align-items: center; gap: 12px; }
.chat-role-badge {
  display: flex; align-items: center; gap: 6px;
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 20px;
  padding: 3px 12px;
  font-size: 12px;
  color: #d1d5db;
}
.chat-role-dot { width: 7px; height: 7px; border-radius: 50%; }

/* ── BODY ────────────────────────────────────────────────────── */
.chat-body { flex: 1; display: flex; overflow: hidden; }

/* ── MAIN (chat + input) ─────────────────────────────────────── */
.chat-main { flex: 1; display: flex; flex-direction: column; overflow: hidden; min-width: 0; }

.chat-agent-lane {
  flex-shrink: 0;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  padding: 14px 18px 12px;
  background: #171717;
  border-bottom: 1px solid rgba(255,255,255,0.06);
}

.chat-agent-card {
  min-height: 106px;
  padding: 12px;
  border-radius: 12px;
  border: 1px solid rgba(255,255,255,0.08);
  background: rgba(255,255,255,0.03);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.chat-agent-card.is-idle {
  opacity: 0.88;
}

.chat-agent-card.is-processing {
  border-color: rgba(16,185,129,0.34);
  box-shadow: 0 0 0 1px rgba(16,185,129,0.14), inset 0 0 18px rgba(16,185,129,0.06);
}

.chat-agent-card.is-completed {
  border-color: rgba(59,130,246,0.26);
}

.chat-agent-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.chat-agent-step {
  font-size: 11px;
  color: #10b981;
  font-family: 'JetBrains Mono', monospace;
}

.chat-agent-name {
  font-size: 11px;
  color: #94a3b8;
  font-family: 'JetBrains Mono', monospace;
}

.chat-agent-title {
  font-size: 13px;
  color: #f8fafc;
}

.chat-agent-summary {
  margin: 0;
  font-size: 12px;
  line-height: 1.55;
  color: #94a3b8;
}

/* ── MESSAGES ────────────────────────────────────────────────── */
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 24px 28px;
  display: flex;
  flex-direction: column;
  gap: 20px;
  scroll-behavior: smooth;
}
.chat-messages::-webkit-scrollbar { width: 6px; }
.chat-messages::-webkit-scrollbar-thumb { background: rgba(16,185,129,0.25); border-radius: 3px; }
.chat-messages::-webkit-scrollbar-track { background: transparent; }

/* welcome */
.chat-welcome {
  display: flex; align-items: center; gap: 16px;
  padding: 20px 24px;
  background: rgba(16,185,129,0.05);
  border: 1px solid rgba(16,185,129,0.15);
  border-radius: 12px;
  max-width: 600px;
  align-self: center;
  margin: auto 0;
}
.chat-welcome-icon {
  width: 48px; height: 48px;
  background: rgba(16,185,129,0.1);
  border: 1px solid rgba(16,185,129,0.25);
  border-radius: 12px;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.chat-welcome-text { font-size: 14px; line-height: 1.7; color: #d1d5db; margin: 0; }
.chat-welcome-text strong { color: #10b981; font-weight: 600; }
.chat-welcome-sub { font-size: 12px; color: #6b7280; }

/* message rows */
.chat-row { display: flex; gap: 12px; max-width: 840px; width: 100%; }
.chat-row-user { align-self: flex-end; flex-direction: row-reverse; }
.chat-row-ai   { align-self: flex-start; }

/* avatars */
.chat-avatar {
  width: 32px; height: 32px;
  border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.chat-avatar-user { background: rgba(37,99,235,0.25); border: 1px solid rgba(59,130,246,0.4); color: #60a5fa; }
.chat-avatar-ai   { background: rgba(16,185,129,0.15); border: 1px solid rgba(16,185,129,0.3); color: #10b981; }
.thinking-pulse { animation: avatar-pulse 1.6s ease-in-out infinite; }
@keyframes avatar-pulse { 0%,100%{opacity:1} 50%{opacity:.45} }

/* user bubble */
.chat-bubble-user {
  background: rgba(37,99,235,0.2);
  border: 1px solid rgba(59,130,246,0.3);
  border-radius: 14px 4px 14px 14px;
  padding: 10px 16px;
  max-width: 72%;
}
.chat-bubble-text { margin: 0; font-size: 14px; line-height: 1.6; color: #e2e8f0; }

/* AI bubble */
.chat-bubble-ai {
  background: #1e1e1e;
  border: 1px solid rgba(255,255,255,0.09);
  border-radius: 4px 14px 14px 14px;
  padding: 16px 18px;
  max-width: 88%;
  position: relative;
  overflow: hidden;
}
.chat-bubble-loading { min-width: 220px; }

/* answer sections */
.chat-answer-section { margin-bottom: 14px; }
.chat-answer-section:last-of-type { margin-bottom: 0; }
.chat-section-title {
  font-size: 12px;
  font-weight: 600;
  color: #10b981;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  margin-bottom: 6px;
}
.chat-section-line {
  margin: 0 0 4px;
  font-size: 13.5px;
  line-height: 1.65;
  color: #d1d5db;
}

/* key numbers strip */
.chat-key-nums {
  display: flex; flex-wrap: wrap; gap: 8px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid rgba(255,255,255,0.07);
}
.chat-kn-badge {
  display: flex; align-items: baseline; gap: 5px;
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 6px;
  padding: 4px 10px;
}
.chat-kn-label { font-size: 11px; color: #6b7280; }
.chat-kn-value { font-size: 14px; font-weight: 600; color: #fff; font-variant-numeric: tabular-nums; }
.chat-kn-value em { font-style: normal; font-size: 11px; color: #9ca3af; margin-left: 2px; }

/* live flow (while loading) */
.chat-live-flow { display: flex; flex-direction: column; gap: 10px; }
.chat-live-header {
  display: flex; align-items: center; gap: 8px;
  font-size: 12px;
  color: #9ca3af;
  font-family: 'JetBrains Mono', monospace;
}
.chat-live-spinner {
  width: 10px; height: 10px;
  border: 2px solid rgba(16,185,129,0.3);
  border-top-color: #10b981;
  border-radius: 50%;
  animation: spin 0.9s linear infinite;
  flex-shrink: 0;
}

/* typing dots */
.chat-typing { display: flex; align-items: center; gap: 5px; padding: 4px 0; }
.chat-typing span {
  width: 6px; height: 6px; border-radius: 50%;
  background: #4b5563;
  animation: typing-bounce 1.2s ease-in-out infinite;
}
.chat-typing span:nth-child(2) { animation-delay: .15s; }
.chat-typing span:nth-child(3) { animation-delay: .30s; }
@keyframes typing-bounce { 0%,80%,100%{transform:translateY(0)} 40%{transform:translateY(-5px)} }

/* follow-up suggestions */
.chat-followup {
  display: flex; flex-wrap: wrap; align-items: center; gap: 8px;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid rgba(255,255,255,0.07);
}
.chat-followup-label { font-size: 11px; color: #6b7280; }
.chat-followup-btn {
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 20px;
  color: #94a3b8;
  font-size: 12px;
  padding: 4px 12px;
  cursor: pointer;
  transition: all .2s;
  white-space: nowrap;
}
.chat-followup-btn:hover { background: rgba(16,185,129,0.08); border-color: rgba(16,185,129,0.3); color: #10b981; }

/* ── FOOTER (prompts + input) ────────────────────────────────── */
.chat-footer {
  flex-shrink: 0;
  background: #1a1a1a;
  border-top: 1px solid rgba(255,255,255,0.07);
  padding: 12px 20px 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* quick prompts: horizontal scroll row */
.chat-prompts {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding-bottom: 2px;
  scrollbar-width: none;
}
.chat-prompts::-webkit-scrollbar { display: none; }
.chat-prompt-pill {
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 20px;
  color: #9ca3af;
  font-size: 12px;
  padding: 5px 14px;
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
  transition: all .2s;
}
.chat-prompt-pill:hover { background: rgba(16,185,129,0.08); border-color: rgba(16,185,129,0.3); color: #10b981; }

/* input wrap */
.chat-input-wrap {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 10px;
  padding: 8px 10px 8px 14px;
  transition: border-color .2s;
}
.chat-input-wrap:focus-within { border-color: rgba(16,185,129,0.4); }
.chat-input-wrap.is-loading { opacity: .7; pointer-events: none; }
.chat-textarea {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  color: #e2e8f0;
  font-size: 14px;
  line-height: 1.55;
  resize: none;
  min-height: 22px;
  max-height: 110px;
  font-family: inherit;
  overflow-y: auto;
  scrollbar-width: none;
}
.chat-textarea::placeholder { color: #4b5563; }
.chat-send {
  width: 36px; height: 36px;
  background: rgba(16,185,129,0.15);
  border: 1px solid rgba(16,185,129,0.3);
  border-radius: 8px;
  color: #10b981;
  display: flex; align-items: center; justify-content: center;
  cursor: pointer;
  flex-shrink: 0;
  transition: all .2s;
}
.chat-send:hover:not(:disabled) { background: rgba(16,185,129,0.25); border-color: rgba(16,185,129,0.5); }
.chat-send:disabled { opacity: .4; cursor: not-allowed; }

/* ── RIGHT PANEL ─────────────────────────────────────────────── */
.chat-panel {
  width: 300px;
  flex-shrink: 0;
  background: #1a1a1a;
  border-left: 1px solid rgba(255,255,255,0.07);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.panel-header {
  height: 46px;
  flex-shrink: 0;
  display: flex; align-items: center;
  padding: 0 16px;
  font-size: 13px;
  font-weight: 500;
  color: #9ca3af;
  border-bottom: 1px solid rgba(255,255,255,0.07);
  letter-spacing: 0.03em;
}
.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 14px 14px 20px;
  scrollbar-width: thin;
  scrollbar-color: rgba(16,185,129,0.2) transparent;
}

.panel-block { margin-bottom: 20px; }
.panel-block:last-child { margin-bottom: 0; }
.panel-block-title {
  display: flex; align-items: center; gap: 7px;
  font-size: 11px;
  font-weight: 600;
  color: #6b7280;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  margin-bottom: 10px;
}
.panel-dot { width: 7px; height: 7px; border-radius: 50%; }
.panel-assurance-card {
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 10px;
  padding: 12px;
  background: rgba(255,255,255,0.03);
}
.panel-assurance-card.is-grounded { border-color: rgba(16,185,129,0.28); background: rgba(16,185,129,0.06); }
.panel-assurance-card.is-review { border-color: rgba(245,158,11,0.28); background: rgba(245,158,11,0.06); }
.panel-assurance-card.is-degraded { border-color: rgba(244,63,94,0.28); background: rgba(244,63,94,0.06); }
.panel-assurance-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 8px; }
.panel-assurance-head strong { font-size: 13px; color: #f8fafc; }
.panel-assurance-badge {
  border-radius: 999px;
  border: 1px solid rgba(255,255,255,0.12);
  padding: 2px 8px;
  font-size: 11px;
  color: #cbd5e1;
}
.panel-assurance-card p { margin: 0 0 8px; font-size: 12px; line-height: 1.5; color: #cbd5e1; }
.panel-assurance-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
  margin-bottom: 8px;
}
.panel-assurance-grid span {
  font-size: 11px;
  color: #94a3b8;
  background: rgba(0,0,0,0.22);
  border-radius: 6px;
  padding: 6px 8px;
}
.panel-assurance-warning { color: #fecaca; }
.panel-assurance-foot { color: #93c5fd; }

/* metrics 2-col grid */
.panel-metrics-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.panel-metric-card {
  background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.07);
  border-radius: 8px;
  padding: 10px 12px;
}
.panel-metric-label { font-size: 11px; color: #6b7280; margin-bottom: 4px; }
.panel-metric-value { font-size: 17px; font-weight: 700; color: #fff; font-variant-numeric: tabular-nums; }
.panel-metric-value em { font-style: normal; font-size: 11px; color: #9ca3af; margin-left: 2px; }

/* tags */
.panel-tags { display: flex; flex-direction: column; gap: 6px; }

/* empty state */
.panel-empty {
  height: 100%;
  display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  gap: 12px;
  color: #374151;
  font-size: 13px;
  padding: 40px 20px;
  text-align: center;
}

/* ── UTILS ───────────────────────────────────────────────────── */
.spin { animation: spin .9s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

/* responsive: collapse panel below 1100px */
@media (max-width: 1100px) {
  .chat-panel { display: none; }
}
@media (max-width: 720px) {
  .chat-agent-lane { grid-template-columns: 1fr; padding: 12px 14px 10px; }
  .chat-messages { padding: 16px; }
  .chat-footer { padding: 10px 14px 12px; }
  .chat-row { max-width: 100%; }
}
</style>
