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
const periodOptions = computed(() =>
  (availablePeriods.value || [])
    .map((item: any) => {
      if (typeof item === 'string') return { value: item, label: item }
      if (item && typeof item === 'object') {
        const value = String(item.value || item.period || item.report_period || item.label || '')
        const label = String(item.label || item.period || item.report_period || item.value || '')
        return value ? { value, label } : null
      }
      return null
    })
    .filter(Boolean) as Array<{ value: string; label: string }>,
)
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
const stressWavefront = computed(() => stressState.data.value?.stress_wavefront || [])
const stressCommandSurface = computed(() => stressState.data.value?.stress_command_surface || null)
const recoverySequence = computed(() => stressState.data.value?.stress_recovery_sequence || [])
const affectedDimensions = computed(() => (stressState.data.value?.affected_dimensions || []).slice(0, 3))
const canRunStress = computed(() => !!selectedCompany.value && !!scenarioDraft.value.trim())
const focusedPropagationSteps = computed(() => propagationSteps.value.slice(0, 3))
const primaryRecoveryAction = computed(() => recoverySequence.value[0] || null)
const activeWavefront = computed(() => stressWavefront.value[activeStressStep.value] || stressWavefront.value[0] || null)
const primaryScenarioLabel = computed(() => selectedCompany.value || '选择公司后开始推演')
const selectedPeriodLabel = computed(() => {
  const match = periodOptions.value.find((item) => item.value === selectedPeriod.value)
  if (match) return match.label
  if (typeof selectedPeriod.value === 'string') return selectedPeriod.value
  return ''
})
const scenarioStatusLine = computed(() => selectedPeriodLabel.value || '默认主周期')
const focusExplanation = computed(
  () =>
    localizeStressText(
      activeWavefront.value?.log ||
        activeWavefront.value?.detail ||
        stressCommandSurface.value?.log_headline ||
        '推演完成后，会在这里把这次冲击为什么会传导成现在的样子说清楚。',
    ),
)

const stressPhraseMap: Record<string, string> = {
  'Material Supply Constraints': '关键材料供给受限',
  'Production Delays': '生产排期延后',
  'Sales Decline in EU Market': '欧洲市场销量回落',
  'Initial Tariff Implementation': '关税冲击开始落地',
  'Supply Chain Disruption': '供应链开始失衡',
  'Market Reaction': '市场开始反应',
  'Temporary tariffs are imposed.': '临时关税开始落地。',
  'Material imports are constrained.': '关键材料进口开始受限。',
  'Stress scenario initiated.': '本轮冲击推演已经启动。',
  'High Risk': '高风险',
  'Severe': '高冲击',
  'Moderate': '中等冲击',
  'Low': '低冲击',
}

