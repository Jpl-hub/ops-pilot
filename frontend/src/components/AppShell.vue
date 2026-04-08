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

const navSections = computed(() => {
  const sections = [
    {
      title: '一、投资者：智能问数与洞察',
      items: [
        { to: '/brain', label: '新能源产业大脑', note: '高频流式数据与事件监控', auth: true },
        { to: '/workspace', label: '多智能体协同研判', note: '围绕问题直接发起判断', auth: true },
        { to: '/graph', label: '图谱增强检索', note: '沿着主链继续追证据', auth: true },
      ],
    },
    {
      title: '二、管理者：运营评估与推演',
      items: [
        { to: '/score', label: '经营诊断与行业对标', note: '五维评分与自动化策略优化', auth: true },
        { to: '/stress', label: '产业链压力测试', note: '宏观冲击与传导模拟', auth: true },
      ],
    },
    {
      title: '三、监管机构：合规与风险筛查',
      items: [
        { to: '/verify', label: '观点核验与成因追溯', note: '研报与财报原文一致性校验', auth: true },
        { to: '/vision', label: '文档复核与结构监控', note: 'OCR产物与原文结构治理', auth: true },
      ],
    },
  ]

  return sections.map((section) => ({
    ...section,
    items: section.items.filter((item) => !item.auth || session.isAuthenticated.value),
  }))
})

const activeNavLabel = computed(() => {
  if (route.path.startsWith('/evidence/')) return '原文证据'
  for (const section of navSections.value) {
    const match = section.items.find((item) => item.to === route.path)
    if (match) return match.label
  }
  return '新能源产业大脑'
})

const routeContext = computed(() => {
  const mapping: Record<string, string> = {
    '/brain': '先看行业变化',
    '/workspace': '围绕问题直接判断',
    '/graph': '沿着主链继续追',
    '/stress': '先说冲击，再看传导',
    '/score': '先看企业体征',
    '/verify': '核对研报和财报',
    '/vision': '回到原文继续看',
  }
  if (route.path.startsWith('/evidence/')) return '回到原文继续核对'
  return mapping[route.path] || activeNavLabel.value
})

async function logout() {
  try {
    await post('/auth/logout', {})
  } catch {
    // 本地仍会清理状态。
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
  <div class="app-shell">
    <aside class="app-sidebar">
      <RouterLink class="app-brand" to="/brain">
        <div class="app-brand-mark" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
            <path d="M8 7v10" />
            <path d="M16 7v10" />
            <path d="M7 8h10" />
            <path d="M7 16h10" />
            <path d="M10 12h4" />
          </svg>
        </div>
        <div class="app-brand-copy">
          <strong>OpsPilot-X</strong>
          <span>新能源运营决策智能体</span>
        </div>
      </RouterLink>

      <nav class="app-nav">
        <section v-for="section in navSections" :key="section.title" class="nav-section">
          <h3>{{ section.title }}</h3>
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
          <span>当前视角</span>
          <strong>{{ activeNavLabel }}</strong>
          <p>{{ routeContext }}</p>
        </div>
        <div class="app-footer-row" v-if="session.isAuthenticated.value">
          <RouterLink to="/profile" class="app-footer-link">个人中心</RouterLink>
          <button type="button" class="app-footer-link" @click="logout">退出</button>
        </div>
      </div>
    </aside>

    <main class="app-main">
      <div class="app-content">
        <slot />
      </div>
    </main>
  </div>
</template>

<style scoped>
.app-shell {
  min-height: 100vh;
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  background:
    linear-gradient(180deg, rgba(9, 11, 16, 0.995), rgba(8, 11, 16, 0.98)),
    radial-gradient(circle at top left, rgba(16, 185, 129, 0.05), transparent 24%);
}

.app-sidebar {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  gap: 16px;
  padding: 18px 12px 14px;
  border-right: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(8, 10, 14, 0.98);
}

.app-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 10px 16px;
  text-decoration: none;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.app-brand-mark {
  width: 42px;
  height: 42px;
  display: grid;
  place-items: center;
  border-radius: 14px;
  color: #58f0c0;
  border: 1px solid rgba(88, 240, 192, 0.26);
  background: rgba(16, 185, 129, 0.08);
}

.app-brand-mark svg {
  width: 18px;
  height: 18px;
}

.app-brand-copy {
  display: grid;
  gap: 4px;
}

.app-brand-copy strong {
  font-size: 18px;
  letter-spacing: 0.01em;
  color: #f8fafc;
}

.app-brand-copy span {
  color: rgba(88, 240, 192, 0.78);
  font-size: 11px;
  letter-spacing: 0.12em;
}

.app-nav {
  display: grid;
  gap: 18px;
  align-content: start;
  overflow-y: auto;
  padding-right: 2px;
}

.nav-section {
  display: grid;
  gap: 8px;
}

.nav-section h3 {
  margin: 0;
  padding: 0 10px;
  color: rgba(148, 163, 184, 0.62);
  font-size: 11px;
  letter-spacing: 0.08em;
}

.app-nav-item {
  display: grid;
  gap: 4px;
  min-height: 62px;
  padding: 11px 12px;
  border-radius: 14px;
  border: 1px solid transparent;
  text-decoration: none;
  transition: background 0.18s ease, border-color 0.18s ease, transform 0.18s ease;
}

.app-nav-item strong {
  color: #eef2f7;
  font-size: 15px;
  line-height: 1.2;
}

.app-nav-item span {
  color: rgba(168, 179, 194, 0.72);
  font-size: 11px;
  line-height: 1.4;
}

.app-nav-item:hover {
  background: rgba(255, 255, 255, 0.03);
  border-color: rgba(255, 255, 255, 0.08);
}

.app-nav-item.router-link-active {
  background: rgba(18, 62, 45, 0.96);
  border-color: rgba(52, 211, 153, 0.28);
}

.app-sidebar-footer {
  display: grid;
  gap: 10px;
  padding-top: 12px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

.app-context-card {
  display: grid;
  gap: 4px;
  padding: 12px;
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.02);
}

.app-context-card span {
  color: rgba(160, 174, 192, 0.68);
  font-size: 10px;
  letter-spacing: 0.08em;
}

.app-context-card strong {
  color: #f8fafc;
  font-size: 14px;
}

.app-context-card p {
  margin: 0;
  color: rgba(191, 207, 228, 0.72);
  font-size: 12px;
  line-height: 1.45;
}

.app-footer-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.app-footer-link {
  flex: 1;
  min-height: 42px;
  padding: 0 14px;
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.02);
  color: #dbe4ee;
  font-size: 13px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  text-decoration: none;
}

.app-main {
  min-width: 0;
  background: rgba(15, 18, 23, 0.94);
}

.app-content {
  min-height: 100vh;
  padding: 22px 24px 28px;
}

@media (max-width: 1100px) {
  .app-shell {
    grid-template-columns: 1fr;
  }

  .app-sidebar {
    grid-template-rows: auto;
    gap: 12px;
    border-right: 0;
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  }

  .app-nav {
    grid-auto-flow: column;
    grid-auto-columns: minmax(220px, 1fr);
    overflow-x: auto;
  }

  .nav-section {
    min-width: 220px;
  }

  .app-content {
    padding: 18px 16px 24px;
  }
}
</style>
