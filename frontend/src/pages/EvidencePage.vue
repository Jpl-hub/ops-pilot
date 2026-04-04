<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import AppShell from '@/components/AppShell.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingState from '@/components/LoadingState.vue'
import { useAsyncState } from '@/composables/useAsyncState'
import { get } from '@/lib/api'
import { useSession } from '@/lib/session'

type RouteLink = {
  label: string
  path: string
  detail?: string
  query?: Record<string, string>
}

type ReferenceEntry = {
  title: string
  detail?: string
  links?: RouteLink[]
}

type ReferencePanel = {
  kind: string
  title: string
  subtitle?: string
  route?: RouteLink | null
  entries?: ReferenceEntry[]
}

type ScoreSnapshot = {
  total_score?: number | string | null
  grade?: string | null
  risk_count?: number | null
  opportunity_count?: number | null
}

type CompanyContext = {
  company_name?: string
  report_period?: string | null
  subindustry?: string | null
  ticker?: string | null
  available_periods?: string[]
  score_snapshot?: ScoreSnapshot | null
}

type ReportContext = {
  title?: string | null
  publish_date?: string | null
  source_name?: string | null
  source_url?: string | null
  attachment_url?: string | null
  rating_text?: string | null
  rating_change?: string | null
  target_price?: number | string | null
  forecast_count?: number | null
}

type EvidenceDetail = {
  chunk_id: string
  company_name?: string
  report_period?: string | null
  source_title?: string | null
  excerpt?: string | null
  source_url?: string | null
  local_path?: string | null
  fingerprint?: string | null
  source_meta?: {
    type_label?: string | null
    page_label?: string | null
  } | null
  company_context?: CompanyContext | null
  report_context?: ReportContext | null
  reference_panels?: ReferencePanel[]
  workflow_links?: RouteLink[]
}

const route = useRoute()
const session = useSession()
const state = useAsyncState<EvidenceDetail>()
const latestRequestId = ref(0)

const currentRole = computed(() => session.activeRole.value || 'management')
const detail = computed(() => state.data.value)
const contextText = computed(() => String(route.query.context || route.params.chunkId || '证据详情'))
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

const sourceTypeLabel = computed(() => detail.value?.source_meta?.type_label || '未标注')
const pageLabel = computed(() => detail.value?.source_meta?.page_label || '页码未标注')
const companyContext = computed(() => detail.value?.company_context || null)
const reportContext = computed(() => detail.value?.report_context || null)
const scoreSnapshot = computed(() => companyContext.value?.score_snapshot || null)
const referencePanels = computed(() => detail.value?.reference_panels || [])
const workflowLinks = computed(() => detail.value?.workflow_links || [])
const sourceFields = computed(() => [
  {
    label: '原文链接',
    href: detail.value?.source_url || reportContext.value?.attachment_url || reportContext.value?.source_url || '',
    text: detail.value?.source_url ? '打开原文' : reportContext.value?.attachment_url ? '打开附件' : '无外部链接',
  },
  {
    label: '系统路径',
    text: detail.value?.local_path || '未记录本地路径',
  },
  {
    label: '哈希指纹',
    text: detail.value?.fingerprint || '未生成指纹',
  },
])

const companyFacts = computed(() => {
  const facts: Array<{ label: string; value: string }> = []
  if (companyContext.value?.ticker) {
    facts.push({ label: '证券代码', value: String(companyContext.value.ticker) })
  }
  if (companyContext.value?.subindustry) {
    facts.push({ label: '子行业', value: String(companyContext.value.subindustry) })
  }
  if (companyContext.value?.report_period) {
    facts.push({ label: '当前报期', value: String(companyContext.value.report_period) })
  }
  if (companyContext.value?.available_periods?.length) {
    facts.push({
      label: '可切换报期',
      value: companyContext.value.available_periods.filter(Boolean).slice(0, 4).join(' · '),
    })
  }
  return facts
})

const scoreFacts = computed(() => {
  if (!scoreSnapshot.value) return []
  return [
    {
      label: '经营总分',
      value:
        scoreSnapshot.value.total_score == null
          ? '未生成'
          : `${scoreSnapshot.value.total_score}${scoreSnapshot.value.grade ? ` / ${scoreSnapshot.value.grade}` : ''}`,
    },
    {
      label: '风险标签',
      value: `${scoreSnapshot.value.risk_count ?? 0}`,
    },
    {
      label: '机会标签',
      value: `${scoreSnapshot.value.opportunity_count ?? 0}`,
    },
  ]
})

