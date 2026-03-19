<script setup lang="ts">
import AppShell from '@/components/AppShell.vue'
import { useSession } from '@/lib/session'

const session = useSession()

const roleCards = [
  { code: '01', title: '投资视角', copy: '看收益质量、同业位置和证据。', route: '/workspace' },
  { code: '02', title: '经营视角', copy: '看经营瓶颈、现金压力和动作。', route: '/score' },
  { code: '03', title: '风控视角', copy: '看风险抬升、事件信号和偏差。', route: '/risk' },
]

const capabilityCards = [
  ['对话分析台', '输入问题后直接查看结果、图表、公式和证据。'],
  ['企业运营体检', '查看总分、五维结构、风险标签和建议动作。'],
  ['行业风险与对标', '按子行业查看风险排行、横向差异和行业背景。'],
  ['研报观点核验', '核对研报观点、评级、目标价和真实财报数据。'],
  ['证据查看器', '定位来源页码、重点片段、原始字段与证据指纹。'],
  ['管理台', '查看数据覆盖、作业入口和异常缺口。'],
]

const systemLayers = [
  ['AI 编排层', '总控调度、信号分析、证据审计、动作生成四个执行单元围绕同一问题协同工作。'],
  ['真实数据层', '交易所财报、东财研报、行业研报和页级证据统一进入 raw / bronze / silver 链路。'],
  ['可复核应用层', '体检、风险、核验、证据查看共享同一批结构化事实和同一条证据回路。'],
]
</script>

<template>
  <AppShell
    kicker="OpsPilot-X"
    title="首页"
    subtitle="真实财报驱动的新能源企业运营分析"
    compact
  >
    <section class="hero-grid">
      <article class="panel hero-panel">
        <div>
          <div class="eyebrow">OpsPilot-X</div>
          <h2 class="hero-title compact">先定位问题，再拆原因，再核证据。</h2>
          <p class="hero-text">围绕具体公司、具体报期和具体问题，统一调用真实财报、真实研报和页级证据完成分析。</p>
        </div>
        <div class="hero-actions">
          <RouterLink v-if="session.isAuthenticated.value" class="button-primary" to="/workspace">进入对话分析台</RouterLink>
          <RouterLink v-else class="button-primary" to="/login">登录</RouterLink>
          <RouterLink class="button-secondary" to="/register">注册账号</RouterLink>
        </div>
      </article>

      <div class="stack-grid">
        <RouterLink v-for="role in roleCards" :key="role.code" :to="role.route" class="command-card-shell role-card engine-link">
          <div class="signal-code">{{ role.code }}</div>
          <h3>{{ role.title }}</h3>
          <p class="command-copy">{{ role.copy }}</p>
        </RouterLink>
      </div>
    </section>

    <section class="metrics-grid">
      <article v-for="[title, copy] in systemLayers" :key="title" class="signal-card">
        <div class="signal-code">系统内核</div>
        <h4>{{ title }}</h4>
        <p class="command-copy">{{ copy }}</p>
      </article>
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
