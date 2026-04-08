<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { post } from '@/lib/api'
import { useSession } from '@/lib/session'
import { buildWorkflowQuery } from '@/lib/workflowContext'

defineProps<{
  title: string
  subtitle?: string
  kicker?: string
  compact?: boolean
}>()

const router = useRouter()
const route = useRoute()
const session = useSession()
const navSections = [
  {
    title: '一、全局数据监控',
    items: [{ to: '/brain', label: '新能源产业大脑', note: '高频流式数据与事件监控', auth: true }],
  },
  {
    title: '二、管理者：运营评估与推演',
    items: [
      { to: '/workspace', label: '协同分析', note: '围绕问题直接判断', auth: true },
      { to: '/score', label: '经营诊断', note: '企业体征与行业对标', auth: true },
      { to: '/stress', label: '压力推演', note: '冲击路径与应对动作', auth: true },
      { to: '/graph', label: '图谱检索', note: '顺着证据继续下钻', auth: true },
    ],
  },
  {
    title: '三、监管机构：合规与风险筛查',
    items: [
      { to: '/verify', label: '观点核验', note: '研报与财报一致性', auth: true },
      { to: '/vision', label: '文档复核', note: '原文结构与提取结果', auth: true },
    ],
  },
]

const visibleNavSections = computed(() =>
  navSections
    .map((section) => ({
      ...section,
      items: section.items.filter((item) => !item.auth || session.isAuthenticated.value),
    }))
    .filter((section) => section.items.length),
)

const flatNavItems = computed(() => visibleNavSections.value.flatMap((section) => section.items))

const activeNavLabel = computed(() => {
  if (route.path.startsWith('/evidence/')) {
    return '原文证据'
  }
  return flatNavItems.value.find((item) => item.to === route.path)?.label || '协同分析'
})

const routeContext = computed(() => {
  const mapping: Record<string, { title: string; note: string }> = {
    '/brain': { title: '先看行业变化', note: '' },
    '/workspace': { title: '围绕问题直接判断', note: '' },
    '/graph': { title: '顺着证据继续追', note: '' },
    '/stress': { title: '看冲击会先传到哪', note: '' },
    '/risk': { title: '先把风险收口到动作', note: '' },
    '/score': { title: '先看企业体质', note: '' },
    '/verify': { title: '核对观点靠不靠谱', note: '' },
    '/vision': { title: '回看财报原文结构', note: '' },
  }
  if (route.path.startsWith('/evidence/')) {
    return { title: '回到原文继续追', note: '' }
  }
  return mapping[route.path] || { title: activeNavLabel.value, note: '' }
})

async function logout() {
  try {
    await post('/auth/logout', {})
  } catch {
    // Frontend still clears stale state locally.
  }
  session.logout()
  await router.push('/login')
}

function buildNavTarget(path: string) {
  const query = buildWorkflowQuery(path, route.query, { role: session.activeRole.value })
  return query ? { path, query } : { path }
}
</script>

<template>
  <div class="shell shell-layout app-shell">
    <aside class="shell-sidebar app-sidebar">
      <RouterLink class="brand-lockup app-brand" to="/">
        <div class="brand-icon app-brand-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
            <path d="M8 7v10" />
            <path d="M16 7v10" />
            <path d="M7 8h10" />
            <path d="M7 16h10" />
            <path d="M10 12h4" />
          </svg>
        </div>
        <div class="brand-copy app-brand-copy">
          <strong class="brand-name">OpsPilot-X</strong>
          <span class="brand-kicker">{{ kicker || '新能源运营决策智能体' }}</span>
        </div>
      </RouterLink>

      <nav class="app-nav">
        <section v-for="section in visibleNavSections" :key="section.title" class="app-nav-group">
          <span class="app-nav-group-title">{{ section.title }}</span>
          <RouterLink
            v-for="item in section.items"
            :key="item.to"
            :to="buildNavTarget(item.to)"
            class="app-nav-item"
          >
            <strong>{{ item.label }}</strong>
            <span>{{ item.note }}</span>
          </RouterLink>
        </section>
      </nav>

      <div class="app-sidebar-footer">
        <div class="app-context-card">
          <span class="app-muted-label">{{ activeNavLabel }}</span>
          <strong>{{ routeContext.title }}</strong>
        </div>

        <div class="app-footer-row">
          <span class="app-footer-role">{{ session.activeRole.value === 'management' ? '管理层' : session.activeRole.value === 'regulator' ? '监管风控' : '投资者' }}</span>
          <button v-if="session.isAuthenticated.value" type="button" class="app-footer-link is-button" @click="logout">退出</button>
        </div>
      </div>
    </aside>

    <main class="shell-main app-main">
      <header v-if="title || subtitle" class="app-topbar">
        <div class="app-topbar-title">
          <span v-if="title && subtitle">{{ title }}</span>
          <strong>{{ subtitle || title }}</strong>
        </div>
      </header>
      <div class="page-content app-content">
        <slot />
      </div>
    </main>
  </div>
