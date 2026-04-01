<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import AppShell from '@/components/AppShell.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingState from '@/components/LoadingState.vue'
import { useAsyncState } from '@/composables/useAsyncState'
import { get, post } from '@/lib/api'

const overviewState = useAsyncState<any>()
const stressState = useAsyncState<any>()
const route = useRoute()

const companies = computed(() => overviewState.data.value?.companies || [])
const availablePeriods = computed(() => overviewState.data.value?.available_periods || [])
const hasCompanies = computed(() => companies.value.length > 0)
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
]

const propagationSteps = computed(() => stressState.data.value?.propagation_steps || [])
const transmissionMatrix = computed(() => stressState.data.value?.transmission_matrix || [])
const simulationLog = computed(() => stressState.data.value?.simulation_log || [])
const stressWavefront = computed(() => stressState.data.value?.stress_wavefront || [])
const stressCommandSurface = computed(() => stressState.data.value?.stress_command_surface || null)
const affectedDimensions = computed(() => stressState.data.value?.affected_dimensions || [])
const recoverySequence = computed(() => stressState.data.value?.stress_recovery_sequence || [])
const activeWavefront = computed(() => stressWavefront.value[activeStressStep.value] || stressWavefront.value[0] || null)
const activeSimulationLog = computed(() => simulationLog.value[activeStressStep.value] || simulationLog.value[0] || null)
const canRunStress = computed(() => !!selectedCompany.value && !!scenarioDraft.value.trim())
const visibleAffectedDimensions = computed(() => affectedDimensions.value.slice(0, 2))
const focusedTransmissionMatrix = computed(() => transmissionMatrix.value.slice(0, 3))
const compactSimulationLog = computed(() => simulationLog.value.slice(0, 3))
const primaryRecoveryAction = computed(() => recoverySequence.value[0] || null)
const primaryScenarioLabel = computed(() => selectedCompany.value || '选择公司后开始推演')
const scenarioStatusLine = computed(() =>
  selectedPeriod.value ? `${selectedPeriod} · 从一个明确冲击假设开始` : '默认主周期 · 从一个明确冲击假设开始',
)

function localizeStressText(value?: string) {
  if (!value) return ''
  return value
    .replace(/\bupstream\b/gi, '上游')
    .replace(/\bmidstream\b/gi, '中游')
    .replace(/\bdownstream\b/gi, '下游')
    .replace(/\bactions?\b/gi, '动作')
    .replace(/\bcritical\b/gi, '极高')
    .replace(/\bhigh\b/gi, '高')
    .replace(/\bmoderate\b/gi, '中')
    .replace(/\bmedium\b/gi, '中')
    .replace(/\blow\b/gi, '低')
    .replace(/\brisk\b/gi, '风险')
    .replace(/\bimpact\b/gi, '冲击')
    .replace(/\bseverity\b/gi, '等级')
}

function displayStageName(value?: string) {
  const normalized = (value || '').toLowerCase()
  const map: Record<string, string> = {
    upstream: '上游',
    midstream: '中游',
    downstream: '下游',
    actions: '动作',
  }
  return map[normalized] || localizeStressText(value)
}

function displaySeverityLevel(level?: string) {
  const map: Record<string, string> = {
    CRITICAL: '极高',
    HIGH: '高',
    MODERATE: '中',
    MEDIUM: '中',
    LOW: '低',
  }
  return map[(level || '').toUpperCase()] || '待定'
}

function displaySeverityBadge(severity?: { label?: string; level?: string }) {
  return severity?.label || displaySeverityLevel(severity?.level)
}

function displayToneClass(color?: string) {
  if (color === 'risk') return 'tone-risk'
  if (color === 'warning') return 'tone-warning'
  if (color === 'success' || color === 'safe') return 'tone-safe'
  return 'tone-warning'
}

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
  }, 3200)
})

onBeforeUnmount(() => {
  if (stressTicker) {
    window.clearInterval(stressTicker)
    stressTicker = null
  }
})

function selectPreset(item: string) {
  scenarioDraft.value = item
  runStress()
}
</script>

