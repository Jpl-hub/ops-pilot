<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import AppShell from '@/components/AppShell.vue'
import ChartPanel from '@/components/ChartPanel.vue'
import ErrorState from '@/components/ErrorState.vue'
import { useAsyncState } from '@/composables/useAsyncState'
import { get, post } from '@/lib/api'

const overviewState = useAsyncState<any>()
const stressState = useAsyncState<any>()
const runsState = useAsyncState<any>()
const runtimeState = useAsyncState<any>()
const route = useRoute()

const companies = computed(() => overviewState.data.value?.companies || [])
const selectedCompany = ref('')
const selectedPeriod = ref('')
const scenario = ref('欧盟对动力电池临时加征关税并限制关键材料进口')
const scenarioDraft = ref(scenario.value)
const activeStressStep = ref(0)
let stressTicker: number | null = null

const presetScenarios = [
  '欧盟对动力电池临时加征关税并限制关键材料进口',
  '上游碳酸锂价格急涨并持续三个月',
  '关键供应商停产两周导致交付延迟',
  '海外主要市场需求快速回落',
]

const propagationSteps = computed(() => stressState.data.value?.propagation_steps || [])
const transmissionMatrix = computed(() => stressState.data.value?.transmission_matrix || [])
const simulationLog = computed(() => stressState.data.value?.simulation_log || [])
const stressWavefront = computed(() => stressState.data.value?.stress_wavefront || [])
const activeSimulationLog = computed(() => simulationLog.value[activeStressStep.value] || null)
const activeWavefront = computed(
  () => stressWavefront.value[activeStressStep.value] || stressWavefront.value[0] || null,
)

async function runStress() {
  if (!selectedCompany.value || !scenarioDraft.value.trim()) return
  scenario.value = scenarioDraft.value.trim()
  await stressState.execute(() =>
    post('/company/stress-test', {
      company_name: selectedCompany.value,
      report_period: selectedPeriod.value || null,
      user_role: 'management',
      scenario: scenario.value,
    }),
  )
  
  const params = new URLSearchParams()
  params.set('company_name', selectedCompany.value)
  if (selectedPeriod.value) params.set('report_period', selectedPeriod.value)
  params.set('user_role', 'management')

  await runsState.execute(() => get(`/stress-test/runs?${params.toString()}&limit=6`))
  await runtimeState.execute(() => get(`/company/intelligence-runtime?${params.toString()}`))
  activeStressStep.value = 0
}

onMounted(async () => {
  await overviewState.execute(() => get('/workspace/overview?user_role=management'))
  selectedCompany.value =
    (typeof route.query.company === 'string' ? route.query.company : '') || companies.value[0] || ''
  selectedPeriod.value = typeof route.query.period === 'string' ? route.query.period : ''
  await runStress()
  stressTicker = window.setInterval(() => {
    if (!propagationSteps.value.length) return
    activeStressStep.value = (activeStressStep.value + 1) % propagationSteps.value.length
  }, 3000)
})

onBeforeUnmount(() => {
  if (stressTicker) {
    window.clearInterval(stressTicker)
    stressTicker = null
  }
})

function selectPreset(item: string) {
  scenarioDraft.value = item
  runStress()
}
</script>

