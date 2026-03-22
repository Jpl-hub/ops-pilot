<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'

import AppShell from '@/components/AppShell.vue'
import ChartPanel from '@/components/ChartPanel.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingState from '@/components/LoadingState.vue'
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
  taskQueue,
  taskSummary,
  alertQueue,
  overviewSummary,
  agentFlow,
  controlPlane,
  charts,
  latestPayload,
  loadingOverview,
  loadingTurn,
  overviewError,
  turnError,
} = storeToRefs(workspace)

const chatScrollRef = ref<HTMLElement | null>(null)
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
    status: item.status === 'completed' ? 'Done' : 'Processing',
  })),
)

// The latest Answer payload for the Right Sidebar Supporting Info
const latestAnswer = computed(() => {
  const ans = messages.value.filter(m => m.kind === 'answer')
  return ans.length > 0 ? ans[ans.length - 1].payload : null
})

function appendWelcomeMessage() {
  workspace.resetConversation(roleCopy.value.title, roleCopy.value.label)
}

async function runQuery(inputQuery?: string) {
  if(inputQuery) query.value = inputQuery;
  await workspace.sendQuery(session.activeRole.value || 'investor', query.value)
  if (!workspace.turnError) {
    await nextTick()
    if(chatScrollRef.value) {
      chatScrollRef.value.scrollTo({ top: chatScrollRef.value.scrollHeight, behavior: 'smooth' })
    }
  }
}

function handleEnter(e: KeyboardEvent) {
  if (!e.shiftKey) {
    e.preventDefault()
    runQuery()
  }
}

// Simulated active speaker detection for video tiles
const activeAgent = computed(() => {
  if (!loadingTurn.value) return 'none'
  const processing = workflowLanes.value.find(l => l.status === 'Processing')
  if (processing) return processing.agent.toLowerCase()
  return 'system'
})

