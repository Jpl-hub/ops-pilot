<script setup lang="ts">
import { computed, onMounted } from 'vue'

import AppShell from '@/components/AppShell.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingState from '@/components/LoadingState.vue'
import StatCard from '@/components/StatCard.vue'
import { useAsyncState } from '@/composables/useAsyncState'
import { get, post } from '@/lib/api'

const state = useAsyncState<{
  health: any
  score: any
  risk: any
  verify: any
  admin: any
}>()

const heroStats = computed(() => {
  if (!state.data.value) return []
  const { health, risk, verify, admin } = state.data.value
  return [
    { label: '主周期', value: String(health.preferred_period), hint: `公司池 ${health.companies} 家`, tone: 'accent' },
    { label: '风险暴露', value: String(risk.risk_board.filter((item: any) => item.risk_count > 0).length), hint: '主周期横向扫描', tone: 'danger' },
    { label: '研报核验', value: String(verify.key_numbers[0]?.value ?? 0), hint: '真实观点对照', tone: 'success' },
    { label: '数据主链', value: String(admin.quality_overview.coverage.preferred_period_ready), hint: '主周期已就绪', tone: 'default' },
  ]
})

onMounted(() => {
  void state.execute(async () => {
    const [health, score, risk, verify, admin] = await Promise.all([
      get('/healthz'),
      post('/company/score', { company_name: 'TCL中环' }),
      get('/industry/risk-scan'),
      post('/claim/verify', { company_name: 'TCL中环' }),
      get('/admin/overview'),
    ])
    return { health, score, risk, verify, admin }
  })
})
</script>

<template>
  <AppShell
    kicker="OpsPilot-X"
    title="让新能源公司的经营质量，一眼进入决策状态。"
    subtitle="从真实财报到研究观点，再到字段级证据，本系统不做说明书式页面，而是把用户真正要用的判断链放到前面。"
  >
    <LoadingState v-if="state.loading.value" />
    <ErrorState v-else-if="state.error.value" :message="state.error.value" />
    <template v-else-if="state.data.value">
      <section class="hero-grid">
        <div class="panel hero-panel">
          <div>
            <div class="eyebrow">真实数据驱动</div>
            <h2 class="hero-title">企业体检、行业风险、研报核验和系统管理，收束成一个驾驶舱。</h2>
            <p class="hero-text">先给用户结论，再给公式，再给证据，最后才给全量细节。</p>
          </div>
          <div class="hero-actions">
            <RouterLink class="button-primary" to="/score">进入企业体检</RouterLink>
            <RouterLink class="button-secondary" to="/risk">查看行业风险</RouterLink>
            <RouterLink class="button-secondary" to="/verify">核验研究观点</RouterLink>
          </div>
        </div>
        <div class="hero-metrics">
          <StatCard
            v-for="item in heroStats"
            :key="item.label"
            :label="item.label"
            :value="item.value"
            :hint="item.hint"
            :tone="item.tone as any"
          />
        </div>
      </section>

      <section class="command-grid">
        <RouterLink class="command-card" to="/score">
          <div class="command-title">企业体检</div>
          <div class="command-copy">围绕单家公司看总分、标签、公式和证据链。</div>
          <div class="command-meta">当前示例 {{ state.data.value.score.company_name }} · {{ state.data.value.score.report_period }}</div>
        </RouterLink>
        <RouterLink class="command-card" to="/risk">
          <div class="command-title">行业风险</div>
          <div class="command-copy">把 50 家公司放到同一主周期，直接看风险密度和行业背景。</div>
          <div class="command-meta">高风险公司 {{ state.data.value.risk.risk_board.filter((item: any) => item.risk_count > 0).length }} 家</div>
        </RouterLink>
        <RouterLink class="command-card" to="/verify">
          <div class="command-title">研报核验</div>
          <div class="command-copy">对照研报数字、评级、目标价和真实财报证据。</div>
          <div class="command-meta">当前示例 {{ state.data.value.verify.report_meta.source_name }}</div>
        </RouterLink>
        <RouterLink class="command-card" to="/admin">
          <div class="command-title">系统管理</div>
          <div class="command-copy">看覆盖缺口、数据状态和标准作业，不需要回终端拼命令。</div>
          <div class="command-meta">主周期完成 {{ state.data.value.admin.quality_overview.coverage.preferred_period_ready }}/50</div>
        </RouterLink>
      </section>
    </template>
  </AppShell>
</template>