<template>
  <AppShell title="">
    <div class="stress-console">
      <section class="stress-header">
        <div class="stress-heading">
          <span class="stress-kicker">冲击推演</span>
          <h1>压力推演</h1>
          <p>{{ primaryScenarioLabel }} · {{ scenarioStatusLine }}</p>
        </div>

        <div class="stress-controls">
          <label class="stress-select">
            <span>公司</span>
            <select v-model="selectedCompany">
              <option v-if="!companies.length" value="">暂无公司</option>
              <option v-for="company in companies" :key="company" :value="company">{{ company }}</option>
            </select>
          </label>
          <label class="stress-select">
            <span>报期</span>
            <select v-model="selectedPeriod">
              <option value="">默认主周期</option>
              <option v-for="period in availablePeriods" :key="period" :value="period">{{ period }}</option>
            </select>
          </label>
        </div>
      </section>

      <section class="scenario-board">
        <div class="scenario-copy">
          <span>输入一个冲击假设</span>
          <strong>看它会先传到哪里、会伤到什么、现在该先做什么。</strong>
        </div>
        <div class="scenario-shell">
          <textarea
            v-model="scenarioDraft"
            class="scenario-input"
            :placeholder="selectedCompany ? '例如：欧洲市场补贴骤降，需求在一个季度内快速回落' : '当前无可推演企业，请先完成公司池接入'"
            :disabled="stressState.loading.value || !selectedCompany"
          />
          <button class="scenario-submit" :disabled="stressState.loading.value || !canRunStress" @click="runStress">
            {{ stressState.loading.value ? '推演中...' : '开始推演' }}
          </button>
        </div>
        <div class="scenario-pills">
          <button
            v-for="item in presetScenarios.slice(0, 2)"
            :key="item"
            class="scenario-pill"
            :disabled="!selectedCompany"
            @click="selectPreset(item)"
          >
            {{ item }}
          </button>
        </div>
      </section>

      <LoadingState v-if="overviewState.loading.value || stressState.loading.value" class="stress-state" />
      <ErrorState v-else-if="stressState.error.value" :message="String(stressState.error.value)" class="stress-state" />
      <section v-else-if="!hasCompanies" class="stress-state stress-empty">
        <p>当前还没有可推演企业，请先完成正式公司池和产业链数据接入。</p>
      </section>

      <template v-else>
        <section class="decision-panel" v-if="stressCommandSurface">
          <div class="decision-head">
            <div>
              <span class="decision-kicker">本轮判断</span>
              <h2>{{ localizeStressText(stressCommandSurface.headline) }}</h2>
              <p>{{ scenario }}</p>
            </div>
            <div class="severity-badge" :class="displayToneClass(stressState.data.value?.severity?.color)">
              {{ displaySeverityBadge(stressState.data.value?.severity) }}
            </div>
          </div>

          <div class="decision-grid" v-if="focusedTransmissionMatrix.length">
            <article
              v-for="item in focusedTransmissionMatrix"
              :key="item.stage"
              class="decision-card"
              :class="`tone-${item.tone || 'warning'}`"
            >
              <span>{{ displayStageName(item.stage) }}</span>
              <strong>{{ localizeStressText(item.headline) }}</strong>
              <p>{{ localizeStressText(item.impact_label) }}</p>
            </article>
          </div>

          <div class="decision-footer">
            <div class="decision-metrics" v-if="visibleAffectedDimensions.length">
              <article v-for="item in visibleAffectedDimensions" :key="item.label" class="metric-chip">
                <span>{{ item.label }}</span>
                <strong>{{ item.value }}</strong>
                <small>{{ item.hint }}</small>
              </article>
            </div>
            <div v-if="primaryRecoveryAction" class="decision-action">
              <span>现在先做</span>
              <strong>{{ primaryRecoveryAction.title }}</strong>
              <p>{{ primaryRecoveryAction.detail }}</p>
            </div>
          </div>
        </section>

        <section class="stress-body">
          <article class="chain-panel" v-if="propagationSteps.length">
            <div class="panel-head">
              <strong>传导主链</strong>
              <span>这次冲击会沿这条线往下走</span>
            </div>
            <div class="chain-steps">
              <div
                v-for="(item, idx) in propagationSteps.slice(0, 3)"
                :key="item.step"
                class="chain-step"
                :class="{ 'is-active': idx <= activeStressStep }"
              >
                <em>{{ String(item.step).padStart(2, '0') }}</em>
                <div>
                  <strong>{{ localizeStressText(item.title) }}</strong>
                  <p>{{ localizeStressText(item.detail) }}</p>
                </div>
              </div>
            </div>
          </article>

          <article class="reason-panel">
            <div class="panel-head">
              <strong>为什么会这样</strong>
              <span>把这轮推演真正说清楚</span>
            </div>

            <div class="reason-focus">
              <span>当前重点</span>
              <strong>{{ localizeStressText(activeWavefront?.headline || stressCommandSurface?.headline || activeSimulationLog?.title || '等待推演') }}</strong>
              <p>{{ localizeStressText(activeWavefront?.log || activeSimulationLog?.detail || stressCommandSurface?.log_headline || '完成推演后，会在这里解释当前重点。') }}</p>
            </div>

            <div class="reason-log" v-if="compactSimulationLog.length">
              <div
                v-for="item in compactSimulationLog"
                :key="`log-${item.step}`"
                class="reason-log-item"
                :class="{ 'is-active': item.step - 1 === activeStressStep }"
              >
                <em>{{ item.step }}</em>
                <div>
                  <strong>{{ localizeStressText(item.title) }}</strong>
                  <p>{{ localizeStressText(item.detail) }}</p>
                </div>
              </div>
            </div>
          </article>
        </section>
      </template>
    </div>
  </AppShell>
