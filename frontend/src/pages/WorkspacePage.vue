<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
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

// Agent 流程状态（用于内联展示，不再是视频格）
const agentSteps = computed(() =>
  agentFlow.value.map((item: any) => ({
    key: `${item.step}-${item.agent_key}`,
    agent_key: item.agent_key,
    agent_label: item.agent_label ?? item.agent,
    title: item.title,
    summary: item.summary,
    status: item.status, // 'completed' | 'processing'
  })),
)

// 最新一条 AI 回答
const latestAnswer = computed(() => {
  const results = messages.value.filter(m => m.kind === 'result')
  return results.length > 0 ? results[results.length - 1].payload : null
})

// 右侧面板数据
const insightCards = computed(() => latestAnswer.value?.insight_cards ?? [])
const actionCards  = computed(() => latestAnswer.value?.action_cards  ?? [])

// 角色显示
const roleLabel = computed(() => {
  const map: Record<string, string> = { investor: '投资者', management: '管理层', regulator: '监管方' }
  return map[session.activeRole.value || 'investor'] ?? '投资者'
})

const roleDot = computed(() => {
  const map: Record<string, string> = { investor: '#60a5fa', management: '#a78bfa', regulator: '#f59e0b' }
  return map[session.activeRole.value || 'investor'] ?? '#60a5fa'
})

// ------------------------------------------------------------------
// Agent icon colors
// ------------------------------------------------------------------
const agentColor: Record<string, { icon: string; dot: string }> = {
  router:   { icon: '#10b981', dot: '#10b981' },
  data:     { icon: '#60a5fa', dot: '#3b82f6' },
  risk:     { icon: '#f59e0b', dot: '#f59e0b' },
  strategy: { icon: '#a78bfa', dot: '#7c3aed' },
}
function agentStyle(key: string) { return agentColor[key] ?? { icon: '#9ca3af', dot: '#6b7280' } }

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

// ------------------------------------------------------------------
// Lifecycle
// ------------------------------------------------------------------
let _timer: ReturnType<typeof setInterval> | null = null

onMounted(async () => {
  workspace.resetConversation(roleCopy.value.title, roleCopy.value.label)
  await workspace.loadOverview(session.activeRole.value || 'investor')
  if (!companies.value.includes(selectedCompany.value)) {
    selectedCompany.value = companies.value[0]
  }
})

onBeforeUnmount(() => {
  if (_timer) clearInterval(_timer)
})

watch(
  () => session.activeRole.value,
  async () => {
    workspace.resetConversation(roleCopy.value.title, roleCopy.value.label)
    await workspace.loadOverview(session.activeRole.value || 'investor')
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

          <!-- messages scroll area -->
          <div class="chat-messages" ref="chatScrollRef">

            <!-- welcome / empty state -->
            <div v-if="messages.length <= 1" class="chat-welcome">
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

                  <!-- agent flow (collapsible thinking block) -->
                  <details
                    v-if="message.payload?.agent_flow?.length"
                    class="chat-thinking"
                  >
                    <summary class="chat-thinking-summary">
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
                      分析过程 · {{ message.payload.agent_flow.length }} 步
                    </summary>
                    <div class="chat-thinking-grid">
                      <div
                        v-for="step in message.payload.agent_flow"
                        :key="step.step"
                        class="chat-think-item"
                        :style="{ '--dot': agentStyle(step.agent_key ?? '').dot }"
                      >
                        <span class="chat-think-dot"/>
                        <div class="chat-think-body">
                          <span class="chat-think-agent">{{ step.agent_label }}</span>
                          <span class="chat-think-title">{{ step.title }}</span>
                        </div>
                        <span class="chat-think-status done">✓</span>
                      </div>
                    </div>
                  </details>

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
                <div v-if="agentSteps.length" class="chat-live-flow">
                  <div class="chat-live-header">
                    <span class="chat-live-spinner"/>
                    正在推理中…
                  </div>
                  <div class="chat-thinking-grid">
                    <div
                      v-for="step in agentSteps"
                      :key="step.key"
                      class="chat-think-item"
                      :style="{ '--dot': agentStyle(step.agent_key).dot }"
                    >
                      <span class="chat-think-dot" :class="step.status === 'completed' ? 'done' : 'active'"/>
                      <div class="chat-think-body">
                        <span class="chat-think-agent">{{ step.agent_label }}</span>
                        <span class="chat-think-title">{{ step.title }}</span>
                      </div>
                      <span v-if="step.status === 'completed'" class="chat-think-status done">✓</span>
                      <span v-else class="chat-think-status pending">…</span>
                    </div>
                  </div>
                </div>
                <div v-else class="chat-typing">
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
                @click="runQuery(`${selectedCompany} ${item}`)"
              >{{ item }}</button>
            </div>

            <div class="chat-input-wrap" :class="{ 'is-loading': loadingTurn }">
              <textarea
                v-model="query"
                class="chat-textarea"
                :placeholder="`向 ${selectedCompany || '...'} 发起分析，Shift+Enter 换行`"
                @keydown.enter="handleEnter"
                rows="1"
              />
              <button
                class="chat-send"
                :disabled="loadingTurn || !query.trim()"
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
                  风险 & 行动
                </div>
                <div class="panel-tags">
                  <TagPill
                    v-for="item in actionCards"
                    :key="item.title"
                    :label="`[${item.priority}] ${item.title}`"
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

/* agent thinking (collapsible) */
.chat-thinking {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid rgba(255,255,255,0.07);
}
.chat-thinking-summary {
  display: flex; align-items: center; gap: 6px;
  font-size: 11px;
  color: #6b7280;
  cursor: pointer;
  list-style: none;
  user-select: none;
  transition: color .2s;
}
.chat-thinking-summary:hover { color: #9ca3af; }
.chat-thinking-summary::-webkit-details-marker { display: none; }

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

/* 2-col thinking grid */
.chat-thinking-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin-top: 10px;
}
.chat-think-item {
  display: flex; align-items: flex-start; gap: 8px;
  background: rgba(0,0,0,0.25);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 8px;
  padding: 8px 10px;
  position: relative;
  overflow: hidden;
}
.chat-think-item::before {
  content: '';
  position: absolute; left: 0; top: 0; bottom: 0;
  width: 2px;
  background: var(--dot, #6b7280);
}
.chat-think-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--dot, #6b7280);
  flex-shrink: 0;
  margin-top: 4px;
}
.chat-think-dot.active { animation: dot-pulse 1.2s ease-in-out infinite; }
.chat-think-dot.done   { background: #10b981; }
@keyframes dot-pulse { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:.4;transform:scale(1.3)} }

.chat-think-body { flex: 1; min-width: 0; }
.chat-think-agent { display: block; font-size: 11px; font-weight: 600; color: #9ca3af; margin-bottom: 2px; font-family: monospace; }
.chat-think-title { display: block; font-size: 12px; color: #d1d5db; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.chat-think-status { font-size: 11px; flex-shrink: 0; }
.chat-think-status.done    { color: #10b981; }
.chat-think-status.pending { color: #6b7280; }

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
  .chat-messages { padding: 16px; }
  .chat-footer { padding: 10px 14px 12px; }
  .chat-row { max-width: 100%; }
  .chat-thinking-grid { grid-template-columns: 1fr; }
}
</style>
