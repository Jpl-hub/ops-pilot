<script setup lang="ts">
import { computed } from 'vue'

import AppShell from '@/components/AppShell.vue'
import { useSession } from '@/lib/session'
import type { UserRole } from '@/lib/api'

type ScenarioCard = {
  role: UserRole
  roleLabel: string
  title: string
  prompt: string
  cue: string
  detail: string
}

const session = useSession()

function buildScenarioRoute(role: UserRole, prompt: string) {
  return {
    path: '/workspace',
    query: {
      role,
      prompt,
      auto_run: '1',
    },
  }
}

const entryAction = computed(() => {
  if (session.isAuthenticated.value) {
    return {
      label: '进入分析台',
      to: '/workspace',
    }
  }
  return {
    label: '登录后开始',
    to: '/login',
  }
})

const scenarioCards: ScenarioCard[] = [
  {
    role: 'investor',
    roleLabel: '投资者',
    title: '看风险和分歧',
    prompt: '这家公司当前最值得警惕的风险是什么？',
    cue: '先看风险，再决定是否继续跟',
    detail: '围绕企业、财报和证据链快速形成一轮投资判断。',
  },
  {
    role: 'management',
    roleLabel: '管理层',
    title: '做经营诊断',
    prompt: '给我一份当前经营体检和整改优先级。',
    cue: '直接形成一轮经营判断',
    detail: '把经营问题、优先动作和证据线索收进同一个工作面。',
  },
  {
    role: 'regulator',
    roleLabel: '监管 / 风控',
    title: '做持续巡检',
    prompt: '当前主周期哪些公司风险抬升最快？',
    cue: '盯变化，不盯花哨指标',
    detail: '沿着行业异动、风险标签和原文证据持续巡检。',
  },
]

const productSurfaces = [
  '产业大脑',
  '协同分析',
  '图谱检索',
  '压力推演',
  '经营诊断',
  '观点核验',
  '文档复核',
]
</script>

<template>
  <AppShell title="">
    <div class="landing">
      <section class="landing-hero">
        <div class="landing-copy">
          <span class="landing-kicker">新能源企业决策工作台</span>
          <h1>OpsPilot-X</h1>
          <p>把行业变化、企业判断和原文证据收进同一个工作面。</p>

          <div class="landing-actions">
            <RouterLink class="button-primary landing-primary" :to="entryAction.to">
              {{ entryAction.label }}
            </RouterLink>
            <RouterLink class="button-secondary landing-secondary" to="/brain">
              先看产业大脑
            </RouterLink>
          </div>

          <div class="landing-surface-rail">
            <span v-for="item in productSurfaces" :key="item">{{ item }}</span>
          </div>
        </div>

        <div class="landing-stage" aria-hidden="true">
          <div class="stage-column">
            <div class="stage-frame stage-frame-lead">
              <span>行业变化</span>
              <strong>先抓真正值得追的主线</strong>
              <p>实时信号、公司异动、政策变化先在这里收束。</p>
            </div>

            <div class="stage-frame">
              <span>企业判断</span>
              <strong>再把结论和动作压成一页</strong>
              <p>不是聊天记录，而是一轮可以直接执行的判断。</p>
            </div>

            <div class="stage-frame">
              <span>原文证据</span>
              <strong>最后回到财报、研报和图谱</strong>
              <p>所有关键判断都能继续追到页码、链路和原文。</p>
            </div>
          </div>

          <div class="stage-tail">
            <span>正式数据</span>
            <span>协同判断</span>
            <span>证据回放</span>
          </div>
        </div>
      </section>

      <section class="landing-dock">
        <RouterLink
          v-for="item in scenarioCards"
          :key="item.role"
          class="dock-strip"
          :class="`is-${item.role}`"
          :to="buildScenarioRoute(item.role, item.prompt)"
        >
          <div class="dock-copy">
            <span>{{ item.roleLabel }}</span>
            <strong>{{ item.title }}</strong>
            <small>{{ item.detail }}</small>
          </div>
          <em>进入</em>
        </RouterLink>
      </section>
    </div>
  </AppShell>
</template>

<style scoped>
.landing {
  min-height: calc(100vh - 56px);
  margin: -16px -24px -24px;
  padding: 0;
  display: grid;
  grid-template-rows: minmax(0, 1fr) auto;
  background:
    radial-gradient(circle at top left, rgba(16, 185, 129, 0.08), transparent 28%),
    radial-gradient(circle at 85% 18%, rgba(59, 130, 246, 0.1), transparent 24%),
    linear-gradient(180deg, rgba(7, 10, 18, 0.98), rgba(7, 10, 18, 0.94));
}

