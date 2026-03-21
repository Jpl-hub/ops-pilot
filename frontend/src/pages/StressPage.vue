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
const stageCards = computed(() => {
  const steps = propagationSteps.value
  return [
    {
      id: 'upstream',
      label: '上游',
      impact: steps[0]?.title || '原料与矿产',
      detail: steps[0]?.detail || '等待推演',
      active: activeStressStep.value === 0,
    },
    {
      id: 'midstream',
      label: '中游',
      impact: steps[1]?.title || '电池与四大主材',
      detail: steps[1]?.detail || '等待推演',
      active: activeStressStep.value === 1,
    },
    {
      id: 'downstream',
      label: '下游',
      impact: steps[2]?.title || '整车与储能',
      detail: steps[2]?.detail || '等待推演',
      active: activeStressStep.value >= 2,
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
              <strong>当前冲击</strong>
              <span>{{ stressState.data.value?.scenario || scenario }}</span>
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
            <section class="stress-inputs stress-inputs-dynamic">
              <div class="signal-code">预设场景</div>
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
                <span>自定义场景</span>
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

              <ChartPanel
                v-if="stressState.data.value?.chart"
                :title="'冲击传导强度'"
                :options="stressState.data.value.chart.options"
              />
            </section>
          </div>

          <div class="graph-support-strip stress-support-strip">
            <section class="graph-support-card">
              <div class="signal-code">优先动作</div>
              <div class="timeline-list compact-timeline">
                <div v-for="item in stressState.data.value?.actions || []" :key="item.title" class="timeline-item">
                  <strong>{{ item.priority }} {{ item.title }}</strong>
                  <span>{{ item.reason }}</span>
                </div>
              </div>
            </section>

            <section class="graph-support-card">
              <div class="signal-code">继续下钻</div>
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
                <div v-for="item in runsState.data.value?.runs || []" :key="item.run_id" class="timeline-item">
                  <strong>{{ item.severity?.level }} · {{ item.company_name }}</strong>
                  <span>{{ item.scenario }}</span>
                </div>
              </div>
            </section>
          </div>
        </article>
      </section>
    </template>
  </AppShell>
</template>
