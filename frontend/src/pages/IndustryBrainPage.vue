<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import AppShell from '@/components/AppShell.vue'
import ChartPanel from '@/components/ChartPanel.vue'
import LoadingState from '@/components/LoadingState.vue'
import { useAsyncState } from '@/composables/useAsyncState'
import { buildWebSocketUrl, get, loadAccessToken } from '@/lib/api'

const state = useAsyncState<any>()
const livePayload = ref<any | null>(null)
const wsStatus = ref<'connecting' | 'connected' | 'disconnected'>('connecting')
let socket: WebSocket | null = null

const payload = computed(() => livePayload.value || state.data.value)
const marketTape = computed(() => payload.value?.market_tape || [])
const brainCommandSurface = computed(() => payload.value?.brain_command_surface || null)
const brainSignalTape = computed(() => payload.value?.brain_signal_tape || [])
const externalSignalStream = computed(() => payload.value?.external_signal_stream || null)
const streamingAnomalies = computed(() => payload.value?.streaming_anomalies || null)
const attentionMatrix = computed(() => payload.value?.attention_matrix || [])
const topRiskCompanies = computed(() => payload.value?.top_risk_companies || [])
const radarEvents = computed(() => payload.value?.radar_events || [])
const topSectorTags = computed(() => (payload.value?.sector_tags || []).slice(0, 4))
const signalFeed = computed(() => externalSignalStream.value?.signals || payload.value?.live_events || [])
const trendChart = computed(() => payload.value?.charts?.[0] || null)
const heatChart = computed(() => payload.value?.charts?.[1] || null)
const anomalyItems = computed(() => (streamingAnomalies.value?.items || []).slice(0, 4))
const focusCompanies = computed(() => attentionMatrix.value.slice(0, 5))
const riskCompanies = computed(() => topRiskCompanies.value.slice(0, 4))
const radarCards = computed(() => radarEvents.value.slice(0, 3))
const signalCards = computed(() => signalFeed.value.slice(0, 6))
const pulseSteps = computed(() => brainSignalTape.value.slice(0, 4))
const tapeItems = computed(() => marketTape.value.slice(0, 6))
const leadMetric = computed(() => marketTape.value[0] || null)
const supportMetrics = computed(() => marketTape.value.slice(1, 4))

const signalFreshnessTone = computed(() => {
  const status = externalSignalStream.value?.status
  return status === 'stale' || status === 'unavailable' ? 'is-risk' : 'is-live'
})

function displayWsStatus(status: 'connecting' | 'connected' | 'disconnected') {
  const map: Record<string, string> = {
    connecting: '连接中',
    connected: '实时已接通',
    disconnected: '实时已断开',
  }
  return map[status] || status
}

function displaySignalMeta(item: any) {
  const parts = [item?.source_name, item?.subindustry, item?.publish_date].filter(Boolean)
  return parts.join(' · ') || '正式信号'
}

function displayFocusMeta(item: any) {
  const parts = [
    item?.signal_status || '持续跟踪',
    item?.signal_count ? `${item.signal_count} 条信号` : '',
    item?.external_heat ? `热度 ${item.external_heat}` : '',
    item?.risk_count ? `风险 ${item.risk_count}` : '',
  ].filter(Boolean)
  return parts.join(' · ')
}

function displayAnomalyMeta(item: any) {
  const parts = [
    item?.signal_status || '流式异动',
    item?.score ? `评分 ${item.score}` : '',
    item?.triggers?.length ? `${item.triggers.length} 个触发因子` : '',
  ].filter(Boolean)
  return parts.join(' · ')
}

function displayAnomalyLevel(level?: string) {
  const map: Record<string, string> = {
    critical: '高危异动',
    high: '重点异动',
    medium: '持续异动',
    low: '轻度异动',
  }
  return map[(level || '').toLowerCase()] || '异动跟踪'
}

