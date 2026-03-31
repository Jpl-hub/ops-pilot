<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'

import AppShell from '@/components/AppShell.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingState from '@/components/LoadingState.vue'
import { useAsyncState } from '@/composables/useAsyncState'
import { get } from '@/lib/api'

const route = useRoute()
const state = useAsyncState<any>()

const contextText = computed(() => String(route.query.context || route.params.chunkId))
const anchorTerms = computed(() => {
  const rawAnchors =
    typeof route.query.anchors === 'string'
      ? route.query.anchors
      : typeof route.query.terms === 'string'
      ? route.query.terms
      : ''
  return rawAnchors
    ? rawAnchors.split(/[|,]/).map((term) => term.trim()).filter(Boolean)
    : []
})
const highlightedExcerpt = computed(() => {
  const excerpt = String(state.data.value?.excerpt || '')
  if (!excerpt || anchorTerms.value.length === 0) {
    return escapeHtml(excerpt)
  }
  return anchorTerms.value.reduce((content, term) => {
    if (!term) return content
    const escaped = term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    // We use a specific span class for styling
    return content.replace(new RegExp(escaped, 'gi'), (matched: string) => `<span class="glow-mark">${matched}</span>`)
  }, escapeHtml(excerpt))
})

const sourceTypeLabel = computed(() => {
  const map: Record<string, string> = {
    official_summary_page: '定期报告页级摘要',
    official_statement_page: '定期报告财务页',
    official_event_page: '定期报告事项页',
    official_snapshot_page: '文档快照页',
    hybrid_rag_chunk: '检索证据片段',
    research_report_excerpt: '研报证据',
    research_forecast_excerpt: '盈利预测摘录',
    bootstrap_note: '补充说明',
  }
  const sourceType = String(state.data.value?.source_type || '')
  return map[sourceType] || sourceType || '未标注'
})

const pageLabel = computed(() => {
  const page = state.data.value?.page
  return typeof page === 'number' || typeof page === 'string' ? `第 ${page} 页` : '页码未标注'
})

function escapeHtml(text: string) {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

onMounted(() => {
  const chunkId = route.params.chunkId as string
  void state.execute(() => get(`/evidence/${encodeURIComponent(chunkId)}`))
})
</script>

<template>
  <AppShell title="证据核验台" compact>
    <div class="evidence-wrapper">
      <LoadingState v-if="state.loading.value" class="state-container" />
      <ErrorState v-else-if="state.error.value" :message="state.error.value" class="state-container" />
      
      <div v-else-if="state.data.value" class="evidence-content glass-panel">
        
        <header class="ev-head border-b-subtle">
           <div class="ev-title-bar">
             <div class="mode-query-icon glow-icon">证</div>
             <div>
                <h3 class="company-name text-gradient">{{ state.data.value.company_name }}</h3>
                <span class="muted">{{ contextText }}</span>
             </div>
           </div>
           
           <div class="ev-meta-strip">
             <div class="ev-meta-item">
               <span class="muted text-xs">来源文档</span>
               <strong class="text-sm">{{ state.data.value.source_title }}</strong>
             </div>
             <div class="ev-meta-item">
               <span class="muted text-xs">文档属性</span>
               <strong class="text-sm">{{ sourceTypeLabel }} · {{ state.data.value.report_period }}</strong>
             </div>
             <div class="ev-meta-item">
               <span class="muted text-xs">定位点</span>
               <strong class="text-sm text-accent">{{ pageLabel }}</strong>
             </div>
           </div>
        </header>

        <main class="ev-body">
           <div v-if="anchorTerms.length" class="ev-anchors mb-4">
             <span class="text-xs muted uppercase tracking-widest mr-3">高亮词</span>
             <div class="anchors-list">
                <span v-for="term in anchorTerms" :key="term" class="anchor-tag">{{ term }}</span>
             </div>
           </div>
           
           <div class="excerpt-viewer">
             <div class="viewer-content scroll-area" v-html="highlightedExcerpt"></div>
           </div>
        </main>

        <footer class="ev-foot border-t-subtle mt-4 pt-4">
           <h4 class="text-xs uppercase muted mb-3">源文件链路</h4>
           <div class="source-grid">
              <div class="source-field">
                <span>原文链接</span>
                <a v-if="state.data.value.source_url" class="text-accent underline" :href="state.data.value.source_url" target="_blank" rel="noreferrer">打开原文</a>
                <code v-else class="system-code">无外部链接</code>
              </div>
              <div class="source-field"><span>系统路径</span><code class="system-code">{{ state.data.value.local_path }}</code></div>
              <div class="source-field"><span>哈希指纹</span><code class="system-code">{{ state.data.value.fingerprint }}</code></div>
           </div>
        </footer>

      </div>
    </div>
  </AppShell>
</template>

<style scoped>
.evidence-wrapper {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100%;
  padding: 20px;
}
.evidence-content {
  width: 100%;
  max-width: 900px;
  max-height: 100%;
  border-radius: 24px;
  display: flex;
  flex-direction: column;
  background: rgba(15, 23, 42, 0.65);
  box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.8);
}

