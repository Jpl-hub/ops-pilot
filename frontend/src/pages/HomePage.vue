<script setup lang="ts">
import AppShell from '@/components/AppShell.vue'
</script>

<template>
  <AppShell
    kicker="OpsPilot-X"
    title="入口"
    subtitle="登录后进入工作台"
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
        <div class="eyebrow">进入系统后</div>
        <div class="timeline-list">
          <div class="timeline-item">
            <strong>对话分析台</strong>
            <span>围绕一个问题统一调度分析、核验和取证。</span>
          </div>
          <div class="timeline-item">
            <strong>企业体检</strong>
            <span>查看经营质量、公式回放和建议动作。</span>
          </div>
          <div class="timeline-item">
            <strong>研报核验</strong>
            <span>对照真实财报核查评级、目标价和研究观点。</span>
          </div>
        </div>
      </article>
    </section>
  </AppShell>
</template>