<template>
  <AppShell title="">
    <div class="rag-layout custom-scrollbar">
      
      <!-- Top Branding -->
      <header class="rag-header">
        <div class="rag-header-left">
          <svg class="rag-header-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"></path></svg>
          <div class="rag-header-titles">
            <h1 class="rag-title">产业链压力测试 (Stress Test)</h1>
            <span class="rag-subtitle">Supply Chain Systemic Risk Simulation</span>
          </div>
        </div>
        
        <!-- Controls -->
        <div class="rag-header-right">
           <label class="rag-label-desktop">Entity:</label>
           <select v-model="selectedCompany" class="rag-select">
             <option v-for="company in companies" :key="company" :value="company" class="rag-option">{{ company }}</option>
           </select>
           <input v-model="selectedPeriod" class="rag-select rag-select-small" placeholder="Period" />
        </div>
      </header>

      <div class="rag-content">
        <ErrorState v-if="stressState.error.value" :message="String(stressState.error.value)" class="rag-error-margin" />
        
        <!-- Search/Scenario Input Interface -->
        <div class="rag-search-box">
           <div class="rag-sb-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="rag-sb-icon-svg"><circle cx="12" cy="12" r="10"></circle><path d="M16 12l-4-4-4 4"></path><path d="M12 16V8"></path></svg>
           </div>
           <div class="rag-sb-input-area">
              <input v-model="scenarioDraft" type="text" class="rag-sb-input" placeholder="输入压力场景，例如：上游核心矿产断供..." @keydown.enter="runStress" :disabled="stressState.loading.value"/>
              <div class="rag-sb-sub">Stress Engine 正在推演冲击传导并量化风险敞口... 
                <span v-if="stressState.loading.value" class="rag-pulse-text">Simulating...</span>
              </div>
           </div>
           
           <div class="rag-sb-stats">
              <svg class="rag-sb-stats-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
              <span>Severity: 
                <strong class="rag-severity-val" :class="stressState.data.value?.severity?.color === 'risk' ? 'rag-tone-risk' : 'rag-tone-safe'">
                  {{ stressState.data.value?.severity?.level || 'N/A' }} 
                  {{ stressState.data.value?.severity?.label || 'Ready' }}
                </strong>
              </span>
           </div>
        </div>
        
        <!-- Preset Scenarios -->
        <div class="rag-preset-list">
          <button
            v-for="item in presetScenarios"
            :key="item"
            class="rag-preset-btn"
            @click="selectPreset(item)"
          >
            >> {{ item }}
          </button>
        </div>

        <!-- Colossal Canvas Area -->
        <div class="rag-canvas-container rag-canvas-stress">
           
           <!-- Left: Transmission Matrix & Ribbon -->
           <div class="rag-main-col">
              
              <div class="rag-section-header">
                 <div class="rag-section-title">冲击传导网络 (Transmission Matrix)</div>
              </div>

              <!-- Transmission Nodes Pipeline -->
              <div class="rag-transmission-grid">
                 <div 
                   v-for="(item, index) in transmissionMatrix" 
                   :key="item.stage"
                   class="rag-transmission-node"
                   :class="[`node-${item.tone || 'warning'}`, { 'is-active': activeWavefront?.active_stage === 'upstream' && index === 0 || activeWavefront?.active_stage === 'midstream' && index === 1 || activeWavefront?.active_stage === 'downstream' && index === 2 }]"
                 >
                    <div class="node-stage-badge">
                      <div class="node-stage-dot"></div>
                      {{ item.stage }}
                    </div>
                    <div class="node-headline">{{ item.headline }}</div>
                    <div class="node-impact-score">{{ item.impact_score }}</div>
                    <div class="node-impact-label">{{ item.impact_label }}</div>
                    
                    <!-- decorative arrow connecting nodes -->
                    <div v-if="index < transmissionMatrix.length - 1" class="node-connector">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14"></path><path d="M12 5l7 7-7 7"></path></svg>
                    </div>
                 </div>
              </div>

              <!-- Embedded Chart Panel if exists -->
              <div v-if="stressState.data.value?.chart" class="rag-chart-wrapper">
                 <ChartPanel
                   :title="'冲击传导强度 (Impact Magnitude over Phases)'"
                   :options="stressState.data.value.chart.options"
                 />
              </div>
              
              <div class="rag-spacer"></div>
              
              <!-- Propagation Ribbon at bottom -->
              <div v-if="propagationSteps.length" class="rag-inference-ribbon">
                <div class="rag-ribbon-title">
                   传播推演链路 (Propagation Chain):
                </div>
                <div class="rag-ribbon-list">
                   <template v-for="(item, idx) in propagationSteps" :key="item.step">
                     <div 
                       class="rag-path-item" 
                       :class="{ 'is-active': item.step - 1 === activeStressStep || idx <= activeStressStep }"
                     >
                        <span class="rag-path-item-main"><span class="rag-path-number">0{{ item.step }}</span> {{ item.title }}</span>
                     </div>
                     <div v-if="idx < propagationSteps.length - 1" class="rag-path-arrow">→</div>
                   </template>
                </div>
              </div>
           </div>
           
           <!-- Right: Simulation Log Stream -->
           <div class="rag-side-col">
              <div class="rag-side-title">仿真日志 (Simulation Stream)</div>
              
              <!-- Highlighted Active Frame -->
              <div class="rag-log-active-frame">
                 <div class="rag-frame-header">
                    <span class="rag-frame-lbl">Current Wavefront</span>
                    <span class="rag-frame-badge">SIM ACTIVE</span>
                 </div>
                 <h4 class="rag-frame-title">{{ activeWavefront?.headline || activeSimulationLog?.title || '等待推演' }}</h4>
                 <p class="rag-frame-desc">{{ activeWavefront?.log || activeSimulationLog?.detail || '系统准备冲击波前计算...' }}</p>
                 
                 <!-- Intensity Meter -->
                 <div class="rag-frame-meter-box">
                    <div class="rag-meter-lbl">
                      <span>IMPACT ENERGY</span>
                      <strong class="rag-meter-val">{{ activeWavefront?.impact_score || 0 }}</strong>
                    </div>
                    <div class="rag-meter-track">
                       <div class="rag-meter-fill" :style="{ width: `${activeWavefront?.energy || 0}%` }"></div>
                    </div>
                 </div>
              </div>
              
              <!-- Historical Log List -->
              <div class="rag-log-list custom-scrollbar">
                 <div 
                   v-for="item in simulationLog" 
                   :key="`log-${item.step}`"
                   class="rag-log-item"
                   :class="{'is-active': item.step - 1 === activeStressStep }"
                 >
                    <div class="rag-log-item-title"><span class="rag-log-item-num">{{ item.step }}.</span>{{ item.title }}</div>
                    <div class="rag-log-item-desc">{{ item.detail }}</div>
                 </div>
              </div>
              
           </div>
           
        </div>

      </div>
    </div>
  </AppShell>
