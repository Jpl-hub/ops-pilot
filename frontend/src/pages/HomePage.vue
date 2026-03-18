<script setup lang="ts">
import AppShell from '@/components/AppShell.vue'
import { useSession } from '@/lib/session'

const session = useSession()

const roleCards = [
  {
    code: '01',
    title: '投资者',
    copy: '查看公司经营质量、同业位置、研究观点和关键证据。',
  },
  {
    code: '02',
    title: '企业管理者',
    copy: '跟踪经营质量、现金压力、周转效率和重点整改事项。',
  },
  {
    code: '03',
    title: '监管 / 风控角色',
    copy: '批量查看风险暴露、事件信号和研究观点偏差。',
  },
]

const capabilityCards = [
  ['对话分析台', '输入问题后直接查看结果、图表、公式和证据。'],
  ['企业运营体检', '查看总分、五维结构、风险标签和建议动作。'],
  ['行业风险与对标', '按子行业查看风险排行、横向差异和行业背景。'],
  ['研报观点核验', '核对研报观点、评级、目标价和真实财报数据。'],
  ['证据查看器', '定位来源页码、重点片段、原始字段与证据指纹。'],
  ['管理台', '查看数据覆盖、作业入口和异常缺口。'],
]
</script>

<template>
  <AppShell
    kicker="OpsPilot-X"
    title="新能源企业运营分析"
    subtitle="用真实财报、真实研报和可复核证据，帮助你更快看清公司经营状态。"
  >
    <section class="hero-grid">
      <article class="panel hero-panel">
        <div>
          <div class="eyebrow">快速开始</div>
          <h2 class="hero-title">先看结果，再看原因，再看证据。</h2>
          <p class="hero-text">登录后即可直接分析公司、查看体检结果、核对研报观点和追踪证据来源。</p>
        </div>
        <div class="hero-actions">
          <RouterLink v-if="session.isAuthenticated.value" class="button-primary" to="/workspace">进入对话分析台</RouterLink>
          <RouterLink v-else class="button-primary" to="/login">登录</RouterLink>
          <RouterLink class="button-secondary" to="/register">注册账号</RouterLink>
        </div>
      </article>

      <div class="stack-grid">
        <article v-for="role in roleCards" :key="role.code" class="command-card-shell role-card">
          <div class="signal-code">{{ role.code }}</div>
          <h3>{{ role.title }}</h3>
          <p class="command-copy">{{ role.copy }}</p>
        </article>
      </div>
    </section>

    <section class="panel">
      <div class="panel-header">
        <div>
          <div class="eyebrow">功能总览</div>
          <h3>你可以直接做什么</h3>
        </div>
      </div>
      <div class="stack-grid capability-grid">
        <article v-for="[title, copy] in capabilityCards" :key="title" class="company-card">
          <h4>{{ title }}</h4>
          <p class="command-copy">{{ copy }}</p>
        </article>
      </div>
    </section>
  </AppShell>
</template>