function anomalyTone(level?: string) {
  const normalized = (level || '').toLowerCase()
  if (normalized === 'critical' || normalized === 'high') return 'is-risk'
  if (normalized === 'medium') return 'is-warning'
  return 'is-calm'
}

function displayResearchSource(event: any) {
  return event?.source || event?.source_name || event?.domain || '外部线索'
}

function closeSocket() {
  socket?.close()
  socket = null
}

function connectStream() {
  const token = loadAccessToken()
  if (!token) {
    wsStatus.value = 'disconnected'
    closeSocket()
    return
  }

  closeSocket()
  const url = `${buildWebSocketUrl('/ws/industry-brain')}?token=${encodeURIComponent(token)}`
  socket = new WebSocket(url)
  wsStatus.value = 'connecting'

  socket.onopen = () => {
    wsStatus.value = 'connected'
  }

  socket.onmessage = (event) => {
    wsStatus.value = 'connected'
    livePayload.value = JSON.parse(event.data)
  }

  socket.onclose = () => {
    wsStatus.value = 'disconnected'
  }

  socket.onerror = () => {
    wsStatus.value = 'disconnected'
  }
}

async function loadPage() {
  await state.execute(() => get('/industry/brain')).catch(() => {})
}

onMounted(async () => {
  await loadPage()
  connectStream()
})

onBeforeUnmount(() => {
  closeSocket()
})
</script>

