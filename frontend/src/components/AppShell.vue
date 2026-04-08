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
        { to: '/brain', label: '全景数据监控', note: '高频流式数据与事件监控', auth: true },
        { to: '/workspace', label: '多智能体协同研判', note: '围绕问题直接判断', auth: true },
        { to: '/graph', label: '图谱增强检索', note: '顺着证据继续追', auth: true },
      ],
    },
    {
      title: '二、管理者：运营评估与推演',
      items: [
        { to: '/score', label: '经营诊断与行业对标', note: '看企业体征与对比', auth: true },
        { to: '/stress', label: '产业链压力测试', note: '看冲击如何传导', auth: true },
      ],
    },
    {
      title: '三、监管机构：合规与风险筛查',
      items: [
        { to: '/verify', label: '观点核验与成因追溯', note: '研报与财报一致性校验', auth: true },
        { to: '/vision', label: '文档复核与自动化监控', note: '回到原文继续核对', auth: true },
      ],
    },
  ]
  return sections
    .map((section) => ({
      ...section,
      items: section.items.filter((item) => !item.auth || session.isAuthenticated.value),
    }))
    .filter((section) => section.items.length)
})

const flatNavItems = computed(() => navSections.value.flatMap((section) => section.items))

const activeNavLabel = computed(() => {
  if (route.path.startsWith('/evidence/')) return '原文证据'
  return flatNavItems.value.find((item) => item.to === route.path)?.label || '全景数据监控'
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
          <strong>N.E.W.S. Agent</strong>
          <span>NEW ENERGY WISDOM SYSTEM</span>
        </div>
      </RouterLink>

      <nav class="app-nav">
        <section v-for="section in navSections" :key="section.title" class="nav-section">
          <h3 class="nav-section-title">{{ section.title }}</h3>
          <div class="nav-section-items">
            <RouterLink
              v-for="item in section.items"
              :key="item.to"
              :to="buildNavTarget(item.to)"
              class="app-nav-item"
            >
              <strong>{{ item.label }}</strong>
              <span>{{ item.note }}</span>
            </RouterLink>
          </div>
        </section>
      </nav>

      <div class="app-sidebar-footer">
        <div class="app-system-row">
          <span class="system-dot"></span>
          <strong>System Online: 99.9%</strong>
        </div>
        <div class="app-footer-row">
          <button v-if="session.isAuthenticated.value" type="button" class="app-footer-link" @click="logout">
            退出
          </button>
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
    radial-gradient(circle at top left, rgba(16, 185, 129, 0.06), transparent 26%);
}

.app-sidebar {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  gap: 18px;
  padding: 20px 14px 16px;
  border-right: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(8, 10, 14, 0.98);
}

.app-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 8px 16px;
  text-decoration: none;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.app-brand-mark {
  width: 40px;
  height: 40px;
  display: grid;
  place-items: center;
  border-radius: 12px;
  color: #58f0c0;
  border: 1px solid rgba(88, 240, 192, 0.28);
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
  font-size: 20px;
  letter-spacing: 0.02em;
  color: #f8fafc;
}

.app-brand-copy span {
  color: rgba(88, 240, 192, 0.78);
  font-size: 9px;
  letter-spacing: 0.28em;
  text-transform: uppercase;
}

.app-nav {
  display: grid;
  gap: 20px;
  align-content: start;
  overflow-y: auto;
  padding-right: 4px;
}

.nav-section {
  display: grid;
  gap: 10px;
}

.nav-section-title {
  margin: 0;
  padding: 0 8px;
  color: rgba(168, 179, 194, 0.6);
  font-size: 10px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.nav-section-items {
  display: grid;
  gap: 8px;
}

.app-nav-item {
  display: grid;
  gap: 5px;
  min-height: 78px;
  padding: 14px 16px;
  border-radius: 16px;
  border: 1px solid rgba(255, 255, 255, 0.07);
  text-decoration: none;
  background: transparent;
  transition: background 0.18s ease, border-color 0.18s ease, transform 0.18s ease;
}

.app-nav-item strong {
  color: #eef2f7;
}

.app-nav-item strong {
  font-size: 16px;
  line-height: 1.18;
}

.app-nav-item span {
  color: rgba(168, 179, 194, 0.78);
}

.app-nav-item span {
  font-size: 10px;
  line-height: 1.35;
}

.app-nav-item:hover {
  background: rgba(255, 255, 255, 0.025);
  border-color: rgba(255, 255, 255, 0.12);
  transform: translateY(-1px);
}

.app-nav-item.router-link-active {
  background: rgba(18, 62, 45, 0.96);
  border-color: rgba(52, 211, 153, 0.28);
}

.app-sidebar-footer {
  display: grid;
  gap: 10px;
  padding-top: 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

.app-system-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 8px;
}

.system-dot {
  width: 10px;
  height: 10px;
  border-radius: 999px;
  background: #22c55e;
  box-shadow: 0 0 18px rgba(34, 197, 94, 0.45);
}

.app-system-row strong {
  color: rgba(168, 179, 194, 0.82);
  font-size: 12px;
  font-weight: 500;
  font-family: 'JetBrains Mono', monospace;
}

.app-footer-row {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
}

.app-footer-link {
  min-height: 38px;
  padding: 0 14px;
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.02);
  color: #d7dee8;
  font-size: 12px;
}

.app-main {
  min-width: 0;
  display: grid;
  min-height: 100vh;
  background: rgba(18, 18, 18, 0.92);
}

.app-content {
  min-width: 0;
  padding: 0;
}

@media (max-width: 1180px) {
  .app-shell {
    grid-template-columns: 1fr;
  }

  .app-sidebar {
    border-right: 0;
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  }
}

@media (max-width: 820px) {
  .app-content {
    padding: 16px;
  }
}
</style>
