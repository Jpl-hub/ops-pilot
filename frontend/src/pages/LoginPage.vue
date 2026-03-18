<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AppShell from '@/components/AppShell.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingState from '@/components/LoadingState.vue'
import { post, saveAuth, type AuthPayload } from '@/lib/api'
import { useSession } from '@/lib/session'

const route = useRoute()
const router = useRouter()
const session = useSession()
const username = ref('')
const password = ref('')
const loading = ref(false)
const errorMessage = ref('')

async function submit() {
  loading.value = true
  errorMessage.value = ''
  try {
    const payload = await post<AuthPayload>('/auth/login', {
      username: username.value,
      password: password.value,
    })
    saveAuth(payload)
    session.setUser(payload.user)
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/workspace'
    await router.push(redirect)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登录失败。'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <AppShell
    kicker="账号登录"
    title="登录 OpsPilot-X"
    subtitle="登录后即可查看企业体检、行业风险、研报核验和证据详情。"
  >
    <section class="auth-grid">
      <article class="panel auth-panel">
        <div class="panel-header">
          <div>
            <div class="eyebrow">登录</div>
            <h3>进入对话分析台</h3>
          </div>
        </div>
        <label class="field">
          <span>用户名</span>
          <input v-model="username" class="text-input" type="text" autocomplete="username" />
        </label>
        <label class="field">
          <span>密码</span>
          <input v-model="password" class="text-input" type="password" autocomplete="current-password" />
        </label>
        <button class="button-primary auth-submit" :disabled="loading" @click="submit">登录</button>
        <LoadingState v-if="loading" />
        <ErrorState v-else-if="errorMessage" :message="errorMessage" />
      </article>

      <article class="panel auth-aside">
        <div class="eyebrow">没有账号</div>
        <h3>先完成注册</h3>
        <p class="hero-text">注册后选择使用身份，即可进入对应视角下的分析界面。</p>
        <RouterLink class="button-secondary" to="/register">去注册</RouterLink>
      </article>
    </section>
  </AppShell>
</template>
