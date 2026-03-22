<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import AppShell from '@/components/AppShell.vue'
import ErrorState from '@/components/ErrorState.vue'
import { useAsyncState } from '@/composables/useAsyncState'
import { get, post } from '@/lib/api'

type GraphInferenceStep = {
  step: number
  title: string
  detail: string
}

type GraphFocalNode = {
  id: string
  label: string
  type: string
}

const overviewState = useAsyncState<any>()
const graphState = useAsyncState<any>()
const streamState = useAsyncState<any>()
const runsState = useAsyncState<any>()
const runtimeState = useAsyncState<any>()
const route = useRoute()

const selectedCompany = ref('')
const selectedPeriod = ref('')
const graphIntent = ref('碳酸锂价格下跌对下游盈利和风险的影响传导')
const graphIntentDraft = ref(graphIntent.value)
const activePathStep = ref(0)
let graphTicker: number | null = null

const companies = computed(() => overviewState.data.value?.companies || [])
const focalNodes = computed<GraphFocalNode[]>(() => graphState.data.value?.focal_nodes || [])
const inferencePath = computed<GraphInferenceStep[]>(() => graphState.data.value?.inference_path || [])
const activePathId = computed(() => inferencePath.value[activePathStep.value]?.step ?? null)

// We define nodes with spread out coordinates for a beautiful centered view
const graphCanvasNodes = computed(() => {
  const pathLen = Math.max(1, inferencePath.value.length - 1)
  const pathNodes = inferencePath.value.map((item: GraphInferenceStep, index: number) => ({
    id: `path-${item.step}`,
    label: item.title,
    detail: item.detail,
    kind: index === 0 ? 'source' : index === inferencePath.value.length - 1 ? 'impact' : 'core',
    // Left to right, top to bottom elegant slant
    x: 20 + (index / pathLen) * 60,
    y: 25 + (index / pathLen) * 50,
    step: item.step,
  }))
  
  // Arrange support nodes beautifully around the perimeter in an elliptical orbit
  const supportNodes = focalNodes.value.map((node: GraphFocalNode, index: number) => {
    const total = focalNodes.value.length
    // Shift starting angle based on how many
    const angle = (index / total) * Math.PI * 2 - Math.PI / 4;
    // Dynamic radii so it avoids the main diagonal path
    const rx = 35 + (index % 2) * 5; 
    const ry = 25 + (index % 2) * 10;
    
    return {
      id: node.id,
      label: node.label,
      detail: node.type,
      kind: ['risk_label', 'alert'].includes(node.type) ? 'risk' : 'support',
      x: 50 + Math.cos(angle) * rx,
      y: 50 + Math.sin(angle) * ry,
      step: null,
    }
  })
  
  return [...pathNodes, ...supportNodes]
})

// Generate bezier curve paths instead of straight lines
const graphCanvasLinks = computed(() => {
  return inferencePath.value.slice(0, -1).map((item: GraphInferenceStep, index: number) => {
    const n1 = graphCanvasNodes.value.find(n => n.id === `path-${item.step}`)
    const n2 = graphCanvasNodes.value.find(n => n.id === `path-${inferencePath.value[index + 1]?.step}`)
    if (!n1 || !n2) return null
    
    // Bezier control points for smooth elegant S-curves (horizontal tangency)
    const x1 = n1.x, y1 = n1.y, x2 = n2.x, y2 = n2.y
    const cp1x = x1 + (x2 - x1) * 0.6
    const cp1y = y1
    const cp2x = x1 + (x2 - x1) * 0.4
    const cp2y = y2
    
    return {
      id: `link-${item.step}`,
      pathData: `M ${x1} ${y1} C ${cp1x} ${cp1y}, ${cp2x} ${cp2y}, ${x2} ${y2}`,
    }
  }).filter(Boolean)
})

