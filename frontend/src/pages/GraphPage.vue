<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import AppShell from '@/components/AppShell.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingState from '@/components/LoadingState.vue'
import TagPill from '@/components/TagPill.vue'
import { useAsyncState } from '@/composables/useAsyncState'
import { get, post } from '@/lib/api'

const overviewState = useAsyncState<any>()
const graphState = useAsyncState<any>()
const streamState = useAsyncState<any>()
const route = useRoute()

const selectedCompany = ref('')
const selectedPeriod = ref('')
const graphIntent = ref('碳酸锂价格下跌对下游盈利和风险的影响传导')
const graphIntentDraft = ref(graphIntent.value)

const companies = computed(() => overviewState.data.value?.companies || [])
const focalNodes = computed(() => graphState.data.value?.focal_nodes || [])
const inferencePath = computed(() => graphState.data.value?.inference_path || [])

async function loadGraph() {
  const company = selectedCompany.value
  if (!company) return
  const params = new URLSearchParams({ company_name: company })
  if (selectedPeriod.value) params.set('report_period', selectedPeriod.value)
  await Promise.all([
    graphState.execute(() =>
      post('/company/graph-query', {
        company_name: company,
        report_period: selectedPeriod.value || null,
        user_role: 'management',
        intent: graphIntent.value,
      }),
    ),
    streamState.execute(() => get(`/company/execution-stream?${params.toString()}&user_role=management&limit=8`)),
  ])
}

onMounted(async () => {
  await overviewState.execute(() => get('/workspace/overview?user_role=management'))
  selectedCompany.value =
    (typeof route.query.company === 'string' ? route.query.company : '') || companies.value[0] || ''
  selectedPeriod.value = typeof route.query.period === 'string' ? route.query.period : ''
  await loadGraph()
})

watch(selectedCompany, async () => {
  await loadGraph()
})

watch(selectedPeriod, async () => {
  await loadGraph()
})

async function submitIntent() {
  graphIntent.value = graphIntentDraft.value.trim() || graphIntent.value
  await loadGraph()
}
</script>

<template>
  <AppShell title="图谱检索" subtitle="图谱检索" compact>
    <LoadingState v-if="overviewState.loading.value && !graphState.data.value" />
    <ErrorState
      v-else-if="overviewState.error.value || graphState.error.value || streamState.error.value"
      :message="String(overviewState.error.value || graphState.error.value || streamState.error.value)"
    />
    <template v-else>
      <section class="mode-stage graph-mode-stage">
        <article class="panel mode-main-panel graph-main-stage">
          <div class="mode-query-panel">
            <div class="graph-search-icon">⌕</div>
            <div class="mode-query-copy">
              <strong>当前问题</strong>
              <span>{{ graphState.data.value?.intent || graphIntent }}</span>
            </div>
            <div class="mode-query-metrics">
              <TagPill :label="`Nodes ${graphState.data.value?.graph?.node_count || 0}`" />
              <TagPill :label="`Edges ${graphState.data.value?.graph?.edge_count || 0}`" />
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

          <div class="chat-composer graph-query-composer">
            <div class="chat-input-wrap-wide">
              <textarea
                v-model="graphIntentDraft"
                class="text-area chat-input"
                placeholder="输入一个问题，例如：碳酸锂价格下跌会怎样影响下游盈利。"
              />
              <button class="button-primary chat-send" @click="submitIntent">开始检索</button>
            </div>
          </div>

          <div class="graph-stage">
            <div class="graph-stage-main">
              <div class="signal-code">影响路径</div>
              <div class="graph-path-flow">
                <div v-for="item in inferencePath" :key="item.step" class="graph-path-card">
                  <span class="graph-path-step">0{{ item.step }}</span>
                  <strong>{{ item.title }}</strong>
                  <small>{{ item.detail }}</small>
                </div>
              </div>
            </div>

            <div class="graph-support-strip">
              <section class="graph-support-card">
                <div class="signal-code">关键节点</div>
                <div class="graph-node-stack">
                  <div
                    v-for="node in focalNodes"
                    :key="node.id"
                    class="graph-node"
                    :class="{
                      core: ['company', 'report_period', 'watchboard', 'research_report'].includes(node.type),
                      risk: ['risk_label', 'alert'].includes(node.type),
                      action: ['task', 'execution_stream'].includes(node.type),
                      evidence: ['document_artifact', 'artifact_evidence'].includes(node.type),
                    }"
                  >
                    {{ node.label }}
                  </div>
                </div>
              </section>

              <section class="graph-support-card">
                <div class="signal-code">继续查看</div>
                <div class="timeline-list compact-timeline">
                  <RouterLink
                    v-for="item in graphState.data.value?.evidence_navigation?.links || []"
                    :key="item.label + item.path"
                    class="timeline-item interactive-card"
                    :to="{ path: item.path, query: item.query || {} }"
                  >
                    <strong>{{ item.label }}</strong>
                  </RouterLink>
                </div>
                <div class="timeline-list compact-timeline">
                  <div v-for="item in streamState.data.value?.records || []" :key="item.id" class="timeline-item">
                    <strong>{{ item.title }}</strong>
                    <span>{{ item.stream_type }} · {{ item.status }}</span>
                  </div>
                </div>
              </section>
            </div>
          </div>
        </article>
      </section>
    </template>
  </AppShell>
</template>
