<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

import AppShell from '@/components/AppShell.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingState from '@/components/LoadingState.vue'
import { useAsyncState } from '@/composables/useAsyncState'
import { get } from '@/lib/api'

const route = useRoute()
const state = useAsyncState<any>()
const latestRequestId = ref(0)

const contextText = computed(() => String(route.query.context || route.params.chunkId))
const sourceMeta = computed(() => state.data.value?.source_meta || null)
const companyContext = computed(() => state.data.value?.company_context || null)
const reportContext = computed(() => state.data.value?.report_context || null)
const workflowLinks = computed(() => state.data.value?.workflow_links || [])
const referencePanels = computed(() => state.data.value?.reference_panels || [])
const scoreSnapshot = computed(() => companyContext.value?.score_snapshot || null)
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
    return content.replace(new RegExp(escaped, 'gi'), (matched: string) => `<span class="glow-mark">${matched}</span>`)
  }, escapeHtml(excerpt))
})

function escapeHtml(text: string) {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

function displayValue(value: unknown) {
  if (value === null || value === undefined || value === '') return '--'
  return String(value)
}

async function loadEvidenceDetail(chunkId: string) {
  const requestId = ++latestRequestId.value
  state.loading.value = true
  state.error.value = null
  try {
    const payload = await get(`/evidence/${encodeURIComponent(chunkId)}`)
    if (requestId !== latestRequestId.value) return
    state.data.value = payload
  } catch (error) {
    if (requestId !== latestRequestId.value) return
    state.data.value = null
    state.error.value = error instanceof Error ? error.message : '请求失败'
  } finally {
    if (requestId === latestRequestId.value) {
      state.loading.value = false
    }
  }
}

watch(
  () => route.params.chunkId,
  (chunkId) => {
    if (typeof chunkId !== 'string' || !chunkId) {
      latestRequestId.value += 1
      state.data.value = null
      state.loading.value = false
      state.error.value = '未指定证据。'
      return
    }
    void loadEvidenceDetail(chunkId)
  },
  { immediate: true },
)
</script>

<template>
  <AppShell title="证据核验台" compact>
    <div class="page-shell">
      <LoadingState v-if="state.loading.value" class="state-container" />
      <ErrorState v-else-if="state.error.value" :message="state.error.value" class="state-container" />

      <template v-else-if="state.data.value">
        <section class="glass-panel hero-panel">
          <div class="hero-copy">
            <span class="eyebrow">Evidence Review</span>
            <div class="hero-title-row">
              <div class="mode-query-icon glow-icon">证</div>
              <div>
                <h1>{{ state.data.value.company_name }}</h1>
                <p>{{ contextText }}</p>
              </div>
            </div>
          </div>

          <div class="hero-meta">
            <span class="hero-chip">{{ sourceMeta?.type_label || '未标注来源' }}</span>
            <span class="hero-chip">{{ sourceMeta?.page_label || '页码未标注' }}</span>
            <span class="hero-chip">{{ companyContext?.report_period || state.data.value.report_period || '未标注报期' }}</span>
            <span v-if="companyContext?.subindustry" class="hero-chip">{{ companyContext.subindustry }}</span>
          </div>

          <div v-if="workflowLinks.length" class="workflow-grid">
            <RouterLink
              v-for="link in workflowLinks"
              :key="`${link.path}-${link.label}`"
              class="workflow-link"
              :to="{ path: link.path, query: link.query }"
            >
              <strong>{{ link.label }}</strong>
              <span>{{ link.detail }}</span>
            </RouterLink>
          </div>
        </section>

        <div class="content-grid">
          <section class="glass-panel excerpt-panel">
            <div v-if="anchorTerms.length" class="anchor-strip">
              <span class="eyebrow">高亮词</span>
              <div class="anchor-list">
                <span v-for="term in anchorTerms" :key="term" class="anchor-chip">{{ term }}</span>
              </div>
            </div>

            <div class="excerpt-viewer">
              <div class="viewer-content scroll-area" v-html="highlightedExcerpt"></div>
            </div>
          </section>

          <aside class="side-rail">
            <section class="glass-panel rail-panel">
              <div class="rail-head">
                <div>
                  <span class="eyebrow">Company Context</span>
                  <h2>主体上下文</h2>
                </div>
              </div>

              <div class="stat-grid">
                <div class="stat-card">
                  <span>总分</span>
                  <strong>{{ displayValue(scoreSnapshot?.total_score) }}</strong>
                </div>
                <div class="stat-card">
                  <span>等级</span>
                  <strong>{{ displayValue(scoreSnapshot?.grade) }}</strong>
                </div>
                <div class="stat-card">
                  <span>风险标签</span>
                  <strong>{{ displayValue(scoreSnapshot?.risk_count) }}</strong>
                </div>
                <div class="stat-card">
                  <span>机会标签</span>
                  <strong>{{ displayValue(scoreSnapshot?.opportunity_count) }}</strong>
                </div>
              </div>

              <div class="meta-list">
                <div class="meta-item">
                  <span>证券代码</span>
                  <strong>{{ displayValue(companyContext?.ticker) }}</strong>
                </div>
                <div class="meta-item">
                  <span>当前报期</span>
                  <strong>{{ displayValue(companyContext?.report_period || state.data.value.report_period) }}</strong>
                </div>
                <div class="meta-item">
                  <span>行业</span>
                  <strong>{{ displayValue(companyContext?.subindustry) }}</strong>
                </div>
                <div class="meta-item periods-item">
                  <span>可回看报期</span>
                  <div class="period-chip-row">
                    <span
                      v-for="period in companyContext?.available_periods || []"
                      :key="period"
                      class="period-chip"
                    >
                      {{ period }}
                    </span>
                    <strong v-if="!(companyContext?.available_periods || []).length">--</strong>
                  </div>
                </div>
              </div>
            </section>

            <section class="glass-panel rail-panel">
              <div class="rail-head">
                <div>
                  <span class="eyebrow">Source Chain</span>
                  <h2>源文件链路</h2>
                </div>
              </div>

              <div class="meta-list compact-list">
                <div class="meta-item">
                  <span>来源标题</span>
                  <strong>{{ displayValue(sourceMeta?.source_title) }}</strong>
                </div>
                <div class="meta-item">
                  <span>来源类型</span>
                  <strong>{{ displayValue(sourceMeta?.type_label) }}</strong>
                </div>
                <div class="meta-item">
                  <span>页码定位</span>
                  <strong>{{ displayValue(sourceMeta?.page_label) }}</strong>
                </div>
                <div class="meta-item">
                  <span>哈希指纹</span>
                  <code class="system-code">{{ displayValue(sourceMeta?.fingerprint) }}</code>
                </div>
                <div class="meta-item">
                  <span>系统路径</span>
                  <code class="system-code">{{ displayValue(sourceMeta?.local_path) }}</code>
                </div>
              </div>

              <div class="source-actions">
                <a
                  v-if="sourceMeta?.source_url"
                  class="inline-link"
                  :href="sourceMeta.source_url"
                  target="_blank"
                  rel="noreferrer"
                >
                  打开原文
                </a>
                <a
                  v-if="reportContext?.attachment_url"
                  class="inline-link"
                  :href="reportContext.attachment_url"
                  target="_blank"
                  rel="noreferrer"
                >
                  原文附件
                </a>
              </div>
            </section>

            <section v-if="reportContext" class="glass-panel rail-panel">
              <div class="rail-head">
                <div>
                  <span class="eyebrow">Report Context</span>
                  <h2>研报上下文</h2>
                </div>
              </div>

              <div class="meta-list compact-list">
                <div class="meta-item">
                  <span>机构</span>
                  <strong>{{ displayValue(reportContext.source_name) }}</strong>
                </div>
                <div class="meta-item">
                  <span>发布日期</span>
                  <strong>{{ displayValue(reportContext.publish_date) }}</strong>
                </div>
                <div class="meta-item">
                  <span>评级</span>
                  <strong>{{ displayValue(reportContext.rating_text) }}</strong>
                </div>
                <div class="meta-item">
                  <span>评级动作</span>
                  <strong>{{ displayValue(reportContext.rating_change) }}</strong>
                </div>
                <div class="meta-item">
                  <span>目标价</span>
                  <strong>{{ displayValue(reportContext.target_price) }}</strong>
                </div>
                <div class="meta-item">
                  <span>预测条数</span>
                  <strong>{{ displayValue(reportContext.forecast_count) }}</strong>
                </div>
              </div>
            </section>
          </aside>
        </div>

        <section v-if="referencePanels.length" class="reference-grid">
          <article v-for="panel in referencePanels" :key="panel.kind" class="glass-panel reference-panel">
            <div class="reference-head">
              <div>
                <span class="eyebrow">{{ panel.kind }}</span>
                <h2>{{ panel.title }}</h2>
                <p>{{ panel.subtitle }}</p>
              </div>
              <RouterLink
                v-if="panel.route"
                class="inline-link"
                :to="{ path: panel.route.path, query: panel.route.query }"
              >
                {{ panel.route.label }}
              </RouterLink>
            </div>

            <div class="reference-list">
              <div v-for="entry in panel.entries" :key="`${panel.kind}-${entry.title}`" class="reference-entry">
                <div class="reference-copy">
                  <strong>{{ entry.title }}</strong>
                  <p>{{ entry.detail || '当前工作面已经引用这条证据。' }}</p>
                </div>
                <div v-if="entry.links?.length" class="reference-links">
                  <RouterLink
                    v-for="link in entry.links"
                    :key="`${entry.title}-${link.path}-${link.label}`"
                    class="sub-link"
                    :to="{ path: link.path, query: link.query }"
                  >
                    {{ link.label }}
                  </RouterLink>
                </div>
              </div>
            </div>
          </article>
        </section>
      </template>
    </div>
  </AppShell>
</template>

<style scoped>
.page-shell {
  display: flex;
  flex-direction: column;
  gap: 20px;
  width: 100%;
  max-width: 1360px;
  margin: 0 auto;
  padding: 12px 8px 28px;
}

.state-container {
  min-height: 420px;
}

.hero-panel,
.excerpt-panel,
.rail-panel,
.reference-panel {
  border-radius: 24px;
}

.hero-panel {
  display: grid;
  gap: 18px;
  padding: 26px 28px;
}

.hero-copy {
  display: grid;
  gap: 14px;
}

.hero-title-row {
  display: flex;
  gap: 18px;
  align-items: center;
}

.glow-icon {
  width: 52px;
  height: 52px;
  border-radius: 16px;
  display: grid;
  place-items: center;
  background: rgba(245, 158, 11, 0.15);
  border: 1px solid rgba(245, 158, 11, 0.34);
  color: #f59e0b;
  font-size: 22px;
  font-weight: 700;
  box-shadow: 0 0 18px rgba(245, 158, 11, 0.18);
}

.eyebrow {
  font-size: 11px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: rgba(148, 163, 184, 0.86);
}

.hero-title-row h1,
.rail-head h2,
.reference-head h2 {
  margin: 0;
  color: #f8fafc;
}

.hero-title-row h1 {
  font-size: 34px;
  line-height: 1;
}

.hero-title-row p,
.reference-head p,
.reference-copy p {
  margin: 6px 0 0;
  color: var(--muted);
  line-height: 1.7;
}

.hero-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.hero-chip,
.anchor-chip,
.period-chip {
  padding: 8px 12px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.04);
  color: #e2e8f0;
  font-size: 12px;
}

