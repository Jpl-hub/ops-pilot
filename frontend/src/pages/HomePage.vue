<script setup lang="ts">
import AppShell from '@/components/AppShell.vue'
import { computed, onMounted } from 'vue'

import LoadingState from '@/components/LoadingState.vue'
import { useAsyncState } from '@/composables/useAsyncState'
import { get } from '@/lib/api'

const overviewState = useAsyncState<any>()

const homeMetrics = computed(() => {
  const data = overviewState.data.value
  return {
    companies: data?.quality_overview?.coverage?.pool_companies ?? null,
    reports: data?.data_status?.periodic_reports?.record_count ?? null,
    dimensions: 19,
  }
})

onMounted(async () => {
  await overviewState.execute(() => get('/admin/overview'))
})
</script>

<template>
  <AppShell
    kicker="OpsPilot-X"
    title="新能源运营分析平台"
    subtitle="系统概览"
    compact
  >
    <div class="home-wrapper">
      <LoadingState v-if="overviewState.loading.value" class="home-loading" />

      <!-- Hero Card -->
      <section v-else class="glass-panel splash-card">
        <div class="splash-inner">
          <div class="glow-icon-splash">OP</div>

          <div class="splash-header">
            <div class="eyebrow splash-eyebrow">2026 全国大学生计算机设计大赛 · 大数据主题</div>
            <h1 class="splash-title text-gradient">新能源企业运营分析与决策支持系统</h1>
            <p class="splash-subtitle muted">OpsPilot-X · Multi-Agent × Hybrid RAG × 19-Indicator Scoring Engine</p>
          </div>

          <!-- Stats Row -->
          <div class="stats-row">
            <div class="stat-item">
              <strong class="stat-val text-accent">{{ homeMetrics.companies ?? '—' }}</strong>
              <span class="stat-lbl">新能源企业</span>
            </div>
            <div class="stat-div"></div>
            <div class="stat-item">
              <strong class="stat-val">{{ homeMetrics.reports ?? '—' }}</strong>
              <span class="stat-lbl">真实财报</span>
            </div>
            <div class="stat-div"></div>
            <div class="stat-item">
              <strong class="stat-val">{{ homeMetrics.dimensions }}</strong>
              <span class="stat-lbl">评分维度</span>
            </div>
            <div class="stat-div"></div>
            <div class="stat-item">
              <strong class="stat-val text-gradient">Hybrid RAG</strong>
              <span class="stat-lbl">BM25 + pgvector</span>
            </div>
          </div>

          <!-- Feature Grid -->
          <div class="feature-grid">
            <RouterLink class="feature-card glass-panel-hover" to="/workspace">
              <div class="fc-icon fc-icon-blue">智</div>
              <div class="fc-body">
                <h4 class="fc-title">协同分析</h4>
                <p class="fc-desc">多角色 Agent 编排 · Tool Calling · 实时溯源</p>
              </div>
            </RouterLink>
            <RouterLink class="feature-card glass-panel-hover" to="/score">
              <div class="fc-icon fc-icon-green">评</div>
              <div class="fc-body">
                <h4 class="fc-title">企业体检</h4>
                <p class="fc-desc">19 指标评分 · A-D 等级 · 行业分位</p>
              </div>
            </RouterLink>
            <RouterLink class="feature-card glass-panel-hover" to="/risk">
              <div class="fc-icon fc-icon-red">警</div>
              <div class="fc-body">
                <h4 class="fc-title">风险预警</h4>
                <p class="fc-desc">全量风险扫描 · 新增风险追踪 · 行业研报</p>
              </div>
            </RouterLink>
            <RouterLink class="feature-card glass-panel-hover" to="/brain">
              <div class="fc-icon fc-icon-purple">脑</div>
              <div class="fc-body">
                <h4 class="fc-title">产业大脑</h4>
                <p class="fc-desc">行业洞察 · 政策解读 · 竞争格局</p>
              </div>
            </RouterLink>
            <RouterLink class="feature-card glass-panel-hover" to="/graph">
              <div class="fc-icon fc-icon-indigo">图</div>
              <div class="fc-body">
                <h4 class="fc-title">图谱检索</h4>
                <p class="fc-desc">关联实体图谱 · 页级证据溯源</p>
              </div>
            </RouterLink>
            <RouterLink class="feature-card glass-panel-hover" to="/verify">
              <div class="fc-icon fc-icon-amber">验</div>
              <div class="fc-body">
                <h4 class="fc-title">研报核验</h4>
                <p class="fc-desc">Claim 核实 · 事实对比 · 可信度评分</p>
              </div>
            </RouterLink>
          </div>

          <div class="hero-actions">
            <RouterLink class="button-primary glow-button splash-btn" to="/workspace">
              进入协同分析
              <svg class="btn-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 5l7 7m0 0l-7 7m7-7H3"/></svg>
            </RouterLink>
            <RouterLink class="button-secondary splash-btn-sec" to="/brain">
              产业大脑
            </RouterLink>
          </div>
        </div>
      </section>
    </div>
  </AppShell>
</template>

<style scoped>
.home-wrapper {
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 8px 0 24px;
  height: 100%;
  overflow-y: auto;
}
.home-loading { width: 100%; max-width: 780px; min-height: 420px; }
.home-wrapper::-webkit-scrollbar { width: 4px; }
.home-wrapper::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 2px; }

