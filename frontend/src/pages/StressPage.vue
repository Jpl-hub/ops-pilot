<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import AppShell from '@/components/AppShell.vue'
import ChartPanel from '@/components/ChartPanel.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingState from '@/components/LoadingState.vue'
import { useAsyncState } from '@/composables/useAsyncState'
import { get, post } from '@/lib/api'

const overviewState = useAsyncState<any>()
const stressState = useAsyncState<any>()
const runsState = useAsyncState<any>()
const route = useRoute()

const companies = computed(() => overviewState.data.value?.companies || [])
const availablePeriods = computed(() => overviewState.data.value?.available_periods || [])
const selectedCompany = ref('')
const selectedPeriod = ref('')
const scenario = ref('欧盟对动力电池临时加征关税并限制关键材料进口')
const scenarioDraft = ref(scenario.value)
const activeStressStep = ref(0)
let stressTicker: number | null = null

const presetScenarios = [
  '欧盟对动力电池临时加征关税并限制关键材料进口',
  '上游碳酸锂价格急涨并持续三个月',
  '关键供应商停产两周导致交付延迟',
  '海外主要市场需求快速回落',
]

const propagationSteps = computed(() => stressState.data.value?.propagation_steps || [])
const transmissionMatrix = computed(() => stressState.data.value?.transmission_matrix || [])
const simulationLog = computed(() => stressState.data.value?.simulation_log || [])
const stressWavefront = computed(() => stressState.data.value?.stress_wavefront || [])
const activeWavefront = computed(() => stressWavefront.value[activeStressStep.value] || stressWavefront.value[0] || null)
const activeSimulationLog = computed(() => simulationLog.value[activeStressStep.value] || null)

async function runStress() {
  if (!selectedCompany.value || !scenarioDraft.value.trim()) return
  scenario.value = scenarioDraft.value.trim()
  await stressState.execute(() =>
    post('/company/stress-test', {
      company_name: selectedCompany.value,
      report_period: selectedPeriod.value || null,
      user_role: 'management',
      scenario: scenario.value,
    }),
  )
  const params = new URLSearchParams({ company_name: selectedCompany.value })
  if (selectedPeriod.value) params.set('report_period', selectedPeriod.value)
  params.set('user_role', 'management')
  await runsState.execute(() => get(`/stress-test/runs?${params.toString()}&limit=6`))
  activeStressStep.value = 0
}

onMounted(async () => {
  await overviewState.execute(() => get('/workspace/companies'))
  selectedCompany.value =
    (typeof route.query.company === 'string' ? route.query.company : '') || companies.value[0] || ''
  selectedPeriod.value = typeof route.query.period === 'string' && route.query.period
    ? route.query.period
    : (overviewState.data.value?.preferred_period || '')
  await runStress()
  stressTicker = window.setInterval(() => {
    if (!propagationSteps.value.length) return
    activeStressStep.value = (activeStressStep.value + 1) % propagationSteps.value.length
  }, 3000)
})

onBeforeUnmount(() => {
  if (stressTicker) { window.clearInterval(stressTicker); stressTicker = null }
})

function selectPreset(item: string) {
  scenarioDraft.value = item
  runStress()
}
</script>

