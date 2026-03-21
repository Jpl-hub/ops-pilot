<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import AppShell from '@/components/AppShell.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingState from '@/components/LoadingState.vue'
import TagPill from '@/components/TagPill.vue'
import { useAsyncState } from '@/composables/useAsyncState'
import { get } from '@/lib/api'

const overviewState = useAsyncState<any>()
const graphState = useAsyncState<any>()
const streamState = useAsyncState<any>()
const route = useRoute()

const selectedCompany = ref('')
const selectedPeriod = ref('')
const graphIntent = ref('碳酸锂价格下跌对下游盈利和风险的影响传导')

const companies = computed(() => overviewState.data.value?.companies || [])
const graphNodes = computed(() => graphState.data.value?.nodes || [])
const graphEdges = computed(() => graphState.data.value?.edges || [])
const inferencePath = computed(() =>
  graphEdges.value.slice(0, 5).map((edge: any) => `${nodeLabel(edge.source)} -> ${nodeLabel(edge.target)}`),
)

const nodeGroups = computed(() => {
  const buckets = {
    core: [] as any[],
    risk: [] as any[],
    execution: [] as any[],
    evidence: [] as any[],
  }
  for (const node of graphNodes.value) {
    if (['company', 'report_period', 'watchboard', 'research_report'].includes(node.type)) {
      buckets.core.push(node)
    } else if (['risk_label', 'alert'].includes(node.type)) {
      buckets.risk.push(node)
    } else if (['task', 'workspace_run', 'execution_stream'].includes(node.type)) {
      buckets.execution.push(node)
    } else {
      buckets.evidence.push(node)
    }
  }
  return buckets
})

function nodeLabel(nodeId: string) {
  return graphNodes.value.find((item: any) => item.id === nodeId)?.label || nodeId
}

async function loadGraph() {
  const company = selectedCompany.value
  if (!company) return
  const params = new URLSearchParams({ company_name: company })
  if (selectedPeriod.value) params.set('report_period', selectedPeriod.value)
  await Promise.all([
    graphState.execute(() => get(`/company/graph?${params.toString()}`)),
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
</script>

<template>
  <AppShell title="图谱增强检索" subtitle="Graph RAG" compact>
    <LoadingState v-if="overviewState.loading.value && !graphState.data.value" />
    <ErrorState
      v-else-if="overviewState.error.value || graphState.error.value || streamState.error.value"
      :message="String(overviewState.error.value || graphState.error.value || streamState.error.value)"
    />
    <template v-else>
      <section class="mode-header">
        <div class="mode-header-copy">
          <div class="eyebrow">New energy supply chain knowledge graph</div>
          <h2 class="hero-title compact">把一个问题压成图谱路径，再看影响如何传导。</h2>
        </div>
      </section>

      <section class="mode-stage graph-mode-stage">
        <article class="panel mode-main-panel">
          <div class="mode-query-panel">
            <div class="graph-search-icon">⌕</div>
            <div class="mode-query-copy">
              <strong>检索意图</strong>
              <span>{{ graphIntent }}</span>
            </div>
            <div class="mode-query-metrics">
              <TagPill :label="`Nodes ${graphState.data.value?.summary?.node_count || 0}`" />
              <TagPill :label="`Edges ${graphState.data.value?.summary?.edge_count || 0}`" />
            </div>
          </div>

          <div class="graph-stage">
            <div class="graph-lane">
              <div class="signal-code">核心节点</div>
              <div class="graph-node-stack">
                <div v-for="node in nodeGroups.core" :key="node.id" class="graph-node core">{{ node.label }}</div>
              </div>
            </div>
            <div class="graph-lane">
              <div class="signal-code">风险与信号</div>
              <div class="graph-node-stack">
                <div v-for="node in nodeGroups.risk" :key="node.id" class="graph-node risk">{{ node.label }}</div>
              </div>
            </div>
            <div class="graph-lane">
              <div class="signal-code">执行链</div>
              <div class="graph-node-stack">
                <div v-for="node in nodeGroups.execution" :key="node.id" class="graph-node action">{{ node.label }}</div>
              </div>
            </div>
            <div class="graph-lane">
              <div class="signal-code">证据与解析</div>
              <div class="graph-node-stack">
                <div v-for="node in nodeGroups.evidence" :key="node.id" class="graph-node evidence">{{ node.label }}</div>
              </div>
            </div>
          </div>

          <div class="graph-path-strip">
            <div class="signal-code">Inference Path</div>
            <div class="graph-path-tags">
              <span v-for="item in inferencePath" :key="item" class="path-chip">{{ item }}</span>
            </div>
          </div>
        </article>

        <aside class="mode-side-panel">
          <section class="panel side-panel-block">
            <div class="panel-header">
              <div>
                <div class="eyebrow">检索上下文</div>
                <h3>当前图谱</h3>
              </div>
            </div>
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
          </section>

          <section class="panel side-panel-block">
            <div class="panel-header">
              <div>
                <div class="eyebrow">执行流</div>
                <h3>最近关联动作</h3>
              </div>
            </div>
            <div class="timeline-list compact-timeline">
              <div v-for="item in streamState.data.value?.records || []" :key="item.id" class="timeline-item">
                <strong>{{ item.title }}</strong>
                <span>{{ item.stream_type }} · {{ item.status }}</span>
              </div>
            </div>
          </section>
        </aside>
      </section>
    </template>
  </AppShell>
</template>
