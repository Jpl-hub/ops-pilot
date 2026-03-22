<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import AppShell from '@/components/AppShell.vue'
import ChartPanel from '@/components/ChartPanel.vue'
import LoadingState from '@/components/LoadingState.vue'
import { useAsyncState } from '@/composables/useAsyncState'
import { get, loadAccessToken } from '@/lib/api'

const state = useAsyncState<any>()
const historyState = useAsyncState<any>()
const livePayload = ref<any | null>(null)
const wsStatus = ref<'connecting' | 'connected' | 'disconnected'>('connecting')
let socket: WebSocket | null = null

const payload = computed(() => livePayload.value || state.data.value)
const marketTape = computed(() => payload.value?.market_tape || [])
const brainCommandSurface = computed(() => payload.value?.brain_command_surface || null)
const executionFlash = computed(() => payload.value?.execution_flash || [])
const liveEvents = computed(() => payload.value?.live_events || [])
const attentionMatrix = computed(() => payload.value?.attention_matrix || [])

// Derive sentiment score based on command surface intensity
const sentimentScore = computed(() => {
  return brainCommandSurface.value?.intensity || 50
})

const showForecast = ref(false)

function connectStream() {
  const token = loadAccessToken()
  if (!token) {
    wsStatus.value = 'disconnected'
    return
  }
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const url = `${protocol}://${window.location.hostname}:8000/api/v1/ws/industry-brain?token=${encodeURIComponent(token)}`
  socket = new WebSocket(url)
  wsStatus.value = 'connecting'

  socket.onopen = () => {
    wsStatus.value = 'connected'
  }

  socket.onmessage = (event) => {
    livePayload.value = JSON.parse(event.data)
  }

  socket.onclose = () => { wsStatus.value = 'disconnected' }
  socket.onerror = () => { wsStatus.value = 'disconnected' }
}

onMounted(async () => {
  try {
    await state.execute(() => get('/industry/brain'))
  } catch (error) {
    console.error('Backend 500 Error Gracefully Caught:', error)
  }
  connectStream()
})

onBeforeUnmount(() => {
  socket?.close()
  socket = null
})
</script>

