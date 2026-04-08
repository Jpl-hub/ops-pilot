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

const navItems = computed(() => [
  { to: '/brain', label: '新能源产业大脑', note: '先看行业', auth: true },
  { to: '/workspace', label: '协同分析', note: '围绕问题直接判断', auth: true },
  { to: '/graph', label: '图谱检索', note: '顺着证据继续追', auth: true },
  { to: '/stress', label: '压力推演', note: '看冲击如何传导', auth: true },
  { to: '/score', label: '经营诊断', note: '看企业体征', auth: true },
  { to: '/verify', label: '观点核验', note: '核对研报和财报', auth: true },
  { to: '/vision', label: '文档复核', note: '回到原文', auth: true },
].filter((item) => !item.auth || session.isAuthenticated.value))

const activeNavLabel = computed(() => {
  if (route.path.startsWith('/evidence/')) return '原文证据'
  return navItems.value.find((item) => item.to === route.path)?.label || '新能源产业大脑'
})

const routeContext = computed(() => {
  const mapping: Record<string, string> = {
    '/brain': '先看行业变化',
    '/workspace': '围绕问题直接判断',
    '/graph': '顺着证据继续追',
    '/stress': '看冲击如何传导',
    '/score': '先看企业体征',
    '/verify': '核对观点靠不靠谱',
    '/vision': '回到原文继续核对',
  }
  if (route.path.startsWith('/evidence/')) return '继续回到原文'
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
        <RouterLink
          v-for="item in navItems"
          :key="item.to"
          :to="buildNavTarget(item.to)"
          class="app-nav-item"
        >
          <strong>{{ item.label }}</strong>
          <span>{{ item.note }}</span>
        </RouterLink>
      </nav>

      <div class="app-sidebar-footer">
        <div class="app-context-card">
          <span>{{ activeNavLabel }}</span>
          <strong>{{ routeContext }}</strong>
        </div>

        <div class="app-footer-row">
          <span class="app-footer-role">{{ session.activeRole.value === 'management' ? '管理层' : session.activeRole.value === 'regulator' ? '监管风控' : '投资者' }}</span>
          <button v-if="session.isAuthenticated.value" type="button" class="app-footer-link" @click="logout">退出</button>
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
  grid-template-columns: 292px minmax(0, 1fr);
  background:
    radial-gradient(circle at top left, rgba(16, 185, 129, 0.08), transparent 24%),
    linear-gradient(180deg, rgba(7, 10, 18, 0.98), rgba(7, 10, 18, 0.94));
}

.app-sidebar {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  gap: 18px;
  padding: 22px 16px 18px;
  border-right: 1px solid rgba(255, 255, 255, 0.06);
  background: linear-gradient(180deg, rgba(7, 8, 12, 0.98), rgba(6, 8, 13, 0.95));
}

.app-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 8px 16px;
  text-decoration: none;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
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
  font-size: 16px;
  letter-spacing: 0.01em;
  color: #f8fafc;
}

.app-brand-copy span {
  color: rgba(88, 240, 192, 0.78);
  font-size: 11px;
  letter-spacing: 0.18em;
}

.app-nav {
  display: grid;
  gap: 10px;
  align-content: start;
}

.app-nav-item {
  display: grid;
  gap: 4px;
  min-height: 72px;
  padding: 14px 16px;
  border-radius: 18px;
  border: 1px solid transparent;
  text-decoration: none;
  background: transparent;
  transition: background 0.18s ease, border-color 0.18s ease, transform 0.18s ease;
}

.app-nav-item strong,
.app-context-card strong {
  color: #eef2f7;
}

.app-nav-item strong {
  font-size: 18px;
  line-height: 1.2;
}

.app-nav-item span,
.app-context-card span,
.app-footer-role {
  color: rgba(168, 179, 194, 0.76);
}

.app-nav-item span {
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

.app-context-card span {
  font-size: 11px;
}

.app-context-card strong {
  font-size: 14px;
  line-height: 1.35;
}

.app-footer-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.app-footer-role {
  font-size: 12px;
}

.app-footer-link {
  min-height: 32px;
  padding: 0 12px;
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.02);
  color: #d7dee8;
  font-size: 12px;
}

.app-main {
  min-width: 0;
  display: grid;
}

.app-content {
  min-width: 0;
  padding: 22px 26px 26px;
}

@media (max-width: 1180px) {
  .app-shell {
    grid-template-columns: 1fr;
  }

  .app-sidebar {
    border-right: 0;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  }

  .app-nav {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 820px) {
  .app-nav {
    grid-template-columns: 1fr;
  }

  .app-content {
    padding: 16px;
  }
}
</style>
