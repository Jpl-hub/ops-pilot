<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

import AppShell from '@/components/AppShell.vue'
import ChartPanel from '@/components/ChartPanel.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingState from '@/components/LoadingState.vue'
import TagPill from '@/components/TagPill.vue'
import { useAsyncState } from '@/composables/useAsyncState'
import { get, post } from '@/lib/api'

const overviewState = useAsyncState<any>()
const stressState = useAsyncState<any>()
const runsState = useAsyncState<any>()
const runtimeState = useAsyncState<any>()
const route = useRoute()

const companies = computed(() => overviewState.data.value?.companies || [])
const selectedCompany = ref('')
const selectedPeriod = ref('')
const scenario = ref('欧盟对动力电池临时加征关税并限制关键材料进口')
const activeStressStep = ref(0)
let stressTicker: number | null = null

const presetScenarios = [
  '欧盟对动力电池临时加征关税并限制关键材料进口',
  '上游碳酸锂价格急涨并持续三个月',
  '关键供应商停产两周导致交付延迟',
  '海外主要市场需求快速回落并触发库存积压',
]

const propagationSteps = computed(() => stressState.data.value?.propagation_steps || [])
const transmissionMatrix = computed(() => stressState.data.value?.transmission_matrix || [])
const simulationLog = computed(() => stressState.data.value?.simulation_log || [])
const stressWavefront = computed(() => stressState.data.value?.stress_wavefront || [])
const stressImpactTape = computed(() => stressState.data.value?.stress_impact_tape || [])
const stressCommandSurface = computed(() => stressState.data.value?.stress_command_surface || null)
const stressRecoverySequence = computed(() => stressState.data.value?.stress_recovery_sequence || [])
const modulePulses = computed(() => runtimeState.data.value?.module_pulses || [])
const activeSimulationLog = computed(() => simulationLog.value[activeStressStep.value] || null)
const activeWavefront = computed(
  () => stressWavefront.value[activeStressStep.value] || stressWavefront.value[0] || null,
)
const stageCards = computed(() => {
  const steps = propagationSteps.value
  return [
    {
      id: 'upstream',
      label: '上游',
      impact: steps[0]?.title || '原料与矿产',
      detail: steps[0]?.detail || '等待推演',
      active: activeWavefront.value?.active_stage === 'upstream',
    },
    {
      id: 'midstream',
      label: '中游',
      impact: steps[1]?.title || '电池与四大主材',
      detail: steps[1]?.detail || '等待推演',
      active: activeWavefront.value?.active_stage === 'midstream',
    },
    {
      id: 'downstream',
      label: '下游',
      impact: steps[2]?.title || '整车与储能',
      detail: steps[2]?.detail || '等待推演',
      active: activeWavefront.value?.active_stage === 'downstream' || activeWavefront.value?.active_stage === 'actions',
    },
  ]
})

async function runStress() {
  if (!selectedCompany.value || !scenario.value.trim()) return
  await stressState.execute(() =>
    post('/company/stress-test', {
      company_name: selectedCompany.value,
      report_period: selectedPeriod.value || null,
      user_role: 'management',
      scenario: scenario.value.trim(),
    }),
  )
  await runsState.execute(() =>
    get(
      `/stress-test/runs?company_name=${encodeURIComponent(selectedCompany.value)}&report_period=${encodeURIComponent(
        selectedPeriod.value || '',
      )}&user_role=management&limit=6`,
    ),
  )
  await runtimeState.execute(() =>
    get(
      `/company/intelligence-runtime?company_name=${encodeURIComponent(selectedCompany.value)}&report_period=${encodeURIComponent(
        selectedPeriod.value || '',
      )}&user_role=management`,
    ),
  )
  activeStressStep.value = 0
}

async function openStressRun(runId: string) {
  await stressState.execute(() => get(`/stress-test/runs/${encodeURIComponent(runId)}`))
  scenario.value = stressState.data.value?.scenario || scenario.value
  activeStressStep.value = 0
}

onMounted(async () => {
  await overviewState.execute(() => get('/workspace/overview?user_role=management'))
  selectedCompany.value =
    (typeof route.query.company === 'string' ? route.query.company : '') || companies.value[0] || ''
  selectedPeriod.value = typeof route.query.period === 'string' ? route.query.period : ''
  await runStress()
  stressTicker = window.setInterval(() => {
    if (!propagationSteps.value.length) return
    activeStressStep.value = (activeStressStep.value + 1) % propagationSteps.value.length
  }, 1700)
})

onBeforeUnmount(() => {
  if (stressTicker) {
    window.clearInterval(stressTicker)
    stressTicker = null
  }
})
</script>

