<script setup lang="ts">
import { computed, onMounted } from 'vue'

import AppShell from '@/components/AppShell.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingState from '@/components/LoadingState.vue'
import { useAsyncState } from '@/composables/useAsyncState'
import { get, type UserRole } from '@/lib/api'
import { useSession } from '@/lib/session'

const session = useSession()
type ProfileSummary = {
  me: {
    username: string
    display_name: string
    role: UserRole
    created_at: string
    last_login_at: string | null
  }
  health: {
    status: string
    env: string
    preferred_period: string | null
    preferred_period_companies: number
  }
  companies: {
    companies: string[]
    preferred_period: string | null
    available_periods: string[]
  }
  dataStatus: {
    periodic_reports: { record_count: number; company_count: number; generated_at: string | null }
    bronze_periodic_reports: { record_count: number; company_count: number; generated_at: string | null }
    silver_financial_metrics: { record_count: number; company_count: number; generated_at: string | null }
  }
}

const state = useAsyncState<ProfileSummary>()

const roleCards: Array<{ value: UserRole; label: string; summary: string }> = [
  { value: 'investor', label: '投资视角', summary: '关注收益质量、同业位置和预期偏差。' },
  { value: 'management', label: '经营视角', summary: '关注经营瓶颈、现金压力和整改动作。' },
  { value: 'regulator', label: '风控视角', summary: '关注风险暴露、异常信号和批量巡检。' },
]

onMounted(() => {
  void state.execute(async () => {
    const [me, health, companies, dataStatus] = await Promise.all([
      get<ProfileSummary['me']>('/auth/me'),
      get<ProfileSummary['health']>('/healthz'),
      get<ProfileSummary['companies']>('/workspace/companies'),
      get<ProfileSummary['dataStatus']>('/admin/official-data/status'),
    ])
    return { me, health, companies, dataStatus }
  })
})

const activeRoleLabel = computed(() => {
  return roleCards.find((item) => item.value === session.activeRole.value)?.label || session.activeRole.value
})

function displayRole(role: UserRole | string | null | undefined): string {
  if (!role) {
    return '-'
  }
  return roleCards.find((item) => item.value === role)?.label || role
}

function displayHealthStatus(status: string | null | undefined): string {
  const map: Record<string, string> = {
    ok: '正常',
    ready: '就绪',
    blocked: '阻断',
    degraded: '降级',
  }
  return map[status || ''] || status || '-'
}