.landing-hero {
  display: grid;
  grid-template-columns: minmax(0, 0.92fr) minmax(460px, 1.08fr);
  align-items: center;
  min-height: 0;
}

.landing-copy,
.landing-stage {
  min-width: 0;
}

.landing-copy {
  display: grid;
  align-content: center;
  gap: 20px;
  padding: 54px 56px;
}

.landing-kicker,
.stage-core span,
.stage-node span,
.dock-strip span {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: rgba(148, 163, 184, 0.82);
}

.landing-copy h1,
.stage-core strong,
.stage-node strong,
.dock-strip strong {
  margin: 0;
  letter-spacing: -0.05em;
  color: #f8fafc;
}

.landing-copy h1 {
  font-size: clamp(42px, 5vw, 72px);
  line-height: 0.94;
  max-width: 520px;
}

.landing-copy p {
  margin: 0;
  color: rgba(203, 213, 225, 0.78);
  font-size: 16px;
  line-height: 1.7;
  max-width: 320px;
}

.landing-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.landing-primary {
  min-width: 156px;
}

.landing-secondary {
  min-width: 156px;
}

.landing-surface-rail {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.landing-surface-rail span,
.stage-tail span {
  min-height: 34px;
  padding: 0 12px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: rgba(203, 213, 225, 0.86);
  font-size: 12px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.025);
}

.landing-stage {
  position: relative;
  min-height: 100%;
  overflow: hidden;
  display: grid;
  place-items: center;
}

.landing-stage::before,
.landing-stage::after {
  content: '';
  position: absolute;
  inset: auto;
}

.landing-stage::before {
  inset: 14% 11% 18% 18%;
  border-radius: 34px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background:
    linear-gradient(180deg, rgba(12, 16, 24, 0.98), rgba(8, 12, 18, 0.94));
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
}

.landing-stage::after {
  inset: 22% 18% 22% 24%;
  border-radius: 30px;
  background: radial-gradient(circle at 16% 14%, rgba(16, 185, 129, 0.16), transparent 28%);
  opacity: 0.84;
}

.stage-column,
.stage-tail {
  position: relative;
  z-index: 1;
}

.stage-column {
  width: min(78%, 520px);
  display: grid;
  gap: 14px;
}

.stage-frame {
  display: grid;
  gap: 8px;
  padding: 18px 20px;
  border-radius: 22px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(12, 16, 24, 0.82);
  backdrop-filter: blur(14px);
}

.stage-frame-lead {
  background:
    linear-gradient(180deg, rgba(10, 33, 27, 0.92), rgba(12, 16, 24, 0.86));
  border-color: rgba(52, 211, 153, 0.16);
}

.stage-frame strong {
  font-size: 21px;
  line-height: 1.08;
}

.stage-frame p {
  margin: 0;
  color: rgba(203, 213, 225, 0.78);
  line-height: 1.7;
  font-size: 13px;
}

.stage-tail {
  position: absolute;
  left: 18%;
  right: 14%;
  bottom: 14%;
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.landing-dock {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  padding: 0 24px 24px;
}

.dock-strip,
.dock-module {
  text-decoration: none;
}

.dock-strip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  min-height: 102px;
  padding: 0 20px;
  border-radius: 24px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.024);
}

.dock-copy {
  display: grid;
  gap: 6px;
}

.dock-copy small {
  color: rgba(148, 163, 184, 0.84);
  font-size: 13px;
  line-height: 1.65;
}

.dock-strip.is-investor {
  background: rgba(59, 130, 246, 0.06);
}

.dock-strip.is-management {
  background: rgba(16, 185, 129, 0.06);
}

.dock-strip.is-regulator {
  background: rgba(245, 158, 11, 0.06);
}

.dock-strip em {
  min-width: 54px;
  min-height: 54px;
  border-radius: 999px;
  display: grid;
  place-items: center;
  font-style: normal;
  color: #f8fafc;
  background: rgba(255, 255, 255, 0.06);
}

@media (max-width: 1260px) {
  .landing-hero {
    grid-template-columns: 1fr;
  }

  .landing-stage {
    min-height: 460px;
    border-top: 1px solid rgba(255, 255, 255, 0.05);
  }

  .landing-dock {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .landing-copy {
    padding: 28px 18px;
  }

  .landing-copy h1 {
    font-size: clamp(32px, 14vw, 50px);
  }

  .landing-stage {
    min-height: 400px;
  }

  .stage-column {
    width: calc(100% - 36px);
  }

  .stage-tail {
    left: 18px;
    right: 18px;
    bottom: 18px;
  }

  .landing-dock {
    padding: 0 16px 16px;
  }
}
</style>
