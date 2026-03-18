<script setup lang="ts">
defineProps<{
  title: string
  subtitle: string
  kicker?: string
}>()
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
        <RouterLink to="/">总览</RouterLink>
        <RouterLink to="/score">企业体检</RouterLink>
        <RouterLink to="/risk">行业风险</RouterLink>
        <RouterLink to="/verify">研报核验</RouterLink>
        <RouterLink to="/admin">系统管理</RouterLink>
      </nav>
    </header>
    <slot />
  </div>
</template>