</template>

<style scoped>
.stress-console {
  min-height: 100%;
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
  gap: 16px;
  width: 100%;
  max-width: 1280px;
  margin: 0 auto;
}

.stress-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 18px;
  padding-bottom: 14px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.stress-heading {
  display: grid;
  gap: 8px;
}

.stress-kicker,
.stress-select span,
.decision-kicker,
.decision-card span,
.metric-chip span,
.decision-action span,
.chain-step em,
.reason-focus span {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.stress-kicker,
.stress-select span,
.decision-kicker,
.decision-card span,
.metric-chip span,
.decision-action span,
.chain-step em,
.reason-focus span {
  color: rgba(120, 143, 172, 0.82);
}

.stress-heading h1,
.decision-head h2,
.decision-card strong,
.decision-action strong,
.chain-step strong,
.reason-focus strong,
.reason-log-item strong {
  margin: 0;
  color: #f8fafc;
  letter-spacing: -0.04em;
}

.stress-heading h1 {
  font-size: clamp(24px, 2.4vw, 30px);
  line-height: 1.02;
}

.stress-heading p,
.decision-head p,
.decision-card p,
.decision-action p,
.chain-step p,
.reason-focus p,
.reason-log-item p,
.panel-head span {
  margin: 0;
  color: rgba(148, 163, 184, 0.9);
  line-height: 1.7;
  font-size: 13px;
}

.stress-controls {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.stress-select {
  display: grid;
  gap: 8px;
}

.stress-select select {
  min-width: 180px;
  min-height: 44px;
  padding: 0 14px;
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.03);
  color: #eef2f7;
}

.scenario-board,
.decision-panel,
.chain-panel,
.reason-panel,
.stress-state {
  border-radius: 20px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: linear-gradient(180deg, rgba(16, 17, 20, 0.98), rgba(12, 13, 17, 0.98));
}

.scenario-board {
  display: grid;
  gap: 12px;
  padding: 14px;
}

.scenario-copy {
  display: grid;
  gap: 6px;
}

.scenario-copy span {
  color: rgba(120, 143, 172, 0.84);
  font-size: 12px;
}

.scenario-copy strong {
  color: #f8fafc;
  font-size: 18px;
  line-height: 1.35;
  letter-spacing: -0.03em;
}

.scenario-shell {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 118px;
  gap: 12px;
  padding: 6px 10px;
  border-radius: 16px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(8, 10, 14, 0.96);
}

.scenario-input {
  width: 100%;
  min-height: 44px;
  resize: none;
  border: none;
  background: transparent;
  color: #eef2f7;
  font: inherit;
  line-height: 1.6;
  outline: none;
}

.scenario-submit {
  border-radius: 14px;
  border: 1px solid rgba(52, 211, 153, 0.26);
  background: rgba(18, 62, 45, 0.92);
  color: #f0fdf4;
  font-weight: 700;
  cursor: pointer;
}

.scenario-submit:disabled,
.scenario-pill:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.scenario-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.scenario-pill {
  min-height: 32px;
  padding: 0 12px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.025);
  color: #dbe7f3;
  cursor: pointer;
  font-size: 12px;
}

