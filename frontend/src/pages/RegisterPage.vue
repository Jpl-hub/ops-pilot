<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import AppShell from '@/components/AppShell.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingState from '@/components/LoadingState.vue'
import { post, saveAuth, type AuthPayload } from '@/lib/api'
import { useSession } from '@/lib/session'

const router = useRouter()
const session = useSession()
const username = ref('')
const displayName = ref('')
const password = ref('')
const loading = ref(false)
const errorMessage = ref('')

async function submit() {
  loading.value = true
  errorMessage.value = ''
  try {
    const payload = await post<AuthPayload>('/auth/register', {
      username: username.value,
      display_name: displayName.value,
      password: password.value,
    })
    saveAuth(payload)
    session.setUser(payload.user)
    await router.push('/workspace')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '注册失败。'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <AppShell
    kicker="账号注册"
    title="创建 OpsPilot-X 账号"
    subtitle="先完成注册，进入系统后再切换分析视角。"
  >
    <section class="auth-grid">
      <article class="panel auth-panel">
        <div class="panel-header">
          <div>
            <div class="eyebrow">注册</div>
            <h3>创建账号</h3>
          </div>
        </div>
        <label class="field">
          <span>用户名</span>
          <input v-model="username" class="text-input" type="text" autocomplete="username" />
        </label>
        <label class="field">
          <span>显示名</span>
          <input v-model="displayName" class="text-input" type="text" autocomplete="name" />
        </label>
        <label class="field">
          <span>密码</span>
          <input v-model="password" class="text-input" type="password" autocomplete="new-password" />
        </label>
        <button class="button-primary auth-submit" :disabled="loading" @click="submit">注册并进入</button>
        <LoadingState v-if="loading" />
        <ErrorState v-else-if="errorMessage" :message="errorMessage" />
      </article>

      <article class="panel auth-aside">
        <div class="eyebrow">已有账号</div>
        <h3>直接登录</h3>
        <p class="hero-text">如果你已经注册过账号，直接登录即可继续使用。</p>
        <RouterLink class="button-secondary" to="/login">去登录</RouterLink>
      </article>
    </section>
  </AppShell>
</template>
