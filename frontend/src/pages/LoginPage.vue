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
    kicker="认证入口"
    title="登录 OpsPilot-X"
    subtitle="使用正式账号进入工作台。登录后才开放企业体检、行业风险、研报核验与系统管理。"
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
        <div class="eyebrow">尚未注册</div>
        <h3>先创建角色账号</h3>
        <p class="hero-text">
          注册时需要选择使用角色，系统会把你的入口文案和默认分析视角收敛到对应业务场景。
        </p>
        <RouterLink class="button-secondary" to="/register">去注册</RouterLink>
      </article>
    </section>
  </AppShell>
</template>