// Time formatter for top bar
const currentTime = ref(new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }))
setInterval(() => {
  currentTime.value = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}, 1000)

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
  <AppShell title="">
    <div class="mtg-container">
      
      <!-- TOP NAVBAR -->
      <header class="mtg-header">
        <div class="mtg-header-left">
          <svg class="mtg-icon-shield" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>
          <div class="mtg-title-block">
            <h1>深度研判专场 - {{ selectedCompany || '初始化中...' }}</h1>
            <span class="mtg-meeting-id">Meeting ID: {{ String(Math.floor(Math.random() * 900) + 100) }}-{{ String(Math.floor(Math.random() * 900) + 100) }}-2026</span>
          </div>
        </div>
        
        <div class="mtg-header-center">
          <div class="mtg-target-selector">
            <span class="mtg-lbl">研判标的:</span>
            <select v-model="selectedCompany" class="mtg-select">
              <option v-for="c in companies" :key="c" :value="c">{{ c }}</option>
            </select>
          </div>
        </div>

        <div class="mtg-header-right">
          <div class="mtg-time">{{ currentTime }}</div>
          <div class="mtg-network">
            <svg viewBox="0 0 24 24" class="mtg-icon-sm" fill="none" stroke="#10b981" stroke-width="2"><path d="M5 12.55a11 11 0 0 1 14.08 0"></path><path d="M1.42 9a16 16 0 0 1 21.16 0"></path><path d="M8.53 16.11a6 6 0 0 1 6.95 0"></path><line x1="12" y1="20" x2="12.01" y2="20"></line></svg>
            <span class="mtg-ms">12ms</span>
          </div>
          <button class="mtg-btn-leave">结束会议</button>
        </div>
      </header>

      <!-- MAIN LAYOUT -->
      <div class="mtg-body">
        
        <!-- LEFT/CENTER COLUMN -->
        <div class="mtg-col-main">
          
          <!-- TOP STAGE: PARTICIPANTS (VIDEO TILES) -->
          <div class="mtg-stage">
            
            <div class="mtg-tile user-tile">
              <div class="mtg-tile-content">
                <div class="mtg-avatar user-avatar">MD</div>
                <div class="mtg-tile-label">指挥台 (User)</div>
              </div>
            </div>

            <div class="mtg-tile" :class="{ 'speaking': activeAgent === 'data' || activeAgent === 'news' }">
              <div class="mtg-tile-content">
                <div class="mtg-avatar data-avatar"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><ellipse cx="12" cy="5" rx="9" ry="3"></ellipse><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"></path><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"></path></svg></div>
                <div class="mtg-tile-label">Data Agent 
                  <span v-if="activeAgent === 'data' || activeAgent === 'news'" class="mtg-status-mic"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 14c1.66 0 2.99-1.34 2.99-3L15 5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm5.3-3c0 3-2.54 5.1-5.3 5.1S6.7 14 6.7 11H5c0 3.41 2.72 6.23 6 6.72V21h2v-3.28c3.28-.48 6-3.3 6-6.72h-1.7z"/></svg></span>
                  <span v-else class="mtg-status-mic muted"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M19 11h-1.7c0 .74-.16 1.43-.43 2.05l1.23 1.23c.56-.98.9-2.09.9-3.28zm-4.02 3.17c-.99.58-2.16.94-3.48.94-3.41 0-6-2.72-6-6.72H5c0 3.41 2.72 6.23 6 6.72v3.28h2v-3.28c.91-.13 1.77-.45 2.54-.9l-1.56-1.56zM7.53 11c0-1.05.35-2.01.93-2.77L6.68 6.44A5.85 5.85 0 0 0 5.83 11h1.7zM12 14c1.66 0 2.99-1.34 2.99-3L15 5c0-1.66-1.34-3-3-3S9 3.34 9 5c0 1-.22 1.94-.61 2.76l1.45 1.45C10.55 8.7 11.23 8.35 12 8.35c.98 0 1.77.79 1.77 1.77 0 .77-.49 1.44-1.19 1.68l1.6 1.6c.45-.66.72-1.48.72-2.4v6c0 .48-.1.93-.27 1.35l1.2 1.2c.48-.7.83-1.52 1.02-2.4h-1.75zM4.27 3L3 4.27l6.01 6.01c-.01.24-.01.48-.01.72v6c0 1.66 1.34 3 3 3 .24 0 .48 0 .72-.01l6.01 6.01L21 19.73 4.27 3z"/></svg></span>
                </div>
              </div>
            </div>

            <div class="mtg-tile" :class="{ 'speaking': activeAgent === 'risk' }">
              <div class="mtg-tile-content">
                <div class="mtg-avatar risk-avatar"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg></div>
                <div class="mtg-tile-label">Risk Agent
                  <span v-if="activeAgent === 'risk'" class="mtg-status-mic"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 14c1.66 0 2.99-1.34 2.99-3L15 5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm5.3-3c0 3-2.54 5.1-5.3 5.1S6.7 14 6.7 11H5c0 3.41 2.72 6.23 6 6.72V21h2v-3.28c3.28-.48 6-3.3 6-6.72h-1.7z"/></svg></span>
                  <span v-else class="mtg-status-mic muted"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M19 11h-1.7c0 .74-.16 1.43-.43 2.05l1.23 1.23c.56-.98.9-2.09.9-3.28zm-4.02 3.17c-.99.58-2.16.94-3.48.94-3.41 0-6-2.72-6-6.72H5c0 3.41 2.72 6.23 6 6.72v3.28h2v-3.28c.91-.13 1.77-.45 2.54-.9l-1.56-1.56zM7.53 11c0-1.05.35-2.01.93-2.77L6.68 6.44A5.85 5.85 0 0 0 5.83 11h1.7zM12 14c1.66 0 2.99-1.34 2.99-3L15 5c0-1.66-1.34-3-3-3S9 3.34 9 5c0 1-.22 1.94-.61 2.76l1.45 1.45C10.55 8.7 11.23 8.35 12 8.35c.98 0 1.77.79 1.77 1.77 0 .77-.49 1.44-1.19 1.68l1.6 1.6c.45-.66.72-1.48.72-2.4v6c0 .48-.1.93-.27 1.35l1.2 1.2c.48-.7.83-1.52 1.02-2.4h-1.75zM4.27 3L3 4.27l6.01 6.01c-.01.24-.01.48-.01.72v6c0 1.66 1.34 3 3 3 .24 0 .48 0 .72-.01l6.01 6.01L21 19.73 4.27 3z"/></svg></span>
                </div>
              </div>
            </div>

            <div class="mtg-tile" :class="{ 'speaking': activeAgent === 'strategy' }">
              <div class="mtg-tile-content">
                <div class="mtg-avatar strat-avatar"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="3 11 22 2 13 21 11 13 3 11"></polygon></svg></div>
                <div class="mtg-tile-label">Strategy Agent
                   <span v-if="activeAgent === 'strategy'" class="mtg-status-mic"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 14c1.66 0 2.99-1.34 2.99-3L15 5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm5.3-3c0 3-2.54 5.1-5.3 5.1S6.7 14 6.7 11H5c0 3.41 2.72 6.23 6 6.72V21h2v-3.28c3.28-.48 6-3.3 6-6.72h-1.7z"/></svg></span>
                  <span v-else class="mtg-status-mic muted"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M19 11h-1.7c0 .74-.16 1.43-.43 2.05l1.23 1.23c.56-.98.9-2.09.9-3.28zm-4.02 3.17c-.99.58-2.16.94-3.48.94-3.41 0-6-2.72-6-6.72H5c0 3.41 2.72 6.23 6 6.72v3.28h2v-3.28c.91-.13 1.77-.45 2.54-.9l-1.56-1.56zM7.53 11c0-1.05.35-2.01.93-2.77L6.68 6.44A5.85 5.85 0 0 0 5.83 11h1.7zM12 14c1.66 0 2.99-1.34 2.99-3L15 5c0-1.66-1.34-3-3-3S9 3.34 9 5c0 1-.22 1.94-.61 2.76l1.45 1.45C10.55 8.7 11.23 8.35 12 8.35c.98 0 1.77.79 1.77 1.77 0 .77-.49 1.44-1.19 1.68l1.6 1.6c.45-.66.72-1.48.72-2.4v6c0 .48-.1.93-.27 1.35l1.2 1.2c.48-.7.83-1.52 1.02-2.4h-1.75zM4.27 3L3 4.27l6.01 6.01c-.01.24-.01.48-.01.72v6c0 1.66 1.34 3 3 3 .24 0 .48 0 .72-.01l6.01 6.01L21 19.73 4.27 3z"/></svg></span>
                </div>
              </div>
            </div>

          </div><!-- end mtg-stage -->

          <!-- MID STAGE: REASONING & CHAT THREAD (MEETING CHAT) -->
          <div class="mtg-chat-area">
            
            <div class="mtg-chat-header">会议通讯录 (Meeting Transcripts)</div>
            <div class="mtg-chat-scroll custom-scrollbar" ref="chatScrollRef">
              
              <!-- Init MSG -->
              <div v-if="messages.length <= 1" class="mtg-msg mtg-msg-sys">
                 <span>[System] 会议已桥接。多模态 Agent 组队完成。聚焦目标《{{selectedCompany}}》. 等待指挥台接入指令。</span>
              </div>

              <!-- Messages Loop -->
              <template v-for="message in messages" :key="message.id">
                
                <div v-if="message.kind === 'query'" class="mtg-msg mtg-msg-user">
                  <div class="mtg-msg-avatar">MD</div>
                  <div class="mtg-msg-content">
                    <div class="mtg-msg-author">指挥台 (You)</div>
                    <div class="mtg-msg-text">{{ message.text }}</div>
                  </div>
                </div>

                <div v-else-if="message.kind === 'answer'" class="mtg-msg mtg-msg-ai">
                  <div class="mtg-msg-avatar"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" class="mtg-icon-sm pt-1"><path d="M12 2a2 2 0 0 1 2 2v2a2 2 0 0 1-2 2h0a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z"/><path d="M12 8v14"/><path d="M5.5 14H12"/><path d="M18.5 14H12"/></svg></div>
                  <div class="mtg-msg-content">
                    <div class="mtg-msg-author">Core Engine</div>
                    <div class="mtg-msg-bubble">
                      <section v-for="section in message.payload?.answer_sections" :key="section.title" class="mb-4">
                        <strong class="cot-color-emerald">{{ section.title }}</strong><br/>
                        <span v-for="line in section.lines" :key="line" style="display:block; margin-top: 4px;">{{ line }}</span>
                      </section>
                      <div v-if="(!message.payload?.answer_sections || message.payload.answer_sections.length === 0) && message.text">
                        {{ message.text }}
                      </div>
                    </div>
                  </div>
                </div>
              </template>

              <!-- CoT Live Tracker (Reasoning Panel) -->
              <div v-if="workflowLanes.length > 0 && loadingTurn" class="mtg-msg mtg-msg-sys mtg-reasoning-panel">
                <div class="mtg-reasoning-title"><svg class="mtg-icon-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline></svg> Chain of Thought (Live Trace)</div>
                <div class="mtg-cot-lane" v-for="lane in workflowLanes" :key="lane.key">
                  <span :class="['mtg-lane-dot', lane.status === 'Processing' ? 'mtg-pulse-blue' : 'mtg-solid-green']"></span>
                  <span style="width: 120px; color: #9ca3af">[{{ lane.agent }}]</span>
                  <span class="mtg-lane-truncate" :style="{ color: lane.status === 'Processing' ? '#fff' : '#6b7280' }">{{ lane.title }}</span>
                </div>
              </div>

              <!-- Loading Indicator -->
              <div v-if="loadingTurn" class="mtg-msg mtg-msg-ai">
                 <div class="mtg-msg-avatar">
                   <svg class="mtg-icon-sm animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-6.219-8.56"></path></svg>
                 </div>
              </div>
              <ErrorState v-if="turnError" :message="turnError" />

            </div>
          </div>
        </div>

        <!-- RIGHT SIDEBAR: SUPPORTING INFO DOCK (Shared Material) -->
        <div class="mtg-sidebar">
          <div class="mtg-sidebar-header">会议材料辅屏 (Shared Intel)</div>
          
          <div class="mtg-sidebar-body custom-scrollbar">
            <template v-if="latestAnswer">
              <!-- Insight Cards -->
              <div v-if="latestAnswer.insight_cards?.length" class="mtg-sb-block">
                <h3><span class="mtg-dot"></span>核心量化指标 (Metrics)</h3>
                <div class="mtg-ic-grid">
                  <div v-for="item in latestAnswer.insight_cards" :key="item.label" class="mtg-ic-card">
                    <div class="mtg-ic-lbl">{{ item.label }}</div>
                    <div class="mtg-ic-val">{{ item.value }} <span class="text-xs text-gray-400">{{item.unit}}</span></div>
                  </div>
                </div>
              </div>

              <!-- Actions/Risks -->
              <div v-if="latestAnswer.action_cards?.length" class="mtg-sb-block">
                <h3><span class="mtg-dot mtg-dot-red"></span>风险/行动点 (Actions)</h3>
                <div class="mtg-act-list">
                  <TagPill
                    v-for="item in latestAnswer.action_cards"
                    :key="item.title"
                    :label="`[${item.priority}] ${item.title}`"
                    :tone="item.priority.toLowerCase() === 'high' ? 'danger' : 'warning'"
                  />
                </div>
              </div>
            </template>
            <div v-else class="mtg-sb-empty">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>
              <span>暂无演示材料</span>
            </div>

             <!-- Pre-rendered Charts as follow up inside AI Response area -->
             <div v-if="charts.length > 0" class="mtg-sb-block mtg-sb-charts">
                <h3><span class="mtg-dot mtg-dot-blue"></span>实时图表 (Charts)</h3>
                <div v-for="chart in charts" :key="chart.title" class="mtg-sb-chart">
                  <ChartPanel :options="chart.options" />
                </div>
             </div>
          </div>
        </div>
      </div> <!-- end mtg-body -->

      <!-- BOTTOM CONTROL BAR -->
      <footer class="mtg-footer">
        <!-- Quick Prompts (floating above input) -->
        <div class="mtg-quick-prompts">
          <button v-for="item in starterQueries.slice(0,4)" :key="item" class="mtg-qp" @click="runQuery(`${selectedCompany} ${item}`)">
            {{ item }}
          </button>
        </div>

        <div class="mtg-controls-wrap">
          <!-- Fake AV Controls -->
          <div class="mtg-av-controls">
            <div class="mtg-av-btn active"><svg viewBox="0 0 24 24"><path d="M12 14c1.66 0 2.99-1.34 2.99-3L15 5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm5.3-3c0 3-2.54 5.1-5.3 5.1S6.7 14 6.7 11H5c0 3.41 2.72 6.23 6 6.72V21h2v-3.28c3.28-.48 6-3.3 6-6.72h-1.7z"/></svg><span>解除静音</span></div>
            <div class="mtg-av-btn"><svg viewBox="0 0 24 24"><path d="M21 6h-7.59l3.29-3.29L16 1.3 11.71 5.58m4.29 4.42l-4.29 4.29-1.41-1.41 4.29-4.29zm-8.8 8l2.79 2.79-1.41 1.41-2.79-2.79-1.41-1.41L1.3 16l1.41-1.41 2.79 2.79 1.41 1.41 2.79-2.79zM5.58 11.71L1.3 16l1.41 1.41 4.29-4.29zm8.42-8.42L16.79 6H21V4h-7z"/></svg><span>开启摄像头</span></div>
            <div class="mtg-av-btn highlight"><svg viewBox="0 0 24 24"><path d="M20 3H4c-1.11 0-2 .89-2 2v10c0 1.11.89 2 2 2h6v2H8v2h8v-2h-2v-2h6c1.11 0 2-.89 2-2V5c0-1.11-.89-2-2-2zm0 12H4V5h16v10z"/></svg><span>共享屏幕</span></div>
          </div>

          <!-- Main Input -->
          <div class="mtg-input-box">
             <textarea
               v-model="query"
               class="mtg-textarea custom-scrollbar"
               placeholder="发送消息到会议室，或使用宏指令如 /stress ..."
               @keydown.enter="handleEnter"
             />
             <button class="mtg-send-btn" :disabled="loadingTurn || !query" @click="runQuery()">
               <svg v-if="loadingTurn" class="mtg-icon-sm animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor"><circle cx="12" cy="12" r="10" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
               <svg v-else class="mtg-icon-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>
             </button>
          </div>
        </div>
      </footer>
    </div>
  </AppShell>