.workflow-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
}

.workflow-link {
  display: grid;
  gap: 6px;
  padding: 16px 18px;
  border-radius: 18px;
  text-decoration: none;
  color: inherit;
  background: linear-gradient(135deg, rgba(15, 23, 42, 0.86), rgba(30, 41, 59, 0.7));
  border: 1px solid rgba(96, 165, 250, 0.18);
  transition: transform 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
}

.workflow-link:hover {
  transform: translateY(-1px);
  border-color: rgba(96, 165, 250, 0.34);
  box-shadow: 0 18px 36px -24px rgba(96, 165, 250, 0.52);
}

.workflow-link strong,
.reference-copy strong,
.meta-item strong {
  color: #f8fafc;
}

.workflow-link span,
.meta-item span {
  color: var(--muted);
  line-height: 1.6;
}

.content-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(320px, 0.85fr);
  gap: 20px;
  align-items: start;
}

.excerpt-panel {
  display: grid;
  gap: 16px;
  min-height: 620px;
  padding: 24px;
}

.anchor-strip {
  display: grid;
  gap: 12px;
}

.anchor-list,
.period-chip-row,
.reference-links,
.source-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.excerpt-viewer {
  min-height: 0;
  height: 100%;
  padding: 24px;
  border-radius: 20px;
  background: rgba(2, 6, 23, 0.72);
  border: 1px solid rgba(255, 255, 255, 0.05);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03);
}

