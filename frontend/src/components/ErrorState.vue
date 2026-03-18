<script setup lang="ts">
defineProps<{
  message: string
}>()
</script>

<template>
  <div class="panel error-state">
    <div class="error-badge">失败</div>
    <div class="error-message">{{ message }}</div>
  </div>
</template>