</template>

<style scoped>
/* Full App Takeover */
.mtg-container { display: flex; flex-direction: column; height: 100vh; width: 100vw; background: #141414; color: #fff; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; overflow: hidden; margin: -16px -24px -24px; padding: 0; box-sizing: border-box; }
* { box-sizing: border-box; }

/* HEADER */
.mtg-header { height: 56px; display: flex; align-items: center; justify-content: space-between; padding: 0 16px; background: #1d1d1d; border-bottom: 1px solid #2a2a2a; flex-shrink: 0; }
.mtg-header-left { display: flex; align-items: center; gap: 12px; }
.mtg-icon-shield { width: 20px; height: 20px; color: #10b981; }
.mtg-title-block h1 { margin: 0; font-size: 15px; font-weight: 500; color: #fff; }
.mtg-meeting-id { font-size: 11px; color: #9ca3af; font-family: monospace; }

.mtg-header-center { flex: 1; display: flex; justify-content: center; }
.mtg-target-selector { background: #2a2a2a; border-radius: 6px; display: flex; align-items: center; padding: 2px 8px; border: 1px solid #333; }
.mtg-lbl { font-size: 12px; color: #9ca3af; margin-right: 8px; }
.mtg-select { background: transparent; border: none; color: #10b981; font-weight: 500; outline: none; font-size: 13px; cursor: pointer; }

.mtg-header-right { display: flex; align-items: center; gap: 16px; font-size: 12px; color: #d1d5db; }
.mtg-network { display: flex; align-items: center; gap: 4px; }
.mtg-btn-leave { background: #dc2626; color: white; border: none; border-radius: 4px; padding: 6px 16px; font-size: 12px; font-weight: 500; cursor: pointer; transition: background 0.2s; }
.mtg-btn-leave:hover { background: #b91c1c; }

/* BODY */
.mtg-body { flex: 1; display: flex; overflow: hidden; }

/* COL MAIN (Stage + Chat) */
.mtg-col-main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }

/* TOP STAGE (Participant Video Tiles) */
.mtg-stage { height: 200px; padding: 16px; display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; background: #0a0a0a; border-bottom: 1px solid #2a2a2a; flex-shrink: 0; }
.mtg-tile { background: #222; border-radius: 8px; border: 1px solid #333; overflow: hidden; position: relative; display: flex; align-items: center; justify-content: center; transition: all 0.3s ease; }
.mtg-tile.speaking { border-color: #10b981; box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.2); }
.mtg-tile-content { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; }
.mtg-avatar { width: 64px; height: 64px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 24px; font-weight: 600; color: #fff; background: #333; }
.user-avatar { background: #2563eb; }
.data-avatar { background: #059669; }
.risk-avatar { background: #d97706; }
.strat-avatar { background: #7c3aed; }
.mtg-tile-label { font-size: 12px; color: #fff; background: rgba(0,0,0,0.6); padding: 4px 12px; border-radius: 12px; position: absolute; bottom: 12px; left: 12px; display: flex; align-items: center; gap: 6px; }
.mtg-status-mic { width: 14px; height: 14px; color: #10b981; }
.mtg-status-mic.muted { color: #f43f5e; }

/* CHAT AREA */
.mtg-chat-area { flex: 1; display: flex; flex-direction: column; background: #141414; overflow: hidden; }
.mtg-chat-header { font-size: 12px; color: #9ca3af; padding: 12px 24px; border-bottom: 1px solid #2a2a2a; background: #1a1a1a; font-weight: 500; letter-spacing: 0.05em; }
.mtg-chat-scroll { flex: 1; overflow-y: auto; padding: 24px; display: flex; flex-direction: column; gap: 16px; scroll-behavior: smooth; }

.mtg-msg { display: flex; gap: 16px; max-width: 900px; margin: 0 auto; width: 100%; }
.mtg-msg-avatar { width: 36px; height: 36px; border-radius: 6px; background: #333; flex-shrink: 0; display: flex; align-items: center; justify-content: center; font-size: 14px; font-weight: bold; }
.mtg-msg-user .mtg-msg-avatar { background: #2563eb; }
.mtg-msg-ai .mtg-msg-avatar { background: #10b981; }
.mtg-msg-sys { padding: 12px 16px; background: #1e1e1e; border: 1px solid #333; border-radius: 8px; color: #9ca3af; font-size: 13px; font-family: monospace; }
.mtg-msg-content { flex: 1; min-width: 0; }
.mtg-msg-author { font-size: 12px; color: #9ca3af; margin-bottom: 6px; }
.mtg-msg-text { font-size: 14px; line-height: 1.6; color: #e5e7eb; }
.mtg-msg-bubble { background: #1e1e1e; border: 1px solid #2a2a2a; border-radius: 8px; padding: 16px; font-size: 14px; line-height: 1.6; color: #e5e7eb; }
.cot-color-emerald { color: #10b981; }

.mtg-reasoning-panel { background: rgba(59, 130, 246, 0.05); border: 1px solid rgba(59, 130, 246, 0.2); flex-direction: column; gap: 8px; align-items: flex-start; }
.mtg-reasoning-title { display: flex; align-items: center; gap: 8px; color: #60a5fa; font-weight: bold; margin-bottom: 8px; }
.mtg-cot-lane { display: flex; align-items: center; gap: 12px; width: 100%; font-size: 12px; }
.mtg-lane-dot { width: 8px; height: 8px; border-radius: 50%; }
.mtg-pulse-blue { background: #60a5fa; box-shadow: 0 0 8px #60a5fa; animation: pulse 1.5s infinite; }
.mtg-solid-green { background: #10b981; }
.mtg-lane-truncate { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

/* RIGHT SIDEBAR (DOCKING INFO BOARD) */
.mtg-sidebar { width: 340px; background: #1a1a1a; border-left: 1px solid #2a2a2a; display: flex; flex-direction: column; flex-shrink: 0; }
.mtg-sidebar-header { height: 48px; display: flex; align-items: center; padding: 0 16px; font-size: 14px; font-weight: 500; border-bottom: 1px solid #2a2a2a; color: #f3f4f6; }
.mtg-sidebar-body { flex: 1; overflow-y: auto; padding: 16px; }
.mtg-sb-empty { height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; color: #6b7280; gap: 12px; font-size: 14px; }
.mtg-sb-empty svg { width: 48px; height: 48px; opacity: 0.5; }

.mtg-sb-block { margin-bottom: 24px; }
.mtg-sb-block h3 { margin: 0 0 12px 0; font-size: 13px; color: #d1d5db; display: flex; align-items: center; gap: 8px; }
.mtg-dot { width: 8px; height: 8px; border-radius: 50%; background: #10b981; }
.mtg-dot-red { background: #f43f5e; }
.mtg-dot-blue { background: #3b82f6; }

.mtg-ic-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.mtg-ic-card { background: #222; border: 1px solid #333; padding: 12px; border-radius: 6px; }
.mtg-ic-lbl { font-size: 11px; color: #9ca3af; margin-bottom: 4px; }
.mtg-ic-val { font-size: 16px; font-weight: bold; color: #fff; }
.mtg-act-list { display: flex; flex-direction: column; gap: 8px; }

.mtg-sb-charts { margin-top: 24px; border-top: 1px solid #2a2a2a; padding-top: 16px; }
.mtg-sb-chart { height: 200px; background: #222; border: 1px solid #333; border-radius: 6px; overflow: hidden; margin-bottom: 16px; }

/* BOTTOM CONTROL BAR */
.mtg-footer { background: #1d1d1d; border-top: 1px solid #2a2a2a; display: flex; flex-direction: column; z-index: 10; position: relative; }
.mtg-quick-prompts { display: flex; gap: 8px; padding: 8px 16px 0; }
.mtg-qp { background: #2a2a2a; border: 1px solid #333; color: #d1d5db; font-size: 11px; padding: 4px 12px; border-radius: 12px; cursor: pointer; white-space: nowrap; transition: 0.2s; }
.mtg-qp:hover { background: #333; border-color: #4b5563; }

.mtg-controls-wrap { display: flex; align-items: center; padding: 12px 24px; gap: 24px; }
.mtg-av-controls { display: flex; gap: 8px; }
.mtg-av-btn { width: 64px; display: flex; flex-direction: column; align-items: center; gap: 6px; color: #9ca3af; cursor: pointer; transition: 0.2s; }
.mtg-av-btn:hover { color: #fff; }
.mtg-av-btn svg { width: 24px; height: 24px; fill: currentColor; }
.mtg-av-btn span { font-size: 10px; }
.mtg-av-btn.active { color: #fff; }
.mtg-av-btn.highlight { color: #10b981; }

.mtg-input-box { flex: 1; display: flex; background: #222; border: 1px solid #333; border-radius: 8px; overflow: hidden; padding: 4px; transition: border 0.2s; }
.mtg-input-box:focus-within { border-color: #10b981; }
.mtg-textarea { flex: 1; background: transparent; border: none; outline: none; padding: 12px; color: #fff; font-size: 14px; resize: none; min-height: 48px; max-height: 96px; line-height: 1.5; }
.mtg-send-btn { width: 44px; display: flex; align-items: center; justify-content: center; background: transparent; border: none; color: #10b981; cursor: pointer; border-radius: 6px; }
.mtg-send-btn:hover:not(:disabled) { background: rgba(16, 185, 129, 0.1); }
.mtg-send-btn:disabled { color: #4b5563; cursor: not-allowed; }

.mtg-icon-sm { width: 18px; height: 18px; }

/* UTILS */
.animate-spin { animation: spin 1s linear infinite; }
@keyframes spin { 100% { transform: rotate(360deg); } }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: .5; } }
.custom-scrollbar::-webkit-scrollbar { width: 6px; height: 6px; }
.custom-scrollbar::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 3px; }
.custom-scrollbar::-webkit-scrollbar-track { background: transparent; }
</style>
