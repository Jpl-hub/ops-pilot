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
const livePayload = ref<any | null>(null)
const wsStatus = ref<'connecting' | 'connected' | 'disconnected'>('connecting')
let socket: WebSocket | null = null

const payload = computed(() => livePayload.value || state.data.value)

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

  socket.onclose = () => {
    wsStatus.value = 'disconnected'
  }

  socket.onerror = () => {
    wsStatus.value = 'disconnected'
  }
}

onMounted(async () => {
  await state.execute(() => get('/industry/brain'))
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
      <section class="brain-hero">
        <div class="brain-title-block">
          <h2 class="hero-title compact">先看市场变化，再看重点公司。</h2>
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

      <section class="brain-board">
        <article class="panel brain-main-panel">
          <div class="brain-inline-metrics">
            <StatCard
              v-for="item in payload.metrics"
              :key="item.label"
              :label="item.label"
              :value="item.value"
              :hint="item.hint"
              :tone="item.tone"
            />
          </div>
          <div class="brain-chart-stack">
            <ChartPanel
              v-for="chart in payload.charts.slice(0, 1)"
              :key="chart.title"
              :title="chart.title"
              :options="chart.options"
            />
            <div class="brain-signal-tape">
              <div
                v-for="item in payload.metrics"
                :key="`tape-${item.label}`"
                class="brain-signal-item"
              >
                <span>{{ item.label }}</span>
                <strong>{{ item.value }}</strong>
              </div>
            </div>
          </div>
        </article>

        <aside class="brain-side-stack">
          <article class="panel">
            <div class="panel-header">
              <div>
                <h3>优先观察名单</h3>
              </div>
              <div class="signal-subtitle">{{ payload.report_period }}</div>
            </div>
            <div class="timeline-list compact-timeline">
              <RouterLink
                v-for="item in payload.top_risk_companies"
                :key="item.company_name"
                class="timeline-item interactive-card"
                :to="{ path: item.route.path, query: item.route.query || {} }"
              >
                <strong>{{ item.company_name }}</strong>
                <span>{{ item.subindustry }} · {{ item.risk_labels.slice(0, 2).join(' / ') || '持续跟踪' }}</span>
              </RouterLink>
            </div>
          </article>

          <article class="panel">
            <div class="panel-header">
              <div>
                <h3>最新变化</h3>
              </div>
              <div class="signal-subtitle">{{ payload.radar_events.length }} 条</div>
            </div>
            <div class="timeline-list compact-timeline">
              <div v-for="item in payload.radar_events.slice(0, 5)" :key="item.title" class="timeline-item">
                <strong>{{ item.title }}</strong>
                <span>{{ item.source }} · {{ item.date || item.published_at || '2026' }}</span>
              </div>
            </div>
          </article>
        </aside>
      </section>

      <section class="split-grid">
        <article class="panel">
          <div class="panel-header">
            <div>
              <div class="eyebrow">风险分布</div>
              <h3>当前需要优先盯住的公司</h3>
            </div>
            <div class="signal-subtitle">{{ payload.report_period }}</div>
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
