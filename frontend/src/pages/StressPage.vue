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
const stressWavefront = computed(() => stressState.data.value?.stress_wavefront || [])
const stressCommandSurface = computed(() => stressState.data.value?.stress_command_surface || null)
const recoverySequence = computed(() => stressState.data.value?.stress_recovery_sequence || [])
const canRunStress = computed(() => !!selectedCompany.value && !!scenarioDraft.value.trim())
const focusedTransmissionMatrix = computed(() => transmissionMatrix.value.slice(0, 3))
const focusedPropagationSteps = computed(() => propagationSteps.value.slice(0, 3))
const primaryRecoveryAction = computed(() => recoverySequence.value[0] || null)
const activeWavefront = computed(() => stressWavefront.value[activeStressStep.value] || stressWavefront.value[0] || null)
const primaryScenarioLabel = computed(() => selectedCompany.value || '选择公司后开始推演')
const scenarioStatusLine = computed(() =>
  selectedPeriod.value ? `${selectedPeriod} · 从一个明确冲击假设开始` : '默认主周期 · 从一个明确冲击假设开始',
)
const focusExplanation = computed(
  () =>
    localizeStressText(
      activeWavefront.value?.log ||
        activeWavefront.value?.detail ||
        stressCommandSurface.value?.log_headline ||
        '推演完成后，会在这里把这次冲击为什么会传导成现在的样子说清楚。',
    ),
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
    .replace(/\bshock\b/gi, '冲击')
    .replace(/\btrend\b/gi, '走势')
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
  const translated = displaySeverityLevel(severity?.level)
  return translated !== '待定' ? translated : localizeStressText(severity?.label)
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
    if (!focusedPropagationSteps.value.length) return
    activeStressStep.value = (activeStressStep.value + 1) % focusedPropagationSteps.value.length
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

      <LoadingState v-if="overviewState.loading.value || stressState.loading.value" class="stress-state" />
      <ErrorState v-else-if="stressState.error.value" :message="String(stressState.error.value)" class="stress-state" />
      <section v-else-if="!hasCompanies" class="stress-state stress-empty">
        <p>当前还没有可推演企业，请先完成正式公司池和产业链数据接入。</p>
      </section>

      <section v-else class="stress-layout">
        <aside class="scenario-panel">
          <div class="panel-head">
            <strong>给一个冲击假设</strong>
            <span>不用懂模型，直接说会发生什么。</span>
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

          <div class="preset-list">
            <button
              v-for="item in presetScenarios"
              :key="item"
              class="preset-card"
              :disabled="!selectedCompany"
              @click="selectPreset(item)"
            >
              {{ item }}
            </button>
          </div>
        </aside>

        <section class="result-panel" v-if="stressCommandSurface">
          <div class="result-head">
            <div>
              <span class="result-kicker">本轮判断</span>
              <h2>{{ localizeStressText(stressCommandSurface.headline) }}</h2>
              <p>{{ scenario }}</p>
            </div>
            <div class="severity-badge" :class="displayToneClass(stressState.data.value?.severity?.color)">
              {{ displaySeverityBadge(stressState.data.value?.severity) }}
            </div>
          </div>

          <div class="impact-grid" v-if="focusedTransmissionMatrix.length">
            <article
              v-for="item in focusedTransmissionMatrix"
              :key="item.stage"
              class="impact-card"
              :class="`tone-${item.tone || 'warning'}`"
            >
              <span>{{ displayStageName(item.stage) }}</span>
              <strong>{{ localizeStressText(item.headline) }}</strong>
              <p>{{ localizeStressText(item.impact_label) }}</p>
            </article>
          </div>

          <div class="result-body">
            <article class="chain-panel" v-if="focusedPropagationSteps.length">
              <div class="panel-head">
                <strong>这条传导主链最值得看</strong>
                <span>它会按这个顺序往下传。</span>
              </div>

              <div class="chain-steps">
                <div
                  v-for="(item, idx) in focusedPropagationSteps"
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

            <article class="action-panel">
              <div class="panel-head">
                <strong>现在先做什么</strong>
                <span>先把当前这一轮的动作说清楚。</span>
              </div>

              <div v-if="primaryRecoveryAction" class="action-focus">
                <span>优先动作</span>
                <strong>{{ primaryRecoveryAction.title }}</strong>
                <p>{{ primaryRecoveryAction.detail }}</p>
              </div>

              <div class="reason-focus">
                <span>为什么会这样</span>
                <strong>{{ localizeStressText(activeWavefront?.headline || stressCommandSurface.headline) }}</strong>
                <p>{{ focusExplanation }}</p>
              </div>
            </article>
          </div>
        </section>
      </section>
    </div>
  </AppShell>
</template>

<style scoped>
.stress-console {
  min-height: 100%;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
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

.stress-heading,
.stress-select,
.panel-head,
.scenario-shell,
.action-focus,
.reason-focus,
.impact-card,
.chain-step {
  display: grid;
}

.stress-heading {
  gap: 8px;
}

.stress-kicker,
.stress-select span,
.result-kicker,
.impact-card span,
.chain-step em,
.action-focus span,
.reason-focus span {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: rgba(120, 143, 172, 0.82);
}

.stress-heading h1,
.result-head h2,
.impact-card strong,
.chain-step strong,
.action-focus strong,
.reason-focus strong {
  margin: 0;
  color: #f8fafc;
  letter-spacing: -0.04em;
}

.stress-heading h1 {
  font-size: clamp(24px, 2.4vw, 30px);
  line-height: 1.02;
}

.stress-heading p,
.result-head p,
.impact-card p,
.chain-step p,
.action-focus p,
.reason-focus p,
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

.stress-layout,
.scenario-panel,
.result-panel,
.chain-panel,
.action-panel,
.stress-state {
  border-radius: 20px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: linear-gradient(180deg, rgba(16, 17, 20, 0.98), rgba(12, 13, 17, 0.98));
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

.stress-layout {
  min-height: 0;
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 16px;
  background: transparent;
  border: none;
}

.scenario-panel,
.result-panel {
  min-height: 0;
  padding: 16px;
}

.scenario-panel {
  gap: 14px;
}

.panel-head {
  gap: 4px;
}

.panel-head strong {
  color: #f8fafc;
  font-size: 14px;
  letter-spacing: -0.02em;
}

.scenario-shell {
  grid-template-columns: 1fr;
  gap: 12px;
  padding: 10px;
  border-radius: 16px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(8, 10, 14, 0.96);
}

.scenario-input {
  width: 100%;
  min-height: 140px;
  resize: none;
  border: none;
  background: transparent;
  color: #eef2f7;
  font: inherit;
  line-height: 1.6;
  outline: none;
}

.scenario-submit {
  min-height: 42px;
  border-radius: 14px;
  border: 1px solid rgba(52, 211, 153, 0.26);
  background: rgba(18, 62, 45, 0.92);
  color: #f0fdf4;
  font-weight: 700;
  cursor: pointer;
}

.scenario-submit:disabled,
.preset-card:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.preset-list {
  display: grid;
  gap: 10px;
}

.preset-card {
  padding: 12px 14px;
  border-radius: 16px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.025);
  color: #dbe7f3;
  text-align: left;
  cursor: pointer;
  line-height: 1.6;
}

.result-panel {
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
  gap: 14px;
}

.result-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.result-head h2 {
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

.impact-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.impact-card {
  gap: 8px;
  min-height: 144px;
  padding: 14px;
  border-radius: 16px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.03);
}

.impact-card strong {
  font-size: 15px;
  line-height: 1.45;
}

.result-body {
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: 14px;
}

.chain-panel,
.action-panel {
  min-height: 0;
  padding: 14px;
  gap: 12px;
}

.chain-steps {
  display: grid;
  gap: 10px;
}

.chain-step {
  grid-template-columns: 36px minmax(0, 1fr);
  gap: 12px;
  padding: 12px;
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.025);
}

.chain-step.is-active {
  border-color: rgba(96, 165, 250, 0.2);
  background: rgba(17, 24, 39, 0.92);
}

.chain-step em {
  width: 36px;
  height: 36px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  background: rgba(255, 255, 255, 0.04);
  font-style: normal;
}

.chain-step strong,
.action-focus strong,
.reason-focus strong {
  display: block;
  margin-bottom: 6px;
  font-size: 15px;
  line-height: 1.45;
}

.action-panel {
  align-content: start;
}

.action-focus,
.reason-focus {
  gap: 8px;
  padding: 14px;
  border-radius: 16px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.025);
}

.reason-focus {
  border-color: rgba(96, 165, 250, 0.18);
  background: rgba(10, 18, 32, 0.72);
}

@media (max-width: 1120px) {
  .stress-layout,
  .impact-grid,
  .result-body {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 860px) {
  .stress-header,
  .stress-controls,
  .result-head {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