<template>
  <AppShell title="产业链压力测试">
    <div class="dashboard-wrapper">

      <!-- Control Bar -->
      <section class="glass-panel control-bar">
        <div class="control-left">
          <div class="glow-icon">压</div>
          <div>
            <h3 class="company-name text-gradient">{{ selectedCompany || '选择公司' }}</h3>
          </div>
        </div>
        <div class="inline-context">
          <label class="inline-field">
            <span class="subtle-label">公司</span>
            <select v-model="selectedCompany" class="glass-select">
              <option v-for="c in companies" :key="c" :value="c">{{ c }}</option>
            </select>
          </label>
          <label class="inline-field">
            <span class="subtle-label">报期</span>
            <select v-model="selectedPeriod" class="glass-select">
              <option value="">默认主周期</option>
              <option v-for="p in availablePeriods" :key="p" :value="p">{{ p }}</option>
            </select>
          </label>
        </div>
      </section>

      <!-- Scenario Input -->
      <section class="glass-panel scenario-bar">
        <div class="scenario-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="18" height="18"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
        </div>
        <input
          v-model="scenarioDraft"
          class="scenario-input"
          placeholder="输入压力场景，例如：上游核心矿产断供…"
          :disabled="stressState.loading.value"
          @keydown.enter="runStress"
        />
        <div v-if="stressState.data.value?.severity" class="severity-badge" :class="`tone-${stressState.data.value.severity.color || 'warning'}`">
          {{ stressState.data.value.severity.level }} {{ stressState.data.value.severity.label }}
        </div>
        <button class="button-primary scenario-btn" :disabled="stressState.loading.value || !selectedCompany" @click="runStress">
          {{ stressState.loading.value ? '推演中…' : '启动推演' }}
        </button>
      </section>

      <!-- Preset Pills -->
      <div class="preset-row">
        <button v-for="item in presetScenarios" :key="item" class="preset-pill" @click="selectPreset(item)">
          {{ item }}
        </button>
      </div>

      <LoadingState v-if="overviewState.loading.value || stressState.loading.value" class="state-container" />
      <ErrorState v-else-if="stressState.error.value" :message="String(stressState.error.value)" class="state-container" />

      <!-- Main Content -->
      <div v-else class="content-grid">

        <!-- Left: Transmission Matrix + Propagation Chain -->
        <div class="left-col">

          <!-- Transmission Matrix -->
          <article class="glass-panel matrix-panel" v-if="transmissionMatrix.length">
            <h3 class="panel-title">冲击传导网络</h3>
            <div class="matrix-grid">
              <div
                v-for="(item, index) in transmissionMatrix"
                :key="item.stage"
                class="matrix-node"
                :class="[`node-${item.tone || 'warning'}`, {
                  'is-active': activeWavefront?.active_stage === 'upstream' && index === 0
                    || activeWavefront?.active_stage === 'midstream' && index === 1
                    || activeWavefront?.active_stage === 'downstream' && index === 2
                }]"
              >
                <div class="node-header">
                  <div class="node-dot"></div>
                  <span class="node-stage">{{ item.stage }}</span>
                  <div v-if="index < transmissionMatrix.length - 1" class="node-arrow">→</div>
                </div>
                <div class="node-headline">{{ item.headline }}</div>
                <div class="node-score">{{ item.impact_score }}</div>
                <div class="node-label muted">{{ item.impact_label }}</div>
              </div>
            </div>
          </article>

          <!-- Chart Panel -->
          <article class="glass-panel chart-panel" v-if="stressState.data.value?.chart">
            <ChartPanel
              title="冲击传导强度"
              :options="stressState.data.value.chart.options"
            />
          </article>

          <!-- Propagation Chain -->
          <article class="glass-panel chain-panel" v-if="propagationSteps.length">
            <h3 class="panel-title">传播推演链路</h3>
            <div class="chain-list">
              <template v-for="(item, idx) in propagationSteps" :key="item.step">
                <div class="chain-item" :class="{ 'is-active': idx <= activeStressStep }">
                  <span class="chain-num">{{ String(item.step).padStart(2, '0') }}</span>
                  <span class="chain-title">{{ item.title }}</span>
                </div>
                <div v-if="idx < propagationSteps.length - 1" class="chain-sep">→</div>
              </template>
            </div>
          </article>

          <!-- Empty Left -->
          <article v-if="!transmissionMatrix.length && !propagationSteps.length" class="glass-panel empty-panel">
            <div class="empty-content">
              <h3 class="text-gradient mb-2">等待压力推演</h3>
              <p class="muted">选择公司并输入压力场景后点击「启动推演」。</p>
            </div>
          </article>
        </div>

        <!-- Right: Simulation Stream -->
        <div class="right-col">
          <article class="glass-panel stream-panel">
            <h3 class="panel-title">仿真日志</h3>

            <!-- Active Wavefront -->
            <div class="wavefront-card">
              <div class="wavefront-head">
                <span class="wavefront-lbl">当前冲击波前</span>
                <span class="wavefront-badge">{{ activeWavefront ? '推演中' : '就绪' }}</span>
              </div>
              <h4 class="wavefront-title">{{ activeWavefront?.headline || activeSimulationLog?.title || '等待推演' }}</h4>
              <p class="wavefront-desc muted">{{ activeWavefront?.log || activeSimulationLog?.detail || '系统准备冲击波前计算…' }}</p>
              <div class="meter-box">
                <div class="meter-row">
                  <span class="muted">冲击能量</span>
                  <strong class="meter-val">{{ activeWavefront?.impact_score || 0 }}</strong>
                </div>
                <div class="meter-track">
                  <div class="meter-fill" :style="{ width: `${activeWavefront?.energy || 0}%` }"></div>
                </div>
              </div>
            </div>

            <!-- Log List -->
            <div class="log-list">
              <div
                v-for="item in simulationLog"
                :key="`log-${item.step}`"
                class="log-item glass-panel-hover"
                :class="{ 'is-active': item.step - 1 === activeStressStep }"
              >
                <div class="log-num">{{ item.step }}</div>
                <div class="log-body">
                  <strong class="log-title">{{ item.title }}</strong>
                  <p class="log-desc muted">{{ item.detail }}</p>
                </div>
              </div>
            </div>

            <!-- Empty Right -->
            <div v-if="!simulationLog.length" class="empty-stream muted">
              推演完成后将显示仿真日志
            </div>
          </article>
        </div>
      </div>
    </div>
  </AppShell>
