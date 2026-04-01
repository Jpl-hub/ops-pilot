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
  },
  {
    role: 'management',
    roleLabel: '管理层',
    title: '做经营诊断',
    prompt: '给我一份当前经营体检和整改优先级。',
  },
  {
    role: 'regulator',
    roleLabel: '监管 / 风控',
    title: '做持续巡检',
    prompt: '当前主周期哪些公司风险抬升最快？',
  },
]
</script>

<template>
  <AppShell title="">
    <div class="landing">
      <section class="landing-hero">
        <div class="landing-copy">
          <h1>OpsPilot-X</h1>

          <div class="landing-actions">
            <RouterLink class="button-primary landing-primary" :to="entryAction.to">
              {{ entryAction.label }}
            </RouterLink>
            <RouterLink class="button-secondary landing-secondary" to="/brain">
              进入产业大脑
            </RouterLink>
          </div>
        </div>

        <div class="landing-stage" aria-hidden="true">
          <div class="stage-column">
            <div class="stage-frame stage-frame-lead">
              <strong>先看主线</strong>
            </div>

            <div class="stage-frame">
              <strong>再做判断</strong>
            </div>

            <div class="stage-frame">
              <strong>最后回到原文</strong>
            </div>
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
          </div>
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
    radial-gradient(circle at 85% 18%, rgba(59, 130, 246, 0.08), transparent 24%),
    linear-gradient(180deg, rgba(7, 10, 18, 0.98), rgba(7, 10, 18, 0.94));
}

.landing-hero {
  display: grid;
  grid-template-columns: minmax(0, 0.9fr) minmax(460px, 1.1fr);
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
  gap: 24px;
  padding: 56px;
}

.landing-copy h1,
.stage-frame strong,
.dock-strip strong {
  margin: 0;
  letter-spacing: -0.05em;
  color: #f8fafc;
}

.landing-copy h1 {
  font-size: clamp(44px, 5vw, 76px);
  line-height: 0.92;
}

.landing-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.landing-primary,
.landing-secondary {
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
  inset: auto;
}

.landing-stage::before {
  inset: 14% 11% 18% 18%;
  border-radius: 34px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: linear-gradient(180deg, rgba(12, 16, 24, 0.98), rgba(8, 12, 18, 0.94));
}

.landing-stage::after {
  inset: 22% 18% 22% 24%;
  border-radius: 30px;
  background: radial-gradient(circle at 16% 14%, rgba(16, 185, 129, 0.16), transparent 28%);
  opacity: 0.84;
}

.stage-column {
  position: relative;
  z-index: 1;
  width: min(76%, 500px);
  display: grid;
  gap: 14px;
}

.stage-frame {
  display: grid;
  gap: 7px;
  padding: 18px 20px;
  border-radius: 22px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(12, 16, 24, 0.82);
  backdrop-filter: blur(14px);
}

.stage-frame-lead {
  background: linear-gradient(180deg, rgba(10, 33, 27, 0.92), rgba(12, 16, 24, 0.86));
  border-color: rgba(52, 211, 153, 0.16);
}

.dock-strip span {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: rgba(148, 163, 184, 0.82);
}

.stage-frame strong {
  font-size: 22px;
  line-height: 1.06;
}

.landing-dock {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  padding: 0 24px 24px;
}

.dock-strip {
  display: flex;
  align-items: center;
  gap: 16px;
  min-height: 92px;
  padding: 0 20px;
  border-radius: 24px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.024);
  text-decoration: none;
}

.dock-copy {
  display: grid;
  gap: 4px;
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
    font-size: clamp(34px, 16vw, 52px);
  }

  .landing-stage {
    min-height: 360px;
  }

  .stage-column {
    width: calc(100% - 36px);
  }

  .landing-dock {
    padding: 0 16px 16px;
  }
}
</style>