<template>
  <AppShell title="">
    <div class="brain-page">
      <LoadingState v-if="state.loading.value && !payload" class="brain-surface brain-loading" />

      <div v-else-if="state.error.value && !payload" class="brain-surface brain-error">
        <strong>产业大脑暂时不可用</strong>
        <p>{{ state.error.value }}</p>
        <button type="button" class="brain-action" @click="() => { loadPage(); connectStream() }">重新连接</button>
      </div>

      <template v-else-if="payload">
        <section class="brain-ribbon">
          <span class="brain-ribbon-label">行业脉冲</span>
          <div class="brain-ribbon-track">
            <span v-for="item in tapeItems" :key="item.label" :class="['brain-ribbon-item', `is-${item.tone || 'default'}`]">
              {{ item.label }} · {{ item.value }} · {{ item.delta }}
            </span>
            <span v-for="item in tapeItems" :key="`${item.label}-dup`" :class="['brain-ribbon-item', `is-${item.tone || 'default'}`]">
              {{ item.label }} · {{ item.value }} · {{ item.delta }}
            </span>
          </div>
        </section>

        <section class="brain-hero">
          <div class="brain-hero-copy">
            <div class="brain-kicker-row">
              <span class="brain-kicker">新能源产业大脑</span>
              <span class="brain-live-chip" :class="wsStatus === 'connected' ? 'is-live' : 'is-risk'">
                {{ displayWsStatus(wsStatus) }}
              </span>
              <span class="brain-live-chip" :class="signalFreshnessTone">
                {{ externalSignalStream?.freshness_label || '正式信号待接入' }}
              </span>
            </div>
            <h1 class="brain-title">
              {{ brainCommandSurface?.title || '行业脉冲' }}
            </h1>
            <p class="brain-summary">
              {{
                brainCommandSurface?.summary
                  || brainCommandSurface?.headline
                  || brainCommandSurface?.dominant_signal?.value
                  || signalCards[0]?.headline
                  || streamingAnomalies?.summary?.focus_line
                  || '正式行业信号会先汇聚到这里，再分发到企业判断链路。'
              }}
            </p>

            <div class="brain-metrics">
              <div v-if="leadMetric" class="brain-metric brain-metric-lead" :class="`is-${leadMetric.tone || 'default'}`">
                <span>{{ leadMetric.label }}</span>
                <strong>{{ leadMetric.value }}</strong>
                <small>{{ leadMetric.delta }}</small>
              </div>
              <div
                v-for="item in supportMetrics"
                :key="item.label"
                class="brain-metric"
                :class="`is-${item.tone || 'default'}`"
              >
                <span>{{ item.label }}</span>
                <strong>{{ item.value }}</strong>
                <small>{{ item.delta }}</small>
              </div>
            </div>
          </div>

          <div class="brain-sector-strip">
            <div v-for="tag in topSectorTags" :key="tag.label" class="brain-sector-pill">
              <span>{{ tag.label }}</span>
              <strong>{{ tag.count }}</strong>
            </div>
          </div>
        </section>

        <section class="brain-stage">
          <article class="brain-surface brain-canvas">
            <div class="brain-section-head">
              <div>
                <h2>走势</h2>
              </div>
            </div>

            <div class="brain-canvas-grid">
              <div class="brain-chart-stage">
                <ChartPanel
                  v-if="trendChart"
                  :title="trendChart.title || '行业脉冲'"
                  :options="trendChart.options"
                  class="brain-chart-panel"
                />
              </div>

              <div class="brain-pulse-list">
                <div v-for="item in pulseSteps" :key="`${item.step}-${item.label}`" class="brain-pulse-card">
                  <span class="brain-pulse-step">0{{ item.step }}</span>
                  <div>
                    <strong>{{ item.label }}</strong>
                    <p>{{ item.value }}</p>
                  </div>
                </div>
              </div>
            </div>
          </article>

          <article class="brain-surface brain-stream">
            <div class="brain-section-head">
              <div>
                <h2>最新动态</h2>
              </div>
              <span class="brain-section-meta">{{ externalSignalStream?.signal_count || 0 }} 条</span>
            </div>

            <div v-if="signalCards.length" class="brain-stream-list">
              <a
                v-for="item in signalCards"
                :key="`${item.company_name}-${item.headline}`"
                class="brain-stream-item"
                :href="item.source_url || '#'"
                :target="item.source_url ? '_blank' : undefined"
                rel="noreferrer"
              >
                <div class="brain-stream-top">
                  <strong>{{ item.company_name }}</strong>
                  <span>{{ item.status || '正式信号' }}</span>
                </div>
                <p>{{ item.headline }}</p>
                <small>{{ displaySignalMeta(item) }}</small>
              </a>
            </div>
            <div v-else class="brain-empty-state">当前没有可展示的正式外部信号。</div>
          </article>
        </section>

        <section class="brain-grid">
          <article class="brain-surface">
            <div class="brain-section-head">
              <div>
                <h2>子行业热度</h2>
              </div>
            </div>
            <ChartPanel
              v-if="heatChart"
              :title="heatChart.title || '子行业热度迁移'"
              :options="heatChart.options"
              class="brain-chart-panel"
            />
            <div v-else class="brain-empty-state">热度迁移图暂不可用。</div>
          </article>

          <article class="brain-surface">
            <div class="brain-section-head">
              <div>
                <h2>异动传导</h2>
              </div>
              <span class="brain-section-meta">
                {{ streamingAnomalies?.summary?.detected_count || 0 }} 家
              </span>
            </div>

            <div v-if="anomalyItems.length" class="brain-anomaly-list">
              <RouterLink
                v-for="item in anomalyItems"
                :key="`${item.company_name}-${item.anomaly_type}`"
                :to="{ path: item.route.path, query: item.route.query || {} }"
                class="brain-anomaly-card"
                :class="anomalyTone(item.severity)"
              >
                <div class="brain-anomaly-top">
                  <strong>{{ item.company_name }}</strong>
                  <span>{{ displayAnomalyLevel(item.severity) }}</span>
                </div>
                <p>{{ item.summary }}</p>
                <small>{{ displayAnomalyMeta(item) }}</small>
              </RouterLink>
            </div>
            <div v-else class="brain-empty-state">
              {{ streamingAnomalies?.freshness_label || '当前没有高优先级异动。' }}
            </div>
          </article>
        </section>

        <section class="brain-grid">
          <article class="brain-surface">
            <div class="brain-section-head">
              <div>
                <h2>重点公司</h2>
              </div>
              <span class="brain-section-meta">{{ focusCompanies.length }} 家</span>
            </div>

            <div v-if="focusCompanies.length" class="brain-company-list">
              <RouterLink
                v-for="item in focusCompanies"
                :key="item.company_name"
                :to="{ path: item.route.path, query: item.route.query || {} }"
                class="brain-company-row"
              >
                <div>
                  <strong>{{ item.company_name }}</strong>
                  <p>{{ item.headline }}</p>
                </div>
                <small>{{ displayFocusMeta(item) }}</small>
              </RouterLink>
            </div>
            <div v-else class="brain-empty-state">当前没有热点公司进入观察池。</div>
          </article>

          <article class="brain-surface">
            <div class="brain-section-head">
              <div>
                <h2>优先处理</h2>
              </div>
              <span class="brain-section-meta">{{ riskCompanies.length }} 家</span>
            </div>

            <div v-if="riskCompanies.length" class="brain-risk-list">
              <RouterLink
                v-for="item in riskCompanies"
                :key="item.company_name"
                :to="{ path: item.route.path, query: item.route.query || {} }"
                class="brain-risk-card"
              >
                <div class="brain-risk-top">
                  <strong>{{ item.company_name }}</strong>
                  <span>{{ item.risk_count }} 个风险</span>
                </div>
                <p>{{ item.subindustry }}</p>
                <small>{{ (item.risk_labels || []).slice(0, 3).join(' · ') }}</small>
              </RouterLink>
            </div>
            <div v-else class="brain-empty-state">当前没有需要优先处置的公司。</div>
          </article>
        </section>

        <section class="brain-surface brain-radar">
          <div class="brain-section-head">
            <div>
              <h2>政策与技术动态</h2>
            </div>
          </div>

          <div v-if="radarCards.length" class="brain-radar-grid">
            <a
              v-for="item in radarCards"
              :key="item.id"
              class="brain-radar-card"
              :href="item.url"
              target="_blank"
              rel="noreferrer"
            >
              <div class="brain-radar-top">
                <span>{{ item.domain }}</span>
                <strong>{{ item.year }}</strong>
              </div>
              <h3>{{ item.title }}</h3>
              <p>{{ (item.core_points || []).slice(0, 2).join(' · ') }}</p>
              <small>{{ displayResearchSource(item) }}</small>
            </a>
          </div>
          <div v-else class="brain-empty-state">当前没有可展示的技术与政策雷达。</div>
        </section>
      </template>
    </div>
  </AppShell>
