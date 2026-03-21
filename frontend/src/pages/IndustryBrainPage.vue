<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import AppShell from '@/components/AppShell.vue'
import ChartPanel from '@/components/ChartPanel.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingState from '@/components/LoadingState.vue'
import StatCard from '@/components/StatCard.vue'
import TagPill from '@/components/TagPill.vue'
import { useAsyncState } from '@/composables/useAsyncState'
import { get, loadAccessToken } from '@/lib/api'

const state = useAsyncState<any>()
const historyState = useAsyncState<any>()
const livePayload = ref<any | null>(null)
const wsStatus = ref<'connecting' | 'connected' | 'disconnected'>('connecting')
let socket: WebSocket | null = null

const payload = computed(() => livePayload.value || state.data.value)
const historyRecords = computed(() => historyState.data.value?.records || [])
const marketTape = computed(() => payload.value?.market_tape || [])
const brainCommandSurface = computed(() => payload.value?.brain_command_surface || null)
const brainSignalTape = computed(() => payload.value?.brain_signal_tape || [])
const executionFlash = computed(() => payload.value?.execution_flash || [])
const liveEvents = computed(() => payload.value?.live_events || [])
const attentionMatrix = computed(() => payload.value?.attention_matrix || [])

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
    const nextPayload = JSON.parse(event.data)
    livePayload.value = nextPayload
    const history = historyState.data.value?.records || []
    historyState.data.value = {
      generated_at: nextPayload.stream?.refreshed_at,
      total: Math.min(history.length + 1, 12),
      records: [
        {
          refreshed_at: nextPayload.stream?.refreshed_at,
          report_period: nextPayload.report_period,
          sequence: nextPayload.stream?.sequence,
          market_tape: nextPayload.market_tape || [],
          live_events: nextPayload.live_events || [],
          attention_matrix: nextPayload.attention_matrix || [],
          execution_flash: nextPayload.execution_flash || [],
        },
        ...history,
      ].slice(0, 12),
    }
  }

  socket.onclose = () => {
    wsStatus.value = 'disconnected'
  }

  socket.onerror = () => {
    wsStatus.value = 'disconnected'
  }
}

onMounted(async () => {
  await state.execute(() => get('/industry/brain'))
  await historyState.execute(() => get('/industry/brain/history?limit=12'))
  connectStream()
})

onBeforeUnmount(() => {
  socket?.close()
  socket = null
})
</script>