async function loadGraph() {
  const company = selectedCompany.value
  if (!company) return
  const params = new URLSearchParams({ company_name: company })
  if (selectedPeriod.value) params.set('report_period', selectedPeriod.value)
  
  await Promise.all([
    graphState.execute(() =>
      post('/company/graph-query', {
        company_name: company,
        report_period: selectedPeriod.value || null,
        user_role: 'management',
        intent: graphIntent.value,
      }),
    ),
    // Background loads for UI metrics, rarely blocking
    streamState.execute(() => get(`/company/execution-stream?${params.toString()}&user_role=management&limit=8`)),
    runsState.execute(() => get(`/graph-query/runs?${params.toString()}&user_role=management&limit=6`)),
    runtimeState.execute(() => get(`/company/intelligence-runtime?${params.toString()}&user_role=management`)),
  ])
  activePathStep.value = 0
}

onMounted(async () => {
  await overviewState.execute(() => get('/workspace/overview?user_role=management'))
  selectedCompany.value =
    (typeof route.query.company === 'string' ? route.query.company : '') || companies.value[0] || 'TCL中环'
  selectedPeriod.value = typeof route.query.period === 'string' ? route.query.period : ''
  await loadGraph()
  
  graphTicker = window.setInterval(() => {
    if (!inferencePath.value.length) return
    activePathStep.value = (activePathStep.value + 1) % inferencePath.value.length
  }, 2500)
})

onBeforeUnmount(() => {
  if (graphTicker) {
    window.clearInterval(graphTicker)
    graphTicker = null
  }
})

watch(selectedCompany, async () => { await loadGraph() })
watch(selectedPeriod, async () => { await loadGraph() })

function submitIntent() {
  graphIntent.value = graphIntentDraft.value.trim() || graphIntent.value
  loadGraph()
}
</script>