</template>

<style scoped>
.brain-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: 100%;
  width: 100%;
  max-width: 1480px;
  margin: 0 auto;
  color: #edf2f7;
}

.brain-surface {
  border-radius: 24px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background:
    linear-gradient(180deg, rgba(15, 16, 20, 0.98), rgba(11, 12, 17, 0.96));
  box-shadow: 0 18px 48px -28px rgba(0, 0, 0, 0.66);
}

.brain-loading,
.brain-error {
  min-height: 420px;
}

.brain-error {
  display: grid;
  place-items: center;
  gap: 10px;
  text-align: center;
  padding: 32px;
}

.brain-error strong {
  font-size: 22px;
  color: #f8fafc;
}

.brain-error p {
  margin: 0;
  max-width: 480px;
  color: rgba(191, 207, 228, 0.78);
  line-height: 1.7;
}

.brain-action {
  min-height: 44px;
  padding: 0 18px;
  border-radius: 999px;
  border: 1px solid rgba(16, 185, 129, 0.28);
  background: rgba(16, 185, 129, 0.14);
  color: #84f4ca;
  cursor: pointer;
}

.brain-ribbon {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 42px;
  padding: 0 14px;
  border-radius: 14px;
  border: 1px solid rgba(52, 211, 153, 0.16);
  background: rgba(9, 28, 22, 0.66);
  overflow: hidden;
}

