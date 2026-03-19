<script setup lang="ts">
import { useRouter } from 'vue-router'

import { post, type UserRole } from '@/lib/api'
import { useSession } from '@/lib/session'

defineProps<{
  title: string
  subtitle?: string
  kicker?: string
  compact?: boolean
}>()

const router = useRouter()
const session = useSession()
const roleOptions: Array<{ value: UserRole; label: string }> = [
  { value: 'investor', label: '投资视角' },
  { value: 'management', label: '经营视角' },
  { value: 'regulator', label: '风控视角' },
]

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
  <div class="shell">
    <header class="page-header">
      <div class="shell-topbar">
        <RouterLink class="brand-lockup" to="/">
          <span class="brand-kicker">{{ kicker || 'OpsPilot-X' }}</span>
          <strong class="brand-name">新能源运营决策系统</strong>
        </RouterLink>
        <nav class="top-nav top-nav-main">
          <RouterLink to="/">首页</RouterLink>
          <RouterLink v-if="session.isAuthenticated.value" to="/workspace">对话分析台</RouterLink>
          <RouterLink v-if="session.isAuthenticated.value" to="/score">企业体检</RouterLink>
          <RouterLink v-if="session.isAuthenticated.value" to="/risk">行业风险</RouterLink>
          <RouterLink v-if="session.isAuthenticated.value" to="/verify">研报核验</RouterLink>
          <RouterLink v-if="session.isAuthenticated.value" to="/admin">管理台</RouterLink>
        </nav>
        <div class="top-nav top-nav-actions">
          <label v-if="session.isAuthenticated.value" class="role-switch">
            <span>分析视角</span>
            <select
              :value="session.activeRole.value"
              @change="session.setActiveRole(($event.target as HTMLSelectElement).value as UserRole)"
            >
              <option v-for="item in roleOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
            </select>
          </label>
          <RouterLink v-if="!session.isAuthenticated.value" to="/login">登录</RouterLink>
          <RouterLink v-if="!session.isAuthenticated.value" to="/register">注册</RouterLink>
          <button v-if="session.isAuthenticated.value" class="button-secondary logout-button" @click="logout">
            {{ session.currentUser.value?.display_name }} · 退出
          </button>
        </div>
      </div>
      <div v-if="title || subtitle" class="page-copy" :class="{ compact }">
        <div class="eyebrow">{{ title }}</div>
        <h1 v-if="subtitle" class="page-title">{{ subtitle }}</h1>
      </div>
    </header>
    <slot />
  </div>
</template>