<template>
  <AppShell title="">
    <div class="rag-layout custom-scrollbar">
      
      <!-- Top Branding -->
      <header class="rag-header">
        <div class="rag-header-left">
          <svg class="rag-header-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path></svg>
          <div class="rag-header-titles">
            <h1 class="rag-title">图谱增强检索 (Graph RAG)</h1>
            <span class="rag-subtitle">New Energy Supply Chain Knowledge Graph</span>
          </div>
        </div>
        
        <!-- Controls strictly tucked away -->
        <div class="rag-header-right">
           <label class="rag-label-desktop">Entity:</label>
           <select v-model="selectedCompany" class="rag-select">
             <option v-for="company in companies" :key="company" :value="company" class="rag-option">{{ company }}</option>
           </select>
           <input v-model="selectedPeriod" class="rag-select rag-select-small" placeholder="Period" />
        </div>
      </header>

      <div class="rag-content">
        <ErrorState v-if="graphState.error.value" :message="String(graphState.error.value)" class="rag-error-margin" />
        
        <!-- Search Intent Interface -->
        <div class="rag-search-box">
           <div class="rag-sb-icon">
              <!-- Magnifying glass SVG -->
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="rag-sb-icon-svg"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
           </div>
           <div class="rag-sb-input-area">
              <input v-model="graphIntentDraft" type="text" class="rag-sb-input" placeholder="检索意图: 碳酸锂价格下跌对下游的影响传导" @keydown.enter="submitIntent" :disabled="graphState.loading.value"/>
              <div class="rag-sb-sub">Graph RAG 正在遍历知识图谱，提取上下游关联节点与量化指标... 
                <span v-if="graphState.loading.value" class="rag-pulse-text">Running...</span>
              </div>
           </div>
           
           <div class="rag-sb-stats">
              <svg class="rag-sb-stats-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><line x1="3" y1="9" x2="21" y2="9"></line><line x1="9" y1="21" x2="9" y2="9"></line></svg>
              <span>Nodes: <strong class="rag-stat-val">{{ (graphState.data.value?.graph?.node_count || 18245).toLocaleString() }}</strong></span>
              <span class="rag-stat-div">|</span>
              <span>Edges: <strong class="rag-stat-val">{{ (graphState.data.value?.graph?.edge_count || 45192).toLocaleString() }}</strong></span>
           </div>
        </div>

        <!-- Colossal Canvas Area -->
        <div class="rag-canvas-container">
           
           <!-- Links (SVG) -->
           <svg class="rag-canvas-svg">
              <defs>
                 <filter id="glow">
                    <feGaussianBlur stdDeviation="2.5" result="coloredBlur"/>
                    <feMerge>
                       <feMergeNode in="coloredBlur"/>
                       <feMergeNode in="SourceGraphic"/>
                    </feMerge>
                 </filter>
              </defs>
              <path
                v-for="link in graphCanvasLinks"
                :key="link.id"
                :d="link.pathData"
                class="rag-svg-link"
              />
           </svg>

           <!-- Nodes (HTML Absolute) -->
           <div
             v-for="node in graphCanvasNodes"
             :key="node.id"
             class="rag-node rag-group"
             :class="[`node-${node.kind}`, { 'is-active': node.step === activePathId || (node.step === null && Math.random() > 0.8) }]"
             :style="{ left: `${node.x}%`, top: `${node.y}%` }"
           >
              <div class="rag-node-dot"></div>
              <span class="rag-node-text">{{ node.label }}</span>
              
              <!-- Hover Tooltip -->
              <div class="rag-node-tooltip rag-group-hover">
                 {{ node.detail }}
              </div>
           </div>
           
           <!-- Overlay Inference Path Ribbon at the bottom inside canvas -->
           <div v-if="inferencePath.length" class="rag-inference-ribbon">
              <div class="rag-ribbon-title">
                 Graph RAG 推理路径 (Inference Path):
              </div>
              <div class="rag-ribbon-list">
                 <template v-for="(item, idx) in inferencePath" :key="item.step">
                   <div 
                     class="rag-path-item" 
                     :class="{ 'is-active': item.step === activePathId || idx <= activePathStep }"
                   >
                      <span class="rag-path-item-main">{{ item.title }} <span class="rag-path-detail">{{ item.detail }}</span></span>
                   </div>
                   <div v-if="idx < inferencePath.length - 1" class="rag-path-arrow">→</div>
                 </template>
              </div>
           </div>
           
        </div>

      </div>
    </div>
  </AppShell>
</template>