.brain-ribbon-label {
  flex: 0 0 auto;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: rgba(116, 247, 198, 0.88);
}

.brain-ribbon-track {
  display: flex;
  gap: 20px;
  white-space: nowrap;
  min-width: 0;
  animation: brain-marquee 28s linear infinite;
}

.brain-ribbon-item {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: rgba(230, 238, 249, 0.88);
}

.brain-ribbon-item.is-risk {
  color: #fda4af;
}

.brain-ribbon-item.is-success,
.brain-ribbon-item.is-accent {
  color: #86efac;
}

.brain-hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 16px;
  padding: 20px 22px 18px;
  border-radius: 24px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background:
    radial-gradient(circle at top left, rgba(16, 185, 129, 0.12), transparent 26%),
    linear-gradient(180deg, rgba(15, 17, 22, 0.98), rgba(11, 12, 17, 0.96));
}

.brain-hero-copy {
  display: grid;
  gap: 14px;
}

.brain-kicker-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}

.brain-kicker {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: rgba(137, 221, 191, 0.86);
}

.brain-live-chip {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding: 0 10px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  font-size: 11px;
  color: rgba(221, 229, 240, 0.86);
}

.brain-live-chip.is-live {
  border-color: rgba(52, 211, 153, 0.24);
  background: rgba(16, 185, 129, 0.12);
  color: #8af4c8;
}

.brain-live-chip.is-risk {
  border-color: rgba(251, 113, 133, 0.22);
  background: rgba(190, 24, 93, 0.12);
  color: #fda4af;
}

.brain-title {
  margin: 0;
  font-size: clamp(22px, 3.8vw, 34px);
  line-height: 1.02;
  letter-spacing: -0.04em;
  color: #f8fafc;
}

.brain-summary {
  margin: 0;
  max-width: 720px;
  font-size: 13px;
  line-height: 1.65;
  color: rgba(200, 211, 228, 0.84);
}

.brain-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.brain-metric {
  display: grid;
  gap: 6px;
  padding: 12px 14px;
  border-radius: 16px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.03);
}

.brain-metric span,
.brain-metric small {
  font-size: 11px;
  color: rgba(163, 178, 198, 0.84);
}

.brain-metric strong {
  font-family: 'JetBrains Mono', monospace;
  font-size: 18px;
  color: #f8fafc;
}

.brain-metric-lead strong {
  font-size: 22px;
}

.brain-metric.is-risk {
  border-color: rgba(251, 113, 133, 0.22);
}

.brain-metric.is-success,
.brain-metric.is-accent {
  border-color: rgba(52, 211, 153, 0.2);
}

.brain-sector-strip {
  display: flex;
  flex-wrap: wrap;
  align-content: flex-start;
  justify-content: flex-end;
  gap: 8px;
  max-width: 320px;
}

.brain-sector-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 34px;
  padding: 0 12px;
  border-radius: 999px;
  border: 1px solid rgba(52, 211, 153, 0.18);
  background: rgba(16, 185, 129, 0.08);
  color: #dff8ee;
}

.brain-sector-pill span {
  font-size: 12px;
}

.brain-sector-pill strong {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  color: #86efac;
}

.brain-stage,
.brain-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(320px, 0.95fr);
  gap: 16px;
}

.brain-canvas,
.brain-stream,
.brain-radar,
.brain-grid > .brain-surface {
  padding: 18px;
}

.brain-section-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.brain-section-kicker {
  display: inline-block;
  margin-bottom: 8px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: rgba(121, 138, 162, 0.82);
}

.brain-section-head h2 {
  margin: 0;
  font-size: 18px;
  line-height: 1.1;
  color: #f8fafc;
}

.brain-section-meta {
  flex: 0 0 auto;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: rgba(156, 169, 188, 0.84);
}

.brain-canvas-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 220px;
  gap: 14px;
  align-items: stretch;
}

.brain-chart-stage {
  min-height: 320px;
}