<template>
  <AppShell
    title="新能源产业大脑"
    subtitle="产业大脑"
    compact
  >
    <LoadingState v-if="state.loading.value && !payload" />
    <ErrorState v-else-if="state.error.value && !payload" :message="state.error.value" />
    <template v-else-if="payload">
      <section class="brain-hero brain-hero-terminal">
        <div class="brain-title-block">
          <h2 class="hero-title compact">先看变化，再锁定公司，再进入处置。</h2>
        </div>
        <div class="brain-header-actions">
          <TagPill
            :label="wsStatus === 'connected' ? 'WS CONNECTED' : wsStatus === 'connecting' ? 'CONNECTING' : 'DISCONNECTED'"
            :tone="wsStatus === 'connected' ? 'success' : 'risk'"
          />
          <TagPill
            v-for="tag in payload.sector_tags"
            :key="tag.label"
            :label="`${tag.label} ${tag.count}`"
          />
        </div>
      </section>

      <section class="brain-market-tape">
        <div v-for="item in marketTape" :key="item.label" class="brain-market-cell" :data-tone="item.tone">
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
          <em>{{ item.delta }}</em>
        </div>
      </section>

      <section v-if="brainCommandSurface" class="graph-canvas-panel evaluation-command-panel">
        <div class="graph-command-surface">
          <div class="graph-command-surface-copy">
            <span>{{ brainCommandSurface.title }}</span>
            <strong>{{ brainCommandSurface.headline }}</strong>
          </div>
          <div class="graph-command-surface-metric">
            <div class="graph-command-meter">
              <label>主信号</label>
              <strong>{{ brainCommandSurface.metric }}</strong>
              <i :style="{ width: `${brainCommandSurface.intensity || 0}%` }" />
            </div>
            <div class="graph-command-signal" :class="`tone-${brainCommandSurface.dominant_signal?.tone || 'accent'}`">
              <span>{{ brainCommandSurface.dominant_signal?.label }}</span>
              <strong>{{ brainCommandSurface.dominant_signal?.value }}</strong>
            </div>
          </div>
        </div>
        <div class="graph-route-bands score-signal-tape">
          <div
            v-for="item in brainSignalTape"
            :key="`${item.step}-${item.label}`"
            class="graph-route-band"
            :class="[`tone-${item.tone || 'accent'}`]"
          >
            <em>{{ item.label }}</em>
            <div class="graph-route-band-copy">
              <strong>{{ item.value }}</strong>
              <span>{{ item.intensity }}%</span>
            </div>
            <i :style="{ width: `${item.intensity || 0}%` }" />
          </div>
        </div>
      </section>

      <section v-if="historyRecords.length" class="brain-signal-river">
        <div
          v-for="item in historyRecords.slice(0, 6)"
          :key="`${item.refreshed_at}-${item.sequence}`"
          class="brain-signal-chip"
        >
          <span>{{ item.refreshed_at?.slice(11, 19) || '--:--:--' }}</span>
          <strong>{{ item.market_tape?.[0]?.value || '0' }} 预警</strong>
          <em>{{ item.execution_flash?.[0]?.title || '持续监测' }}</em>
        </div>
      </section>

      <section class="brain-terminal-stage">
        <article class="panel brain-terminal-main">
          <div class="brain-chart-stack">
            <ChartPanel
              v-for="chart in payload.charts.slice(0, 1)"
              :key="chart.title"
              :title="chart.title"
              :options="chart.options"
            />
          </div>

          <div class="brain-live-ribbon">
            <div
              v-for="item in liveEvents"
              :key="`${item.company_name}-${item.headline}`"
              class="brain-live-event"
            >
              <RouterLink class="brain-live-link" :to="{ path: item.route.path, query: item.route.query || {} }">
                <strong>{{ item.company_name }}</strong>
                <span>{{ item.headline }}</span>
                <em>{{ item.status }}</em>
              </RouterLink>
            </div>
          </div>
        </article>

        <aside class="brain-terminal-rail">
          <article class="panel">
            <div class="panel-header">
              <div><h3>优先观察</h3></div>
              <div class="signal-subtitle">{{ payload.report_period }}</div>
            </div>
            <div class="timeline-list compact-timeline">
              <RouterLink
                v-for="item in attentionMatrix"
                :key="item.company_name"
                class="timeline-item interactive-card"
                :to="{ path: item.route.path, query: item.route.query || {} }"
              >
                <strong>{{ item.company_name }}</strong>
                <span>{{ item.subindustry }} · {{ item.headline }}</span>
              </RouterLink>
            </div>
          </article>

          <article class="panel">
            <div class="panel-header">
              <div><h3>最新运行</h3></div>
            </div>
            <div class="timeline-list compact-timeline">
              <RouterLink
                v-for="item in executionFlash"
                :key="`${item.title}-${item.status}`"
                class="timeline-item interactive-card"
                :to="item.route ? { path: item.route.path, query: item.route.query || {} } : { path: '/workspace' }"
              >
                <strong>{{ item.title }}</strong>
                <span>{{ item.summary }} · {{ item.status }}</span>
              </RouterLink>
            </div>
          </article>
        </aside>
      </section>

      <section class="split-grid">
        <article class="panel">
          <div class="panel-header">
            <div><h3>重点公司</h3></div>
          </div>
          <div class="company-grid">
            <RouterLink
              v-for="item in payload.top_risk_companies"
              :key="item.company_name"
              class="company-card interactive-card"
              :to="{ path: item.route.path, query: item.route.query || {} }"
            >
              <div class="signal-top">
                <div>
                  <div class="signal-code">{{ item.subindustry }}</div>
                  <h4>{{ item.company_name }}</h4>
                </div>
                <div class="signal-value">{{ item.risk_count }}</div>
              </div>
              <div class="tag-row">
                <TagPill
                  v-for="label in item.risk_labels"
                  :key="`${item.company_name}-${label}`"
                  :label="label"
                  tone="risk"
                />
              </div>
            </RouterLink>
          </div>
        </article>
        <article class="panel brain-secondary-panel">
          <ChartPanel
            v-for="chart in payload.charts.slice(1)"
            :key="chart.title"
            :title="chart.title"
            :options="chart.options"
          />
        </article>
      </section>
    </template>
  </AppShell>
</template>