.stress-state {
  min-height: 320px;
  display: grid;
  place-items: center;
  padding: 32px;
}

.stress-empty p {
  margin: 0;
  color: rgba(148, 163, 184, 0.9);
}

.decision-panel {
  display: grid;
  gap: 16px;
  padding: 16px;
}

.decision-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.decision-head h2 {
  font-size: clamp(20px, 2.1vw, 26px);
  line-height: 1.14;
  margin-top: 6px;
}

.severity-badge {
  min-height: 34px;
  padding: 0 12px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  font-size: 12px;
  font-weight: 700;
  flex-shrink: 0;
}

.tone-risk {
  background: rgba(69, 10, 10, 0.76);
  color: #fecaca;
  border: 1px solid rgba(244, 63, 94, 0.3);
}

.tone-warning {
  background: rgba(120, 53, 15, 0.62);
  color: #fde68a;
  border: 1px solid rgba(245, 158, 11, 0.24);
}

.tone-safe {
  background: rgba(6, 78, 59, 0.7);
  color: #bbf7d0;
  border: 1px solid rgba(16, 185, 129, 0.24);
}

.decision-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.decision-card {
  display: grid;
  gap: 8px;
  min-height: 148px;
  padding: 14px;
  border-radius: 16px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.03);
}

.decision-card strong {
  font-size: 15px;
  line-height: 1.45;
}

.decision-footer {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: 14px;
}

.decision-metrics {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.metric-chip,
.decision-action {
  display: grid;
  gap: 6px;
  padding: 12px;
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.025);
}

.metric-chip strong {
  font-size: 18px;
  color: #f8fafc;
  letter-spacing: -0.04em;
}

.metric-chip small {
  color: rgba(148, 163, 184, 0.82);
  font-size: 12px;
}

.decision-action strong {
  font-size: 16px;
}

.stress-body {
  min-height: 0;
  display: grid;
  grid-template-columns: 360px minmax(0, 1fr);
  gap: 16px;
}

.chain-panel,
.reason-panel {
  min-height: 0;
  padding: 16px;
  display: grid;
  gap: 14px;
}

.panel-head {
  display: grid;
  gap: 4px;
}

.panel-head strong {
  color: #f8fafc;
  font-size: 14px;
  letter-spacing: -0.02em;
}

.chain-steps,
.reason-log {
  display: grid;
  gap: 10px;
}

.chain-step,
.reason-log-item {
  display: grid;
  grid-template-columns: 36px minmax(0, 1fr);
  gap: 12px;
  padding: 12px;
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.025);
}

.chain-step.is-active,
.reason-log-item.is-active {
  border-color: rgba(96, 165, 250, 0.2);
  background: rgba(17, 24, 39, 0.92);
}

.chain-step em,
.reason-log-item em {
  width: 36px;
  height: 36px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  background: rgba(255, 255, 255, 0.04);
  font-style: normal;
}

.chain-step strong,
.reason-focus strong,
.reason-log-item strong {
  display: block;
  margin-bottom: 6px;
  font-size: 15px;
  line-height: 1.45;
}

.reason-focus {
  display: grid;
  gap: 8px;
  padding: 14px;
  border-radius: 16px;
  border: 1px solid rgba(96, 165, 250, 0.18);
  background: rgba(10, 18, 32, 0.72);
}

@media (max-width: 1120px) {
  .decision-grid,
  .decision-footer,
  .stress-body {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 860px) {
  .stress-header,
  .stress-controls,
  .scenario-shell,
  .decision-head {
    grid-template-columns: 1fr;
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
