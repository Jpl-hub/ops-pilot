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
  '海外主要市场需求快速回落',
]

const propagationSteps = computed(() => stressState.data.value?.propagation_steps || [])
const transmissionMatrix = computed(() => stressState.data.value?.transmission_matrix || [])
const simulationLog = computed(() => stressState.data.value?.simulation_log || [])
const stressWavefront = computed(() => stressState.data.value?.stress_wavefront || [])
const stressCommandSurface = computed(() => stressState.data.value?.stress_command_surface || null)
const affectedDimensions = computed(() => stressState.data.value?.affected_dimensions || [])
const recoverySequence = computed(() => stressState.data.value?.stress_recovery_sequence || [])
const compactSimulationLog = computed(() => simulationLog.value.slice(0, 3))
const activeWavefront = computed(() => stressWavefront.value[activeStressStep.value] || stressWavefront.value[0] || null)
const activeSimulationLog = computed(() => simulationLog.value[activeStressStep.value] || null)
const canRunStress = computed(() => !!selectedCompany.value && !!scenarioDraft.value.trim())
const visibleAffectedDimensions = computed(() => affectedDimensions.value.slice(0, 3))
const focusedTransmissionMatrix = computed(() => transmissionMatrix.value.slice(0, 3))

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
  <AppShell title="">
    <div class="dashboard-wrapper">

      <!-- Control Bar -->
      <section class="glass-panel control-bar">
        <div class="control-left">
          <div class="glow-icon">压</div>
          <div class="control-copy">
            <span class="control-kicker">压力推演</span>
            <h3 class="company-name text-gradient">压力推演</h3>
            <p class="control-meta">{{ selectedCompany || '选择公司' }}<span v-if="selectedPeriod"> · {{ selectedPeriod }}</span></p>
          </div>
        </div>
        <div class="inline-context">
          <label class="inline-field">
            <span class="subtle-label">公司</span>
            <select v-model="selectedCompany" class="glass-select">
              <option v-if="!companies.length" value="">{{ overviewState.loading.value ? '正在载入公司池' : '当前无公司' }}</option>
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
          :placeholder="selectedCompany ? '输入压力场景，例如：上游核心矿产断供…' : '当前无可推演企业，请先完成公司池接入'"
          :disabled="stressState.loading.value || !selectedCompany"
          @keydown.enter="runStress"
        />
        <div
          v-if="stressState.data.value?.severity"
          class="severity-badge"
          :class="displayToneClass(stressState.data.value.severity.color)"
        >
          {{ displaySeverityBadge(stressState.data.value.severity) }}
        </div>
        <button class="button-primary scenario-btn" :disabled="stressState.loading.value || !canRunStress" @click="runStress">
          {{ stressState.loading.value ? '推演中…' : '启动推演' }}
        </button>
      </section>

      <!-- Preset Pills -->
      <div class="preset-row">
        <button v-for="item in presetScenarios.slice(0, 2)" :key="item" class="preset-pill" :disabled="!selectedCompany" @click="selectPreset(item)">
          {{ item }}
        </button>
      </div>

      <LoadingState v-if="overviewState.loading.value || stressState.loading.value" class="state-container" />
      <ErrorState v-else-if="stressState.error.value" :message="String(stressState.error.value)" class="state-container" />
      <section v-else-if="!hasCompanies" class="glass-panel empty-panel">
        <div class="empty-content">
          <h3 class="text-gradient mb-2">公司池为空</h3>
          <p class="muted">当前环境还没有可推演企业，请先完成正式公司池和产业链数据接入。</p>
        </div>
      </section>

      <!-- Main Content -->
      <div v-else class="content-grid">

        <!-- Left: Transmission Matrix + Propagation Chain -->
        <div class="left-col">

          <article class="glass-panel overview-panel" v-if="stressCommandSurface">
            <div class="overview-head">
              <div>
                <span class="overview-eyebrow">本轮冲击结论</span>
                <h3 class="overview-title">{{ stressCommandSurface.headline }}</h3>
                <p class="overview-desc muted">{{ scenario }}</p>
              </div>
              <div
                class="severity-badge"
                :class="displayToneClass(stressState.data.value?.severity?.color)"
              >
                {{ displaySeverityBadge(stressState.data.value?.severity) }}
              </div>
            </div>
            <div class="overview-grid">
              <div
                v-for="item in visibleAffectedDimensions"
                :key="item.label"
                class="overview-stat"
              >
                <span>{{ item.label }}</span>
                <strong>{{ item.value }}</strong>
                <small>{{ item.hint }}</small>
              </div>
            </div>
            <p class="overview-note">{{ stressCommandSurface.log_headline }}</p>
          </article>

          <article class="glass-panel recovery-panel" v-if="recoverySequence.length">
            <div class="section-head">
              <h3 class="panel-title">先做什么</h3>
            </div>
            <div class="recovery-list">
              <article
                v-for="item in recoverySequence.slice(0, 2)"
                :key="item.step"
                class="recovery-card"
                :class="`tone-${item.tone || 'accent'}`"
              >
                <div class="recovery-step">0{{ item.step }}</div>
                <div class="recovery-body">
                  <strong>{{ item.title }}</strong>
                  <p class="muted">{{ item.detail }}</p>
                </div>
              </article>
            </div>
          </article>

          <!-- Transmission Matrix -->
          <article class="glass-panel matrix-panel" v-if="focusedTransmissionMatrix.length">
            <h3 class="panel-title">重点传导环节</h3>
            <div class="matrix-grid">
              <div
                v-for="(item, index) in focusedTransmissionMatrix"
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
                <div class="node-label-row">
                  <span class="node-label muted">{{ item.impact_label }}</span>
                  <strong class="node-score">{{ item.impact_score }}</strong>
                </div>
              </div>
            </div>
          </article>

          <!-- Propagation Chain -->
          <article class="glass-panel chain-panel" v-if="propagationSteps.length">
            <h3 class="panel-title">传导主链</h3>
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
            <h3 class="panel-title">为什么会这样</h3>

            <!-- Active Wavefront -->
            <div class="wavefront-card">
              <div class="wavefront-head">
                <span class="wavefront-lbl">当前重点</span>
                <span class="wavefront-badge">{{ activeWavefront ? '推演中' : '就绪' }}</span>
              </div>
              <h4 class="wavefront-title">{{ activeWavefront?.headline || stressCommandSurface?.headline || activeSimulationLog?.title || '等待推演' }}</h4>
              <p class="wavefront-desc muted">{{ activeWavefront?.log || stressCommandSurface?.impact_label || activeSimulationLog?.detail || '系统准备冲击波前计算…' }}</p>
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
                v-for="item in compactSimulationLog"
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
.dashboard-wrapper { display: flex; flex-direction: column; gap: 14px; height: 100%; overflow: hidden; width: 100%; max-width: 1280px; margin: 0 auto; }

