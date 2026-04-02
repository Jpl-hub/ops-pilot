<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import AppShell from '@/components/AppShell.vue'
import ChartPanel from '@/components/ChartPanel.vue'
import LoadingState from '@/components/LoadingState.vue'
import { useAsyncState } from '@/composables/useAsyncState'
import { get } from '@/lib/api'

const state = useAsyncState<any>()
const livePayload = ref<any | null>(null)
const wsStatus = ref<'connecting' | 'connected' | 'disconnected'>('connecting')
let liveTimer: number | null = null

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
const anomalyItems = computed(() => (streamingAnomalies.value?.items || []).slice(0, 4))
const focusCompanies = computed(() => attentionMatrix.value.slice(0, 4))
const riskCompanies = computed(() => topRiskCompanies.value.slice(0, 3))
const radarCards = computed(() => radarEvents.value.slice(0, 3))
const signalCards = computed(() => signalFeed.value.slice(0, 4))
const pulseSteps = computed(() => brainSignalTape.value.slice(0, 3))
const leadMetric = computed(() => marketTape.value[0] || null)
const supportMetrics = computed(() => marketTape.value.slice(1, 4))

const companyQueue = computed(() => {
  const merged = new Map<
    string,
    {
      companyName: string
      badge: string
      tone: string
      detail: string
      meta: string
      route: { path: string; query?: Record<string, string> }
    }
  >()

  anomalyItems.value.forEach((item: any) => {
    if (!item?.company_name || merged.has(item.company_name)) return
    merged.set(item.company_name, {
      companyName: item.company_name,
      badge: '先处理',
      tone: anomalyTone(item.severity),
      detail: item.summary || '先处理这一轮突发变化。',
      meta: displayAnomalyMeta(item),
      route: item.route,
    })
  })

  riskCompanies.value.forEach((item: any) => {
    if (!item?.company_name || merged.has(item.company_name)) return
    merged.set(item.company_name, {
      companyName: item.company_name,
      badge: '先看风险',
      tone: 'is-risk',
      detail: (item.risk_labels || []).slice(0, 2).join(' · ') || item.subindustry || '先回到风险原文。',
      meta: `${item.risk_count || 0} 个风险`,
      route: item.route,
    })
  })

  focusCompanies.value.forEach((item: any) => {
    if (!item?.company_name || merged.has(item.company_name)) return
    merged.set(item.company_name, {
      companyName: item.company_name,
      badge: '继续看',
      tone: 'is-calm',
      detail: item.headline || '继续跟这一轮变化。',
      meta: displayFocusMeta(item),
      route: item.route,
    })
  })

  return Array.from(merged.values()).slice(0, 4)
})

function displayWsStatus(status: 'connecting' | 'connected' | 'disconnected') {
  const map: Record<string, string> = {
    connecting: '连通中',
    connected: '实时连通',
    disconnected: '已断开',
  }
  return map[status] || status
}

function displaySignalMeta(item: any) {
  const parts = [item?.source_name, item?.subindustry, item?.publish_date].filter(Boolean)
  return parts.join(' · ') || '正式信号'
}

function displayFocusMeta(item: any) {
  const parts = [
    item?.signal_status || '持续关注',
    item?.signal_count ? `${item.signal_count} 条信号` : '',
    item?.external_heat ? `热度 ${item.external_heat}` : '',
    item?.risk_count ? `风险 ${item.risk_count}` : '',
  ].filter(Boolean)
  return parts.join(' · ')
}

