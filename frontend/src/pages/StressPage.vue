<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
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
const route = useRoute()

const companies = computed(() => overviewState.data.value?.companies || [])
const selectedCompany = ref('')
const selectedPeriod = ref('')
const scenario = ref('欧盟对动力电池临时加征关税并限制关键材料进口')

const presetScenarios = [
  '欧盟对动力电池临时加征关税并限制关键材料进口',
  '上游碳酸锂价格急涨并持续三个月',
  '关键供应商停产两周导致交付延迟',
  '海外主要市场需求快速回落并触发库存积压',
]

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
}

onMounted(async () => {
  await overviewState.execute(() => get('/workspace/overview?user_role=management'))
  selectedCompany.value =
    (typeof route.query.company === 'string' ? route.query.company : '') || companies.value[0] || ''
  selectedPeriod.value = typeof route.query.period === 'string' ? route.query.period : ''
  await runStress()
})
</script>

<template>
  <AppShell title="产业链压力测试" subtitle="Stress Test" compact>
    <LoadingState v-if="overviewState.loading.value && !stressState.data.value" />
    <ErrorState
      v-else-if="overviewState.error.value || stressState.error.value"
      :message="String(overviewState.error.value || stressState.error.value)"
    />
    <template v-else>
      <section class="mode-header">
        <div class="mode-header-copy">
          <div class="eyebrow">Shock injection & propagation</div>
          <h2 class="hero-title compact">把宏观冲击注进去，再看它怎样传导到风险、动作和证据。</h2>
        </div>
      </section>

      <section class="mode-stage stress-mode-stage">
        <article class="panel mode-main-panel stress-main-panel">
          <div class="stress-layout">
            <div class="stress-inputs">
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
              <div class="subsection-label">预设冲击事件</div>
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
                <span>自定义冲击</span>
                <textarea v-model="scenario" class="text-area stress-input" />
              </label>
              <button class="button-primary stress-submit" @click="runStress">启动推演</button>
            </div>

            <div class="stress-output">
              <div class="stress-hero">
                <div>
                  <div class="signal-code">Scenario</div>
                  <h3>{{ stressState.data.value?.scenario }}</h3>
                </div>
                <TagPill
                  v-if="stressState.data.value?.severity"
                  :label="`${stressState.data.value.severity.level} ${stressState.data.value.severity.label}`"
                  :tone="stressState.data.value.severity.color === 'risk' ? 'risk' : 'success'"
                />
              </div>

              <div class="chip-grid">
                <div
                  v-for="item in stressState.data.value?.affected_dimensions || []"
                  :key="item.label"
                  class="metric-chip"
                >
                  <span>{{ item.label }}</span>
                  <strong>{{ item.value }}</strong>
                </div>
              </div>

              <div class="stress-propagation">
                <div v-for="item in stressState.data.value?.propagation_steps || []" :key="item.step" class="stress-step">
                  <div class="signal-code">Step {{ item.step }}</div>
                  <strong>{{ item.title }}</strong>
                  <span>{{ item.detail }}</span>
                </div>
              </div>

              <ChartPanel
                v-if="stressState.data.value?.chart"
                :title="'冲击传导强度'"
                :options="stressState.data.value.chart.options"
              />
            </div>
          </div>
        </article>

        <aside class="mode-side-panel">
          <section class="panel side-panel-block">
            <div class="panel-header">
              <div>
                <div class="eyebrow">优先动作</div>
                <h3>先做什么</h3>
              </div>
            </div>
            <div class="timeline-list compact-timeline">
              <div v-for="item in stressState.data.value?.actions || []" :key="item.title" class="timeline-item">
                <strong>{{ item.priority }} {{ item.title }}</strong>
                <span>{{ item.reason }}</span>
              </div>
            </div>
          </section>

          <section class="panel side-panel-block">
            <div class="panel-header">
              <div>
                <div class="eyebrow">跳转</div>
                <h3>继续下钻</h3>
              </div>
            </div>
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
            <div v-if="stressState.data.value?.evidence_navigation?.links?.length" class="subsection-label rail-gap">证据入口</div>
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
          </section>
        </aside>
      </section>
    </template>
  </AppShell>
</template>
