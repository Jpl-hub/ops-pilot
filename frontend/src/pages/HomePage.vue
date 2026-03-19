<script setup lang="ts">
import AppShell from '@/components/AppShell.vue'
</script>

<template>
  <AppShell
    kicker="OpsPilot-X"
    title="入口"
    subtitle="进入系统"
    compact
  >
    <section class="auth-grid">
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
            <strong>真实财报 / 真实研报 / 页级证据</strong>
          </div>
          <div class="detail-row">
            <span>进入后主链</span>
            <strong>工作台 → 体检 / 风险 / 核验 / 证据</strong>
          </div>
        </div>
        <div class="hero-actions">
          <RouterLink class="button-primary" to="/login">登录</RouterLink>
          <RouterLink class="button-secondary" to="/register">注册</RouterLink>
        </div>
      </article>

      <article class="panel auth-aside">
        <div class="eyebrow">系统能力</div>
        <div class="company-grid">
          <div class="company-card">
            <div class="signal-code">AGENT</div>
            <h4>任务编排</h4>
          </div>
          <div class="company-card">
            <div class="signal-code">MM</div>
            <h4>多模态解析</h4>
          </div>
          <div class="company-card">
            <div class="signal-code">DATA</div>
            <h4>真实数据链</h4>
          </div>
        </div>
      </article>
    </section>
  </AppShell>
</template>
