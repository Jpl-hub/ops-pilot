<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { post, type UserRole } from '@/lib/api'
import { useSession } from '@/lib/session'

defineProps<{
  title: string
  subtitle?: string
  kicker?: string
  compact?: boolean
}>()

const router = useRouter()
const route = useRoute()
const session = useSession()
const roleOptions: Array<{ value: UserRole; label: string }> = [
  { value: 'investor', label: '投资者' },
  { value: 'management', label: '管理层' },
  { value: 'regulator', label: '监管风控' },
]

const sidebarItems = [
  { to: '/brain', label: '产业大脑', detail: '行业变化', auth: true },
  { to: '/workspace', label: '协同分析', detail: '直接判断', auth: true },
  { to: '/graph', label: '图谱检索', detail: '证据追溯', auth: true },
  { to: '/stress', label: '压力推演', detail: '冲击传导', auth: true },
  { to: '/score', label: '经营诊断', detail: '经营体检', auth: true },
  { to: '/verify', label: '观点核验', detail: '研报对照', auth: true },
  { to: '/vision', label: '文档复核', detail: '财报原文', auth: true },
]

const visibleSidebarItems = computed(() =>
  sidebarItems.filter((item) => !item.auth || session.isAuthenticated.value),
)

const activeNavLabel = computed(
  () => sidebarItems.find((item) => item.to === route.path)?.label || '协同分析',
)

const routeContext = computed(() => {
  const mapping: Record<string, { title: string; note: string }> = {
    '/brain': { title: '先看行业变化', note: '把今天值得继续盯的变化先拎出来。' },
    '/workspace': { title: '围绕问题直接判断', note: '把结论、动作和证据压成一页。' },
    '/graph': { title: '顺着证据继续追', note: '沿节点和原文继续追这条判断。' },
    '/stress': { title: '看冲击会传到哪', note: '先看冲击会先打到哪，再决定先做什么。' },
    '/score': { title: '先看企业体质', note: '把经营问题和优先动作先看清。' },
    '/verify': { title: '核对观点靠不靠谱', note: '把研报说法和财报原文放在一起。' },
    '/vision': { title: '回看财报原文结构', note: '直接回看页块、表格和原文。' },
  }
  return mapping[route.path] || { title: activeNavLabel.value, note: '先看当前工作面，再决定下一步往哪追。' }
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
        <RouterLink
          v-for="item in visibleSidebarItems"
          :key="item.to"
          :to="item.to"
          class="app-nav-item"
        >
          <strong>{{ item.label }}</strong>
        </RouterLink>
      </nav>

      <div class="app-sidebar-footer">
        <div class="app-context-card">
          <span class="app-muted-label">{{ activeNavLabel }}</span>
          <strong>{{ routeContext.title }}</strong>
        </div>

        <div v-if="session.isAuthenticated.value" class="app-role-box">
          <span class="app-muted-label">当前视角</span>
          <label class="app-role-select">
            <select
              :value="session.activeRole.value"
              @change="session.setActiveRole(($event.target as HTMLSelectElement).value as UserRole)"
            >
              <option v-for="item in roleOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
            </select>
          </label>
        </div>

        <div class="app-user-box">
          <template v-if="session.isAuthenticated.value">
            <RouterLink to="/profile" class="app-footer-link">
              {{ session.currentUser.value?.display_name || '个人档案' }}
            </RouterLink>
            <RouterLink to="/admin" class="app-footer-link">保障台</RouterLink>
            <button type="button" class="app-footer-link is-button" @click="logout">退出</button>
          </template>
          <template v-else>
            <RouterLink to="/login" class="app-footer-link">登录</RouterLink>
            <RouterLink to="/register" class="app-footer-link">注册</RouterLink>
          </template>
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
  gap: 10px;
  padding-top: 2px;
}

.app-nav-item {
  display: grid;
  gap: 6px;
  width: 100%;
  padding: 12px 14px;
  border-radius: 16px;
  border: 1px solid transparent;
  background: transparent;
  color: inherit;
  text-decoration: none;
  transition: background 0.18s ease, border-color 0.18s ease, transform 0.18s ease;
}

.app-nav-item strong {
  font-size: 14px;
  line-height: 1.25;
  color: #eef2f7;
}

.app-nav-item span {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.1em;
  color: rgba(110, 137, 170, 0.9);
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

.app-nav-item.router-link-active span {
  color: rgba(110, 242, 194, 0.82);
}

.app-sidebar-footer {
  margin-top: auto;
  display: grid;
  gap: 14px;
  padding-top: 14px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.app-context-card {
  display: grid;
  gap: 8px;
  padding: 12px 12px 10px;
  border-radius: 16px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.025);
}

.app-context-card strong {
  font-size: 14px;
  line-height: 1.35;
  color: #eef2f7;
}

.app-context-card p {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  color: rgba(187, 200, 217, 0.82);
}

.app-muted-label {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: rgba(120, 143, 172, 0.78);
}

.app-role-box,
.app-user-box {
  display: grid;
  gap: 8px;
}

.app-role-select select {
  width: 100%;
  min-height: 44px;
  padding: 0 12px;
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.03);
  color: #eef2f7;
}

.app-user-box {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.app-footer-link {
  min-height: 38px;
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

  .app-user-box {
    grid-template-columns: 1fr;
  }
}
</style>