.ev-head { padding: 32px; display: flex; flex-direction: column; gap: 24px; }
.border-b-subtle { border-bottom: 1px solid rgba(255,255,255,0.05); }
.border-t-subtle { border-top: 1px solid rgba(255,255,255,0.05); }

.ev-title-bar { display: flex; align-items: center; gap: 20px; }
.glow-icon { width: 48px; height: 48px; border-radius: 14px; background: rgba(245, 158, 11, 0.15); border: 1px solid rgba(245, 158, 11, 0.4); color: #f59e0b; display: grid; place-items: center; font-weight: bold; font-size: 22px; box-shadow: 0 0 20px rgba(245, 158, 11, 0.2); }
.company-name { margin: 0 0 4px; font-size: 24px; font-weight: 600; }
.text-gradient { background-clip: text; -webkit-text-fill-color: transparent; background-image: linear-gradient(to right, #fcd34d, #f59e0b); }
.muted { color: var(--muted); }

.ev-meta-strip { display: flex; gap: 40px; }
.ev-meta-item { display: flex; flex-direction: column; gap: 4px; }
.text-xs { font-size: 12px; }
.text-sm { font-size: 14px; }
.text-accent { color: #f59e0b; }

.ev-body { padding: 0 32px; flex: 1; min-height: 0; display: flex; flex-direction: column; overflow: hidden; margin-top: 24px; }
.mb-4 { margin-bottom: 16px; }
.ev-anchors { display: flex; align-items: center; }
.uppercase { text-transform: uppercase; }
.tracking-widest { letter-spacing: 0.1em; }
.mr-3 { margin-right: 12px; }
.anchors-list { display: flex; gap: 8px; flex-wrap: wrap; }
.anchor-tag { padding: 4px 10px; border-radius: 6px; font-size: 12px; font-family: 'JetBrains Mono', monospace; background: rgba(245, 158, 11, 0.1); color: #fcd34d; border: 1px solid rgba(245, 158, 11, 0.3); }

.excerpt-viewer { flex: 1; border-radius: 16px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.05); padding: 24px; overflow: hidden; display: flex; flex-direction: column; }
.viewer-content { flex: 1; white-space: pre-wrap; font-size: 16px; line-height: 1.8; color: #e2e8f0; }

.scroll-area { overflow-y: auto; }
.scroll-area::-webkit-scrollbar { width: 6px; }

:deep(.glow-mark) {
  background: rgba(245, 158, 11, 0.2);
  color: #fff;
  border-bottom: 2px solid #f59e0b;
  padding: 0 2px;
  border-radius: 2px;
  box-shadow: 0 0 10px rgba(245, 158, 11, 0.3);
}

.ev-foot { padding: 0 32px 32px; }
.mt-4 { margin-top: 16px; }
.pt-4 { padding-top: 16px; }
.mb-3 { margin-bottom: 12px; }

.source-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; }
.source-field { display: flex; flex-direction: column; gap: 6px; font-size: 13px; }
.source-field span { color: var(--muted); }
.underline { text-decoration: underline; text-underline-offset: 4px; }
.system-code { font-family: 'JetBrains Mono', monospace; font-size: 11px; background: rgba(255,255,255,0.05); padding: 6px 10px; border-radius: 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: #94a3b8; }
</style>
