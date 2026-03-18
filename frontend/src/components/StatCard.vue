<script setup lang="ts">
defineProps<{
  label: string
  value: string
  hint?: string
  tone?: 'default' | 'accent' | 'danger' | 'success'
}>()
</script>

<template>
  <section class="stat-card" :class="tone ? `is-${tone}` : ''">
    <div class="stat-label">{{ label }}</div>
    <div class="stat-value">{{ value }}</div>
    <div v-if="hint" class="stat-hint">{{ hint }}</div>
  </section>
</template>
