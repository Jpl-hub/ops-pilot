<script setup lang="ts">
import AppShell from '@/components/AppShell.vue'
</script>

<template>
  <AppShell
    kicker="OpsPilot-X"
    title="决策会议室"
    subtitle="进入系统"
    compact
  >
    <section class="auth-grid" style="grid-template-columns: 1fr; max-width: 600px; margin: 0 auto;">
      <article class="panel auth-panel">
        <div class="panel-header">
          <div>
            <div class="eyebrow">系统入口</div>
            <h3>新能源运营决策系统</h3>
          </div>
        </div>
        <div class="detail-list">
          <div class="detail-row">
            <span>分析对象</span>
            <strong>新能源企业</strong>
          </div>
          <div class="detail-row">
            <span>数据来源</span>
            <strong>真实财报 / 全量事件池 / 页级证据</strong>
          </div>
        </div>
        <div class="hero-actions" style="margin-top: 24px;">
          <RouterLink class="button-primary" to="/workspace" style="width: 100%;">直接进入会议室</RouterLink>
        </div>
      </article>

    </section>
  </AppShell>
</template>