<template>
  <AppShell title="">
    <div class="ib-layout">
      <!-- Error / Loading -->
      <LoadingState v-if="state.loading.value && !payload" class="ib-glass min-h-[400px]" />
      <div v-else-if="state.error.value && !payload" class="ib-glass min-h-[400px] flex-center flex-col">
          <div class="ib-error-icon mb-4">⚠</div>
          <h3 class="text-xl text-red-400 mb-2">后端服务暂时不可用</h3>
          <p class="ib-muted max-w-md text-center">{{ state.error.value }}</p>
          <button class="ib-btn-primary mt-6" @click="() => { state.execute(() => get('/industry/brain')).catch(e => console.error(e)); connectStream(); }">重试连接</button>
      </div>

      <template v-else-if="payload">
        <!-- Scrolling Ticker -->
        <div class="ib-ticker-bar">
          <div class="ib-ticker-title">
            <svg class="ib-pulse-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline></svg>
            Live Feed
          </div>
          <div class="ib-ticker-overflow">
            <div class="ib-ticker-track">
              <!-- Tape x2 for seamless marquee -->
              <span v-for="item in marketTape" :key="item.label" :class="item.tone === 'risk' ? 'text-red-400' : 'text-emerald-400'">
                [{{ item.label }}] {{ item.value }} ({{ item.delta }})
              </span>
              <span v-for="item in marketTape" :key="item.label + '_dup'" :class="item.tone === 'risk' ? 'text-red-400' : 'text-emerald-400'">
                [{{ item.label }}] {{ item.value }} ({{ item.delta }})
              </span>
            </div>
          </div>
        </div>

        <div class="ib-main-scroll custom-scrollbar">
          <!-- Header -->
          <div class="ib-header">
            <div class="ib-header-left">
              <h2 class="ib-title">
                <svg class="ib-globe-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path></svg>
                新能源产业大脑 (Industry Brain)
              </h2>
              <div class="ib-meta-row">
                <p class="ib-meta-desc">Global Macro & Micro Telemetry</p>
                <div class="ib-ws-badge" :class="wsStatus === 'connected' ? 'connected' : 'disconnected'">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="2" width="20" height="8" rx="2" ry="2"></rect><rect x="2" y="14" width="20" height="8" rx="2" ry="2"></rect><line x1="6" y1="6" x2="6.01" y2="6"></line><line x1="6" y1="18" x2="6.01" y2="18"></line></svg>
                  {{ wsStatus === 'connected' ? "WS CONNECTED" : "WS DISCONNECTED" }}
                </div>
              </div>
            </div>
            <div class="ib-header-right">
              <div class="ib-badge active" v-for="tag in payload.sector_tags" :key="tag.label">
                <span>{{ tag.label }}</span>
                <strong>{{ tag.count }}</strong>
              </div>
            </div>
          </div>

          <!-- Top KPI Grid -->
          <div class="ib-kpi-grid">
            <div class="ib-stat-card border-glow" v-if="marketTape[0]">
              <div class="ib-card-accent bg-emerald-500"></div>
              <p class="ib-stat-label">{{ marketTape[0].label }}</p>
              <h4 class="ib-stat-value text-emerald-400">{{ marketTape[0].value }}</h4>
              <div class="ib-stat-trend text-emerald-400"><span class="bg-emerald-500-10">{{ marketTape[0].delta }}</span> MoM</div>
            </div>
            <div class="ib-stat-card border-glow-risk" v-if="marketTape[1]">
              <div class="ib-card-accent bg-rose-500"></div>
              <p class="ib-stat-label">{{ marketTape[1].label }}</p>
              <h4 class="ib-stat-value text-rose-400">{{ marketTape[1].value }}</h4>
              <div class="ib-stat-trend text-rose-400"><span class="bg-rose-500-10">{{ marketTape[1].delta }}</span> MoM</div>
            </div>
            <div class="ib-stat-card" v-for="item in marketTape.slice(2, 4)" :key="item.label">
              <p class="ib-stat-label">{{ item.label }}</p>
              <h4 class="ib-stat-value">{{ item.value }}</h4>
              <div class="ib-stat-trend" :class="item.tone === 'risk' ? 'text-rose-400' : 'text-emerald-400'">
                <span :class="item.tone === 'risk' ? 'bg-rose-500-10' : 'bg-emerald-500-10'">{{ item.delta }}</span> MoM
              </div>
            </div>

            <!-- Sentiment Gauge -->
            <div class="ib-gauge-card group hover-glow-emerald">
              <div class="ib-gauge-label">Market Sentiment</div>
              <div class="ib-gauge-draw">
                <svg viewBox="0 0 100 50" class="ib-gauge-svg">
                  <!-- Background Arc -->
                  <path d="M 10 50 A 40 40 0 0 1 90 50" fill="none" stroke="#1e293b" stroke-width="12" stroke-linecap="round" />
                  <!-- Foreground Arc -->
                  <path d="M 10 50 A 40 40 0 0 1 90 50" fill="none" :stroke="sentimentScore > 60 ? '#10b981' : sentimentScore > 40 ? '#f59e0b' : '#ef4444'" stroke-width="12" stroke-dasharray="125.6" :stroke-dashoffset="125.6 - (125.6 * sentimentScore / 100)" stroke-linecap="round" class="ib-gauge-val" />
                </svg>
              </div>
              <div class="ib-gauge-text">
                <span class="ib-gauge-num">{{ sentimentScore }}</span>
                <span class="ib-gauge-desc">{{ sentimentScore > 60 ? 'Greed' : sentimentScore > 40 ? 'Neutral' : 'Fear' }}</span>
              </div>
            </div>
          </div>

          <!-- Main Charts Grid -->
          <div class="ib-grid-main">
            <!-- Left Massive Chart -->
            <div class="ib-glass p-5 relative min-h-[380px] ib-col-span-2 flex flex-col hover-border-emerald">
              <div class="absolute right-5 top-5 z-10">
                <button class="ib-ai-btn" :class="{ active: showForecast }" @click="showForecast = !showForecast">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="ib-spark-icon" :class="{ 'animate-pulse': showForecast }"><path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a4.936 4.936 0 0 1 0-9.462l6.135-1.581A2 2 0 0 0 9.937.5L11.52.012a4.936 4.936 0 0 1 9.462 0l1.582 6.135a2 2 0 0 0 1.438 1.437l6.135 1.582a4.936 4.936 0 0 1 0 9.462l-6.135 1.582a2 2 0 0 0-1.438 1.437l-1.582 6.135a4.936 4.936 0 0 1-9.462 0z"></path></svg>
                  Gemini 3.1 预测模型
                </button>
              </div>
              <h3 class="ib-panel-title">
                <div class="ib-dot bg-emerald-500 animate-pulse"></div>
                产业核心全局监测走势 (WebSocket 流数据)
              </h3>
              <div class="ib-chart-container" v-if="payload.charts && payload.charts[0]">
                <ChartPanel :options="payload.charts[0].options" class="ib-naked-chart" />
              </div>
            </div>

            <!-- Right Feed: Live Anomalies -->
            <div class="ib-glass p-5 flex flex-col min-h-[380px] ib-col-span-1 border-white-5 shadow-xl">
              <h3 class="ib-panel-title flex justify-between">
                <div class="flex items-center gap-2">
                  <div class="ib-dot bg-amber-500 animate-pulse"></div>
                  AI 异常检测 (Live Anomalies)
                </div>
                <span class="ib-auto-refresh">Auto-refresh</span>
              </h3>
              <div class="ib-feed-list custom-scrollbar">
                <div v-if="liveEvents.length === 0" class="ib-empty-feed">
                   <svg class="opacity-20 mb-2" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline></svg>
                   Monitoring streams...
                </div>
                <div v-for="event in liveEvents" :key="`${event.company_name}-${event.headline}`" class="ib-anomaly-item" :class="event.status === 'Alert' ? 'high-risk' : 'med-risk'">
                  <div class="flex items-start gap-2 relative z-10">
                    <svg class="ib-alert-icon" :class="event.status === 'Alert' ? 'text-red-400' : 'text-amber-400'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>
                    <span class="ib-anomaly-text">{{ event.headline }} ({{ event.company_name }})</span>
                  </div>
                  <div class="ib-anomaly-time">LIVE</div>
                </div>
                <div v-for="flash in executionFlash" :key="`${flash.title}-${flash.status}`" class="ib-anomaly-item low-risk">
                  <div class="flex items-start gap-2 relative z-10">
                    <svg class="ib-alert-icon text-blue-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>
                    <span class="ib-anomaly-text">{{ flash.title }}</span>
                  </div>
                  <div class="ib-anomaly-time">{{ flash.status }}</div>
                </div>
              </div>
            </div>
          </div>

          <!-- Bottom Grid -->
          <div class="ib-grid-bottom">
            <div class="ib-glass p-5 min-h-[340px] flex flex-col">
              <h3 class="ib-panel-title">
                <div class="ib-dot bg-blue-500 animate-pulse"></div>
                核心板块对比与深度下钻
              </h3>
              <div class="ib-chart-container" v-if="payload.charts && payload.charts[1]">
                <ChartPanel :options="payload.charts[1].options" class="ib-naked-chart" />
              </div>
            </div>
            
            <div class="ib-glass p-5 min-h-[340px] flex flex-col">
              <h3 class="ib-panel-title">
                <div class="ib-dot bg-purple-500 animate-pulse"></div>
                全球政策与技术雷达 (Global Radar)
              </h3>
              <div class="ib-radar-grid">
                <RouterLink v-for="matrix in attentionMatrix" :key="matrix.company_name" :to="{ path: matrix.route.path, query: matrix.route.query || {} }" class="ib-radar-card group relative">
                  <div class="ib-radar-bg group-hover:opacity-100"></div>
                  <div class="flex justify-between items-start mb-2 relative z-10">
                    <span class="ib-radar-date">{{ matrix.company_name }}</span>
                    <span class="ib-radar-impact border-blue-500">MONITOR</span>
                  </div>
                  <h4 class="ib-radar-head relative z-10 group-hover:text-purple-300">{{ matrix.headline }}</h4>
                </RouterLink>
              </div>
            </div>
          </div>

        </div>
      </template>

    </div>
  </AppShell>