</template>

<style scoped>
.app-shell {
  background:
    linear-gradient(180deg, rgba(6, 8, 13, 0.98), rgba(8, 10, 16, 0.96)),
    radial-gradient(circle at top left, rgba(16, 185, 129, 0.08), transparent 24%);
}

.app-sidebar {
  width: 288px;
  padding: 22px 16px 18px;
  gap: 18px;
  background:
    linear-gradient(180deg, rgba(7, 8, 12, 0.98), rgba(6, 8, 13, 0.95));
  border-right: 1px solid rgba(255, 255, 255, 0.06);
  box-shadow: none;
}

.app-brand {
  align-items: center;
  gap: 12px;
  padding: 8px 8px 14px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.app-brand-icon {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  color: #58f0c0;
  border-color: rgba(88, 240, 192, 0.3);
  background: rgba(16, 185, 129, 0.08);
}

.app-brand-icon svg {
  width: 18px;
  height: 18px;
}

.app-brand-copy {
  gap: 6px;
}

.app-brand-copy .brand-name {
  font-size: 16px;
  letter-spacing: 0.02em;
}

.app-brand-copy .brand-kicker {
  color: rgba(88, 240, 192, 0.78);
  font-size: 10px;
  letter-spacing: 0.24em;
}

.app-nav {
  display: grid;
  gap: 18px;
  padding-top: 2px;
}

.app-nav-group {
  display: grid;
  gap: 10px;
}

.app-nav-group-title {
  padding: 0 8px;
  color: rgba(168, 179, 194, 0.74);
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.02em;
}

.app-nav-item {
  display: grid;
  gap: 4px;
  align-content: center;
  width: 100%;
  min-height: 72px;
  padding: 12px 14px;
  border-radius: 16px;
  border: 1px solid transparent;
  background: transparent;
  color: inherit;
  text-decoration: none;
  transition: background 0.18s ease, border-color 0.18s ease, transform 0.18s ease;
}

.app-nav-item strong {
  font-size: 15px;
  line-height: 1.25;
  color: #eef2f7;
}

.app-nav-item span {
  color: rgba(168, 179, 194, 0.72);
  font-size: 12px;
  line-height: 1.35;
}

.app-nav-item:hover {
  background: rgba(255, 255, 255, 0.03);
  border-color: rgba(255, 255, 255, 0.06);
  transform: translateY(-1px);
}

.app-nav-item.router-link-active {
  background: rgba(18, 62, 45, 0.88);
  border-color: rgba(52, 211, 153, 0.22);
}

.app-sidebar-footer {
  margin-top: auto;
  display: grid;
  gap: 10px;
  padding-top: 14px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.app-context-card {
  display: grid;
  gap: 4px;
  padding: 12px;
  border-radius: 16px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.025);
}

.app-context-card strong {
  font-size: 14px;
  line-height: 1.35;
  color: #eef2f7;
}

.app-muted-label {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: rgba(120, 143, 172, 0.78);
}

.app-footer-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.app-footer-role {
  color: rgba(203, 213, 225, 0.82);
  font-size: 12px;
}

.app-footer-link {
  min-height: 32px;
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.02);
  color: #d7dee8;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  text-decoration: none;
  font-size: 12px;
}

.app-footer-link.is-button {
  cursor: pointer;
}

.app-main {
  background:
    linear-gradient(180deg, rgba(14, 15, 18, 0.98), rgba(10, 11, 15, 0.98));
}

.app-topbar {
  min-height: 42px;
  padding: 12px 22px 0;
  display: flex;
  justify-content: center;
}

.app-topbar-title {
  display: grid;
  justify-items: center;
  gap: 4px;
  text-align: center;
}

.app-topbar-title span {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: rgba(120, 143, 172, 0.72);
}

.app-topbar-title strong {
  font-size: 13px;
  font-weight: 600;
  color: rgba(232, 238, 245, 0.92);
}

.app-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding: 16px 18px 20px;
  overflow-y: auto;
}

@media (max-width: 960px) {
  .app-sidebar {
    width: 100%;
    height: auto;
    max-height: none;
  }
}
</style>