:deep(.brain-chart-panel) {
  height: 100%;
  padding: 0 !important;
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
}

.brain-pulse-list {
  display: grid;
  gap: 8px;
}

.brain-pulse-card {
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr);
  gap: 10px;
  padding: 12px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.brain-pulse-step {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border-radius: 14px;
  background: rgba(16, 185, 129, 0.12);
  color: #8af4c8;
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
}

.brain-pulse-card strong {
  display: block;
  margin-bottom: 6px;
  font-size: 13px;
  color: #f8fafc;
}

.brain-pulse-card p {
  margin: 0;
  font-size: 11px;
  line-height: 1.6;
  color: rgba(191, 205, 223, 0.82);
}

.brain-stream-list,
.brain-company-list,
.brain-risk-list,
.brain-anomaly-list {
  display: grid;
  gap: 8px;
}

.brain-stream-item,
.brain-company-row,
.brain-risk-card,
.brain-anomaly-card {
  display: grid;
  gap: 6px;
  padding: 12px 13px;
  border-radius: 16px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.03);
  color: inherit;
  text-decoration: none;
  transition: transform 0.18s ease, border-color 0.18s ease, background 0.18s ease;
}

.brain-stream-item:hover,
.brain-company-row:hover,
.brain-risk-card:hover,
.brain-anomaly-card:hover,
.brain-radar-card:hover {
  transform: translateY(-2px);
  border-color: rgba(52, 211, 153, 0.18);
  background: rgba(255, 255, 255, 0.045);
}

.brain-stream-top,
.brain-risk-top,
.brain-anomaly-top,
.brain-radar-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.brain-stream-top strong,
.brain-company-row strong,
.brain-risk-top strong,
.brain-anomaly-top strong,
.brain-radar-card h3 {
  color: #f8fafc;
}

.brain-stream-top span,
.brain-risk-top span,
.brain-anomaly-top span,
.brain-radar-top span,
.brain-radar-top strong {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: rgba(165, 179, 198, 0.8);
}

.brain-stream-item p,
.brain-company-row p,
.brain-risk-card p,
.brain-anomaly-card p,
.brain-radar-card p {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  color: rgba(197, 210, 227, 0.84);
}

.brain-stream-item small,
.brain-company-row small,
.brain-risk-card small,
.brain-anomaly-card small,
.brain-radar-card small {
  font-size: 11px;
  color: rgba(144, 160, 181, 0.78);
}

.brain-anomaly-card.is-risk {
  border-color: rgba(251, 113, 133, 0.22);
  background: rgba(190, 24, 93, 0.08);
}

.brain-anomaly-card.is-warning {
  border-color: rgba(251, 191, 36, 0.18);
  background: rgba(120, 53, 15, 0.08);
}

.brain-radar-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.brain-radar-card {
  display: grid;
  gap: 10px;
  padding: 14px;
  border-radius: 16px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.03);
  color: inherit;
  text-decoration: none;
}

.brain-radar-card h3 {
  margin: 0;
  font-size: 14px;
  line-height: 1.4;
}

.brain-empty-state {
  display: grid;
  place-items: center;
  min-height: 160px;
  color: rgba(152, 167, 187, 0.72);
  text-align: center;
  font-size: 13px;
}

@keyframes brain-marquee {
  from { transform: translateX(0); }
  to { transform: translateX(-50%); }
}

@media (max-width: 1260px) {
  .brain-stage,
  .brain-grid,
  .brain-hero {
    grid-template-columns: 1fr;
  }

  .brain-sector-strip {
    justify-content: flex-start;
    max-width: none;
  }

  .brain-canvas-grid,
  .brain-radar-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 860px) {
  .brain-title {
    font-size: 26px;
  }

  .brain-metrics {
    grid-template-columns: 1fr;
  }

  .brain-canvas,
  .brain-stream,
  .brain-radar,
  .brain-grid > .brain-surface {
    padding: 18px;
  }
}
</style>
