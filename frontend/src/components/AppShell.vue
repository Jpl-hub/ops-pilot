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

const navItems = [
  { to: '/', label: '首页', description: '进入系统总入口' },
  { to: '/workspace', label: '对话分析台', description: '围绕公司与问题展开协同分析', auth: true },
  { to: '/score', label: '企业体检', description: '查看评分、轨迹与关键风险', auth: true },
  { to: '/risk', label: '行业风险', description: '横向观察预警与行业分布', auth: true },
  { to: '/verify', label: '研报核验', description: '核对观点、预测与真实财报', auth: true },
  { to: '/admin', label: '管理台', description: '查看作业、监测与解析链路', auth: true },
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
  <div class="shell shell-layout">
    <aside class="shell-sidebar">
      <RouterLink class="brand-lockup" to="/">
        <span class="brand-kicker">{{ kicker || 'OpsPilot-X' }}</span>
        <strong class="brand-name">新能源运营决策系统</strong>
        <span class="brand-subtitle">以真实财报、研报和证据链驱动持续监测与分析</span>
      </RouterLink>

      <div class="sidebar-group">
        <div class="sidebar-label">导航</div>
        <nav class="top-nav top-nav-main top-nav-vertical">
          <RouterLink
            v-for="item in navItems"
            v-show="!item.auth || session.isAuthenticated.value"
            :key="item.to"
            :to="item.to"
            class="sidebar-nav-item"
          >
            <strong>{{ item.label }}</strong>
            <span>{{ item.description }}</span>
          </RouterLink>
        </nav>
      </div>

      <div class="sidebar-footer">
        <div class="system-status">
          <span class="system-dot"></span>
          <strong>系统在线</strong>
          <span>数据链路与分析服务可用</span>
        </div>

        <div v-if="session.isAuthenticated.value" class="sidebar-group">
          <div class="sidebar-label">分析视角</div>
          <div class="sidebar-control">
            <label class="role-switch">
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
          <div v-if="session.isAuthenticated.value" class="user-panel">
            <div class="sidebar-label">当前账户</div>
            <strong>{{ session.currentUser.value?.display_name }}</strong>
            <span>{{ session.currentUser.value?.username }}</span>
          </div>
          <div class="top-nav top-nav-actions top-nav-vertical">
            <RouterLink v-if="!session.isAuthenticated.value" to="/login">登录</RouterLink>
            <RouterLink v-if="!session.isAuthenticated.value" to="/register">注册</RouterLink>
            <button v-if="session.isAuthenticated.value" class="button-secondary logout-button" @click="logout">
              退出登录
            </button>
          </div>
        </div>
      </div>
    </aside>
    <main class="shell-main">
      <header class="page-header">
        <div v-if="title || subtitle" class="page-copy" :class="{ compact }">
          <div class="page-context">
            <div v-if="title" class="eyebrow">{{ title }}</div>
            <h1 v-if="subtitle" class="page-title">{{ subtitle }}</h1>
          </div>
        </div>
      </header>
      <slot />
    </main>
  </div>
</template>
