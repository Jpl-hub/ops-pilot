<script setup lang="ts">
import { RouterLink } from 'vue-router'
import AppShell from '@/components/AppShell.vue'
</script>

<template>
  <AppShell title="" compact>
    <div class="nf-wrapper">
      <div class="nf-card glass-panel">
        <div class="nf-code">404</div>
        <h1 class="nf-title text-gradient">页面未找到</h1>
        <p class="nf-desc muted">您访问的路径不存在，请返回主页或选择功能模块。</p>
        <div class="nf-actions">
          <RouterLink class="button-primary nf-btn" to="/workspace">进入协同分析</RouterLink>
          <RouterLink class="nf-btn-sec" to="/">返回主页</RouterLink>
        </div>
        <div class="nf-grid">
          <RouterLink class="nf-link glass-panel-hover" to="/score">企业体检</RouterLink>
          <RouterLink class="nf-link glass-panel-hover" to="/risk">风险预警</RouterLink>
          <RouterLink class="nf-link glass-panel-hover" to="/brain">产业大脑</RouterLink>
          <RouterLink class="nf-link glass-panel-hover" to="/verify">研报核验</RouterLink>
        </div>
      </div>
    </div>
  </AppShell>
</template>

<style scoped>
.nf-wrapper {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  padding: 24px;
}

.nf-card {
  max-width: 480px;
  width: 100%;
  padding: 48px 40px;
  border-radius: 24px;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 20px;
}

.nf-code {
  font-size: 72px;
  font-weight: 800;
  line-height: 1;
  background: linear-gradient(to right, #60a5fa, #34d399);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  font-family: 'JetBrains Mono', monospace;
}

.nf-title {
  font-size: 24px;
  font-weight: 700;
  margin: 0;
}

.text-gradient {
  background-clip: text;
  -webkit-text-fill-color: transparent;
  background-image: linear-gradient(to right, #60a5fa, #34d399);
}

.nf-desc {
  font-size: 14px;
  margin: 0;
  line-height: 1.6;
}
.muted { color: var(--muted); }

.nf-actions {
  display: flex;
  gap: 12px;
  width: 100%;
}

.nf-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 12px;
  font-size: 14px;
  font-weight: 500;
  border-radius: 10px;
  text-decoration: none;
}

.nf-btn-sec {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 12px 20px;
  font-size: 14px;
  border-radius: 10px;
  text-decoration: none;
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.1);
  color: #94a3b8;
  transition: all 0.2s;
  white-space: nowrap;
}
.nf-btn-sec:hover { background: rgba(255,255,255,0.08); color: #fff; }

.nf-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
  width: 100%;
}

.nf-link {
  padding: 10px;
  border-radius: 10px;
  border: 1px solid rgba(255,255,255,0.06);
  text-decoration: none;
  font-size: 13px;
  color: #94a3b8;
  transition: all 0.2s;
  text-align: center;
}
.nf-link:hover { color: #fff; border-color: rgba(16,185,129,0.3); background: rgba(16,185,129,0.05); }
</style>