function escapeForReplace(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function localizeStressText(value?: string) {
  if (!value) return ''
  let localized = value
  Object.entries(stressPhraseMap).forEach(([english, chinese]) => {
    localized = localized.replace(new RegExp(escapeForReplace(english), 'gi'), chinese)
  })
  return localized
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
    .replace(/\brecovery\b/gi, '修复')
    .replace(/\bsupply\b/gi, '供应')
    .replace(/\bdelay(s)?\b/gi, '延后')
    .replace(/\bmarket\b/gi, '市场')
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
  const preferredPeriod = overviewState.data.value?.preferred_period
  selectedPeriod.value = typeof route.query.period === 'string' && route.query.period
    ? route.query.period
    : typeof preferredPeriod === 'string'
      ? preferredPeriod
      : String(preferredPeriod?.value || preferredPeriod?.period || preferredPeriod?.report_period || preferredPeriod?.label || '')
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
          <h1>压力推演</h1>
          <p>{{ primaryScenarioLabel }} · {{ scenarioStatusLine }}</p>
        </div>
      </section>

      <LoadingState v-if="overviewState.loading.value || stressState.loading.value" class="stress-state" />
      <ErrorState v-else-if="stressState.error.value" :message="String(stressState.error.value)" class="stress-state" />
      <section v-else-if="!hasCompanies" class="stress-state stress-empty">
        <p>当前还没有可推演企业，请先完成正式公司池和产业链数据接入。</p>
      </section>

      <section v-else class="stress-layout">
        <aside class="scenario-panel">
          <div class="scenario-panel-head">
            <h2>给一个冲击假设</h2>
            <p>先定对象，再说这轮会发生什么。</p>
          </div>

          <div class="scenario-context">
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
                <option v-for="period in periodOptions" :key="period.value" :value="period.value">{{ period.label }}</option>
              </select>
            </label>
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

          <div class="preset-strip">
            <span class="preset-strip-label">直接试这几种</span>
            <button
              v-for="item in presetScenarios"
              :key="item"
              class="preset-chip"
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
              <h2>{{ localizeStressText(stressCommandSurface.headline) }}</h2>
              <p>{{ scenario }}</p>
            </div>
            <div class="severity-badge" :class="displayToneClass(stressState.data.value?.severity?.color)">
              {{ displaySeverityBadge(stressState.data.value?.severity) }}
            </div>
          </div>

          <div v-if="affectedDimensions.length" class="impact-strip">
            <div
              v-for="item in affectedDimensions"
              :key="item.label"
              class="impact-chip"
            >
              <span>{{ item.label }}</span>
              <strong>{{ item.value }}</strong>
              <small>{{ item.hint }}</small>
            </div>
          </div>

          <div class="result-body">
            <article class="chain-panel" v-if="focusedPropagationSteps.length">
              <div class="section-head">
                <strong>冲击会先传到哪里</strong>
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
              <div class="section-head">
                <strong>这一轮先做什么</strong>
              </div>

              <div v-if="primaryRecoveryAction" class="action-focus">
                <span>优先动作</span>
                <strong>{{ localizeStressText(primaryRecoveryAction.title) }}</strong>
                <p>{{ localizeStressText(primaryRecoveryAction.detail) }}</p>
              </div>
              <div v-else class="action-focus">
                <span>优先动作</span>
                <strong>先把冲击路径说清楚</strong>
                <p>当前还没有收敛出明确动作，先看传导链和最先受影响的环节。</p>
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
  display: grid;
  gap: 8px;
  padding-bottom: 14px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.stress-heading,
.stress-select,
.panel-head,
.scenario-shell,
.action-focus,
.reason-focus,
 .chain-step {
  display: grid;
}

.stress-heading {
  gap: 8px;
}

.stress-select span,
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
.chain-step p,
.action-focus p,
.reason-focus p,
.panel-head span {
  margin: 0;
  color: rgba(148, 163, 184, 0.9);
  line-height: 1.7;
  font-size: 13px;
}

.stress-select {
  gap: 8px;
}

.stress-select select {
  width: 100%;
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
  display: grid;
  gap: 14px;
}

.scenario-panel-head {
  display: grid;
  gap: 6px;
}

.scenario-panel h2,
.section-head strong {
  margin: 0;
  color: #f8fafc;
  font-size: 16px;
  letter-spacing: -0.02em;
}

.scenario-panel-head p {
  margin: 0;
  color: rgba(148, 163, 184, 0.82);
  line-height: 1.6;
  font-size: 13px;
}

.scenario-context {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: flex-start;
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
.preset-chip:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.preset-strip {
  display: grid;
  gap: 10px;
}

.preset-strip-label,
.impact-chip span,
.impact-chip small {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.preset-strip-label {
  color: rgba(120, 143, 172, 0.78);
}

.preset-chip {
  width: 100%;
  min-height: 34px;
  padding: 0 12px;
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.025);
  color: #dbe7f3;
  cursor: pointer;
  line-height: 1;
  text-align: left;
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

.impact-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.impact-chip {
  display: grid;
  gap: 4px;
  padding: 12px 14px;
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.025);
}

.impact-chip span,
.impact-chip small {
  color: rgba(120, 143, 172, 0.78);
}

.impact-chip strong {
  color: #f8fafc;
  font-size: 18px;
  line-height: 1.1;
}

.result-body {
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 336px;
  gap: 14px;
}

.chain-panel,
.action-panel {
  min-height: 0;
  padding: 16px;
  gap: 12px;
}

.chain-steps {
  display: grid;
  gap: 12px;
}

.chain-step {
  grid-template-columns: 36px minmax(0, 1fr);
  gap: 12px;
  padding: 14px;
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
  padding: 16px;
  border-radius: 16px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.025);
}

.reason-focus {
  border-color: rgba(96, 165, 250, 0.18);
  background: rgba(10, 18, 32, 0.72);
}

@media (max-width: 1120px) {
  .impact-strip,
  .stress-layout,
  .result-body {
    grid-template-columns: 1fr;
  }

  .scenario-context {
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