const reportFacts = computed(() => {
  if (!reportContext.value) return []
  return [
    {
      label: '研报来源',
      value: reportContext.value.source_name || '未标注',
    },
    {
      label: '发布日期',
      value: reportContext.value.publish_date || '未标注',
    },
    {
      label: '评级',
      value:
        [reportContext.value.rating_text, reportContext.value.rating_change].filter(Boolean).join(' · ') || '未标注',
    },
    {
      label: '目标价 / 预测数',
      value:
        reportContext.value.target_price != null || reportContext.value.forecast_count != null
          ? `${reportContext.value.target_price ?? '--'} / ${reportContext.value.forecast_count ?? 0}`
          : '未标注',
    },
  ]
})

const highlightedExcerpt = computed(() => {
  const excerpt = String(detail.value?.excerpt || '')
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

async function loadEvidence() {
  const requestId = ++latestRequestId.value
  const chunkId = String(route.params.chunkId || '').trim()
  if (!chunkId) {
    state.data.value = null
    state.loading.value = false
    state.error.value = '未指定证据。'
    return
  }
  state.loading.value = true
  state.error.value = null
  try {
    const payload = await get<EvidenceDetail>(
      `/evidence/${encodeURIComponent(chunkId)}?user_role=${encodeURIComponent(currentRole.value)}`,
    )
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
  [() => route.params.chunkId, () => route.query.anchors, () => route.query.terms, currentRole],
  () => {
    void loadEvidence()
  },
  { immediate: true },
)
</script>

<template>
  <AppShell title="证据核验台" subtitle="证据详情与回流链路" compact>
    <div class="evidence-wrapper">
      <LoadingState v-if="state.loading.value" class="state-container" />
      <ErrorState v-else-if="state.error.value" :message="state.error.value" class="state-container" />

      <div v-else-if="detail" class="evidence-content glass-panel">
        <header class="ev-head border-b-subtle">
          <div class="ev-title-bar">
            <div class="glow-icon">证</div>
            <div class="hero-copy">
              <h3 class="company-name text-gradient">{{ companyContext?.company_name || detail.company_name || '证据详情' }}</h3>
              <span class="muted">{{ contextText }}</span>
              <p class="hero-subtitle">{{ detail.source_title || '未标注文档标题' }}</p>
            </div>
          </div>

          <div class="ev-meta-strip">
            <article class="ev-meta-item">
              <span class="muted text-xs">证据类型</span>
              <strong class="text-sm">{{ sourceTypeLabel }}</strong>
            </article>
            <article class="ev-meta-item">
              <span class="muted text-xs">定位点</span>
              <strong class="text-sm text-accent">{{ pageLabel }}</strong>
            </article>
            <article class="ev-meta-item">
              <span class="muted text-xs">工作流</span>
              <strong class="text-sm">{{ workflowLinks.length }} 个回流入口</strong>
            </article>
          </div>
        </header>

        <main class="ev-body">
          <section class="fact-grid">
            <article class="fact-card">
              <span class="card-kicker">公司上下文</span>
              <strong>{{ companyContext?.company_name || detail.company_name || '未标注公司' }}</strong>
              <div class="fact-list">
                <div v-for="item in companyFacts" :key="item.label" class="fact-row">
                  <span>{{ item.label }}</span>
                  <strong>{{ item.value }}</strong>
                </div>
                <div v-if="!companyFacts.length" class="fact-row">
                  <span>上下文</span>
                  <strong>未加载</strong>
                </div>
              </div>
            </article>

            <article class="fact-card">
              <span class="card-kicker">经营快照</span>
              <strong>{{ scoreFacts.length ? '这条证据已回挂经营诊断' : '当前没有经营快照' }}</strong>
              <div class="fact-list">
                <div v-for="item in scoreFacts" :key="item.label" class="fact-row">
                  <span>{{ item.label }}</span>
                  <strong>{{ item.value }}</strong>
                </div>
                <div v-if="!scoreFacts.length" class="fact-row">
                  <span>诊断状态</span>
                  <strong>未命中评分链路</strong>
                </div>
              </div>
            </article>

            <article class="fact-card">
              <span class="card-kicker">研报上下文</span>
              <strong>{{ reportContext?.title || '当前不是研报主证据' }}</strong>
              <div class="fact-list">
                <div v-for="item in reportFacts" :key="item.label" class="fact-row">
                  <span>{{ item.label }}</span>
                  <strong>{{ item.value }}</strong>
                </div>
                <div v-if="!reportFacts.length" class="fact-row">
                  <span>核验状态</span>
                  <strong>未挂接研报上下文</strong>
                </div>
              </div>
            </article>
          </section>

          <section v-if="anchorTerms.length" class="ev-anchors">
            <span class="text-xs muted uppercase tracking-widest">高亮词</span>
            <div class="anchors-list">
              <span v-for="term in anchorTerms" :key="term" class="anchor-tag">{{ term }}</span>
            </div>
          </section>

          <section class="excerpt-viewer">
            <div class="section-head">
              <span class="card-kicker">原文摘录</span>
              <strong>先回到触发判断的文本</strong>
            </div>
            <div class="viewer-content scroll-area" v-html="highlightedExcerpt"></div>
          </section>

          <section v-if="referencePanels.length" class="panel-stack">
            <article v-for="panel in referencePanels" :key="panel.kind" class="panel-card">
              <div class="section-head">
                <span class="card-kicker">{{ panel.title }}</span>
                <strong>{{ panel.subtitle || '当前没有补充说明。' }}</strong>
              </div>

              <div class="entry-stack">
                <section v-for="entry in panel.entries || []" :key="`${panel.kind}-${entry.title}`" class="entry-card">
                  <strong>{{ entry.title }}</strong>
                  <p>{{ entry.detail || '该引用已经把当前证据挂到对应工序。' }}</p>
                  <div v-if="entry.links?.length" class="link-stack">
                    <RouterLink
                      v-for="link in entry.links"
                      :key="`${entry.title}-${link.path}-${link.label}`"
                      :to="{ path: link.path, query: link.query || {} }"
                      class="jump-link"
                    >
                      <span>{{ link.label }}</span>
                      <strong>打开</strong>
                    </RouterLink>
                  </div>
                </section>
              </div>

              <RouterLink
                v-if="panel.route?.path"
                :to="{ path: panel.route.path, query: panel.route.query || {} }"
                class="panel-route"
              >
                <span>{{ panel.route.label || '返回对应工作面' }}</span>
                <strong>进入</strong>
              </RouterLink>
            </article>
          </section>

          <section v-if="workflowLinks.length" class="panel-card">
            <div class="section-head">
              <span class="card-kicker">继续推进</span>
              <strong>顺着这条证据回到判断、图谱和执行动作</strong>
            </div>

            <div class="workflow-grid">
              <RouterLink
                v-for="link in workflowLinks"
                :key="`${link.path}-${link.label}`"
                :to="{ path: link.path, query: link.query || {} }"
                class="workflow-card"
              >
                <span>{{ link.label }}</span>
                <strong>{{ link.detail || '继续查看' }}</strong>
              </RouterLink>
            </div>
          </section>
        </main>

        <footer class="ev-foot border-t-subtle">
          <h4 class="text-xs uppercase muted">源文件链路</h4>
          <div class="source-grid">
            <div v-for="field in sourceFields" :key="field.label" class="source-field">
              <span>{{ field.label }}</span>
              <a
                v-if="field.href"
                class="text-accent underline"
                :href="field.href"
                target="_blank"
                rel="noreferrer"
              >
                {{ field.text }}
              </a>
              <code v-else class="system-code">{{ field.text }}</code>
            </div>
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
  min-height: 100%;
  padding: 20px;
}

.evidence-content {
  width: 100%;
  max-width: 1180px;
  border-radius: 24px;
  display: flex;
  flex-direction: column;
  background: rgba(15, 23, 42, 0.65);
  box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.8);
}

.ev-head,
.ev-body,
.ev-foot {
  padding-left: 28px;
  padding-right: 28px;
}

.ev-head {
  display: grid;
  gap: 24px;
  padding-top: 28px;
  padding-bottom: 24px;
}

.border-b-subtle {
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.border-t-subtle {
  border-top: 1px solid rgba(255, 255, 255, 0.05);
}

.ev-title-bar {
  display: flex;
  align-items: flex-start;
  gap: 20px;
}

.glow-icon {
  width: 48px;
  height: 48px;
  border-radius: 14px;
  background: rgba(245, 158, 11, 0.15);
  border: 1px solid rgba(245, 158, 11, 0.4);
  color: #f59e0b;
  display: grid;
  place-items: center;
  font-weight: 700;
  font-size: 22px;
  box-shadow: 0 0 20px rgba(245, 158, 11, 0.2);
}

.hero-copy {
  display: grid;
  gap: 6px;
}

.company-name {
  margin: 0;
  font-size: 28px;
  font-weight: 700;
}

.hero-subtitle {
  margin: 0;
  color: rgba(226, 232, 240, 0.88);
  line-height: 1.6;
}

.text-gradient {
  background-clip: text;
  -webkit-text-fill-color: transparent;
  background-image: linear-gradient(90deg, #fde68a, #f59e0b);
}

.muted {
  color: var(--muted);
}

.ev-meta-strip,
.fact-grid,
.source-grid,
.workflow-grid {
  display: grid;
  gap: 14px;
}

.ev-meta-strip {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.ev-meta-item,
.fact-card,
.panel-card,
.entry-card,
.workflow-card {
  border-radius: 18px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.025);
}

.ev-meta-item {
  display: grid;
  gap: 4px;
  padding: 14px 16px;
}

.text-xs {
  font-size: 12px;
}

.text-sm {
  font-size: 14px;
}

.text-accent {
  color: #f59e0b;
}

.ev-body {
  display: grid;
  gap: 18px;
  padding-top: 22px;
  padding-bottom: 24px;
}

.fact-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.fact-card,
.panel-card {
  display: grid;
  gap: 14px;
  padding: 18px;
}

.fact-card > strong,
.section-head strong,
.entry-card strong,
.workflow-card strong {
  color: #f8fafc;
}

.card-kicker {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: rgba(120, 143, 172, 0.82);
}

.fact-list,
.panel-stack,
.entry-stack,
.link-stack {
  display: grid;
  gap: 10px;
}

.fact-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.fact-row span,
.source-field span {
  color: rgba(148, 163, 184, 0.82);
  font-size: 12px;
}

.fact-row strong {
  font-size: 13px;
  text-align: right;
}

.ev-anchors {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.uppercase {
  text-transform: uppercase;
}

.tracking-widest {
  letter-spacing: 0.1em;
}

.anchors-list {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.anchor-tag {
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-family: 'JetBrains Mono', monospace;
  background: rgba(245, 158, 11, 0.1);
  color: #fcd34d;
  border: 1px solid rgba(245, 158, 11, 0.3);
}

.excerpt-viewer {
  display: grid;
  gap: 14px;
  padding: 18px;
  border-radius: 18px;
  background: rgba(0, 0, 0, 0.28);
  border: 1px solid rgba(255, 255, 255, 0.05);
}

.section-head {
  display: grid;
  gap: 6px;
}

.viewer-content {
  min-height: 180px;
  max-height: 360px;
  white-space: pre-wrap;
  font-size: 15px;
  line-height: 1.85;
  color: #e2e8f0;
}

.scroll-area {
  overflow-y: auto;
}

.scroll-area::-webkit-scrollbar {
  width: 6px;
}

:deep(.glow-mark) {
  background: rgba(245, 158, 11, 0.2);
  color: #fff;
  border-bottom: 2px solid #f59e0b;
  padding: 0 2px;
  border-radius: 2px;
  box-shadow: 0 0 10px rgba(245, 158, 11, 0.3);
}

.entry-card {
  display: grid;
  gap: 8px;
  padding: 14px 16px;
}

.entry-card p,
.workflow-card span,
.source-field,
.panel-route span {
  color: rgba(203, 213, 225, 0.84);
  line-height: 1.7;
}

.jump-link,
.panel-route,
.workflow-card {
  text-decoration: none;
}

.jump-link,
.panel-route {
  min-height: 40px;
  padding: 0 14px;
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.03);
  color: #dbe7f3;
  display: inline-flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.panel-route {
  width: fit-content;
}

.jump-link strong,
.panel-route strong {
  font-size: 12px;
  color: #73f0c7;
}

.workflow-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.workflow-card {
  display: grid;
  gap: 8px;
  padding: 16px;
}

.workflow-card span {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.ev-foot {
  display: grid;
  gap: 14px;
  padding-top: 20px;
  padding-bottom: 24px;
}

.source-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.source-field {
  display: grid;
  gap: 6px;
  font-size: 13px;
}

.underline {
  text-decoration: underline;
  text-underline-offset: 4px;
}

.system-code {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  background: rgba(255, 255, 255, 0.05);
  padding: 6px 10px;
  border-radius: 6px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: #94a3b8;
}

@media (max-width: 1080px) {
  .fact-grid,
  .workflow-grid,
  .source-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .ev-head,
  .ev-body,
  .ev-foot {
    padding-left: 18px;
    padding-right: 18px;
  }

  .ev-meta-strip {
    grid-template-columns: 1fr;
  }

  .ev-title-bar {
    flex-direction: column;
  }
}
</style>
