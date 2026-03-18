<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import AppShell from '@/components/AppShell.vue'
import ChartPanel from '@/components/ChartPanel.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingState from '@/components/LoadingState.vue'
import StatCard from '@/components/StatCard.vue'
import { useAsyncState } from '@/composables/useAsyncState'
import { get, post } from '@/lib/api'
import { buildEvidenceLink } from '@/lib/format'
import { useSession } from '@/lib/session'

const session = useSession()
const companies = ref<string[]>([])
const selectedCompany = ref('TCL中环')
const query = ref('请给我TCL中环2025Q3的经营体检结论，并解释主要风险标签。')
const workspaceState = useAsyncState<any>()

const roleLabel = computed(() => {
  const mapping: Record<string, string> = {
    investor: '投资者',
    management: '企业管理者',
    regulator: '监管 / 风控角色',
  }
  return mapping[session.currentUser.value?.role || 'investor']
})

async function loadCompanies() {
  const risk = await get<any>('/industry/risk-scan')
  companies.value = risk.risk_board.map((item: any) => item.company_name)
}

async function runQuery() {
  await workspaceState.execute(() =>
    post('/chat/turn', {
      query: query.value,
      company_name: selectedCompany.value,
      user_role: session.currentUser.value?.role || 'investor',
    }),
  )
}

const keyNumbers = computed(() => workspaceState.data.value?.key_numbers || [])
const evidenceGroups = computed(() => workspaceState.data.value?.evidence_groups || [])
const calculations = computed(() => workspaceState.data.value?.calculations || [])
const charts = computed(() => workspaceState.data.value?.charts || [])
const formulas = computed(() => workspaceState.data.value?.formula_cards || [])

onMounted(async () => {
  await loadCompanies()
  if (!companies.value.includes(selectedCompany.value)) {
    selectedCompany.value = companies.value[0]
  }
  await runQuery()
})
</script>

<template>
  <AppShell
    title="对话分析台"
    subtitle="输入公司和问题后，直接查看结果、图表、公式和证据。"
  >
    <section class="workspace-grid">
      <article class="panel workspace-main">
        <div class="panel-header">
          <div>
            <div class="eyebrow">问题输入</div>
            <h3>{{ roleLabel }}</h3>
          </div>
        </div>
        <div class="toolbar multi workspace-toolbar">
          <label class="field">
            <span>公司</span>
            <select v-model="selectedCompany">
              <option v-for="company in companies" :key="company" :value="company">{{ company }}</option>
            </select>
          </label>
          <label class="field field-wide">
            <span>问题</span>
            <textarea v-model="query" class="text-area" />
          </label>
          <button class="button-primary workspace-submit" @click="runQuery">执行分析</button>
        </div>
        <LoadingState v-if="workspaceState.loading.value" />
        <ErrorState v-else-if="workspaceState.error.value" :message="workspaceState.error.value" />
        <template v-else-if="workspaceState.data.value">
          <div class="analysis-answer">
            <div class="eyebrow">分析结果</div>
            <div class="analysis-copy">{{ workspaceState.data.value.answer_markdown }}</div>
          </div>
          <div class="metrics-grid">
            <StatCard
              v-for="item in keyNumbers"
              :key="item.label"
              :label="item.label"
              :value="String(item.value)"
              :hint="item.unit || '核心数值'"
              tone="accent"
            />
          </div>
        </template>
      </article>

      <article class="panel workspace-side" v-if="evidenceGroups.length">
        <div class="panel-header">
          <div>
            <div class="eyebrow">证据侧栏</div>
            <h3>重点证据</h3>
          </div>
        </div>
        <div class="timeline-list">
          <div v-for="group in evidenceGroups.slice(0, 4)" :key="group.code" class="timeline-item">
            <strong>{{ group.title }}</strong>
            <span>{{ group.subtitle }}</span>
            <RouterLink
              v-for="item in group.items.slice(0, 2)"
              :key="item.chunk_id"
              class="inline-link"
              :to="buildEvidenceLink(item.chunk_id, group.title, group.anchor_terms)"
            >
              {{ item.source_title }} · p.{{ item.page }}
            </RouterLink>
          </div>
        </div>
      </article>
    </section>

    <section v-if="charts.length" class="chart-grid">
      <ChartPanel v-for="chart in charts" :key="chart.title" :title="chart.title" :options="chart.options" />
    </section>

    <section class="workspace-lower">
      <article class="panel">
        <div class="panel-header">
          <div>
            <div class="eyebrow">计算步骤</div>
            <h3>计算链</h3>
          </div>
        </div>
        <div class="detail-list">
          <div v-for="item in calculations" :key="item.step" class="detail-row">
            <span>{{ item.step }}</span>
            <strong>{{ item.detail }}</strong>
          </div>
        </div>
      </article>

      <article class="panel">
        <div class="panel-header">
          <div>
            <div class="eyebrow">公式回放</div>
            <h3>关键公式</h3>
          </div>
        </div>
        <div class="stack-grid">
          <article v-for="formula in formulas" :key="formula.metric_code" class="formula-card">
            <div class="signal-top">
              <div>
                <div class="signal-code">{{ formula.metric_code }}</div>
                <h4>{{ formula.title }}</h4>
              </div>
              <div class="signal-value">{{ formula.value }}</div>
            </div>
            <code class="formula-inline">{{ formula.formula }}</code>
          </article>
        </div>
      </article>
    </section>
  </AppShell>
</template>