/* Control Bar */
.control-bar { display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; border-radius: 14px; flex-shrink: 0; }
.control-left { display: flex; align-items: center; gap: 16px; }
.control-copy { display: grid; gap: 4px; }
.control-kicker { font-family: 'JetBrains Mono', monospace; font-size: 10px; letter-spacing: 0.16em; text-transform: uppercase; color: var(--muted); }
.control-meta { margin: 0; font-size: 12px; color: var(--muted); }
.glow-icon { width: 40px; height: 40px; border-radius: 12px; background: rgba(244,63,94,0.15); border: 1px solid rgba(244,63,94,0.4); color: #f43f5e; display: grid; place-items: center; font-weight: bold; font-size: 18px; box-shadow: 0 0 15px rgba(244,63,94,0.2); }
.company-name { margin: 0; font-size: 18px; font-weight: 600; }
.text-gradient { background-clip: text; -webkit-text-fill-color: transparent; background-image: linear-gradient(to right, #f43f5e, #fb923c); }
.inline-context { display: flex; align-items: center; gap: 16px; }
.inline-field { display: flex; align-items: center; gap: 8px; }
.subtle-label { font-size: 12px; color: var(--muted); text-transform: uppercase; }
.glass-select { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); min-height: 36px; padding: 0 12px; border-radius: 8px; color: #fff; }
.glass-input { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); min-height: 36px; padding: 0 12px; border-radius: 8px; color: #fff; width: 100px; outline: none; }

/* Scenario Bar */
.scenario-bar { display: flex; align-items: center; gap: 12px; padding: 10px 14px; border-radius: 12px; flex-shrink: 0; }
.scenario-icon { width: 36px; height: 36px; border-radius: 50%; background: rgba(244,63,94,0.1); border: 1px solid rgba(244,63,94,0.2); display: flex; align-items: center; justify-content: center; color: #f43f5e; flex-shrink: 0; }
.scenario-input { flex: 1; background: transparent; border: none; font-size: 14px; color: #fff; outline: none; font-weight: 500; }
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
.content-grid { display: grid; grid-template-columns: minmax(0, 1fr) 292px; gap: 14px; flex: 1; min-height: 0; }
.left-col { display: flex; flex-direction: column; gap: 14px; min-height: 0; overflow-y: auto; }
.left-col::-webkit-scrollbar { width: 4px; }
.left-col::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 2px; }
.right-col { display: flex; flex-direction: column; min-height: 0; overflow: hidden; }

.panel-title { font-size: 12px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); margin: 0 0 14px; padding-bottom: 10px; border-bottom: 1px solid rgba(255,255,255,0.05); }
.muted { color: var(--muted); }

/* Overview */
.overview-panel,
.recovery-panel { padding: 16px; border-radius: 14px; flex-shrink: 0; }
.overview-head,
.section-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.overview-eyebrow {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(244,63,94,0.12);
  color: #fda4af;
  font-size: 11px;
  letter-spacing: 0.05em;
  margin-bottom: 10px;
}
.overview-title {
  margin: 0;
  font-size: 18px;
  line-height: 1.35;
  color: #fff;
}
.overview-desc {
  margin: 8px 0 0;
  font-size: 13px;
  line-height: 1.6;
}
.overview-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-top: 14px;
}
.overview-stat {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px;
  border-radius: 10px;
  border: 1px solid rgba(255,255,255,0.06);
  background: rgba(255,255,255,0.03);
}
.overview-stat span,
.overview-stat small {
  color: var(--muted);
  font-size: 11px;
}
.overview-stat strong {
  font-size: 16px;
  color: #fff;
}
.overview-note {
  margin: 16px 0 0;
  padding-top: 14px;
  border-top: 1px solid rgba(255,255,255,0.06);
  color: #cbd5e1;
  font-size: 13px;
  line-height: 1.6;
}
.section-note {
  font-size: 11px;
  color: var(--muted);
}
.recovery-list { display: flex; flex-direction: column; gap: 10px; }
.recovery-card {
  display: flex;
  gap: 12px;
  padding: 12px;
  border-radius: 10px;
  border: 1px solid rgba(255,255,255,0.06);
  background: rgba(255,255,255,0.03);
}
.recovery-card.tone-risk {
  border-color: rgba(244,63,94,0.26);
  background: rgba(127,29,29,0.16);
}
.recovery-step {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: 11px;
  font-weight: 700;
  color: #fb7185;
  background: rgba(244,63,94,0.1);
  border: 1px solid rgba(244,63,94,0.2);
  flex-shrink: 0;
}
.recovery-body strong {
  display: block;
  margin-bottom: 6px;
  color: #fff;
  font-size: 14px;
}
.recovery-body p {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
}
.stress-link {
  padding: 8px 12px;
  border-radius: 999px;
  border: 1px solid rgba(255,255,255,0.1);
  background: rgba(255,255,255,0.04);
  color: #cbd5e1;
  text-decoration: none;
  font-size: 12px;
  transition: all 0.2s;
}
.stress-link:hover {
  border-color: rgba(244,63,94,0.28);
  background: rgba(244,63,94,0.08);
  color: #fff;
}

/* Matrix */
.matrix-panel { padding: 18px; border-radius: 14px; flex-shrink: 0; }
.matrix-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.matrix-node { position: relative; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 12px; padding: 14px; display: flex; flex-direction: column; gap: 10px; transition: all 0.3s; }
.matrix-node:hover { transform: translateY(-2px); }
.matrix-node.is-active { background: rgba(127,29,29,0.12); border-color: rgba(244,63,94,0.22); box-shadow: 0 0 18px rgba(244,63,94,0.08); }
.node-header { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.node-dot { width: 6px; height: 6px; border-radius: 50%; background: rgba(255,255,255,0.3); flex-shrink: 0; }
.is-active .node-dot { background: #f43f5e; box-shadow: 0 0 6px #f43f5e; }
.node-stage { font-size: 11px; letter-spacing: 0.08em; color: var(--muted); }
.node-arrow { margin-left: auto; color: rgba(255,255,255,0.15); font-size: 14px; }
.node-headline { font-size: 13px; font-weight: 600; color: #f3f4f6; line-height: 1.4; }
.node-label-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.node-score { font-size: 14px; font-family: 'JetBrains Mono', monospace; font-weight: 600; color: #fda4af; }
.node-label { font-size: 12px; }

/* Propagation Chain */
.chain-panel { padding: 18px; border-radius: 14px; flex-shrink: 0; }
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
.stream-panel { flex: 1; padding: 18px; border-radius: 14px; display: flex; flex-direction: column; gap: 14px; overflow: hidden; }
.wavefront-card { background: linear-gradient(135deg, rgba(244,63,94,0.06), rgba(255,255,255,0.02)); border: 1px solid rgba(244,63,94,0.16); border-radius: 12px; padding: 14px; flex-shrink: 0; }
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

@media (max-width: 1180px) {
  .overview-grid,
  .matrix-grid { grid-template-columns: 1fr; }
}

@media (max-width: 900px) {
  .overview-head,
  .section-head { flex-direction: column; }
}
</style>
