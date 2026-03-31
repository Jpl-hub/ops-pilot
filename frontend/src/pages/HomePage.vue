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
  },
  {
    role: 'management',
    roleLabel: '管理层',
    title: '做经营诊断',
    prompt: '给我一份当前经营体检和整改优先级。',
    cue: '直接形成一轮经营判断',
  },
  {
    role: 'regulator',
    roleLabel: '监管 / 风控',
    title: '做持续巡检',
    prompt: '当前主周期哪些公司风险抬升最快？',
    cue: '盯变化，不盯花哨指标',
  },
]
</script>

<template>
  <AppShell title="">
    <div class="landing">
      <section class="landing-hero">
        <div class="landing-copy">
          <span class="landing-kicker">新能源产业决策系统</span>
          <h1>OpsPilot-X</h1>
          <p>看企业，做判断。</p>

          <div class="landing-actions">
            <RouterLink class="button-primary landing-primary" :to="entryAction.to">
              {{ entryAction.label }}
            </RouterLink>
          </div>
        </div>

        <div class="landing-stage" aria-hidden="true">
          <div class="stage-core">
            <span>Agent</span>
            <strong>决策中枢</strong>
          </div>

          <div class="stage-node stage-node-investor">
            <span>{{ scenarioCards[0].roleLabel }}</span>
            <strong>{{ scenarioCards[0].title }}</strong>
          </div>
          <div class="stage-node stage-node-management">
            <span>{{ scenarioCards[1].roleLabel }}</span>
            <strong>{{ scenarioCards[1].title }}</strong>
          </div>
          <div class="stage-node stage-node-regulator">
            <span>{{ scenarioCards[2].roleLabel }}</span>
            <strong>{{ scenarioCards[2].title }}</strong>
          </div>

          <div class="stage-footnote">
            <span>实时监测</span>
            <span>图谱溯源</span>
            <span>压力推演</span>
            <span>文档核验</span>
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
            <small>{{ item.cue }}</small>
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
    radial-gradient(circle at right, rgba(59, 130, 246, 0.08), transparent 24%),
    linear-gradient(180deg, rgba(7, 10, 18, 0.98), rgba(7, 10, 18, 0.94));
}

.landing-hero {
  display: grid;
  grid-template-columns: minmax(0, 0.92fr) minmax(420px, 1.08fr);
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
  gap: 18px;
  padding: 48px 54px;
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
  font-size: clamp(40px, 5vw, 68px);
  line-height: 0.96;
  max-width: 520px;
}

.landing-copy p {
  margin: 0;
  color: rgba(203, 213, 225, 0.78);
  font-size: 16px;
  max-width: 240px;
}

.landing-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.landing-primary {
  min-width: 156px;
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
  border-radius: 999px;
  inset: 50%;
  transform: translate(-50%, -50%);
}

.landing-stage::before {
  width: min(52vw, 640px);
  height: min(52vw, 640px);
  border: 1px solid rgba(52, 211, 153, 0.12);
  box-shadow:
    0 0 0 90px rgba(52, 211, 153, 0.03),
    0 0 0 180px rgba(52, 211, 153, 0.02);
}

.landing-stage::after {
  width: min(26vw, 320px);
  height: min(26vw, 320px);
  background: radial-gradient(circle, rgba(16, 185, 129, 0.18), transparent 68%);
}

.stage-core,
.stage-node {
  position: absolute;
  z-index: 1;
}

.stage-core {
  display: grid;
  gap: 8px;
  padding: 34px;
  width: 220px;
  height: 220px;
  border-radius: 999px;
  place-content: center;
  text-align: center;
  background:
    radial-gradient(circle, rgba(16, 185, 129, 0.2), rgba(16, 185, 129, 0.05)),
    rgba(8, 12, 18, 0.72);
  border: 1px solid rgba(52, 211, 153, 0.18);
}

.stage-core strong {
  font-size: 28px;
  line-height: 1.02;
}

.stage-node {
  display: grid;
  gap: 6px;
  width: 190px;
  padding: 16px 18px;
  border-radius: 22px;
  border: 1px solid rgba(255, 255, 255, 0.07);
  background: rgba(8, 12, 18, 0.76);
  backdrop-filter: blur(10px);
}

.stage-node strong {
  font-size: 18px;
  line-height: 1.1;
}

.stage-node-investor {
  top: 16%;
  right: 16%;
}

.stage-node-management {
  bottom: 18%;
  right: 10%;
}

.stage-node-regulator {
  bottom: 20%;
  left: 10%;
}

.stage-footnote {
  position: absolute;
  left: 50%;
  bottom: 8%;
  transform: translateX(-50%);
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: center;
}

.stage-footnote span {
  min-height: 34px;
  padding: 0 12px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.025);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: rgba(203, 213, 225, 0.84);
  font-size: 12px;
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
  min-height: 92px;
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
    min-height: 420px;
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
    min-height: 360px;
  }

  .stage-core {
    width: 180px;
    height: 180px;
  }

  .stage-node {
    width: 148px;
    padding: 12px 14px;
  }

  .stage-node strong {
    font-size: 15px;
  }

  .stage-node-investor {
    top: 10%;
    right: 4%;
  }

  .stage-node-management {
    bottom: 10%;
    right: 2%;
  }

  .stage-node-regulator {
    bottom: 12%;
    left: 2%;
  }

  .stage-footnote {
    bottom: 4%;
    width: calc(100% - 32px);
  }

  .landing-dock {
    padding: 0 16px 16px;
  }
}
</style>
