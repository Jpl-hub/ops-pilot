<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import AppShell from '@/components/AppShell.vue'
import ChartPanel from '@/components/ChartPanel.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingState from '@/components/LoadingState.vue'
import StatCard from '@/components/StatCard.vue'
import TagPill from '@/components/TagPill.vue'
import { useAsyncState } from '@/composables/useAsyncState'
import { get } from '@/lib/api'

const state = useAsyncState<any>()
const selectedAlertCompany = ref('')
const alertFilter = ref<'all' | 'delta'>('all')
const route = useRoute()

const alertBoard = computed(() => {
  const alerts = state.data.value?.alert_board || []
  if (alertFilter.value === 'delta') {
    return alerts.filter((item: any) => item.risk_delta > 0)
  }
  return alerts
})

const selectedAlert = computed(() => {
  const alerts = alertBoard.value
  if (!alerts.length) return null
  return alerts.find((item: any) => item.company_name === selectedAlertCompany.value) || alerts[0]
})

watch(
  alertBoard,
  (alerts) => {
    if (!alerts.length) {
      selectedAlertCompany.value = ''
      return
    }
    if (!alerts.some((item: any) => item.company_name === selectedAlertCompany.value)) {
      selectedAlertCompany.value = alerts[0].company_name
    }
  },
  { immediate: true },
)

onMounted(() => {
  void state.execute(() => get('/industry/risk-scan'))
})

watch(
  () => route.query.company,
  (companyQuery) => {
    const company = typeof companyQuery === 'string' ? companyQuery : ''
    if (!company) {
      return
    }
    selectedAlertCompany.value = company
  },
  { immediate: true },
)
</script>