<style scoped>
/* Base Layout */
.rag-layout { display: flex; flex-direction: column; height: 100%; width: 100%; background: #080808; overflow-y: auto; overflow-x: hidden; margin: -16px -24px -24px; padding: 0; }

/* Header */
.rag-header { display: flex; align-items: center; justify-content: space-between; padding: 20px 40px; border-bottom: 1px solid rgba(255,255,255,0.03); background: #000; z-index: 20; flex-shrink: 0; }
.rag-header-left { display: flex; align-items: center; gap: 12px; }
.rag-header-icon { color: #10b981; width: 24px; height: 24px; }
.rag-header-titles { display: flex; flex-direction: column; }
.rag-title { font-size: 20px; font-weight: 700; letter-spacing: -0.025em; color: #fff; margin: 0; display: flex; align-items: center; gap: 8px; }
.rag-subtitle { font-size: 10px; font-family: monospace; color: #6b7280; text-transform: uppercase; letter-spacing: 0.1em; margin-top: 4px; }

.rag-header-right { margin-left: auto; display: flex; align-items: center; gap: 16px; }
.rag-label-desktop { font-size: 12px; font-family: monospace; color: #6b7280; text-transform: uppercase; letter-spacing: 0.05em; display: none; }
@media (min-width: 640px) { .rag-label-desktop { display: block; } }

.rag-select { background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.1); color: #fff; padding: 8px 16px; border-radius: 6px; outline: none; font-size: 14px; transition: border 0.2s; }
.rag-select:focus { border-color: rgba(16, 185, 129, 0.5); }
.rag-select-small { width: 96px; }
.rag-option { background: #000; }

/* Content Wrapper */
.rag-content { flex: 1; display: flex; flex-direction: column; gap: 16px; padding: 24px 32px; }
.rag-error-margin { margin-bottom: 16px; }

/* Search Box */
.rag-search-box { 
  display: flex; align-items: center; gap: 20px; padding: 16px 24px; 
  background: rgba(15, 15, 20, 0.8); border: 1px solid rgba(255,255,255,0.06); 
  border-radius: 12px; box-shadow: 0 10px 30px rgba(0,0,0,0.5);
  backdrop-filter: blur(20px); z-index: 10;
}
.rag-sb-icon { 
  width: 40px; height: 40px; border-radius: 50%; background: rgba(30, 41, 59, 0.6); 
  display: flex; align-items: center; justify-content: center; color: #60a5fa; flex-shrink: 0;
  border: 1px solid rgba(59, 130, 246, 0.2);
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
.rag-pulse-text { color: #10b981; margin-left: 8px; animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite; }

.rag-sb-stats { 
  display: flex; align-items: center; padding: 6px 12px; background: rgba(0,0,0,0.4); 
  border: 1px solid rgba(59, 130, 246, 0.2); border-radius: 6px; color: #93c5fd; 
  font-size: 11px; font-family: monospace; flex-shrink: 0;
}
.rag-sb-stats-icon { width: 14px; height: 14px; margin-right: 6px; }
.rag-stat-val { color: #fff; font-weight: bold; }
.rag-stat-div { margin: 0 8px; color: rgba(255,255,255,0.2); }

/* Colossal Canvas */
.rag-canvas-container { 
  position: relative; flex: 1; min-height: 500px;
  background: radial-gradient(circle at 50% 50%, rgba(16, 185, 129, 0.02) 0%, rgba(0,0,0,0) 70%), #040404; 
  border: 1px solid rgba(255,255,255,0.03); border-radius: 12px; overflow: hidden;
}

/* Canvas SVG & Links */
.rag-canvas-svg { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
.rag-svg-link { 
  fill: none; stroke: rgba(255,255,255, 0.05); stroke-width: 1.5; 
  transition: all 0.5s ease; stroke-dasharray: 4 4; animation: dash 30s linear infinite;
}
@keyframes dash { to { stroke-dashoffset: -100; } }

/* Nodes */
.rag-node { 
  position: absolute; transform: translate(-50%, -50%); 
  display: inline-flex; align-items: center; gap: 8px;
  padding: 6px 14px; border-radius: 999px; /* Pill */
  font-size: 13px; font-weight: 500; cursor: pointer; 
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  z-index: 10; backdrop-filter: blur(8px);
}
.rag-group:hover, .rag-node:hover { transform: translate(-50%, -50%) scale(1.05); z-index: 20; }
.rag-node-dot { width: 6px; height: 6px; border-radius: 50%; opacity: 0.9; }
.rag-node-text { white-space: nowrap; }

/* Node Kind Variants */
.node-source { background: rgba(30, 58, 138, 0.3); border: 1px solid rgba(59, 130, 246, 0.4); color: #93c5fd; }
.node-source .rag-node-dot { background: #60a5fa; box-shadow: 0 0 8px #60a5fa; }
.node-source.is-active { box-shadow: 0 0 20px rgba(59, 130, 246, 0.4); background: rgba(30, 58, 138, 0.6); }

.node-core { background: rgba(6, 78, 59, 0.3); border: 1px solid rgba(16, 185, 129, 0.4); color: #6ee7b7; text-shadow: 0 0 10px rgba(110, 231, 183, 0.5); }
.node-core .rag-node-dot { background: #10b981; box-shadow: 0 0 8px #10b981; }
.node-core.is-active { box-shadow: 0 0 20px rgba(16, 185, 129, 0.4); background: rgba(6, 78, 59, 0.6); }

.node-impact { background: rgba(88, 28, 135, 0.4); border: 1px solid rgba(168, 85, 247, 0.5); color: #d8b4fe; }
.node-impact .rag-node-dot { background: #a855f7; box-shadow: 0 0 8px #a855f7; }
.node-impact.is-active { box-shadow: 0 0 25px rgba(168, 85, 247, 0.5); background: rgba(88, 28, 135, 0.8); }

.node-support { background: rgba(39, 39, 42, 0.5); border: 1px solid rgba(161, 161, 170, 0.3); color: #d4d4d8; opacity: 0.8; }
.node-support .rag-node-dot { background: #a1a1aa; }
.node-support.is-active { opacity: 1; border-color: rgba(161, 161, 170, 0.5); }

.node-risk { background: rgba(127, 29, 29, 0.3); border: 1px solid rgba(239, 68, 68, 0.3); color: #fca5a5; }
.node-risk .rag-node-dot { background: #ef4444; box-shadow: 0 0 8px #ef4444; }

/* Tooltip overlay for graph nodes */
.rag-node-tooltip {
  position: absolute; top: -100%; left: 50%; transform: translateX(-50%) translateY(-10px) scale(0.9); 
  background: rgba(0,0,0,0.9); border: 1px solid rgba(255,255,255,0.1); 
  padding: 8px 12px; border-radius: 8px; color: #e2e8f0; font-size: 11px; 
  white-space: nowrap; pointer-events: none; opacity: 0; 
  transition: all 0.2s; box-shadow: 0 10px 25px rgba(0,0,0,0.8);
}
.rag-group:hover .rag-group-hover { opacity: 1; transform: translateX(-50%) translateY(-10px) scale(1); }

/* Bottom Ribbon inside canvas */
.rag-inference-ribbon {
  position: absolute; bottom: 24px; left: 24px; right: 24px;
  background: rgba(10, 10, 12, 0.85); backdrop-filter: blur(16px);
  border: 1px solid rgba(255,255,255,0.05); border-radius: 8px;
  padding: 16px 24px; box-shadow: 0 20px 40px rgba(0,0,0,0.8); z-index: 5;
}
.rag-ribbon-title { font-size: 13px; font-family: monospace; color: #10b981; margin-bottom: 16px; letter-spacing: 0.05em; font-weight: bold; }
.rag-ribbon-list { display: flex; align-items: stretch; gap: 12px; overflow-x: auto; padding-bottom: 4px; }
.rag-path-item {
  position: relative;
  padding: 10px 16px; border-radius: 6px; background: rgba(88, 28, 135, 0.1); 
  border: 1px solid rgba(168, 85, 247, 0.15); font-size: 13px; white-space: nowrap;
  display: flex; flex-direction: column; gap: 4px;
  transition: all 0.3s ease;
}
.rag-path-item-main { color: #e5e7eb; font-weight: 500; display: flex; align-items: center; gap: 8px;}
.rag-path-detail { color: #6b7280; font-size: 12px; }
.rag-path-arrow { display: flex; align-items: center; color: #4b5563; font-weight: 300; font-size: 18px; padding: 0 4px; }

.rag-path-item.is-active { background: rgba(88, 28, 135, 0.25); border-color: rgba(168, 85, 247, 0.4); box-shadow: 0 0 20px rgba(168, 85, 247, 0.15); }
.rag-path-item.is-active::after {
  content: ''; position: absolute; bottom: -1px; left: 0; height: 3px; width: 100%;
  background: #10b981; border-radius: 0 0 6px 6px;
  box-shadow: 0 -2px 10px rgba(16, 185, 129, 0.5);
}

/* Generic utilities */
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: .5; } }
.custom-scrollbar::-webkit-scrollbar { width: 6px; height: 6px; }
.custom-scrollbar::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 3px; }
.custom-scrollbar::-webkit-scrollbar-track { background: transparent; }
</style>
