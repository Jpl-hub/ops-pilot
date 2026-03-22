<script setup lang="ts">
import { computed, ref } from 'vue'
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
const toolsExpanded = ref(true)
const roleOptions: Array<{ value: UserRole; label: string }> = [
  { value: 'investor', label: '投资视角' },
  { value: 'management', label: '经营视角' },
  { value: 'regulator', label: '风控视角' },
]

const primaryNavItems = [
  { to: '/', label: '首页' },
  { to: '/brain', label: '产业大脑', auth: true },
  { to: '/workspace', label: '协同分析', auth: true },
  { to: '/score', label: '企业体检', auth: true },
  { to: '/admin', label: '管理台', auth: true },
]
const toolNavItems = [
  { to: '/graph', label: '图谱检索', auth: true },
  { to: '/stress', label: '压力测试', auth: true },
  { to: '/verify', label: '研报核验', auth: true },
  { to: '/vision', label: '多模态解析', auth: true },
]
const isToolRoute = computed(() => toolNavItems.some((item) => item.to === route.path))
if (isToolRoute.value) {
  toolsExpanded.value = true
}

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
  <div class="shell shell-layout">
    <div class="absolute-bg shell-bg-pattern" style="position: absolute; inset: 0; pointer-events: none; z-index: 0;"></div>
    <div class="absolute-bg shell-bg-glow" style="position: absolute; inset: 0; pointer-events: none; z-index: 0;"></div>

    <aside class="shell-sidebar glass-panel">
      <RouterLink class="brand-lockup" to="/">
        <div class="brand-icon">◎</div>
        <div class="brand-copy">
          <span class="brand-kicker">{{ kicker || 'OpsPilot-X' }}</span>
          <strong class="brand-name">N.E.W.S. Agent</strong>
        </div>
      </RouterLink>

      <div class="sidebar-group">
        <nav class="top-nav top-nav-main top-nav-vertical">
          <RouterLink
            v-for="item in primaryNavItems"
            v-show="!item.auth || session.isAuthenticated.value"
            :key="item.to"
            :to="item.to"
            class="sidebar-nav-item"
          >
            <strong>{{ item.label }}</strong>
          </RouterLink>
        </nav>
      </div>

      <div v-if="session.isAuthenticated.value" class="sidebar-group">
        <button class="sidebar-collapse" type="button" @click="toolsExpanded = !toolsExpanded">
          <span>分析工具</span>
          <strong>{{ toolsExpanded ? '−' : '+' }}</strong>
        </button>
        <nav v-if="toolsExpanded" class="top-nav top-nav-main top-nav-vertical">
          <RouterLink
            v-for="item in toolNavItems"
            :key="item.to"
            :to="item.to"
            class="sidebar-nav-item sidebar-nav-item-subtle"
          >
            <strong>{{ item.label }}</strong>
          </RouterLink>
        </nav>
      </div>

      <div class="sidebar-footer">
        <div v-if="session.isAuthenticated.value" class="sidebar-group">
          <div class="sidebar-control">
            <label class="role-switch role-switch-card">
              <select
                :value="session.activeRole.value"
                @change="session.setActiveRole(($event.target as HTMLSelectElement).value as UserRole)"
              >
                <option v-for="item in roleOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
              </select>
            </label>
          </div>
        </div>

        <div class="sidebar-group">
          <div v-if="session.isAuthenticated.value" class="sidebar-utility-stack">
            <RouterLink to="/profile" class="sidebar-utility-card sidebar-utility-card-action sidebar-utility-card-compact">
              <strong>{{ session.currentUser.value?.display_name }}</strong>
            </RouterLink>
            <button class="button-secondary sidebar-utility-card sidebar-utility-card-compact sidebar-utility-card-action" @click="logout">
              <strong>退出登录</strong>
            </button>
          </div>
          <div v-else class="sidebar-utility-stack">
            <RouterLink to="/login" class="sidebar-utility-card sidebar-utility-card-action sidebar-utility-card-compact">
              <strong>登录</strong>
            </RouterLink>
            <RouterLink to="/register" class="sidebar-utility-card sidebar-utility-card-action sidebar-utility-card-compact">
              <strong>注册</strong>
            </RouterLink>
          </div>
        </div>
      </div>
    </aside>
    <main class="shell-main">
      <header class="page-header" style="padding: 24px 24px 0; flex-shrink: 0;">
        <div v-if="title || subtitle" class="page-copy" :class="{ compact }">
          <div class="page-context">
            <div v-if="title && subtitle" class="eyebrow">{{ title }}</div>
            <h1 class="page-title">{{ subtitle || title }}</h1>
          </div>
        </div>
      </header>
      <div class="page-content" style="flex: 1; display: flex; flex-direction: column; padding: 16px 24px 24px; overflow-y: auto; min-height: 0;">
        <slot />
      </div>
    </main>
  </div>
</template>