</template>

<style scoped>
.dashboard-wrapper { display: flex; flex-direction: column; gap: 14px; height: 100%; overflow: hidden; }

/* Control Bar */
.control-bar { display: flex; justify-content: space-between; align-items: center; padding: 16px 24px; border-radius: 16px; flex-shrink: 0; }
.control-left { display: flex; align-items: center; gap: 16px; }
.glow-icon { width: 40px; height: 40px; border-radius: 12px; background: rgba(244,63,94,0.15); border: 1px solid rgba(244,63,94,0.4); color: #f43f5e; display: grid; place-items: center; font-weight: bold; font-size: 18px; box-shadow: 0 0 15px rgba(244,63,94,0.2); }
.company-name { margin: 0; font-size: 20px; font-weight: 600; }
.text-gradient { background-clip: text; -webkit-text-fill-color: transparent; background-image: linear-gradient(to right, #f43f5e, #fb923c); }
.inline-context { display: flex; align-items: center; gap: 16px; }
.inline-field { display: flex; align-items: center; gap: 8px; }
.subtle-label { font-size: 12px; color: var(--muted); text-transform: uppercase; }
.glass-select { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); min-height: 36px; padding: 0 12px; border-radius: 8px; color: #fff; }
.glass-input { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); min-height: 36px; padding: 0 12px; border-radius: 8px; color: #fff; width: 100px; outline: none; }

/* Scenario Bar */
.scenario-bar { display: flex; align-items: center; gap: 14px; padding: 14px 20px; border-radius: 12px; flex-shrink: 0; }
.scenario-icon { width: 36px; height: 36px; border-radius: 50%; background: rgba(244,63,94,0.1); border: 1px solid rgba(244,63,94,0.2); display: flex; align-items: center; justify-content: center; color: #f43f5e; flex-shrink: 0; }
.scenario-input { flex: 1; background: transparent; border: none; font-size: 15px; color: #fff; outline: none; font-weight: 500; }
.scenario-input::placeholder { color: var(--muted); }
.scenario-input:disabled { opacity: 0.5; }
.severity-badge { font-size: 12px; padding: 4px 12px; border-radius: 6px; font-weight: 600; flex-shrink: 0; }
.tone-risk { background: rgba(244,63,94,0.15); color: #f43f5e; border: 1px solid rgba(244,63,94,0.3); }
.tone-warning { background: rgba(245,158,11,0.15); color: #f59e0b; border: 1px solid rgba(245,158,11,0.3); }
.tone-safe { background: rgba(16,185,129,0.15); color: #10b981; border: 1px solid rgba(16,185,129,0.3); }
.scenario-btn { min-height: 36px; padding: 0 16px; border-radius: 8px; font-size: 13px; flex-shrink: 0; }

/* Presets */
.preset-row { display: flex; flex-wrap: wrap; gap: 8px; flex-shrink: 0; }
.preset-pill { background: transparent; border: 1px solid rgba(255,255,255,0.1); color: var(--muted); padding: 6px 14px; border-radius: 99px; font-size: 12px; cursor: pointer; transition: all 0.2s; }
.preset-pill:hover { background: rgba(244,63,94,0.1); border-color: rgba(244,63,94,0.3); color: #fb7185; }

.state-container { flex: 1; }

/* Content Grid */
.content-grid { display: grid; grid-template-columns: 1fr 320px; gap: 14px; flex: 1; min-height: 0; }
.left-col { display: flex; flex-direction: column; gap: 14px; min-height: 0; overflow-y: auto; }
.left-col::-webkit-scrollbar { width: 4px; }
.left-col::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 2px; }
.right-col { display: flex; flex-direction: column; min-height: 0; overflow: hidden; }

.panel-title { font-size: 12px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); margin: 0 0 14px; padding-bottom: 10px; border-bottom: 1px solid rgba(255,255,255,0.05); }
.muted { color: var(--muted); }

/* Matrix */
.matrix-panel { padding: 20px; border-radius: 16px; flex-shrink: 0; }
.matrix-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.matrix-node { position: relative; background: rgba(39,39,42,0.4); border: 1px solid rgba(255,255,255,0.06); border-radius: 14px; padding: 16px; display: flex; flex-direction: column; gap: 8px; transition: all 0.3s; }
.matrix-node:hover { transform: translateY(-3px); }
.matrix-node.is-active { background: rgba(127,29,29,0.2); border-color: rgba(244,63,94,0.3); box-shadow: 0 0 24px rgba(244,63,94,0.12); }
.node-header { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.node-dot { width: 6px; height: 6px; border-radius: 50%; background: rgba(255,255,255,0.3); flex-shrink: 0; }
.is-active .node-dot { background: #f43f5e; box-shadow: 0 0 6px #f43f5e; }
.node-stage { font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); }
.node-arrow { margin-left: auto; color: rgba(255,255,255,0.15); font-size: 14px; }
.node-headline { font-size: 14px; font-weight: 600; color: #f3f4f6; line-height: 1.4; }
.node-score { font-size: 26px; font-family: 'JetBrains Mono', monospace; font-weight: 300; color: #fb7185; }
.node-label { font-size: 12px; }

/* Chart */
.chart-panel { padding: 16px; border-radius: 16px; flex-shrink: 0; min-height: 220px; display: flex; flex-direction: column; }
:deep(.chart-panel-inner) { flex: 1; min-height: 0; }

/* Propagation Chain */
.chain-panel { padding: 20px; border-radius: 16px; flex-shrink: 0; }
.chain-list { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.chain-item { padding: 8px 14px; border-radius: 6px; background: rgba(127,29,29,0.1); border: 1px solid rgba(244,63,94,0.12); display: flex; align-items: center; gap: 8px; transition: all 0.3s; }
.chain-item.is-active { background: rgba(127,29,29,0.25); border-color: rgba(244,63,94,0.35); box-shadow: 0 0 14px rgba(244,63,94,0.12); }
.chain-num { font-size: 11px; color: rgba(244,63,94,0.7); font-family: 'JetBrains Mono', monospace; }
.chain-title { font-size: 13px; color: #e5e7eb; white-space: nowrap; }
.chain-sep { color: rgba(255,255,255,0.15); font-size: 14px; }

/* Empty */
.empty-panel { display: grid; place-items: center; flex: 1; border-radius: 16px; }
.empty-content { text-align: center; }
.text-gradient { background-clip: text; -webkit-text-fill-color: transparent; background-image: linear-gradient(to right, #f43f5e, #fb923c); }
.mb-2 { margin-bottom: 8px; }

/* Simulation Stream */
.stream-panel { flex: 1; padding: 20px; border-radius: 16px; display: flex; flex-direction: column; gap: 14px; overflow: hidden; }

.wavefront-card { background: linear-gradient(135deg, rgba(244,63,94,0.08), rgba(0,0,0,0.3)); border: 1px solid rgba(244,63,94,0.2); border-radius: 12px; padding: 14px; flex-shrink: 0; }
.wavefront-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.wavefront-lbl { font-size: 11px; color: #fb7185; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; }
.wavefront-badge { font-size: 10px; background: rgba(244,63,94,0.15); color: #fda4af; padding: 2px 8px; border-radius: 4px; border: 1px solid rgba(244,63,94,0.25); }
.wavefront-title { font-size: 14px; font-weight: 600; color: #fff; margin: 0 0 6px; line-height: 1.4; }
.wavefront-desc { font-size: 12px; margin: 0; line-height: 1.5; }
.meter-box { margin-top: 12px; }
.meter-row { display: flex; justify-content: space-between; font-size: 11px; margin-bottom: 4px; }
.meter-val { color: #fb7185; font-weight: 700; }
.meter-track { height: 4px; background: rgba(255,255,255,0.05); border-radius: 2px; overflow: hidden; }
.meter-fill { height: 100%; background: #f43f5e; box-shadow: 0 0 8px #f43f5e; transition: width 0.5s ease; }

.log-list { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; }
.log-list::-webkit-scrollbar { width: 4px; }
.log-list::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 2px; }
.log-item { display: flex; gap: 12px; align-items: flex-start; padding: 10px 12px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.05); transition: all 0.3s; }
.log-item.is-active { border-color: rgba(244,63,94,0.3); background: rgba(244,63,94,0.05); }
.log-num { width: 24px; height: 24px; border-radius: 50%; background: rgba(244,63,94,0.1); border: 1px solid rgba(244,63,94,0.2); color: #fb7185; display: grid; place-items: center; font-size: 11px; font-weight: 700; flex-shrink: 0; }
.log-body { display: flex; flex-direction: column; gap: 3px; }
.log-title { font-size: 13px; color: #fff; }
.log-desc { font-size: 12px; margin: 0; line-height: 1.5; }

.empty-stream { text-align: center; padding: 32px; font-size: 13px; }
</style>