</template>

<style scoped>
/* Full App Canvas Overrides */
.ib-layout { display: flex; flex-direction: column; height: 100%; width: 100%; background: transparent; color: #e2e8f0; font-family: ui-sans-serif, system-ui, sans-serif; overflow: hidden; margin: -16px -24px -24px; padding: 0; }
.ib-glass { background: #121212; border: 1px solid rgba(255, 255, 255, 0.05); border-radius: 12px; box-shadow: 0 10px 30px -10px rgba(0, 0, 0, 0.5); position: relative; overflow: hidden; }

/* Ticker Tape */
.ib-ticker-bar { background: rgba(2, 44, 34, 0.3); border-bottom: 1px solid rgba(16, 185, 129, 0.2); padding: 8px 16px; display: flex; align-items: center; overflow: hidden; flex-shrink: 0; backdrop-filter: blur(8px); z-index: 20; }
.ib-ticker-title { display: flex; align-items: center; gap: 8px; color: #34d399; font-family: monospace; font-size: 12px; font-weight: bold; text-transform: uppercase; letter-spacing: 0.1em; flex-shrink: 0; margin-right: 16px; padding-right: 16px; border-right: 1px solid rgba(16, 185, 129, 0.3); }
.ib-pulse-svg { width: 14px; height: 14px; animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite; }
.ib-ticker-overflow { flex: 1; overflow: hidden; position: relative; }
.ib-ticker-track { display: flex; white-space: nowrap; gap: 32px; font-size: 12px; font-family: monospace; animation: marquee 20s linear infinite; }
@keyframes marquee { 0% { transform: translateX(0); } 100% { transform: translateX(-50%); } }

/* Main Content Scroll */
.ib-main-scroll { padding: 24px; flex: 1; overflow-y: auto; overflow-x: hidden; display: flex; flex-direction: column; gap: 24px; }

/* Header */
.ib-header { display: flex; flex-direction: column; gap: 16px; border-bottom: 1px solid rgba(255, 255, 255, 0.1); padding-bottom: 16px; }
@media (min-width: 1024px) { .ib-header { flex-direction: row; align-items: center; justify-content: space-between; } }
.ib-header-left { min-width: 0; }
.ib-title { font-size: 24px; font-weight: bold; color: white; display: flex; align-items: center; gap: 12px; margin: 0; letter-spacing: -0.02em; }
.ib-globe-icon { width: 24px; height: 24px; color: #34d399; flex-shrink: 0; }
.ib-meta-row { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin-top: 4px; }
.ib-meta-desc { color: #94a3b8; font-family: monospace; font-size: 12px; text-transform: uppercase; letter-spacing: 0.1em; margin: 0; }
.ib-ws-badge { padding: 2px 8px; border-radius: 4px; font-size: 10px; font-family: monospace; display: flex; align-items: center; gap: 6px; border: 1px solid transparent; }
.ib-ws-badge svg { width: 10px; height: 10px; }
.ib-ws-badge.connected { background: rgba(16, 185, 129, 0.1); color: #34d399; border-color: rgba(16, 185, 129, 0.3); }
.ib-ws-badge.disconnected { background: rgba(244, 63, 94, 0.1); color: #fb7185; border-color: rgba(244, 63, 94, 0.3); }

.ib-header-right { display: flex; flex-wrap: wrap; gap: 8px; flex-shrink: 0; }
.ib-badge { display: flex; align-items: center; gap: 6px; padding: 6px 12px; border-radius: 9999px; border: 1px solid rgba(255, 255, 255, 0.1); font-size: 12px; font-weight: 500; background: rgba(255, 255, 255, 0.05); color: #94a3b8; }
.ib-badge.active { background: rgba(16, 185, 129, 0.1); border-color: rgba(16, 185, 129, 0.3); color: #34d399; }

/* KPI Grid */
.ib-kpi-grid { display: grid; grid-template-columns: 1fr; gap: 16px; }
@media (min-width: 640px) { .ib-kpi-grid { grid-template-columns: repeat(2, 1fr); } }
@media (min-width: 1280px) { .ib-kpi-grid { grid-template-columns: repeat(5, 1fr); } }
.ib-stat-card { background: #121212; padding: 16px; border-radius: 12px; border: 1px solid rgba(255, 255, 255, 0.05); box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); position: relative; overflow: hidden; display: flex; flex-direction: column; justify-content: space-between; transition: border-color 0.2s; }
.ib-stat-card:hover { border-color: rgba(16, 185, 129, 0.3); }
.ib-stat-card.border-glow { border-color: rgba(16, 185, 129, 0.3); }
.ib-stat-card.border-glow-risk { border-color: rgba(244, 63, 94, 0.3); }
.ib-card-accent { position: absolute; top: 0; left: 0; right: 0; height: 4px; }
.ib-stat-label { font-size: 10px; font-family: monospace; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; margin: 0 0 8px; }
.ib-stat-value { font-size: 24px; font-weight: bold; font-family: monospace; color: white; margin: 0; }
.ib-stat-trend { display: flex; align-items: center; margin-top: 4px; font-size: 10px; font-weight: 500; }
.ib-stat-trend span { padding: 2px 6px; border-radius: 4px; font-family: monospace; margin-right: 6px; }

.ib-gauge-card { background: #121212; padding: 16px; border-radius: 12px; border: 1px solid rgba(255, 255, 255, 0.05); display: flex; flex-direction: column; align-items: center; justify-content: center; position: relative; overflow: hidden; transition: border-color 0.2s; }
.ib-gauge-card.hover-glow-emerald:hover { border-color: rgba(16, 185, 129, 0.3); }
.ib-gauge-label { position: absolute; top: 8px; left: 12px; font-size: 10px; font-family: monospace; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.1em; }
.ib-gauge-draw { height: 80px; width: 100%; margin-top: 8px; }
.ib-gauge-svg { width: 100%; height: 100%; }
.ib-gauge-val { transition: stroke-dashoffset 1s ease-out; }
.ib-gauge-text { position: absolute; bottom: 12px; display: flex; flex-direction: column; align-items: center; }
.ib-gauge-num { font-size: 20px; font-weight: bold; font-family: monospace; color: white; line-height: 1; }
.ib-gauge-desc { font-size: 9px; color: #64748b; text-transform: uppercase; margin-top: 2px; }

/* Grid Layouts */
.ib-grid-main { display: grid; grid-template-columns: 1fr; gap: 24px; }
@media (min-width: 1280px) { .ib-grid-main { grid-template-columns: repeat(3, 1fr); } }
.ib-col-span-2 { grid-column: span 2 / span 2; }
.ib-col-span-1 { grid-column: span 1 / span 1; }

.ib-grid-bottom { display: grid; grid-template-columns: 1fr; gap: 24px; }
@media (min-width: 1280px) { .ib-grid-bottom { grid-template-columns: repeat(2, 1fr); } }

.ib-panel-title { font-size: 14px; font-weight: bold; color: white; display: flex; align-items: center; gap: 8px; font-family: monospace; letter-spacing: 0.05em; margin: 0 0 24px; }
.ib-dot { width: 8px; height: 8px; border-radius: 50%; }
.hover-border-emerald:hover { border-color: rgba(16, 185, 129, 0.3); }

.ib-ai-btn { display: flex; align-items: center; gap: 8px; padding: 6px 12px; border-radius: 9999px; font-size: 12px; font-family: monospace; transition: all 0.2s; background: rgba(255, 255, 255, 0.05); color: #94a3b8; border: 1px solid rgba(255, 255, 255, 0.1); cursor: pointer; }
.ib-ai-btn:hover { background: rgba(255, 255, 255, 0.1); }
.ib-ai-btn.active { background: rgba(168, 85, 247, 0.2); color: #c084fc; border-color: rgba(168, 85, 247, 0.5); box-shadow: 0 0 15px rgba(168, 85, 247, 0.3); }
.ib-spark-icon { width: 14px; height: 14px; }

.ib-chart-container { flex: 1; display: flex; flex-direction: column; min-height: 0; }
:deep(.ib-naked-chart) { padding: 0 !important; background: transparent !important; border: none !important; margin: 0 !important; }

/* Anomalies Feed */
.ib-auto-refresh { font-size: 10px; background: rgba(255, 255, 255, 0.1); padding: 2px 8px; border-radius: 4px; color: #94a3b8; }
.ib-feed-list { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; padding-right: 8px; margin-top: -8px; }
.ib-empty-feed { height: 100%; display: flex; flex-direction: column; justify-content: center; align-items: center; color: #64748b; font-family: monospace; font-size: 12px; }
.ib-anomaly-item { padding: 12px; border-radius: 8px; border: 1px solid transparent; font-size: 12px; font-family: monospace; position: relative; overflow: hidden; }
.high-risk { background: rgba(244, 63, 94, 0.1); border-color: rgba(244, 63, 94, 0.3); color: #fecdd3; }
.high-risk .ib-alert-icon { color: #fb7185; }
.med-risk { background: rgba(245, 158, 11, 0.1); border-color: rgba(245, 158, 11, 0.3); color: #fde68a; }
.med-risk .ib-alert-icon { color: #fbbf24; }
.low-risk { background: rgba(59, 130, 246, 0.1); border-color: rgba(59, 130, 246, 0.3); color: #bfdbfe; }
.ib-alert-icon { width: 14px; height: 14px; flex-shrink: 0; margin-top: 2px; }
.ib-anomaly-text { line-height: 1.6; }
.ib-anomaly-time { margin-top: 8px; font-size: 9px; opacity: 0.5; text-align: right; }

/* Radar Grid */
.ib-radar-grid { display: grid; grid-template-columns: 1fr; gap: 12px; }
@media (min-width: 768px) { .ib-radar-grid { grid-template-columns: repeat(2, 1fr); } }
.ib-radar-card { padding: 12px; border-radius: 8px; border: 1px solid rgba(255, 255, 255, 0.05); background: rgba(255, 255, 255, 0.02); text-decoration: none; display: block; overflow: hidden; transition: background 0.2s; }
.ib-radar-bg { position: absolute; inset: 0; background: linear-gradient(to right, transparent, rgba(168, 85, 247, 0.1)); opacity: 0; transition: opacity 0.2s; pointer-events: none; }
.ib-radar-date { font-size: 10px; font-family: monospace; color: #64748b; }
.ib-radar-impact { font-size: 9px; padding: 2px 6px; border-radius: 4px; font-family: monospace; text-transform: uppercase; letter-spacing: 0.05em; border: 1px solid; background: rgba(59, 130, 246, 0.1); color: #60a5fa; border-color: rgba(59, 130, 246, 0.3); }
.ib-radar-head { font-size: 12px; font-weight: 500; color: #cbd5e1; margin: 0; line-height: 1.6; display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; transition: color 0.2s; }

/* Tailwind Colors Polyfill */
.bg-emerald-500 { background-color: #10b981; }
.bg-rose-500 { background-color: #f43f5e; }
.text-emerald-400 { color: #34d399; }
.text-rose-400 { color: #fb7185; }
.bg-emerald-500-10 { background-color: rgba(16, 185, 129, 0.1); }
.bg-rose-500-10 { background-color: rgba(244, 63, 94, 0.1); }
.bg-amber-500 { background-color: #f59e0b; }
.bg-blue-500 { background-color: #3b82f6; }
.bg-purple-500 { background-color: #a855f7; }

/* Animation Utility */
.animate-pulse { animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: .5; } }
.flex-center { display: flex; align-items: center; justify-content: center; }
.ib-btn-primary { background: #34d399; color: black; font-weight: bold; padding: 10px 24px; border-radius: 8px; border: none; cursor: pointer; transition: background 0.2s; font-family: inherit; }
.ib-btn-primary:hover { background: #10b981; }

.custom-scrollbar::-webkit-scrollbar { width: 6px; height: 6px; }
.custom-scrollbar::-webkit-scrollbar-thumb { background: rgba(255, 255, 255, 0.1); border-radius: 3px; }
.custom-scrollbar::-webkit-scrollbar-track { background: transparent; }
</style>
