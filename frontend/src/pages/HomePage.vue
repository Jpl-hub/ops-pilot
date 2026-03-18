<script setup lang="ts">
import AppShell from '@/components/AppShell.vue'
import { useSession } from '@/lib/session'

const session = useSession()

const roleCards = [
  {
    code: '01',
    title: '投资者',
    copy: '围绕单家公司完成问数、评分、对标、研报核验和证据复盘。',
  },
  {
    code: '02',
    title: '企业管理者',
    copy: '把经营质量、现金压力、周转效率和竞争位置放到一张工作台里看。',
  },
  {
    code: '03',
    title: '监管 / 风控角色',
    copy: '批量观察主周期风险暴露、事件信号与研究观点偏差。',
  },
]

const capabilityCards = [
  ['对话分析台', '围绕公司、报期和问题发起分析，集中查看回答、图表、证据和计算步骤。'],
  ['企业运营体检', '输出总分、五维结构、风险/机会标签、建议动作与证据链接。'],
  ['行业风险与对标', '按子行业看风险排行、横向差异和行业研究背景。'],
  ['研报观点核验', '把真实研报观点与真实财报数据放到一屏核对。'],
  ['证据查看器', '定位来源页码、重点片段、原始字段与证据指纹。'],
  ['系统管理台', '统一看数据覆盖、作业入口、缺口定位和系统状态。'],
]
</script>

<template>
  <AppShell
    kicker="OpsPilot-X"
    title="新能源企业运营分析与决策支持系统"
    subtitle="围绕真实财报、真实研报和可复核证据，给用户一套能直接落到判断与行动的产品主链。"
  >
    <section class="hero-grid">
      <article class="panel hero-panel">
        <div>
          <div class="eyebrow">角色导向入口</div>
          <h2 class="hero-title">不是堆数据，而是把用户从问题带到结论，再带到证据。</h2>
          <p class="hero-text">
            登录后默认进入对话分析台。所有页面围绕“具体公司、具体报期、具体问题”组织，而不是把原始指标平铺给用户。
          </p>
        </div>
        <div class="hero-actions">
          <RouterLink v-if="session.isAuthenticated.value" class="button-primary" to="/workspace">进入对话分析台</RouterLink>
          <RouterLink v-else class="button-primary" to="/login">登录系统</RouterLink>
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
          <div class="eyebrow">产品主线</div>
          <h3>统一工作流</h3>
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
