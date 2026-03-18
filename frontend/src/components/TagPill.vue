<script setup lang="ts">
defineProps<{
  label: string
  tone?: 'default' | 'risk' | 'success'
}>()
</script>

<template>
  <span class="tag-pill" :class="tone ? `is-${tone}` : ''">{{ label }}</span>
</template>