</template>

<style scoped>
/* Base Layout (Shared with Graph) */
.rag-layout { display: flex; flex-direction: column; height: 100%; width: 100%; background: #080808; overflow-y: auto; overflow-x: hidden; margin: -16px -24px -24px; padding: 0; }
.rag-header { display: flex; align-items: center; justify-content: space-between; padding: 20px 40px; border-bottom: 1px solid rgba(255,255,255,0.03); background: #000; z-index: 20; flex-shrink: 0; }
.rag-header-left { display: flex; align-items: center; gap: 12px; }
.rag-header-icon { color: #f43f5e; width: 24px; height: 24px; }
.rag-header-titles { display: flex; flex-direction: column; }
.rag-title { font-size: 20px; font-weight: 700; letter-spacing: -0.025em; color: #fff; margin: 0; display: flex; align-items: center; gap: 8px; }
.rag-subtitle { font-size: 10px; font-family: monospace; color: #6b7280; text-transform: uppercase; letter-spacing: 0.1em; margin-top: 4px; }

.rag-header-right { margin-left: auto; display: flex; align-items: center; gap: 16px; }
.rag-label-desktop { font-size: 12px; font-family: monospace; color: #6b7280; text-transform: uppercase; letter-spacing: 0.05em; display: none; }
@media (min-width: 640px) { .rag-label-desktop { display: block; } }

.rag-select { background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.1); color: #fff; padding: 8px 16px; border-radius: 6px; outline: none; font-size: 14px; transition: border 0.2s; }
.rag-select:focus { border-color: rgba(244, 63, 94, 0.5); }
.rag-select-small { width: 96px; }
.rag-option { background: #000; }

/* Content Wrapper */
.rag-content { flex: 1; display: flex; flex-direction: column; gap: 16px; padding: 24px 32px; }
.rag-error-margin { margin-bottom: 16px; }

/* Preset Buttons */
.rag-preset-list { display: flex; flex-wrap: wrap; gap: 8px; padding: 0 8px; }
.rag-preset-btn {
  background: transparent; border: 1px solid rgba(255,255,255,0.1); color: #9ca3af;
  padding: 6px 14px; border-radius: 99px; font-size: 12px; font-family: 'JetBrains Mono', monospace;
  cursor: pointer; transition: all 0.2s; backdrop-filter: blur(8px);
}
.rag-preset-btn:hover { background: rgba(244, 63, 94, 0.1); border-color: rgba(244, 63, 94, 0.3); color: #fb7185; }

/* Search Box (Rose variant) */
.rag-search-box { 
  display: flex; align-items: center; gap: 20px; padding: 16px 24px; 
  background: rgba(15, 15, 20, 0.8); border: 1px solid rgba(255,255,255,0.06); 
  border-radius: 12px; box-shadow: 0 10px 30px rgba(0,0,0,0.5);
  backdrop-filter: blur(20px); z-index: 10;
}
.rag-sb-icon { 
  width: 40px; height: 40px; border-radius: 50%; background: rgba(244, 63, 94, 0.1); 
  display: flex; align-items: center; justify-content: center; color: #fb7185; flex-shrink: 0;
  border: 1px solid rgba(244, 63, 94, 0.2);
}
.rag-sb-icon-svg { width: 18px; height: 18px; }
.rag-sb-input-area { flex: 1; display: flex; flex-direction: column; gap: 4px; }
.rag-sb-input { 
  background: transparent; border: none; font-size: 16px; color: #fff; width: 100%; 
  font-weight: 500; outline: none;
}
.rag-sb-input::placeholder { color: #4b5563; }
.rag-sb-input:focus { outline: none; }
.rag-sb-sub { font-size: 12px; color: #6b7280; font-family: monospace; }
.rag-pulse-text { color: #f43f5e; margin-left: 8px; animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite; }

.rag-sb-stats { 
  display: flex; align-items: center; padding: 6px 12px; background: rgba(0,0,0,0.4); 
  border: 1px solid rgba(244, 63, 94, 0.2); border-radius: 6px; color: #fda4af; 
  font-size: 11px; font-family: monospace; flex-shrink: 0;
}
.rag-sb-stats-icon { width: 14px; height: 14px; margin-right: 6px; }
.rag-tone-risk { color: #f43f5e; }
.rag-tone-safe { color: #10b981; }

/* Canvas Area */
.rag-canvas-container { 
  position: relative; flex: 1; min-height: 500px;
  background: radial-gradient(circle at 10% 90%, rgba(244, 63, 94, 0.05) 0%, rgba(0,0,0,0) 60%), #040404; 
  border: 1px solid rgba(255,255,255,0.03); border-radius: 12px; overflow: hidden;
  display: flex; gap: 24px; padding: 24px;
}
.rag-main-col { flex: 1; display: flex; flex-direction: column; gap: 24px; position: relative; z-index: 10; }
.rag-side-col { width: 320px; display: flex; flex-direction: column; gap: 16px; border-left: 1px solid rgba(255,255,255,0.05); padding-left: 24px; position: relative; z-index: 10; }

.rag-section-header { display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 8px; }
.rag-section-title { font-size: 14px; font-weight: 700; color: #fff; letter-spacing: 0.1em; text-transform: uppercase; }
.rag-spacer { flex: 1; }

/* Transmission Nodes */
.rag-transmission-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 24px; min-height: 192px; }
.rag-transmission-node {
  position: relative; background: rgba(39, 39, 42, 0.3); backdrop-filter: blur(8px);
  border: 1px solid rgba(255,255,255,0.05); border-radius: 16px;
  padding: 24px; display: flex; flex-direction: column; justify-content: flex-start;
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}
.rag-transmission-node:hover { transform: translateY(-5px); background: rgba(255,255,255,0.04); }
.rag-transmission-node.is-active {
  background: rgba(127, 29, 29, 0.2); border-color: rgba(239, 68, 68, 0.3);
  box-shadow: 0 0 30px rgba(244, 63, 94, 0.15);
}

.node-stage-badge { 
  align-self: flex-start; font-size: 11px; font-family: monospace; font-weight: 500;
  text-transform: uppercase; letter-spacing: 1px; padding: 6px 12px; border-radius: 99px; 
  background: rgba(255,255,255,0.05); color: #9ca3af; margin-bottom: 12px;
  display: flex; align-items: center; gap: 6px;
}
.node-stage-dot { width: 6px; height: 6px; border-radius: 50%; background: #9ca3af; }
.is-active .node-stage-badge { background: rgba(244, 63, 94, 0.2); color: #fda4af; }
.is-active .node-stage-dot { background: #fda4af; box-shadow: 0 0 8px #fda4af; }

.node-headline { font-size: 16px; font-weight: bold; color: #f3f4f6; margin-bottom: auto; line-height: 1.4; }
.node-impact-score { font-size: 28px; font-family: 'JetBrains Mono'; font-weight: 300; color: #fb7185; margin: 16px 0 4px; }
.node-impact-label { font-size: 13px; color: #9ca3af; }

.node-connector {
  position: absolute; right: -28px; top: 50%; transform: translateY(-50%);
  width: 32px; height: 32px; color: rgba(255,255,255,0.1);
}
.is-active .node-connector { color: rgba(244, 63, 94, 0.5); animation: pulse 2s infinite; }

/* Chart Wrapper */
.rag-chart-wrapper { background: rgba(0,0,0,0.4); border-radius: 12px; padding: 16px; border: 1px solid rgba(255,255,255,0.03); flex: 1; min-height: 250px; display: flex; }

/* Ribbon */
.rag-inference-ribbon { background: rgba(10, 10, 12, 0.85); backdrop-filter: blur(16px); border: 1px solid rgba(255,255,255,0.05); border-radius: 8px; padding: 16px 24px; box-shadow: 0 20px 40px rgba(0,0,0,0.8); z-index: 5; }
.rag-ribbon-title { font-size: 13px; font-family: monospace; color: #fb7185; margin-bottom: 16px; letter-spacing: 0.05em; font-weight: bold; }
.rag-ribbon-list { display: flex; align-items: stretch; gap: 12px; overflow-x: auto; padding-bottom: 4px; }
.rag-path-item {
  position: relative;
  padding: 10px 16px; border-radius: 6px; background: rgba(153, 27, 27, 0.1); 
  border: 1px solid rgba(244, 63, 94, 0.15); font-size: 13px; white-space: nowrap;
  display: flex; flex-direction: column; gap: 4px; transition: all 0.3s ease;
}
.rag-path-item-main { color: #e5e7eb; font-weight: 500; display: flex; align-items: center; gap: 8px;}
.rag-path-number { opacity: 0.5; color: #fb7185; }
.rag-path-arrow { display: flex; align-items: center; color: #4b5563; font-weight: 300; font-size: 18px; padding: 0 4px; }

.rag-path-item.is-active { background: rgba(153, 27, 27, 0.25); border-color: rgba(244, 63, 94, 0.4); box-shadow: 0 0 20px rgba(244, 63, 94, 0.15); }
.rag-path-item.is-active::after {
  content: ''; position: absolute; bottom: -1px; left: 0; height: 3px; width: 100%;
  background: #f43f5e; border-radius: 0 0 6px 6px;
  box-shadow: 0 -2px 10px rgba(244, 63, 94, 0.5);
}

/* Simulation Side Stream */
.rag-side-title { font-size: 12px; font-family: monospace; color: #9ca3af; text-transform: uppercase; letter-spacing: 0.1em; }
.rag-log-active-frame { background: linear-gradient(135deg, rgba(244, 63, 94, 0.1) 0%, rgba(0,0,0,0.4) 100%); border: 1px solid rgba(244, 63, 94, 0.2); border-radius: 12px; padding: 16px; box-shadow: 0 8px 32px rgba(0,0,0,0.4); backdrop-filter: blur(8px); }
.rag-frame-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.rag-frame-lbl { color: #fb7185; font-weight: 700; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; }
.rag-frame-badge { font-size: 10px; background: rgba(244, 63, 94, 0.2); color: #fda4af; padding: 0 8px; border-radius: 4px; font-family: monospace; border: 1px solid rgba(244, 63, 94, 0.3); line-height: 18px; }
.rag-frame-title { color: #fff; font-size: 14px; font-weight: 500; margin: 0 0 4px; line-height: 1.3; }
.rag-frame-desc { color: #9ca3af; font-size: 12px; margin: 0; line-height: 1.5; }
.rag-frame-meter-box { margin-top: 16px; background: rgba(0,0,0,0.5); border-radius: 4px; padding: 8px; border: 1px solid rgba(255,255,255,0.05); }
.rag-meter-lbl { display: flex; justify-content: space-between; font-size: 10px; font-family: monospace; color: #6b7280; margin-bottom: 4px; }
.rag-meter-val { color: #fb7185; }
.rag-meter-track { height: 4px; background: rgba(255,255,255,0.05); border-radius: 2px; overflow: hidden; }
.rag-meter-fill { height: 100%; background: #f43f5e; box-shadow: 0 0 8px #f43f5e; transition: width 0.5s ease; }

.rag-log-list { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; padding-right: 8px; }
.rag-log-item { padding: 12px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.05); background: rgba(0,0,0,0.3); transition: all 0.3s ease; backdrop-filter: blur(4px); }
.rag-log-item.is-active { border-color: rgba(244, 63, 94, 0.3); background: rgba(244, 63, 94, 0.05); }
.rag-log-item-title { font-size: 12px; font-weight: 700; color: #fff; margin-bottom: 4px; }
.rag-log-item-num { color: rgba(244, 63, 94, 0.7); margin-right: 4px; }
.rag-log-item-desc { font-size: 12px; color: #6b7280; }

/* Utilities */
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: .5; } }
.custom-scrollbar::-webkit-scrollbar { width: 6px; height: 6px; }
.custom-scrollbar::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 3px; }
.custom-scrollbar::-webkit-scrollbar-track { background: transparent; }
</style>
