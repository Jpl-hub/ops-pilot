<script setup lang="ts">
import { useRouter } from 'vue-router'

import { post } from '@/lib/api'
import { useSession } from '@/lib/session'

defineProps<{
  title: string
  subtitle: string
  kicker?: string
}>()

const router = useRouter()
const session = useSession()

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
      <div class="page-copy">
        <div v-if="kicker" class="eyebrow">{{ kicker }}</div>
        <h1 class="page-title">{{ title }}</h1>
        <p class="page-subtitle">{{ subtitle }}</p>
      </div>
      <nav class="top-nav">
        <RouterLink to="/">首页</RouterLink>
        <RouterLink v-if="session.isAuthenticated.value" to="/workspace">对话分析台</RouterLink>
        <RouterLink v-if="session.isAuthenticated.value" to="/score">企业体检</RouterLink>
        <RouterLink v-if="session.isAuthenticated.value" to="/risk">行业风险</RouterLink>
        <RouterLink v-if="session.isAuthenticated.value" to="/verify">研报核验</RouterLink>
        <RouterLink v-if="session.isAuthenticated.value" to="/admin">系统管理</RouterLink>
        <RouterLink v-if="!session.isAuthenticated.value" to="/login">登录</RouterLink>
        <RouterLink v-if="!session.isAuthenticated.value" to="/register">注册</RouterLink>
        <button v-if="session.isAuthenticated.value" class="button-secondary" @click="logout">
          {{ session.currentUser.value?.display_name }} · 退出
        </button>
      </nav>
    </header>
    <slot />
  </div>
</template>
