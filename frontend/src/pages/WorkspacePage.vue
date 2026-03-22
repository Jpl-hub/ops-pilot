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
    status: item.status === 'completed' ? 'Done' : 'Processing',
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

function handleEnter(e: KeyboardEvent) {
  if (!e.shiftKey) {
    e.preventDefault()
    runQuery()
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

watch(selectedCompany, async (company, previous) => {
  if (!company || company === previous) return
  await workspace.loadCompanyWorkspace(session.activeRole.value || 'investor')
})
</script>

<template>
  <AppShell title="">
    <div class="cot-layout">
      <!-- Top Branding specific to Workspace -->
      <header class="cot-header">
        <div class="cot-header-left">
          <svg class="cot-icon-lg cot-color-emerald" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path></svg>
          <h1 class="cot-h1">多智能体协同研判 (Multi-Agent CoT)</h1>
        </div>
        <div class="cot-header-sub">
          DATA <span class="cot-muted-cross">×</span> RISK <span class="cot-muted-cross">×</span> STRATEGY <span class="cot-muted-cross">×</span> SELF-REFLECTION
        </div>
        <div class="cot-header-right">
          <label class="cot-target-lbl">Target Entity:</label>
          <select v-model="selectedCompany" class="cot-select">
            <option v-for="company in companies" :key="company" :value="company" class="cot-opt">{{ company }}</option>
          </select>
        </div>
      </header>

      <!-- Main Central Chat Canvas -->
      <div class="cot-canvas custom-scrollbar" ref="threadRef">
        <div class="cot-max-width">
          
          <ErrorState v-if="overviewError" :message="overviewError" class="cot-mb-6" />

          <!-- Dynamic CoT Visulization Block -->
          <div v-if="workflowLanes.length > 0 || controlPlane" class="cot-proc-block cot-mb-8">
            <div class="cot-proc-head">
              <svg class="cot-icon-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path><polyline points="3.29 7.08 12 12.05 20.71 7.08"></polyline><line x1="12" y1="22.08" x2="12" y2="12"></line></svg>
              CHAIN OF THOUGHT (CoT) PROCESS
            </div>
            <div class="cot-proc-lanes">
              <div v-for="lane in workflowLanes" :key="lane.key" class="cot-proc-lane">
                <span class="cot-lane-text">
                  <strong :class="`agent-${lane.agent.toLowerCase().replace(/\s/g, '-')}`">[{{ lane.agent }} Agent]</strong>
                  {{ lane.title }}
                </span>
                <span class="cot-lane-status" :class="lane.status === 'Done' ? 'cot-color-emerald' : 'cot-color-blue animate-pulse'">
                  {{ lane.status === 'Done' ? '✓ Done' : '↻ Processing' }}
                </span>
              </div>
            </div>
            <div v-if="controlPlane" class="cot-proc-foot">
              <span>Session: <strong class="cot-color-white">{{ controlPlane.session_label }}</strong></span>
              <span>Overall Progress: {{ controlPlane.steps_completed }}/{{ controlPlane.step_total }} Steps</span>
            </div>
          </div>

          <!-- Empty State / Init Log -->
          <div v-if="messages.length <= 1 && !loadingTurn" class="cot-card cot-init-card cot-mb-8">
            <div class="cot-init-text">
              <span class="cot-color-emerald">[System Initialization]</span> Multi-Agent Collaboration Framework Activated.<br/>
              <span class="cot-color-emerald">[Persona]</span> {{ roleCopy.title }}<br/>
              <span class="cot-color-emerald">[Time Stamp]</span> {{ new Date().toISOString().replace('T', ' ').substring(0, 19) }} UTC<br/>
              <span class="cot-color-emerald">[Processing Mode]</span> Objective, Data-Driven, Hardcore Financial & Strategic Analysis<br/>
              <br/>
              系统已就绪，当前聚焦企业：<strong class="cot-color-white">{{ selectedCompany }}</strong>。随时接受复杂交叉研判指令。
            </div>
          </div>

          <!-- Message Thread -->
          <template v-for="message in messages" :key="message.id">
            
            <!-- User Prompt -->
            <div v-if="message.kind === 'query'" class="cot-row-user cot-mb-8">
              <div class="cot-user-bubble">
                {{ message.text }}
              </div>
            </div>

            <!-- AI Response -->
            <div v-else-if="message.kind === 'answer'" class="cot-card cot-mb-8">
               <div class="cot-ans-header">
                 <div class="cot-ans-top">
                   <div class="cot-logo-box">
                     <svg class="cot-icon-md cot-color-emerald" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a2 2 0 0 1 2 2v2a2 2 0 0 1-2 2h0a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z"/><path d="M12 8v14"/><path d="M5.5 14H12"/><path d="M18.5 14H12"/></svg>
                   </div>
                   <h3 class="cot-ans-title">
                     {{ message.payload?.company_name || '行业视图' }} <span v-if="message.payload?.report_period" class="cot-ans-period">({{ message.payload.report_period }})</span>
                   </h3>
                 </div>
               </div>

               <div class="cot-ans-body">
                 <!-- text sections -->
                 <section v-for="section in message.payload?.answer_sections" :key="section.title" class="cot-mb-6">
                    <h4 class="cot-sec-title">
                      <span class="cot-dot-emerald"></span> {{ section.title }}
                    </h4>
                    <div class="cot-sec-lines">
                      <div v-for="line in section.lines" :key="line" class="cot-sec-line">
                        {{ line }}
                      </div>
                    </div>
                 </section>
                 
                 <!-- Insight Cards / Metrics -->
                 <div v-if="message.payload?.insight_cards?.length" class="cot-insight-grid cot-mb-6">
                   <div v-for="item in message.payload.insight_cards" :key="item.label" class="cot-insight-card">
                     <div class="cot-ic-label">{{ item.label }}</div>
                     <div class="cot-ic-value">{{ item.value }}<span v-if="item.unit" class="cot-ic-unit">{{ item.unit }}</span></div>
                   </div>
                 </div>

                 <!-- Action Tags -->
                 <div v-if="message.payload?.action_cards?.length" class="cot-action-tags">
                    <TagPill
                      v-for="item in message.payload.action_cards"
                      :key="item.title"
                      :label="`[${item.priority}] ${item.title}`"
                      tone="success"
                      class="cot-action-pill"
                    />
                 </div>
               </div>
            </div>

            <!-- Pre-rendered Charts as follow up inside AI Response area -->
            <div v-if="message.kind === 'answer' && charts.length > 0" class="cot-card cot-mb-8">
               <h4 class="cot-sec-title cot-p-6">
                 <span class="cot-dot-blue"></span> 深度数据穿透视图 (Data Insights)
               </h4>
               <div class="cot-chart-grid">
                 <div v-for="chart in charts" :key="chart.title" class="cot-chart-wrapper">
                   <ChartPanel :options="chart.options" class="cot-chart-naked" />
                 </div>
               </div>
            </div>

          </template>

          <LoadingState v-if="loadingTurn" class="cot-loading cot-mb-8" />
          <ErrorState v-if="turnError" :message="turnError" class="cot-mb-8" />
        </div>
      </div>

      <!-- Footer Control Panel -->
      <footer class="cot-footer">
        <div class="cot-input-block">
          <div class="cot-textarea-container">
             <!-- Real prompt input -->
             <textarea
               v-model="query"
               class="cot-textarea custom-scrollbar"
               placeholder="输入复杂研判指令，例如：'推演当前高管变更带来的战略不确定性对毛利率的量化影响'..."
               @keydown.enter="handleEnter"
             />
             <button class="cot-send-btn outline-none focus:outline-none" :disabled="loadingTurn || loadingOverview || !query" @click="runQuery()">
               <svg v-if="loadingTurn" class="cot-icon-md animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-6.219-8.56"></path></svg>
               <svg v-else class="cot-icon-md" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>
             </button>
          </div>
          <div class="cot-quick-bar">
             <span class="cot-qp-lbl">Quick Prompts:</span>
             <button v-for="item in starterQueries.slice(0, 3)" :key="item" class="cot-qp-btn" @click="runQuery(`${selectedCompany} ${item}`)">
               &gt;&gt; {{ item }}
             </button>
          </div>
        </div>

        <!-- System Meta Bar (replaces the noisy right column) -->
        <div class="cot-system-bar">
           <div class="cot-sys-left">
             <div class="cot-dot-pulse"></div>
             <span>System Online: {{ overviewSummary ? '99.9%' : 'Connecting' }}</span>
           </div>
           
           <div class="cot-sys-right">
             <span>
               预警池: <strong class="cot-color-rose">{{ overviewSummary?.total_alerts || 0 }}</strong>
             </span>
             <span>
               在办任务: <strong class="cot-color-blue">{{ taskSummary?.in_progress || 0 }}</strong>
             </span>
             <span>
               数据库覆盖: <strong class="cot-color-emerald">{{ overviewSummary?.active_companies || 0 }} 家企业</strong>
             </span>
           </div>
        </div>
      </footer>

    </div>
  </AppShell>
</template>

<style scoped>
/* Full App Takeover */
.cot-layout { display: flex; flex-direction: column; height: 100%; width: 100%; background: #080808; color: #e2e8f0; font-family: ui-sans-serif, system-ui, sans-serif; overflow: hidden; margin: -16px -24px -24px; padding: 0; }

/* Utilities */
.cot-mb-6 { margin-bottom: 24px; }
.cot-mb-8 { margin-bottom: 32px; }
.cot-p-6 { padding: 24px 24px 0 24px; }
.cot-color-emerald { color: #10b981; }
.cot-color-blue { color: #60a5fa; }
.cot-color-rose { color: #f43f5e; }
.cot-color-white { color: #ffffff; }
.cot-icon-sm { width: 16px; height: 16px; }
.cot-icon-md { width: 20px; height: 20px; }
.cot-icon-lg { width: 24px; height: 24px; }
.cot-muted-cross { margin: 0 8px; color: rgba(255, 255, 255, 0.2); }

/* Header */
.cot-header { display: flex; align-items: center; justify-content: space-between; padding: 16px 32px; border-bottom: 1px solid rgba(255,255,255,0.05); background: rgba(0,0,0,0.5); backdrop-filter: blur(12px); z-index: 20; flex-shrink: 0; }
.cot-header-left { display: flex; align-items: center; gap: 12px; }
.cot-h1 { font-size: 20px; font-weight: bold; letter-spacing: -0.02em; color: #fff; margin: 0; }
.cot-header-sub { font-family: 'JetBrains Mono', monospace; font-size: 11px; letter-spacing: 0.1em; color: #64748b; display: none; }
@media (min-width: 768px) { .cot-header-sub { display: block; } }
.cot-header-right { display: flex; align-items: center; gap: 12px; }
.cot-target-lbl { font-size: 12px; font-family: monospace; color: #6b7280; text-transform: uppercase; letter-spacing: 0.05em; display: none; }
@media (min-width: 640px) { .cot-target-lbl { display: block; } }
.cot-select { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); color: #fff; padding: 6px 16px; border-radius: 6px; outline: none; font-size: 14px; }
.cot-opt { background: #000; }

/* Chat Area */
.cot-canvas { flex: 1; overflow-y: auto; overflow-x: hidden; padding: 32px; scroll-behavior: smooth; }
.cot-max-width { max-width: 900px; margin: 0 auto; width: 100%; }

/* Bubble Cards */
.cot-card { background: #121212; border: 1px solid rgba(255,255,255,0.05); border-radius: 12px; box-shadow: 0 4px 20px -5px rgba(0,0,0,0.5); overflow: hidden; }
.cot-row-user { display: flex; justify-content: flex-end; }
.cot-user-bubble { background: rgba(59, 130, 246, 0.1); border: 1px solid rgba(59, 130, 246, 0.2); border-radius: 12px; padding: 16px 24px; color: #bfdbfe; font-size: 15px; line-height: 1.6; max-width: 80%; box-shadow: 0 4px 15px rgba(0,0,0,0.2); white-space: pre-wrap; }

.cot-ans-header { padding: 24px; border-bottom: 1px solid rgba(255,255,255,0.05); background: rgba(0,0,0,0.2); }
.cot-ans-top { display: flex; align-items: center; gap: 12px; }
.cot-logo-box { background: rgba(16, 185, 129, 0.2); padding: 8px; border-radius: 8px; border: 1px solid rgba(16, 185, 129, 0.3); display: flex; align-items: center; justify-content: center; }
.cot-ans-title { margin: 0; font-size: 18px; font-weight: 600; color: #fff; letter-spacing: 0.02em; }
.cot-ans-period { color: #9ca3af; font-weight: 400; font-size: 16px; margin-left: 8px; }
.cot-ans-body { padding: 24px; }

/* Chain of Thought Process Block */
.cot-proc-block { background: rgba(0,0,0,0.4); border: 1px solid rgba(255,255,255,0.05); border-radius: 12px; padding: 24px; font-family: 'JetBrains Mono', monospace; }
.cot-proc-head { color: #34d399; font-size: 12px; font-weight: bold; letter-spacing: 0.1em; display: flex; align-items: center; gap: 8px; margin-bottom: 16px; }
.cot-proc-lanes { display: flex; flex-direction: column; gap: 8px; }
.cot-proc-lane { display: flex; justify-content: space-between; align-items: center; background: rgba(255,255,255,0.02); padding: 8px 16px; border-radius: 6px; }
.cot-lane-text { font-size: 14px; color: #d1d5db; }
.cot-lane-status { font-size: 14px; }
.cot-proc-foot { margin-top: 16px; padding-top: 12px; border-top: 1px solid rgba(255,255,255,0.1); display: flex; justify-content: space-between; align-items: center; font-size: 12px; color: #9ca3af; }

/* Agent Colors */
.agent-data { color: #60a5fa; }
.agent-risk { color: #f59e0b; }
.agent-strategy { color: #a855f7; }
.agent-self-reflection { color: #ec4899; }

/* Init Log */
.cot-init-card { background: transparent !important; border: none !important; box-shadow: none !important; opacity: 0.7; }
.cot-init-text { font-family: 'JetBrains Mono', monospace; font-size: 14px; color: #9ca3af; line-height: 1.8; }

/* Sections */
.cot-sec-title { font-family: 'JetBrains Mono', monospace; color: #10b981; margin: 0 0 12px 0; font-size: 14px; display: flex; align-items: center; gap: 8px; }
.cot-dot-emerald { width: 6px; height: 6px; background-color: #10b981; border-radius: 50%; }
.cot-dot-blue { width: 6px; height: 6px; background-color: #60a5fa; border-radius: 50%; }
.cot-sec-lines { display: flex; flex-direction: column; gap: 8px; color: #d1d5db; font-size: 14px; line-height: 1.6; white-space: pre-wrap; }
.cot-sec-line { position: relative; padding-left: 12px; }
.cot-sec-line::before { content: ''; position: absolute; left: 0; top: 10px; width: 4px; height: 4px; background: rgba(255,255,255,0.2); border-radius: 50%; }

/* Insights */
.cot-insight-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 16px; padding-top: 16px; border-top: 1px solid rgba(255,255,255,0.05); }
.cot-insight-card { background: rgba(0,0,0,0.4); padding: 12px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.05); }
.cot-ic-label { font-size: 12px; font-family: 'JetBrains Mono', monospace; color: #6b7280; text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 4px; }
.cot-ic-value { font-size: 20px; font-weight: 600; color: #fff; }
.cot-ic-unit { font-size: 14px; color: #9ca3af; margin-left: 4px; }

/* Action Tags */
.cot-action-tags { display: flex; flex-wrap: wrap; gap: 8px; padding-top: 8px; border-top: 1px solid rgba(255,255,255,0.05); }
:deep(.cot-action-pill) { border-radius: 6px !important; background: rgba(16, 185, 129, 0.1) !important; border: 1px solid rgba(16, 185, 129, 0.2) !important; color: #34d399 !important; font-family: monospace !important; }

/* Follow-up Charts */
.cot-chart-grid { display: grid; grid-template-columns: 1fr; gap: 24px; padding: 24px; }
@media (min-width: 1024px) { .cot-chart-grid { grid-template-columns: 1fr 1fr; } }
.cot-chart-wrapper { background: rgba(0,0,0,0.4); border: 1px solid rgba(255,255,255,0.05); border-radius: 12px; display: flex; flex-direction: column; min-height: 340px; }
:deep(.cot-chart-naked) { background: transparent !important; padding: 16px !important; border: none !important; flex: 1 !important; height: 100% !important; min-height: 300px !important; }

/* Loading & Error */
.cot-loading { padding: 48px; background: transparent; }

/* Footer */
.cot-footer { display: flex; flex-direction: column; background: #000; border-top: 1px solid rgba(255,255,255,0.05); z-index: 20; flex-shrink: 0; }
.cot-input-block { padding: 24px 32px 16px; display: flex; flex-direction: column; align-items: center; }
.cot-textarea-container { position: relative; width: 100%; max-width: 900px; background: #121212; border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; transition: border-color 0.2s; display: flex; }
.cot-textarea-container:focus-within { border-color: rgba(16, 185, 129, 0.5); box-shadow: 0 0 15px rgba(16, 185, 129, 0.1); }
.cot-textarea { flex: 1; min-height: 56px; max-height: 120px; background: transparent; border: none; padding: 16px 56px 16px 20px; font-size: 14px; color: #fff; resize: none; outline: none; line-height: 1.5; }
.cot-send-btn { position: absolute; right: 12px; bottom: 12px; height: 32px; width: 32px; display: flex; align-items: center; justify-content: center; background: rgba(16, 185, 129, 0.1); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.2); border-radius: 8px; cursor: pointer; transition: all 0.2s; }
.cot-send-btn:hover:not(:disabled) { background: #10b981; color: #000; }
.cot-send-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.cot-quick-bar { width: 100%; max-width: 900px; margin-top: 12px; display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.cot-qp-lbl { font-size: 10px; font-family: 'JetBrains Mono', monospace; font-weight: bold; color: #059669; letter-spacing: 0.1em; text-transform: uppercase; margin-right: 8px; }
.cot-qp-btn { background: transparent; border: none; font-family: 'JetBrains Mono', monospace; font-size: 11px; color: #64748b; cursor: pointer; transition: color 0.2s; white-space: nowrap; }
.cot-qp-btn:hover { color: #d1d5db; }

/* System Bar */
.cot-system-bar { padding: 8px 32px; border-top: 1px solid rgba(255,255,255,0.03); display: flex; justify-content: space-between; align-items: center; background: rgba(0,0,0,0.8); }
.cot-sys-left { display: flex; align-items: center; gap: 8px; font-size: 10px; color: #6b7280; font-family: 'JetBrains Mono', monospace; letter-spacing: 0.1em; text-transform: uppercase; }
.cot-dot-pulse { width: 8px; height: 8px; border-radius: 50%; background-color: #10b981; animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite; }
.cot-sys-right { display: flex; align-items: center; gap: 24px; font-size: 10px; color: #6b7280; font-family: 'JetBrains Mono', monospace; letter-spacing: 0.1em; text-transform: uppercase; display: none; }
@media (min-width: 768px) { .cot-sys-right { display: flex; } }

/* Animations */
.animate-spin { animation: spin 1s linear infinite; }
@keyframes spin { 100% { transform: rotate(360deg); } }
.animate-pulse { animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: .5; } }
.custom-scrollbar::-webkit-scrollbar { width: 6px; height: 6px; }
.custom-scrollbar::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 3px; }
.custom-scrollbar::-webkit-scrollbar-track { background: transparent; }
</style>