<template>
  <AppShell
    title="行业风险与机会"
    subtitle="主动预警研判与全量高危追踪"
  >
    <LoadingState v-if="state.loading.value" class="state-container" />
    <ErrorState v-else-if="state.error.value" :message="state.error.value" class="state-container" />
    
    <div v-else-if="state.data.value" class="dashboard-wrapper">
      
      <!-- Top Metrics Strip -->
      <section class="glass-panel metrics-strip">
        <div class="metric-block">
          <span class="mb-label">覆盖公司</span>
          <strong class="mb-value text-gradient">{{ state.data.value.risk_board.length }}</strong>
        </div>
        <div class="metric-block">
          <span class="mb-label">高风险公司</span>
          <strong class="mb-value risk-text">{{ state.data.value.risk_board.filter((item: any) => item.risk_count > 0).length }}</strong>
        </div>
        <div class="metric-block">
          <span class="mb-label">行业研究</span>
          <strong class="mb-value">{{ state.data.value.industry_research.key_numbers[0].value }}</strong>
        </div>
        <div class="metric-block border-none">
          <span class="mb-label">行业研报</span>
          <strong class="mb-value text-accent">{{ state.data.value.industry_research.key_numbers[1].value }}</strong>
        </div>
      </section>

      <!-- Main Split Layout -->
      <div class="dashboard-grid">
        
        <!-- Left: Alerts List -->
        <div class="dashboard-col glass-panel alerts-panel">
          <div class="panel-header-sticky">
            <h3 class="panel-sm-title m-0">主动预警</h3>
            <div class="segmented-control">
              <button
                class="segment-btn" :class="{ active: alertFilter === 'all' }"
                @click="alertFilter = 'all'"
              >全部</button>
              <button
                class="segment-btn" :class="{ active: alertFilter === 'delta' }"
                @click="alertFilter = 'delta'"
              >新增风险</button>
            </div>
          </div>
          
          <div class="alerts-scroll-view scroll-area">
            <div v-if="alertBoard.length" class="alerts-list">
              <div
                v-for="item in alertBoard"
                :key="`${item.company_name}-${item.report_period}`"
                class="alert-card glass-panel-hover"
                :class="{ 'is-active': selectedAlertCompany === item.company_name }"
                @click="selectedAlertCompany = item.company_name"
              >
                <div class="ac-head">
                  <span class="ac-code">{{ item.subindustry }}</span>
                  <span class="ac-risk-count" :class="item.risk_delta > 0 ? 'risk-text' : 'muted'">{{ item.risk_count }}项</span>
                </div>
                <h4 class="ac-title">{{ item.company_name }}</h4>
                <div class="ac-tags">
                  <span v-if="item.risk_delta > 0" class="tag risk-tag">+{{ item.risk_delta }}风险</span>
                  <span v-else class="tag subtle-tag">风险延续</span>
                  <span class="tag subtle-tag">{{ item.report_period }}</span>
                </div>
              </div>
            </div>
            <div v-else class="empty-state">当前无预警</div>
          </div>
        </div>

        <!-- Right: Maps/Charts/Selected Detail -->
        <div class="dashboard-col main-panel scroll-area">
          
          <!-- Selected Alert Details -->
          <article v-if="selectedAlert" class="glass-panel selected-alert-panel mb-4">
            <div class="sa-head">
              <div class="sa-title-block">
                <div class="eyebrow">预警分析</div>
                <h3 class="sa-company text-gradient">{{ selectedAlert.company_name }}</h3>
                <span class="sa-period">{{ selectedAlert.report_period }}</span>
              </div>
              <div class="sa-actions">
                <RouterLink
                   class="button-primary glow-button"
                   :to="`/score?company=${encodeURIComponent(selectedAlert.company_name)}&period=${encodeURIComponent(selectedAlert.report_period)}`"
                >体检下钻</RouterLink>
                <RouterLink
                   v-if="selectedAlert.previous_period"
                   class="button-secondary p-btn"
                   :to="`/score?company=${encodeURIComponent(selectedAlert.company_name)}&period=${encodeURIComponent(selectedAlert.previous_period)}`"
                >环比分析</RouterLink>
              </div>
            </div>
            <p class="sa-summary">{{ selectedAlert.summary }}</p>
            <div v-if="selectedAlert.new_labels?.length" class="sa-new-labels mt-3">
              <span class="eyebrow inline-mr">新增标签:</span>
              <TagPill v-for="label in selectedAlert.new_labels" :key="label" :label="label" tone="risk" />
            </div>
          </article>

          <!-- Charts -->
          <div class="charts-row mb-4">
            <div v-for="chart in state.data.value.charts" :key="chart.title" class="glass-panel chart-container">
              <ChartPanel :title="chart.title" :options="chart.options" />
            </div>
          </div>

          <!-- Bottom Split -->
          <div class="bottom-split">
            <!-- Full Risk Board Grid -->
            <div class="glass-panel flex-1 min-w-0 p-5 scroll-area" style="max-height: 400px;">
              <h3 class="panel-sm-title mb-3">全量风险名单</h3>
              <div class="company-grid-mini">
                <RouterLink
                  v-for="item in state.data.value.risk_board"
                  :key="item.company_name"
                  class="mini-company-card glass-panel-hover"
                  :to="`/score?company=${encodeURIComponent(item.company_name)}`"
                >
                  <div class="mcc-head">
                    <span class="mcc-title">{{ item.company_name }}</span>
                    <span class="mcc-count" :class="item.risk_count > 0 ? 'risk-text' : 'muted'">{{ item.risk_count }}</span>
                  </div>
                  <div class="mcc-industry">{{ item.subindustry }}</div>
                </RouterLink>
              </div>
            </div>

            <!-- Reports List -->
            <div class="glass-panel flex-1 min-w-0 p-5 scroll-area" style="max-height: 400px;">
              <h3 class="panel-sm-title mb-3">行业研报观察</h3>
              <div class="reports-list">
                <article v-for="group in state.data.value.industry_research.groups" :key="group.industry_name" class="report-card glass-panel-hover">
                  <div class="rc-head">
                    <span class="rc-industry">{{ group.industry_name }}</span>
                    <span class="rc-count">{{ group.report_count }}篇</span>
                  </div>
                  <h5 class="rc-title">{{ group.latest_report.title }}</h5>
                  <div class="rc-meta">
                    <span class="muted">{{ group.latest_report.source_name }}</span>
                    <span class="muted">{{ group.latest_report.publish_date }}</span>
                    <a :href="group.latest_report.source_url" target="_blank" class="rc-link text-accent">阅读全文</a>
                  </div>
                </article>
              </div>
            </div>
          </div>

        </div>
      </div>
    </div>
  </AppShell>
</template>

<style scoped>
.dashboard-wrapper {
  display: flex;
  flex-direction: column;
  height: 100%;
  gap: 16px;
}