<template>
  <AppShell title="压力测试" compact>
    <LoadingState v-if="overviewState.loading.value && !stressState.data.value" />
    <ErrorState
      v-else-if="overviewState.error.value || stressState.error.value"
      :message="String(overviewState.error.value || stressState.error.value)"
    />
    <template v-else>
      <section class="mode-stage stress-mode-stage">
        <article class="panel mode-main-panel stress-main-panel stress-main-panel-dynamic">
          <div class="mode-query-panel">
            <div class="graph-search-icon">ϟ</div>
            <div class="mode-query-copy">
              <strong>{{ stressState.data.value?.scenario || scenario }}</strong>
              <span>{{ selectedCompany }} · {{ selectedPeriod || '默认主周期' }}</span>
            </div>
            <div class="mode-query-metrics">
              <TagPill
                v-if="stressState.data.value?.severity"
                :label="`${stressState.data.value.severity.level} ${stressState.data.value.severity.label}`"
                :tone="stressState.data.value.severity.color === 'risk' ? 'risk' : 'success'"
              />
            </div>
          </div>

          <div class="graph-context-bar">
            <label class="field">
              <span>公司</span>
              <select v-model="selectedCompany">
                <option v-for="company in companies" :key="company" :value="company">{{ company }}</option>
              </select>
            </label>
            <label class="field">
              <span>报期</span>
              <input v-model="selectedPeriod" class="text-input" placeholder="默认主周期" />
            </label>
          </div>

          <div class="stress-dynamic-layout">
            <div v-if="modulePulses.length" class="mode-pulse-strip">
              <RouterLink
                v-for="item in modulePulses"
                :key="item.module_key"
                class="mode-pulse-card"
                :to="{ path: item.route.path, query: item.route.query || {} }"
              >
                <span>{{ item.label }}</span>
                <strong>{{ item.signal }}</strong>
                <em :style="{ width: `${item.intensity || 0}%` }" />
              </RouterLink>
            </div>
            <section class="stress-inputs stress-inputs-dynamic">
              <div class="timeline-list compact-timeline">
                <button
                  v-for="item in presetScenarios"
                  :key="item"
                  type="button"
                  class="timeline-item interactive-card"
                  @click="scenario = item"
                >
                  <strong>{{ item }}</strong>
                </button>
              </div>
              <label class="field">
                <span>场景</span>
                <textarea v-model="scenario" class="text-area stress-input" />
              </label>
              <button class="button-primary stress-submit" @click="runStress">启动推演</button>
            </section>

            <section class="stress-output stress-output-dynamic">
              <div class="stress-command-surface">
                <div class="stress-command-core" :class="{ running: stressState.loading.value }">
                  <div class="stress-command-ring" />
                  <div class="stress-command-copy">
                    <strong>{{ selectedCompany }}</strong>
                    <span>{{ stressState.loading.value ? '正在推演冲击传导…' : '冲击路径已生成' }}</span>
                  </div>
                </div>
                <div v-if="stressCommandSurface" class="stress-command-radar">
                  <div class="stress-command-radar-copy">
                    <span>{{ stressCommandSurface.title }}</span>
                    <strong>{{ stressCommandSurface.headline }}</strong>
                    <small>{{ stressCommandSurface.log_headline }}</small>
                  </div>
                  <div class="stress-command-radar-grid">
                    <div
                      v-for="item in stressCommandSurface.watch_items || []"
                      :key="item.label"
                      class="stress-command-radar-cell"
                    >
                      <span>{{ item.label }}</span>
                      <strong>{{ item.value }}</strong>
                    </div>
                  </div>
                  <div class="stress-energy-curve">
                    <i
                      v-for="(value, index) in stressCommandSurface.energy_curve || []"
                      :key="`energy-${index}`"
                      :style="{ height: `${Math.max(18, value || 0)}%` }"
                    />
                  </div>
                </div>
                <div class="stress-stage-banner">
                  <div class="stress-stage-banner-copy">
                    <span>当前传导</span>
                    <strong>{{ activeWavefront?.headline || activeSimulationLog?.title || '等待推演' }}</strong>
                  </div>
                  <div class="stress-stage-banner-metric">
                    {{ activeWavefront?.frame ? `STEP 0${activeWavefront.frame}` : 'SIM' }}
                  </div>
                </div>
                <div class="stress-stage-cards">
                  <div
                    v-for="card in stageCards"
                    :key="card.id"
                    class="stress-stage-card"
                    :class="{ active: card.active }"
                  >
                    <span>{{ card.label }}</span>
                    <strong>{{ card.impact }}</strong>
                    <small>{{ card.detail }}</small>
                  </div>
                </div>
                <div class="stress-wavefront-panel">
                  <div class="stress-wavefront-copy">
                    <strong>{{ activeWavefront?.impact_label || '等待波前计算' }}</strong>
                    <span>{{ activeWavefront?.log || '系统将根据冲击传播阶段生成实时波前日志。' }}</span>
                  </div>
                  <div class="stress-wavefront-meter">
                    <div class="stress-wavefront-meter-label">
                      <span>Impact</span>
                      <strong>{{ activeWavefront?.impact_score || 0 }}</strong>
                    </div>
                    <div class="stress-wavefront-meter-track">
                      <i :style="{ width: `${activeWavefront?.energy || 0}%` }" />
                    </div>
                  </div>
                </div>
              </div>

              <div class="stress-pulse-ribbon">
                <div
                  v-for="item in propagationSteps"
                  :key="`step-${item.step}`"
                  class="stress-ribbon-step"
                  :class="{ active: item.step - 1 === activeStressStep }"
                >
                  <em>0{{ item.step }}</em>
                  <strong>{{ item.title }}</strong>
                  <span>{{ item.detail }}</span>
                </div>
              </div>

              <div class="stress-impact-tape">
                <div
                  v-for="item in stressImpactTape"
                  :key="`impact-${item.step}`"
                  class="stress-impact-cell"
                  :class="[`tone-${item.tone || 'warning'}`, { active: item.step - 1 === activeStressStep }]"
                >
                  <span>{{ item.label }}</span>
                  <strong>{{ item.headline }}</strong>
                  <i :style="{ width: `${item.intensity || 0}%` }" />
                </div>
              </div>

              <div class="stress-transmission-grid">
                <article
                  v-for="(item, index) in transmissionMatrix"
                  :key="item.stage"
                  class="stress-transmission-card"
                  :class="[
                    `tone-${item.tone || 'warning'}`,
                    {
                      active:
                        (index === 0 && activeWavefront?.active_stage === 'upstream') ||
                        (index === 1 && activeWavefront?.active_stage === 'midstream') ||
                        (index === 2 &&
                          (activeWavefront?.active_stage === 'downstream' ||
                            activeWavefront?.active_stage === 'actions')),
                    },
                  ]"
                >
                  <span>{{ item.stage }}</span>
                  <strong>{{ item.headline }}</strong>
                  <div class="stress-transmission-score">{{ item.impact_score }}</div>
                  <small>{{ item.impact_label }}</small>
                </article>
              </div>

              <ChartPanel
                v-if="stressState.data.value?.chart"
                :title="'冲击传导强度'"
                :options="stressState.data.value.chart.options"
              />
            </section>
          </div>

          <div class="graph-support-strip stress-support-strip">
            <section class="graph-support-card">
              <div v-if="stressRecoverySequence.length" class="stress-recovery-sequence">
                <div
                  v-for="item in stressRecoverySequence"
                  :key="`recovery-${item.step}`"
                  class="stress-recovery-step"
                  :class="`tone-${item.tone || 'accent'}`"
                >
                  <em>0{{ item.step }}</em>
                  <div class="stress-recovery-copy">
                    <strong>{{ item.title }}</strong>
                    <span>{{ item.detail }}</span>
                  </div>
                </div>
              </div>
            </section>

            <section class="graph-support-card">
              <div class="timeline-list compact-timeline">
                <div v-for="item in stressState.data.value?.actions || []" :key="item.title" class="timeline-item">
                  <strong>{{ item.priority }} {{ item.title }}</strong>
                  <span>{{ item.reason }}</span>
                </div>
              </div>
            </section>

            <section class="graph-support-card">
              <div class="timeline-list compact-timeline">
                <RouterLink
                  v-for="item in stressState.data.value?.related_routes || []"
                  :key="item.label"
                  class="timeline-item interactive-card"
                  :to="{ path: item.path, query: item.query || {} }"
                >
                  <strong>{{ item.label }}</strong>
                </RouterLink>
              </div>
              <div class="timeline-list compact-timeline">
                <RouterLink
                  v-for="item in stressState.data.value?.evidence_navigation?.links || []"
                  :key="item.label + item.path"
                  class="timeline-item interactive-card"
                  :to="{ path: item.path, query: item.query || {} }"
                >
                  <strong>{{ item.label }}</strong>
                </RouterLink>
              </div>
              <div v-if="runsState.data.value?.runs?.length" class="timeline-list compact-timeline">
                <div
                  v-for="item in runsState.data.value?.runs || []"
                  :key="item.run_id"
                  class="timeline-item interactive-card"
                  @click="openStressRun(item.run_id)"
                >
                  <strong>{{ item.severity?.level }} · {{ item.company_name }}</strong>
                  <span>{{ item.scenario }}</span>
                </div>
              </div>
            </section>

            <section class="graph-support-card">
              <div class="timeline-list compact-timeline">
                <div
                  v-for="item in simulationLog"
                  :key="`log-${item.step}`"
                  class="timeline-item"
                >
                  <strong>{{ item.step }}. {{ item.title }}</strong>
                  <span>{{ item.detail }}</span>
                </div>
              </div>
            </section>
          </div>
        </article>
      </section>
    </template>
  </AppShell>
</template>