.viewer-content {
  height: 100%;
  white-space: pre-wrap;
  color: #e2e8f0;
  font-size: 16px;
  line-height: 1.85;
}

.scroll-area {
  overflow-y: auto;
}

.side-rail {
  display: grid;
  gap: 20px;
}

.rail-panel {
  display: grid;
  gap: 18px;
  padding: 22px;
}

.rail-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.stat-card {
  display: grid;
  gap: 4px;
  padding: 14px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.stat-card span {
  color: var(--muted);
  font-size: 12px;
}

.stat-card strong {
  color: #f8fafc;
  font-size: 22px;
}

.meta-list {
  display: grid;
  gap: 14px;
}

.meta-item {
  display: grid;
  gap: 6px;
}

.compact-list .meta-item {
  gap: 5px;
}

.periods-item strong {
  color: var(--muted);
}

.reference-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 20px;
}

.reference-panel {
  display: grid;
  gap: 18px;
  padding: 22px;
}

.reference-head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
}

.reference-list {
  display: grid;
  gap: 14px;
}

.reference-entry {
  display: grid;
  gap: 10px;
  padding-top: 14px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.reference-entry:first-child {
  padding-top: 0;
  border-top: none;
}

.inline-link,
.sub-link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 36px;
  padding: 8px 14px;
  border-radius: 999px;
  text-decoration: none;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.04);
  color: #cbd5e1;
  transition: color 0.18s ease, border-color 0.18s ease, background 0.18s ease;
}

.inline-link:hover,
.sub-link:hover {
  color: #f8fafc;
  border-color: rgba(96, 165, 250, 0.3);
  background: rgba(59, 130, 246, 0.1);
}

.system-code {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: #94a3b8;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.04);
  border-radius: 10px;
  padding: 8px 10px;
}

:deep(.glow-mark) {
  background: rgba(245, 158, 11, 0.22);
  color: #fff;
  border-bottom: 2px solid #f59e0b;
  padding: 0 2px;
  border-radius: 2px;
  box-shadow: 0 0 10px rgba(245, 158, 11, 0.25);
}

@media (max-width: 1080px) {
  .content-grid {
    grid-template-columns: 1fr;
  }

  .excerpt-panel {
    min-height: 520px;
  }
}

@media (max-width: 720px) {
  .page-shell {
    padding: 0 0 22px;
  }

  .hero-panel,
  .excerpt-panel,
  .rail-panel,
  .reference-panel {
    padding: 18px;
  }

  .hero-title-row {
    align-items: flex-start;
  }

  .hero-title-row h1 {
    font-size: 28px;
  }

  .stat-grid {
    grid-template-columns: 1fr 1fr;
  }

  .reference-head {
    flex-direction: column;
  }
}
</style>
