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
    <div class="home-wrapper">
      <section class="glass-panel splash-card">
        <div class="glow-icon-splash">
          OP
        </div>
        
        <div class="splash-header">
          <div class="eyebrow splash-eyebrow">系统入口</div>
          <h1 class="splash-title text-gradient">新能源运营决策系统</h1>
          <p class="splash-subtitle muted">OpsPilot-X · 多智能体协同分析平台</p>
        </div>

        <div class="splash-details">
          <div class="detail-block">
            <span class="db-lbl">分析对象</span>
            <strong class="db-val">新能源企业</strong>
          </div>
          <div class="db-div"></div>
          <div class="detail-block">
            <span class="db-lbl">数据来源</span>
            <strong class="db-val">真实财报 / 事件池 / 页级证据</strong>
          </div>
        </div>

        <div class="hero-actions w-full">
          <RouterLink class="button-primary glow-button splash-btn" to="/workspace">
            直接进入决策会议室
            <svg class="btn-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 5l7 7m0 0l-7 7m7-7H3"></path></svg>
          </RouterLink>
        </div>
      </section>
    </div>
  </AppShell>
</template>

<style scoped>
.home-wrapper {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 70vh;
  padding: 40px 20px;
}

.splash-card {
  max-width: 640px;
  width: 100%;
  padding: 60px 40px;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  position: relative;
  overflow: hidden;
  background: rgba(15, 23, 42, 0.4); 
  backdrop-filter: blur(12px); 
  border: 1px solid rgba(255, 255, 255, 0.05); 
  border-radius: 24px; 
  box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.7);
}

/* Background ambient glow inside card */
.splash-card::before {
  content: '';
  position: absolute;
  top: -100px;
  left: 50%;
  transform: translateX(-50%);
  width: 300px;
  height: 300px;
  background: radial-gradient(circle, rgba(16,185,129,0.15) 0%, transparent 70%);
  pointer-events: none;
}

.glow-icon-splash {
  width: 80px;
  height: 80px;
  border-radius: 20px;
  background: rgba(16, 185, 129, 0.1);
  border: 1px solid rgba(16, 185, 129, 0.3);
  display: grid;
  place-items: center;
  box-shadow: 0 0 30px rgba(16, 185, 129, 0.2);
  margin-bottom: 32px;
  color: #10b981;
  font-size: 32px;
  font-weight: bold;
}

.splash-header {
  margin-bottom: 32px;
}

.splash-eyebrow {
  display: inline-block;
  padding: 4px 12px;
  border-radius: 4px;
  background: rgba(59, 130, 246, 0.1);
  color: #60a5fa;
  border: 1px solid rgba(59, 130, 246, 0.2);
  font-size: 12px;
  margin-bottom: 16px;
}

.splash-title {
  font-size: 36px;
  font-weight: 700;
  margin: 0 0 8px;
  letter-spacing: -0.02em;
}

.text-gradient {
  background-clip: text;
  -webkit-text-fill-color: transparent;
  background-image: linear-gradient(to right, #60a5fa, #34d399);
}

.muted { color: #94a3b8; }
.splash-subtitle {
  font-size: 16px;
  margin: 0;
}

.splash-details {
  display: flex;
  gap: 32px;
  justify-content: center;
  margin-bottom: 48px;
}

.detail-block {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.db-lbl {
  color: var(--muted);
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
}

.db-val {
  font-size: 18px;
  color: #fff;
  font-weight: 500;
}

.db-div {
  width: 1px;
  background-color: rgba(255, 255, 255, 0.1);
}

.hero-actions { width: 100%; }

.splash-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  padding: 16px;
  font-size: 16px;
  font-weight: 500;
  border-radius: 12px;
}
.btn-icon { width: 20px; height: 20px; margin-left: 8px; }

.glow-button {
  transition: all 0.2s ease;
  box-shadow: 0 0 20px rgba(59, 130, 246, 0.2);
}
.glow-button:hover {
  transform: translateY(-2px);
  box-shadow: 0 0 30px rgba(59, 130, 246, 0.4);
}
</style>
