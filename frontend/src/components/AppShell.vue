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
  { to: '/', label: '首页', description: '系统入口' },
  { to: '/brain', label: '产业大脑', description: '实时监测', auth: true },
  { to: '/workspace', label: '协同分析', description: '任务主台', auth: true },
  { to: '/graph', label: '图谱检索', description: '路径推理', auth: true },
  { to: '/stress', label: '压力测试', description: '冲击推演', auth: true },
  { to: '/score', label: '企业体检', description: '经营诊断', auth: true },
  { to: '/verify', label: '研报核验', description: '观点核对', auth: true },
  { to: '/vision', label: '多模态解析', description: '文档理解', auth: true },
  { to: '/admin', label: '管理台', description: '作业链路', auth: true },
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
        <div class="brand-icon">◎</div>
        <div class="brand-copy">
          <span class="brand-kicker">{{ kicker || 'OpsPilot-X' }}</span>
          <strong class="brand-name">N.E.W.S. Agent</strong>
          <span class="brand-subtitle">New Energy Wisdom System</span>
        </div>
      </RouterLink>

      <div class="sidebar-group">
        <div class="sidebar-label">System Modes</div>
        <nav class="top-nav top-nav-main top-nav-vertical">
          <RouterLink
            v-for="item in navItems"
            v-show="!item.auth || session.isAuthenticated.value"
            :key="item.to"
            :to="item.to"
            class="sidebar-nav-item"
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
            <RouterLink to="/profile" class="sidebar-utility-card sidebar-utility-card-action">
              <strong>{{ session.currentUser.value?.display_name }}</strong>
            </RouterLink>
            <button class="button-secondary sidebar-utility-card sidebar-utility-card-action" @click="logout">
              <strong>退出登录</strong>
            </button>
          </div>
          <div v-else class="sidebar-utility-stack">
            <RouterLink to="/login" class="sidebar-utility-card sidebar-utility-card-action">
              <span class="sidebar-utility-label">账户入口</span>
              <strong>登录</strong>
              <small>进入系统工作区</small>
            </RouterLink>
            <RouterLink to="/register" class="sidebar-utility-card sidebar-utility-card-action">
              <span class="sidebar-utility-label">新建账户</span>
              <strong>注册</strong>
              <small>创建新的工作账号</small>
            </RouterLink>
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