function formatTime(value: string | null | undefined): string {
  if (!value) {
    return '未记录'
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}
</script>

<template>
  <AppShell title="账户与偏好" subtitle="账户控制台" compact>
    <LoadingState v-if="state.loading.value" class="state-shell" />
    <ErrorState v-else-if="state.error.value" :message="state.error.value" class="state-shell" />

    <section v-else-if="state.data.value" class="profile-layout">
      <article class="panel profile-hero">
        <div class="profile-identity">
          <div class="profile-avatar">{{ state.data.value.me.display_name.slice(0, 1) }}</div>
          <div class="profile-copy">
            <div class="signal-code">当前账户</div>
            <h2>{{ state.data.value.me.display_name }}</h2>
            <p>{{ state.data.value.me.username }}</p>
          </div>
        </div>
        <div class="profile-metrics">
          <div class="metric-card">
            <span>当前角色</span>
            <strong>{{ activeRoleLabel }}</strong>
            <small>侧边栏切换后即刻生效</small>
          </div>
          <div class="metric-card">
            <span>主评估周期</span>
            <strong>{{ state.data.value.health.preferred_period || '-' }}</strong>
            <small>{{ state.data.value.health.preferred_period_companies }} 家公司可评估</small>
          </div>
          <div class="metric-card">
            <span>系统环境</span>
            <strong>{{ state.data.value.health.env }}</strong>
            <small>{{ displayHealthStatus(state.data.value.health.status) }}</small>
          </div>
        </div>
      </article>

      <div class="profile-grid">
        <article class="panel profile-section">
          <div class="panel-head">
            <div>
              <div class="eyebrow">角色切换</div>
              <h3>角色工作面</h3>
            </div>
          </div>
          <div class="role-card-list">
            <button
              v-for="item in roleCards"
              :key="item.value"
              type="button"
              class="role-card"
              :class="{ active: session.activeRole.value === item.value }"
              @click="session.setActiveRole(item.value)"
            >
              <strong>{{ item.label }}</strong>
              <span>{{ item.summary }}</span>
            </button>
          </div>
        </article>

        <article class="panel profile-section">
          <div class="panel-head">
            <div>
              <div class="eyebrow">账户信息</div>
              <h3>账户元数据</h3>
            </div>
          </div>
          <div class="meta-list">
            <div class="meta-row">
              <span>注册角色</span>
              <strong>{{ displayRole(state.data.value.me.role) }}</strong>
            </div>
            <div class="meta-row">
              <span>创建时间</span>
              <strong>{{ formatTime(state.data.value.me.created_at) }}</strong>
            </div>
            <div class="meta-row">
              <span>最近登录</span>
              <strong>{{ formatTime(state.data.value.me.last_login_at) }}</strong>
            </div>
          </div>
        </article>

        <article class="panel profile-section">
          <div class="panel-head">
            <div>
              <div class="eyebrow">覆盖快照</div>
              <h3>数据接入快照</h3>
            </div>
          </div>
          <div class="stats-grid">
            <div class="stat-tile">
              <span>公司池</span>
              <strong>{{ state.data.value.companies.companies.length }}</strong>
              <small>当前可选择企业总数</small>
            </div>
            <div class="stat-tile">
              <span>定期报告</span>
              <strong>{{ state.data.value.dataStatus.periodic_reports.record_count }}</strong>
              <small>{{ state.data.value.dataStatus.periodic_reports.company_count }} 家公司</small>
            </div>
            <div class="stat-tile">
              <span>页级解析</span>
              <strong>{{ state.data.value.dataStatus.bronze_periodic_reports.record_count }}</strong>
              <small>{{ state.data.value.dataStatus.bronze_periodic_reports.company_count }} 家公司</small>
            </div>
            <div class="stat-tile">
              <span>结构化指标</span>
              <strong>{{ state.data.value.dataStatus.silver_financial_metrics.record_count }}</strong>
              <small>{{ state.data.value.dataStatus.silver_financial_metrics.company_count }} 家公司</small>
            </div>
          </div>
        </article>

        <article class="panel profile-section">
          <div class="panel-head">
            <div>
              <div class="eyebrow">运行窗口</div>
              <h3>运行窗口</h3>
            </div>
          </div>
          <div class="meta-list">
            <div class="meta-row">
              <span>可用报期</span>
              <strong>{{ state.data.value.companies.available_periods.join(' / ') || '-' }}</strong>
            </div>
            <div class="meta-row">
              <span>原始数据更新时间</span>
              <strong>{{ formatTime(state.data.value.dataStatus.periodic_reports.generated_at) }}</strong>
            </div>
            <div class="meta-row">
              <span>银层更新时间</span>
              <strong>{{ formatTime(state.data.value.dataStatus.silver_financial_metrics.generated_at) }}</strong>
            </div>
          </div>
        </article>
      </div>
    </section>
  </AppShell>
</template>

<style scoped>
.state-shell {
  min-height: 320px;
}

.profile-layout {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.profile-hero {
  display: grid;
  grid-template-columns: minmax(260px, 1fr) minmax(420px, 1.3fr);
  gap: 20px;
  padding: 24px;
}

.profile-identity {
  display: flex;
  align-items: center;
  gap: 20px;
}

.profile-avatar {
  width: 88px;
  height: 88px;
  border-radius: 24px;
  display: grid;
  place-items: center;
  font-size: 36px;
  font-weight: 700;
  color: #0f172a;
  background: linear-gradient(135deg, #34d399, #93c5fd);
}

.profile-copy h2 {
  margin: 6px 0 4px;
  font-size: 28px;
}

.profile-copy p {
  margin: 0;
  color: var(--muted);
}

.profile-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.metric-card,
.stat-tile,
.role-card,
.meta-row {
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.03);
  border-radius: 16px;
}

.metric-card,
.stat-tile {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.metric-card span,
.stat-tile span,
.meta-row span {
  color: var(--muted);
  font-size: 12px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.metric-card strong,
.stat-tile strong {
  font-size: 24px;
  line-height: 1.1;
}

.metric-card small,
.stat-tile small {
  color: var(--muted);
}

.profile-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 24px;
}

.profile-section {
  padding: 24px;
}

.panel-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.panel-head h3 {
  margin: 4px 0 0;
  font-size: 20px;
}

.role-card-list,
.stats-grid,
.meta-list {
  display: grid;
  gap: 12px;
}

.role-card-list,
.stats-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.role-card {
  padding: 18px;
  text-align: left;
  color: inherit;
  cursor: pointer;
}

.role-card strong {
  display: block;
  margin-bottom: 8px;
  font-size: 16px;
}

.role-card span {
  color: var(--muted);
  line-height: 1.5;
}

.role-card.active {
  border-color: rgba(52, 211, 153, 0.45);
  box-shadow: inset 0 0 0 1px rgba(52, 211, 153, 0.24);
  background: rgba(16, 185, 129, 0.08);
}

.meta-row {
  padding: 16px 18px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.meta-row strong {
  text-align: right;
}

@media (max-width: 1200px) {
  .profile-hero,
  .profile-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .profile-identity {
    flex-direction: column;
    align-items: flex-start;
  }

  .profile-metrics,
  .role-card-list,
  .stats-grid {
    grid-template-columns: 1fr;
  }
}
</style>