/* Metrics Strip */
.metrics-strip {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  padding: 16px 24px;
  border-radius: 16px;
  flex-shrink: 0;
}
.metric-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
  border-right: 1px solid rgba(255, 255, 255, 0.08);
  padding: 0 16px;
}
.metric-block.border-none { border-right: none; }
.mb-label { font-size: 13px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; font-family: 'JetBrains Mono', monospace; }
.mb-value { font-size: 28px; line-height: 1; font-weight: 600; }
.text-accent { color: #10b981; }

/* Dashboard Grid */
.dashboard-grid {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 16px;
  flex: 1;
  min-height: 0;
}
.dashboard-col {
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.scroll-area { overflow-y: auto; }
.scroll-area::-webkit-scrollbar { width: 4px; }

/* Alerts Panel */
.alerts-panel {
  border-radius: 20px;
  overflow: hidden;
}
.panel-header-sticky {
  position: sticky;
  top: 0;
  background: rgba(15, 23, 42, 0.85);
  backdrop-filter: blur(12px);
  padding: 16px 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  z-index: 10;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.m-0 { margin: 0; }

.segmented-control {
  display: flex;
  background: rgba(0,0,0,0.3);
  border-radius: 8px;
  padding: 4px;
}
.segment-btn {
  flex: 1;
  background: transparent;
  color: var(--muted);
  border: none;
  border-radius: 6px;
  padding: 6px 0;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
}
.segment-btn.active {
  background: rgba(16, 185, 129, 0.15);
  color: #10b981;
  box-shadow: 0 2px 4px rgba(0,0,0,0.2);
}

.alerts-scroll-view {
  flex: 1;
  padding: 12px 20px 20px;
}
.alerts-list { display: flex; flex-direction: column; gap: 8px; }
.alert-card {
  padding: 14px;
  border-radius: 12px;
  border: 1px solid rgba(255,255,255,0.05);
  cursor: pointer;
  background: rgba(255,255,255,0.02);
  transition: all 0.2s;
}
.alert-card.is-active {
  border-color: rgba(16, 185, 129, 0.4);
  background: rgba(16, 185, 129, 0.08);
  box-shadow: 0 0 20px rgba(16, 185, 129, 0.1);
}
.ac-head { display: flex; justify-content: space-between; font-size: 11px; font-family: 'JetBrains Mono', monospace; margin-bottom: 6px; }
.ac-code { color: var(--muted); }
.ac-risk-count { font-weight: bold; }
.ac-title { margin: 0 0 10px; font-size: 15px; font-weight: 500; color: #fff; }
.ac-tags { display: flex; gap: 6px; flex-wrap: wrap; }
.tag { font-size: 11px; padding: 2px 6px; border-radius: 4px; }
.risk-tag { background: rgba(244, 63, 94, 0.15); color: #f43f5e; border: 1px solid rgba(244, 63, 94, 0.3); }
.subtle-tag { background: rgba(255,255,255,0.05); color: var(--muted); border: 1px solid rgba(255,255,255,0.1); }

/* Main Panel Right side */
.main-panel {
  border-radius: 20px;
  flex: 1;
}

/* Selected Alert */
.selected-alert-panel {
  padding: 24px;
  border-radius: 20px;
}
.sa-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }
.sa-title-block { display: flex; flex-direction: column; gap: 6px; }
.sa-company { margin: 0; font-size: 24px; font-weight: 600; }
.sa-period { font-size: 13px; color: var(--muted); }
.sa-actions { display: flex; gap: 8px; }
.glow-button { box-shadow: 0 0 15px rgba(16, 185, 129, 0.2); }
.p-btn { padding: 0 12px; height: 40px; }
.sa-summary { margin: 0; font-size: 14px; line-height: 1.6; color: #cbd5e1; }
.inline-mr { margin-right: 8px; font-size: 12px; }

/* Charts */
.charts-row {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
  height: 380px;
  flex-shrink: 0;
}
.mb-4 { margin-bottom: 16px; }
.mt-3 { margin-top: 12px; }
.p-5 { padding: 20px; }
.chart-container {
  border-radius: 20px;
  padding: 16px;
  display: flex;
  flex-direction: column;
}
:deep(.chart-panel) { padding: 0; flex: 1; display: flex; flex-direction: column; background: transparent !important; border: none !important; }
:deep(.chart-root) { flex: 1; height: auto !important; }

/* Bottom Splits */
.bottom-split {
  display: flex;
  gap: 16px;
  flex-shrink: 0;
}
.company-grid-mini {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}
.mini-company-card {
  padding: 12px;
  border-radius: 10px;
  border: 1px solid rgba(255,255,255,0.05);
  display: flex;
  flex-direction: column;
  gap: 6px;
  text-decoration: none;
}
.mcc-head { display: flex; justify-content: space-between; align-items: center; }
.mcc-title { font-size: 14px; font-weight: 500; color: #fff; }
.mcc-industry { font-size: 11px; color: var(--muted); font-family: 'JetBrains Mono', monospace; }

.reports-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.report-card {
  padding: 14px;
  border-radius: 12px;
  border: 1px solid rgba(255,255,255,0.05);
}
.rc-head { display: flex; justify-content: space-between; font-size: 12px; font-family: 'JetBrains Mono', monospace; margin-bottom: 8px;}
.rc-industry { color: #818cf8; background: rgba(129, 140, 248, 0.1); padding: 2px 6px; border-radius: 4px; }
.rc-count { color: var(--muted); }
.rc-title { margin: 0 0 12px; font-size: 15px; font-weight: 500; color: #fff; line-height: 1.4; }
.rc-meta { display: flex; justify-content: space-between; font-size: 12px; align-items: center; }
.rc-link { text-decoration: none; font-weight: 500; }
</style>