function displayAnomalyMeta(item: any) {
  const parts = [
    item?.signal_status || '异动观察',
    item?.score ? `评分 ${item.score}` : '',
    item?.triggers?.length ? `${item.triggers.length} 个触发因子` : '',
  ].filter(Boolean)
  return parts.join(' · ')
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

function stopLiveRefresh() {
  if (liveTimer !== null) {
    window.clearInterval(liveTimer)
    liveTimer = null
  }
}

async function refreshLive() {
  try {
    const nextPayload = await get('/industry/brain/tick')
    livePayload.value = nextPayload
    wsStatus.value = 'connected'
  } catch {
    wsStatus.value = 'disconnected'
  }
}

function startLiveRefresh() {
  stopLiveRefresh()
  wsStatus.value = 'connecting'
  void refreshLive()
  liveTimer = window.setInterval(() => {
    void refreshLive()
  }, 4000)
}

async function loadPage() {
  await state.execute(() => get('/industry/brain')).catch(() => {})
}

onMounted(async () => {
  await loadPage()
  startLiveRefresh()
})

onBeforeUnmount(() => {
  stopLiveRefresh()
})
</script>

<template>
  <AppShell title="">
    <div class="brain-console">
      <LoadingState v-if="state.loading.value && !payload" class="brain-panel brain-loading" />

      <div v-else-if="state.error.value && !payload" class="brain-panel brain-error">
        <strong>产业大脑暂时不可用</strong>
        <p>{{ state.error.value }}</p>
        <button type="button" class="brain-action" @click="() => { loadPage(); startLiveRefresh() }">重新连接</button>
      </div>

      <template v-else-if="payload">
        <section class="brain-header">
          <div class="brain-title">
            <div class="brain-title-row">
              <h1>新能源产业大脑</h1>
              <span class="brain-live-chip" :class="wsStatus === 'connected' ? 'is-live' : 'is-risk'">
                {{ displayWsStatus(wsStatus) }}
              </span>
            </div>
            <p>
              {{
                brainCommandSurface?.headline
                  || signalCards[0]?.headline
                  || '先把今天真正值得继续看的行业变化拎出来。'
              }}
            </p>
          </div>

          <div class="brain-sector-strip">
            <div v-for="tag in topSectorTags" :key="tag.label" class="brain-sector-pill">
              <span>{{ tag.label }}</span>
              <strong>{{ tag.count }}</strong>
            </div>
          </div>
        </section>

        <section class="brain-metric-strip" v-if="leadMetric">
          <article class="brain-metric brain-metric-lead" :class="`is-${leadMetric.tone || 'default'}`">
            <span>{{ leadMetric.label }}</span>
            <strong>{{ leadMetric.value }}</strong>
            <small>{{ leadMetric.delta }}</small>
          </article>
          <article
            v-for="item in supportMetrics"
            :key="item.label"
            class="brain-metric"
            :class="`is-${item.tone || 'default'}`"
          >
            <span>{{ item.label }}</span>
            <strong>{{ item.value }}</strong>
            <small>{{ item.delta }}</small>
          </article>
        </section>

        <section class="brain-main">
          <article class="brain-panel brain-chart-surface">
            <div class="section-head">
              <strong>先看主线</strong>
            </div>

            <div class="brain-chart-wrap">
              <ChartPanel
                v-if="trendChart"
                :title="trendChart.title || '行业脉冲'"
                :options="trendChart.options"
                class="brain-chart-panel"
              />
            </div>

            <div v-if="pulseSteps.length" class="brain-pulse-strip">
              <div v-for="item in pulseSteps" :key="`${item.step}-${item.label}`" class="brain-pulse-item">
                <em>0{{ item.step }}</em>
                <div>
                  <strong>{{ item.label }}</strong>
                  <p>{{ item.value }}</p>
                </div>
              </div>
            </div>
          </article>

          <aside class="brain-panel brain-queue-surface">
            <div class="section-head">
              <strong>今天先处理谁</strong>
            </div>

            <div v-if="companyQueue.length" class="brain-queue-list">
              <RouterLink
                v-for="item in companyQueue"
                :key="item.companyName"
                class="brain-queue-card"
                :class="item.tone"
                :to="{ path: item.route.path, query: item.route.query || {} }"
              >
                <div class="brain-queue-top">
                  <strong>{{ item.companyName }}</strong>
                  <span>{{ item.badge }}</span>
                </div>
                <p>{{ item.detail }}</p>
                <small>{{ item.meta }}</small>
              </RouterLink>
            </div>
            <div v-else class="brain-empty-state">当前没有需要立刻处理的企业。</div>
          </aside>
        </section>

        <section class="brain-bottom">
          <article class="brain-panel">
            <div class="section-head">
              <strong>最新变化</strong>
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
            <div v-else class="brain-empty-state">当前还没有新的正式线索。</div>
          </article>

          <article class="brain-panel">
            <div class="section-head">
              <strong>政策与技术变化</strong>
            </div>

            <div v-if="radarCards.length" class="brain-radar-list">
              <a
                v-for="item in radarCards"
                :key="item.id"
                class="brain-radar-card"
                :href="item.url"
                target="_blank"
                rel="noreferrer"
              >
                <div class="brain-radar-top">
                  <span>{{ item.year }}</span>
                  <strong>{{ displayResearchSource(item) }}</strong>
                </div>
                <h3>{{ item.title }}</h3>
                <p>{{ (item.core_points || []).slice(0, 2).join(' · ') }}</p>
              </a>
            </div>
            <div v-else class="brain-empty-state">当前还没有需要重点关注的变化。</div>
          </article>
        </section>
      </template>
    </div>
  </AppShell>
</template>

<style scoped>
.brain-console {
  display: grid;
  gap: 14px;
  min-height: 100%;
  width: 100%;
  max-width: 1280px;
  margin: 0 auto;
  color: #edf2f7;
}

.brain-panel {
  border-radius: 22px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: linear-gradient(180deg, rgba(15, 16, 20, 0.98), rgba(11, 12, 17, 0.96));
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

.brain-error strong,
.brain-title h1,
.section-head strong,
.brain-queue-top strong,
.brain-stream-top strong,
.brain-radar-card h3 {
  margin: 0;
  color: #f8fafc;
}

.brain-error p,
.brain-title p,
.brain-pulse-item p,
.brain-queue-card p,
.brain-stream-item p,
.brain-radar-card p {
  margin: 0;
  color: rgba(191, 207, 228, 0.82);
  line-height: 1.65;
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

.brain-header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 14px;
  align-items: end;
  padding: 4px 2px 2px;
}

.brain-title {
  display: grid;
  gap: 8px;
}

.brain-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.brain-title h1 {
  font-size: clamp(28px, 2.9vw, 36px);
  line-height: 0.98;
  letter-spacing: -0.05em;
}

.brain-live-chip,
.brain-sector-pill {
  min-height: 32px;
  padding: 0 10px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  font-size: 11px;
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

.brain-sector-strip {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
  max-width: 320px;
}

.brain-sector-pill {
  background: rgba(255, 255, 255, 0.025);
  color: #dff8ee;
}

.brain-sector-pill strong {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  color: #86efac;
}

.brain-metric-strip {
  display: grid;
  grid-template-columns: 1.1fr repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.brain-metric {
  display: grid;
  gap: 6px;
  padding: 14px 16px;
  border-radius: 18px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.03);
}

.brain-metric span,
.brain-metric small,
.brain-pulse-item em,
.brain-stream-top span,
.brain-queue-top span,
.brain-stream-item small,
.brain-queue-card small,
.brain-radar-top span,
.brain-radar-top strong {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: rgba(160, 175, 194, 0.82);
}

.brain-metric strong {
  font-family: 'JetBrains Mono', monospace;
  font-size: 18px;
  color: #f8fafc;
}

.brain-metric-lead strong {
  font-size: 24px;
}

.brain-main,
.brain-bottom {
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(320px, 0.95fr);
  gap: 14px;
}

.brain-chart-surface,
.brain-queue-surface,
.brain-bottom > .brain-panel {
  padding: 16px;
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}

.section-head strong {
  font-size: 16px;
  letter-spacing: -0.03em;
}

.brain-chart-wrap {
  min-height: 316px;
}

:deep(.brain-chart-panel) {
  height: 100%;
  padding: 0 !important;
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
}

.brain-pulse-strip,
.brain-queue-list,
.brain-stream-list,
.brain-radar-list {
  display: grid;
  gap: 10px;
}

.brain-pulse-strip {
  margin-top: 12px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.brain-pulse-item {
  display: grid;
  gap: 6px;
  padding: 12px 14px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.brain-pulse-item strong {
  color: #f8fafc;
  font-size: 14px;
}

.brain-queue-card,
.brain-stream-item,
.brain-radar-card {
  display: grid;
  gap: 6px;
  padding: 14px;
  border-radius: 18px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.03);
  color: inherit;
  text-decoration: none;
  transition: transform 0.18s ease, border-color 0.18s ease, background 0.18s ease;
}

.brain-queue-card:hover,
.brain-stream-item:hover,
.brain-radar-card:hover {
  transform: translateY(-2px);
  border-color: rgba(52, 211, 153, 0.18);
  background: rgba(255, 255, 255, 0.045);
}

.brain-queue-card.is-risk {
  border-color: rgba(251, 113, 133, 0.22);
  background: rgba(190, 24, 93, 0.08);
}

.brain-queue-card.is-warning {
  border-color: rgba(251, 191, 36, 0.18);
  background: rgba(120, 53, 15, 0.08);
}

.brain-queue-top,
.brain-stream-top,
.brain-radar-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.brain-radar-card h3 {
  font-size: 14px;
  line-height: 1.45;
}

.brain-empty-state {
  display: grid;
  place-items: center;
  min-height: 160px;
  color: rgba(152, 167, 187, 0.72);
  text-align: center;
  font-size: 13px;
}

@media (max-width: 1180px) {
  .brain-metric-strip,
  .brain-main,
  .brain-bottom {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 860px) {
  .brain-header {
    grid-template-columns: 1fr;
  }

  .brain-sector-strip {
    justify-content: flex-start;
    max-width: none;
  }

  .brain-pulse-strip {
    grid-template-columns: 1fr;
  }
}
</style>