.splash-card {
  max-width: 780px;
  width: 100%;
  padding: 0;
  border-radius: 24px;
  overflow: hidden;
}

.splash-inner {
  padding: 40px;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 28px;
  position: relative;
}

.splash-inner::before {
  content: '';
  position: absolute;
  top: -80px;
  left: 50%;
  transform: translateX(-50%);
  width: 400px;
  height: 300px;
  background: radial-gradient(circle, rgba(16,185,129,0.12) 0%, transparent 70%);
  pointer-events: none;
}

.glow-icon-splash {
  width: 72px;
  height: 72px;
  border-radius: 18px;
  background: rgba(16, 185, 129, 0.1);
  border: 1px solid rgba(16, 185, 129, 0.3);
  display: grid;
  place-items: center;
  box-shadow: 0 0 30px rgba(16, 185, 129, 0.2);
  color: #10b981;
  font-size: 28px;
  font-weight: 700;
  flex-shrink: 0;
}

.splash-eyebrow {
  display: inline-block;
  padding: 4px 12px;
  border-radius: 4px;
  background: rgba(59, 130, 246, 0.1);
  color: #60a5fa;
  border: 1px solid rgba(59, 130, 246, 0.2);
  font-size: 12px;
  margin-bottom: 12px;
  font-family: 'JetBrains Mono', monospace;
}

.splash-title {
  font-size: 28px;
  font-weight: 700;
  margin: 0 0 8px;
  letter-spacing: -0.02em;
  line-height: 1.3;
}

.text-gradient {
  background-clip: text;
  -webkit-text-fill-color: transparent;
  background-image: linear-gradient(to right, #60a5fa, #34d399);
}

.text-accent { color: #10b981; }

.muted { color: #94a3b8; }
.splash-subtitle {
  font-size: 13px;
  margin: 0;
  font-family: 'JetBrains Mono', monospace;
}

/* Stats */
.stats-row {
  display: flex;
  gap: 0;
  justify-content: center;
  background: rgba(0,0,0,0.2);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 14px;
  width: 100%;
  padding: 0;
  overflow: hidden;
}

.stat-item {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 16px 12px;
}

.stat-val {
  font-size: 22px;
  font-weight: 700;
  line-height: 1;
  color: #fff;
}

.stat-lbl {
  font-size: 11px;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  font-family: 'JetBrains Mono', monospace;
}

.stat-div {
  width: 1px;
  background: rgba(255,255,255,0.07);
  align-self: stretch;
  flex-shrink: 0;
}

/* Feature Grid */
.feature-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  width: 100%;
}

.feature-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  border-radius: 14px;
  border: 1px solid rgba(255,255,255,0.05);
  text-decoration: none;
  background: rgba(255,255,255,0.02);
  transition: all 0.2s;
  text-align: left;
}

.feature-card:hover {
  border-color: rgba(16,185,129,0.3);
  background: rgba(16,185,129,0.05);
  transform: translateY(-1px);
}

.fc-icon {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  font-weight: 700;
  font-size: 15px;
  flex-shrink: 0;
}

.fc-icon-blue { background: rgba(59,130,246,0.15); color: #60a5fa; border: 1px solid rgba(59,130,246,0.25); }
.fc-icon-green { background: rgba(16,185,129,0.15); color: #10b981; border: 1px solid rgba(16,185,129,0.25); }
.fc-icon-red { background: rgba(244,63,94,0.15); color: #f43f5e; border: 1px solid rgba(244,63,94,0.25); }
.fc-icon-purple { background: rgba(168,85,247,0.15); color: #a855f7; border: 1px solid rgba(168,85,247,0.25); }
.fc-icon-indigo { background: rgba(129,140,248,0.15); color: #818cf8; border: 1px solid rgba(129,140,248,0.25); }
.fc-icon-amber { background: rgba(245,158,11,0.15); color: #f59e0b; border: 1px solid rgba(245,158,11,0.25); }

.fc-body { min-width: 0; }
.fc-title { margin: 0 0 4px; font-size: 14px; font-weight: 600; color: #fff; }
.fc-desc { margin: 0; font-size: 11px; color: var(--muted); line-height: 1.5; font-family: 'JetBrains Mono', monospace; }

/* Actions */
.hero-actions {
  display: flex;
  gap: 12px;
  width: 100%;
}

.glow-button {
  transition: all 0.2s ease;
  box-shadow: 0 0 20px rgba(16, 185, 129, 0.2);
}
.glow-button:hover {
  transform: translateY(-2px);
  box-shadow: 0 0 30px rgba(16, 185, 129, 0.4);
}

.splash-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 14px;
  font-size: 15px;
  font-weight: 500;
  border-radius: 12px;
  text-decoration: none;
}

.splash-btn-sec {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 14px 24px;
  font-size: 15px;
  border-radius: 12px;
  text-decoration: none;
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.1);
  color: #94a3b8;
  transition: all 0.2s;
}
.splash-btn-sec:hover {
  background: rgba(255,255,255,0.08);
  color: #fff;
}

.btn-icon { width: 18px; height: 18px; margin-left: 8px; }

.splash-header { width: 100%; }
</style>
